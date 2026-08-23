from __future__ import annotations

import base64
import json
import stat
from pathlib import Path

import numpy as np
import pytest
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from services.voice.enrollment import (
    ENROLLMENT_REJECTED,
    VoiceEnrollment,
    VoiceProfileStore,
)
from services.voice.keychain import KeychainSecretStore
from services.voice.speaker import EmbeddingObservation


PROFILE_ID = "11111111-1111-4111-8111-111111111111"
MODEL_VERSION = "speechbrain-ecapa-v1"


class FakeKeychain:
    def __init__(self) -> None:
        self.values: dict[tuple[str, str], bytes] = {}

    def read(self, service: str, account: str) -> bytes | None:
        return self.values.get((service, account))

    def write(self, service: str, account: str, secret: bytes) -> None:
        self.values[(service, account)] = bytes(secret)

    def delete(self, service: str, account: str) -> None:
        self.values.pop((service, account), None)


def pcm(value: int) -> bytes:
    return np.full(16_000, value, dtype="<i2").tobytes()


def vector(offset: float) -> tuple[float, ...]:
    values = np.zeros(192, dtype=np.float32)
    values[0] = 1.0
    values[1] = offset
    values /= np.linalg.norm(values)
    return tuple(float(value) for value in values)


class EnrollmentRunner:
    def __init__(self, *, bad_quality: bool = False) -> None:
        self.bad_quality = bad_quality
        self.calls = 0

    def __call__(self, _samples: np.ndarray) -> EmbeddingObservation:
        self.calls += 1
        return EmbeddingObservation(
            embedding=vector(0.01 * self.calls),
            speech_seconds=0.4 if self.bad_quality else 1.0,
            snr_db=20.0,
            overlap_probability=0.0,
        )


def profile_store(tmp_path: Path) -> tuple[VoiceProfileStore, FakeKeychain, Path]:
    backend = FakeKeychain()
    secrets = KeychainSecretStore(backend, random_bytes=lambda size: b"k" * size)
    path = tmp_path / "runtime/private/voice-profile.json"
    return VoiceProfileStore(path, secrets, random_bytes=lambda size: b"n" * size), backend, path


def test_enrollment_encrypts_embedding_and_persists_only_bounded_metadata(
    tmp_path: Path,
) -> None:
    store, _backend, path = profile_store(tmp_path)
    runner = EnrollmentRunner()
    enrollment = VoiceEnrollment(
        runner=runner,
        store=store,
        model_version=MODEL_VERSION,
        profile_id_factory=lambda: PROFILE_ID,
    )

    created = enrollment.create((pcm(2_000), pcm(2_200), pcm(2_400)))
    loaded = store.read()

    assert created == loaded
    assert runner.calls == 3
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    envelope = json.loads(path.read_text(encoding="ascii"))
    assert set(envelope) == {
        "acceptThreshold", "ciphertext", "enrollmentQuality", "modelVersion",
        "nonce", "profileId", "schemaVersion", "uncertainThreshold",
    }
    serialized = path.read_bytes()
    for forbidden in (b"embedding", b"sample", b"transcript", pcm(2_000)[:16]):
        assert forbidden not in serialized


def test_profile_deletion_removes_ciphertext_and_its_key(tmp_path: Path) -> None:
    store, backend, path = profile_store(tmp_path)
    enrollment = VoiceEnrollment(
        runner=EnrollmentRunner(),
        store=store,
        model_version=MODEL_VERSION,
        profile_id_factory=lambda: PROFILE_ID,
    )
    enrollment.create((pcm(2_000), pcm(2_200), pcm(2_400)))

    store.delete()

    assert not path.exists()
    assert backend.values == {}
    assert store.read() is None


def test_enrollment_rejects_bad_count_or_quality_without_a_profile(tmp_path: Path) -> None:
    for samples, bad_quality in [((pcm(2_000),), False), ((pcm(2_000),) * 3, True)]:
        store, backend, path = profile_store(tmp_path / str(len(samples)) / str(bad_quality))
        enrollment = VoiceEnrollment(
            runner=EnrollmentRunner(bad_quality=bad_quality),
            store=store,
            model_version=MODEL_VERSION,
            profile_id_factory=lambda: PROFILE_ID,
        )
        with pytest.raises(ValueError, match=f"^{ENROLLMENT_REJECTED}$"):
            enrollment.create(samples)
        assert not path.exists()
        assert backend.values == {}


def test_profile_store_rejects_tamper_and_wrong_mode(tmp_path: Path) -> None:
    store, _backend, path = profile_store(tmp_path)
    enrollment = VoiceEnrollment(
        runner=EnrollmentRunner(),
        store=store,
        model_version=MODEL_VERSION,
        profile_id_factory=lambda: PROFILE_ID,
    )
    enrollment.create((pcm(2_000), pcm(2_200), pcm(2_400)))
    path.chmod(0o644)
    with pytest.raises(ValueError, match="^voice_profile_unavailable$"):
        store.read()

    path.chmod(0o600)
    payload = bytearray(path.read_bytes())
    payload[-3] = ord("A") if payload[-3] != ord("A") else ord("B")
    path.write_bytes(payload)
    path.chmod(0o600)
    with pytest.raises(ValueError, match="^voice_profile_unavailable$"):
        store.read()


def test_profile_store_refuses_a_symlinked_profile(tmp_path: Path) -> None:
    store, _backend, path = profile_store(tmp_path)
    path.parent.mkdir(parents=True)
    outside = tmp_path / "outside"
    outside.write_text("synthetic", encoding="ascii")
    path.symlink_to(outside)

    with pytest.raises(ValueError, match="^voice_profile_unavailable$"):
        store.read()


def test_profile_store_rejects_an_authenticated_unknown_schema(tmp_path: Path) -> None:
    store, backend, path = profile_store(tmp_path)
    enrollment = VoiceEnrollment(
        runner=EnrollmentRunner(),
        store=store,
        model_version=MODEL_VERSION,
        profile_id_factory=lambda: PROFILE_ID,
    )
    enrollment.create((pcm(2_000), pcm(2_200), pcm(2_400)))
    envelope = json.loads(path.read_text(encoding="ascii"))
    metadata = {
        key: value
        for key, value in envelope.items()
        if key not in {"ciphertext", "nonce"}
    }
    def canonical(value: object) -> bytes:
        return (
            json.dumps(value, separators=(",", ":"), sort_keys=True) + "\n"
        ).encode("ascii")
    key = backend.values[
        ("com.baby-monitor-local.voice-care", "voice-profile-key.v1")
    ]
    nonce = base64.b64decode(envelope["nonce"])
    plaintext = AESGCM(key).decrypt(
        nonce, base64.b64decode(envelope["ciphertext"]), canonical(metadata)
    )
    metadata["schemaVersion"] = 2
    envelope.update(metadata)
    envelope["ciphertext"] = base64.b64encode(
        AESGCM(key).encrypt(nonce, plaintext, canonical(metadata))
    ).decode("ascii")
    path.write_bytes(canonical(envelope))
    path.chmod(0o600)

    with pytest.raises(ValueError, match="^voice_profile_unavailable$"):
        store.read()
