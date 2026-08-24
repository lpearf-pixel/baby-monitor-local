"""Adult-only speaker enrollment and encrypted local profile persistence."""

from __future__ import annotations

import base64
import json
import os
import secrets
import stat
import tempfile
from collections.abc import Callable, Sequence
from pathlib import Path
from uuid import UUID, uuid4

import numpy as np
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from services.voice.keychain import KeychainSecretStore
from services.voice.speaker import (
    MAX_OVERLAP_PROBABILITY,
    MIN_PCM_SECONDS,
    MIN_SNR_DB,
    EmbeddingRunner,
    VoiceProfile,
    _validated_observation,
    _validated_pcm,
)


ENROLLMENT_REJECTED = "voice_enrollment_rejected"
PROFILE_UNAVAILABLE = "voice_profile_unavailable"
PROFILE_KEY_ACCOUNT_PREFIX = "voice-profile-key.v1."
MIN_ENROLLMENT_SAMPLES = 3
MAX_ENROLLMENT_SAMPLES = 5
_MAX_PROFILE_BYTES = 65_536
_SCHEMA_VERSION = 1


class VoiceProfileStore:
    """Store only AES-GCM ciphertext plus bounded non-secret profile metadata."""

    def __init__(
        self,
        path: Path,
        keychain: KeychainSecretStore,
        *,
        boundary: Path,
        profile_id: str,
        random_bytes: Callable[[int], bytes] = secrets.token_bytes,
    ) -> None:
        self._path = path
        self._keychain = keychain
        if boundary.is_symlink():
            raise ValueError(PROFILE_UNAVAILABLE)
        try:
            self._boundary = boundary.resolve(strict=True)
        except Exception:
            raise ValueError(PROFILE_UNAVAILABLE) from None
        if not self._boundary.is_dir():
            raise ValueError(PROFILE_UNAVAILABLE)
        self._profile_id = _canonical_profile_id(profile_id)
        self._key_account = f"{PROFILE_KEY_ACCOUNT_PREFIX}{self._profile_id}"
        self._random_bytes = random_bytes

    def create(self, profile: VoiceProfile) -> None:
        key_created = False
        try:
            self._validate_boundary()
            if profile.profile_id != self._profile_id:
                raise ValueError(PROFILE_UNAVAILABLE)
            if self._path.exists() or self._path.is_symlink():
                raise ValueError(PROFILE_UNAVAILABLE)
            if self._keychain.read(self._key_account, size=32) is not None:
                raise ValueError(PROFILE_UNAVAILABLE)
            parent = self._path.parent
            parent.mkdir(mode=0o700, parents=True, exist_ok=True)
            if parent.is_symlink() or not parent.is_dir():
                raise ValueError(PROFILE_UNAVAILABLE)
            parent.chmod(0o700)
            key = self._keychain.get_or_create(self._key_account, size=32)
            key_created = True
            nonce = self._random_bytes(12)
            if type(nonce) is not bytes or len(nonce) != 12:
                raise ValueError(PROFILE_UNAVAILABLE)
            metadata = _metadata(profile)
            aad = _canonical_json(metadata)
            plaintext = _canonical_json({"embedding": list(profile.embedding)})
            ciphertext = AESGCM(key).encrypt(nonce, plaintext, aad)
            envelope = {
                **metadata,
                "ciphertext": base64.b64encode(ciphertext).decode("ascii"),
                "nonce": base64.b64encode(nonce).decode("ascii"),
            }
            payload = _canonical_json(envelope)
            if len(payload) > _MAX_PROFILE_BYTES:
                raise ValueError(PROFILE_UNAVAILABLE)
            _publish_exclusive(self._path, payload)
        except Exception:
            if key_created and not self._path.exists() and not self._path.is_symlink():
                try:
                    self._keychain.delete(self._key_account)
                except Exception:
                    pass
            raise ValueError(PROFILE_UNAVAILABLE) from None

    def read(self) -> VoiceProfile | None:
        self._validate_boundary()
        if not self._path.exists() and not self._path.is_symlink():
            return None
        try:
            descriptor = os.open(self._path, os.O_RDONLY | os.O_NOFOLLOW)
            try:
                value = os.fstat(descriptor)
                with os.fdopen(descriptor, "rb", closefd=True) as handle:
                    descriptor = -1
                    payload = handle.read(_MAX_PROFILE_BYTES + 1)
            finally:
                if descriptor >= 0:
                    os.close(descriptor)
            if (
                not stat.S_ISREG(value.st_mode)
                or stat.S_IMODE(value.st_mode) != 0o600
                or not 0 < value.st_size <= _MAX_PROFILE_BYTES
                or len(payload) != value.st_size
            ):
                raise ValueError(PROFILE_UNAVAILABLE)
            envelope = json.loads(payload.decode("ascii"))
            if not isinstance(envelope, dict) or payload != _canonical_json(envelope):
                raise ValueError(PROFILE_UNAVAILABLE)
            expected = {
                "acceptThreshold",
                "ciphertext",
                "enrollmentQuality",
                "modelVersion",
                "nonce",
                "profileId",
                "schemaVersion",
                "uncertainThreshold",
            }
            if set(envelope) != expected:
                raise ValueError(PROFILE_UNAVAILABLE)
            if envelope["schemaVersion"] != _SCHEMA_VERSION:
                raise ValueError(PROFILE_UNAVAILABLE)
            if envelope["profileId"] != self._profile_id:
                raise ValueError(PROFILE_UNAVAILABLE)
            metadata = {key: envelope[key] for key in expected - {"ciphertext", "nonce"}}
            key = self._keychain.read(self._key_account, size=32)
            if key is None:
                raise ValueError(PROFILE_UNAVAILABLE)
            nonce = base64.b64decode(envelope["nonce"], validate=True)
            ciphertext = base64.b64decode(envelope["ciphertext"], validate=True)
            if len(nonce) != 12 or len(ciphertext) < 16:
                raise ValueError(PROFILE_UNAVAILABLE)
            plaintext = AESGCM(key).decrypt(
                nonce, ciphertext, _canonical_json(metadata)
            )
            private = json.loads(plaintext.decode("ascii"))
            if (
                not isinstance(private, dict)
                or set(private) != {"embedding"}
                or plaintext != _canonical_json(private)
            ):
                raise ValueError(PROFILE_UNAVAILABLE)
            return VoiceProfile(
                profile_id=envelope["profileId"],
                model_version=envelope["modelVersion"],
                embedding=tuple(private["embedding"]),
                accept_threshold=envelope["acceptThreshold"],
                uncertain_threshold=envelope["uncertainThreshold"],
                enrollment_quality=envelope["enrollmentQuality"],
            )
        except Exception:
            raise ValueError(PROFILE_UNAVAILABLE) from None

    def delete(self) -> None:
        try:
            self._validate_boundary()
            if self._path.is_symlink():
                raise ValueError(PROFILE_UNAVAILABLE)
            if self._path.exists():
                value = self._path.lstat()
                if not stat.S_ISREG(value.st_mode):
                    raise ValueError(PROFILE_UNAVAILABLE)
            self._keychain.delete(self._key_account)
            if self._path.exists():
                self._path.unlink()
        except Exception:
            raise ValueError(PROFILE_UNAVAILABLE) from None

    def _validate_boundary(self) -> None:
        try:
            relative = self._path.relative_to(self._boundary)
            if not relative.parts or relative.is_absolute() or ".." in relative.parts:
                raise ValueError(PROFILE_UNAVAILABLE)
            current = self._boundary
            for part in relative.parts[:-1]:
                current = current / part
                if current.is_symlink() or (
                    current.exists() and not current.is_dir()
                ):
                    raise ValueError(PROFILE_UNAVAILABLE)
        except Exception:
            raise ValueError(PROFILE_UNAVAILABLE) from None


class VoiceEnrollment:
    """Create one opaque adult voice profile from several quality-bounded samples."""

    def __init__(
        self,
        *,
        runner: EmbeddingRunner,
        store: VoiceProfileStore,
        model_version: str,
        profile_id_factory: Callable[[], str] = lambda: str(uuid4()),
    ) -> None:
        self._runner = runner
        self._store = store
        self._model_version = model_version
        self._profile_id_factory = profile_id_factory

    def create(self, samples: Sequence[bytes]) -> VoiceProfile:
        try:
            if (
                not isinstance(samples, (tuple, list))
                or not MIN_ENROLLMENT_SAMPLES <= len(samples) <= MAX_ENROLLMENT_SAMPLES
            ):
                raise ValueError(ENROLLMENT_REJECTED)
            embeddings: list[tuple[float, ...]] = []
            for pcm in samples:
                waveform = _validated_pcm(pcm)
                observation = self._runner(waveform)
                embedding = _validated_observation(observation)
                if (
                    observation.speech_seconds < MIN_PCM_SECONDS
                    or observation.snr_db < MIN_SNR_DB
                    or observation.overlap_probability > MAX_OVERLAP_PROBABILITY
                ):
                    raise ValueError(ENROLLMENT_REJECTED)
                embeddings.append(embedding)
            centroid = np.mean(np.asarray(embeddings, dtype=np.float64), axis=0)
            norm = float(np.linalg.norm(centroid))
            if not np.isfinite(norm) or norm <= 0.0:
                raise ValueError(ENROLLMENT_REJECTED)
            centroid /= norm
            similarities = np.asarray(embeddings) @ centroid
            minimum = float(np.min(similarities))
            if not np.isfinite(minimum) or minimum < 0.70:
                raise ValueError(ENROLLMENT_REJECTED)
            accept = max(0.72, min(0.90, minimum - 0.02))
            uncertain = max(0.50, accept - 0.15)
            profile = VoiceProfile(
                profile_id=self._profile_id_factory(),
                model_version=self._model_version,
                embedding=tuple(float(value) for value in centroid),
                accept_threshold=accept,
                uncertain_threshold=uncertain,
                enrollment_quality="accepted",
            )
            self._store.create(profile)
            return profile
        except Exception:
            raise ValueError(ENROLLMENT_REJECTED) from None


def _metadata(profile: VoiceProfile) -> dict[str, object]:
    return {
        "acceptThreshold": profile.accept_threshold,
        "enrollmentQuality": profile.enrollment_quality,
        "modelVersion": profile.model_version,
        "profileId": profile.profile_id,
        "schemaVersion": _SCHEMA_VERSION,
        "uncertainThreshold": profile.uncertain_threshold,
    }


def _canonical_profile_id(profile_id: str) -> str:
    try:
        canonical = str(UUID(profile_id))
    except Exception:
        raise ValueError(PROFILE_UNAVAILABLE) from None
    if canonical != profile_id:
        raise ValueError(PROFILE_UNAVAILABLE)
    return canonical


def _canonical_json(value: object) -> bytes:
    serialized = json.dumps(
        value, ensure_ascii=True, separators=(",", ":"), sort_keys=True
    )
    return f"{serialized}\n".encode("ascii")


def _publish_exclusive(path: Path, payload: bytes) -> None:
    descriptor, temporary = tempfile.mkstemp(prefix=".voice-profile-", dir=path.parent)
    temporary_path = Path(temporary)
    try:
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "wb", closefd=True) as handle:
            descriptor = -1
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.link(temporary_path, path, follow_symlinks=False)
        directory = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        if descriptor >= 0:
            os.close(descriptor)
        temporary_path.unlink(missing_ok=True)


__all__ = [
    "ENROLLMENT_REJECTED",
    "PROFILE_UNAVAILABLE",
    "VoiceEnrollment",
    "VoiceProfileStore",
]
