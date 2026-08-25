from __future__ import annotations

import json
import stat
from pathlib import Path

import pytest

from services.voice.asr_corpus import (
    ASR_CORPUS_UNAVAILABLE,
    PRIVATE_ASR_PROMPTS,
    PrivateAsrCorpus,
)
from services.voice.keychain import KeychainSecretStore


class FakeKeychain:
    def __init__(self) -> None:
        self.values: dict[tuple[str, str], bytes] = {}

    def read(self, service: str, account: str) -> bytes | None:
        return self.values.get((service, account))

    def write(self, service: str, account: str, secret: bytes) -> None:
        self.values[(service, account)] = bytes(secret)

    def delete(self, service: str, account: str) -> None:
        self.values.pop((service, account), None)


def corpus(tmp_path: Path) -> tuple[PrivateAsrCorpus, FakeKeychain, Path]:
    backend = FakeKeychain()
    keychain = KeychainSecretStore(backend, random_bytes=lambda size: b"k" * size)
    path = tmp_path / "runtime/private/voice-asr-calibration.json"
    nonce_values = iter(bytes([index]) * 12 for index in range(1, 32))
    return (
        PrivateAsrCorpus(
            path,
            keychain,
            boundary=tmp_path,
            random_bytes=lambda size: next(nonce_values),
        ),
        backend,
        path,
    )


def test_corpus_encrypts_fixed_prompt_pcm_and_reads_it_back(tmp_path: Path) -> None:
    store, backend, path = corpus(tmp_path)
    pcm = b"\x34\x12" * 16_000

    store.append("feeding_start_dad", pcm)

    assert store.read_all() == (("feeding_start_dad", pcm),)
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert len(backend.values) == 1
    serialized = path.read_bytes()
    assert pcm[:64] not in serialized
    assert PRIVATE_ASR_PROMPTS["feeding_start_dad"].encode("utf-8") not in serialized
    envelope = json.loads(serialized.decode("ascii"))
    assert set(envelope) == {"clips", "schemaVersion"}
    assert set(envelope["clips"][0]) == {
        "ciphertext", "nonce", "pcmBytes", "promptId"
    }


def test_corpus_atomically_appends_a_fixed_prompt_batch(tmp_path: Path) -> None:
    store, backend, path = corpus(tmp_path)
    clips = tuple(
        (prompt_id, bytes([index, 0]) * 4_000)
        for index, prompt_id in enumerate(PRIVATE_ASR_PROMPTS, start=1)
    )

    store.append_many(clips)

    assert store.read_all() == clips
    assert len(backend.values) == 1
    assert stat.S_IMODE(path.stat().st_mode) == 0o600

    invalid = clips + (("free_form", b"\0\0" * 4_000),)
    with pytest.raises(ValueError, match=f"^{ASR_CORPUS_UNAVAILABLE}$"):
        store.append_many(invalid)
    assert store.read_all() == clips


def test_corpus_atomically_replaces_one_fixed_prompt_in_place(tmp_path: Path) -> None:
    store, _backend, path = corpus(tmp_path)
    original = (
        ("feeding_start_dad", b"\x01\0" * 4_000),
        ("negative_weather", b"\x02\0" * 4_000),
    )
    replacement = b"\x03\0" * 4_000
    store.append_many(original)
    before = json.loads(path.read_text(encoding="ascii"))

    store.put("negative_weather", replacement)

    after = json.loads(path.read_text(encoding="ascii"))
    assert store.read_all() == (original[0], ("negative_weather", replacement))
    assert len(after["clips"]) == 2
    assert after["clips"][0] == before["clips"][0]
    assert after["clips"][1]["nonce"] != before["clips"][1]["nonce"]
    assert after["clips"][1]["ciphertext"] != before["clips"][1]["ciphertext"]


def test_corpus_failed_replacement_preserves_original_bytes(tmp_path: Path) -> None:
    backend = FakeKeychain()
    path = tmp_path / "runtime/private/voice-asr-calibration.json"
    store = PrivateAsrCorpus(
        path,
        KeychainSecretStore(backend, random_bytes=lambda size: b"k" * size),
        boundary=tmp_path,
        random_bytes=lambda size: b"n" * size,
    )
    original = b"\x01\0" * 4_000
    store.append("negative_weather", original)
    original_envelope = path.read_bytes()

    with pytest.raises(ValueError, match=f"^{ASR_CORPUS_UNAVAILABLE}$"):
        store.put("negative_weather", b"\x02\0" * 4_000)

    assert path.read_bytes() == original_envelope
    assert store.read_all() == (("negative_weather", original),)


def test_corpus_rejects_unknown_prompt_invalid_pcm_tamper_and_overflow(
    tmp_path: Path,
) -> None:
    store, _backend, path = corpus(tmp_path)
    with pytest.raises(ValueError, match=f"^{ASR_CORPUS_UNAVAILABLE}$"):
        store.append("free_form", b"\0\0" * 16_000)
    with pytest.raises(ValueError, match=f"^{ASR_CORPUS_UNAVAILABLE}$"):
        store.append("feeding_start_dad", b"\0")

    for index in range(20):
        store.append("feeding_start_dad", bytes([index, 0]) * 4_000)
    with pytest.raises(ValueError, match=f"^{ASR_CORPUS_UNAVAILABLE}$"):
        store.append("feeding_start_dad", b"\0\0" * 4_000)

    payload = bytearray(path.read_bytes())
    payload[-8] ^= 1
    path.write_bytes(payload)
    path.chmod(0o600)
    with pytest.raises(ValueError, match=f"^{ASR_CORPUS_UNAVAILABLE}$"):
        store.read_all()


def test_corpus_refuses_to_append_to_cryptographically_invalid_history(
    tmp_path: Path,
) -> None:
    store, _backend, path = corpus(tmp_path)
    store.append("feeding_start_dad", b"\x34\x12" * 4_000)
    envelope = json.loads(path.read_text(encoding="ascii"))
    ciphertext = envelope["clips"][0]["ciphertext"]
    envelope["clips"][0]["ciphertext"] = ("A" if ciphertext[0] != "A" else "B") + ciphertext[1:]
    path.write_text(
        json.dumps(envelope, sort_keys=True, separators=(",", ":")) + "\n",
        encoding="ascii",
    )
    path.chmod(0o600)
    invalid_history = path.read_bytes()

    with pytest.raises(ValueError, match=f"^{ASR_CORPUS_UNAVAILABLE}$"):
        store.append("feeding_start_mom", b"\x78\x56" * 4_000)

    assert path.read_bytes() == invalid_history


def test_corpus_refuses_symlinked_ancestor_without_external_write(
    tmp_path: Path,
) -> None:
    outside = tmp_path / "outside"
    outside.mkdir()
    runtime = tmp_path / "runtime"
    runtime.symlink_to(outside, target_is_directory=True)
    backend = FakeKeychain()
    store = PrivateAsrCorpus(
        runtime / "private/corpus.json",
        KeychainSecretStore(backend, random_bytes=lambda size: b"k" * size),
        boundary=tmp_path,
    )

    with pytest.raises(ValueError, match=f"^{ASR_CORPUS_UNAVAILABLE}$"):
        store.append("feeding_start_dad", b"\0\0" * 4_000)

    assert list(outside.iterdir()) == []
    assert backend.values == {}
