"""Encrypted, bounded private corpus for supervised ASR calibration only."""

from __future__ import annotations

import base64
import json
import os
import secrets
import stat
import tempfile
from collections.abc import Callable
from pathlib import Path

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from services.voice.keychain import KeychainSecretStore


ASR_CORPUS_UNAVAILABLE = "voice_asr_corpus_unavailable"
LEGACY_ASR_CORPUS_KEY_ACCOUNT = "voice-asr-calibration-key.v1"
ASR_CORPUS_KEY_ACCOUNT = "voice-asr-calibration-key.v2"
PRIVATE_ASR_PROMPTS = {
    "feeding_start_dad": "小小，我是爸爸，现在开始喂奶",
    "feeding_start_mom": "小小，我是妈妈，现在开始喂奶",
    "feeding_amount": "小小，宝宝喝了九十毫升配方奶",
    "feeding_finish": "小小，喂奶结束",
    "care_cancel": "小小，取消这次记录",
    "negative_weather": "今天天气不错",
}
_SCHEMA_VERSION = 1
_MIN_PCM_BYTES = 8_000
_MAX_PCM_BYTES = 256_000
_MAX_CLIPS = 20
_MAX_CORPUS_BYTES = 8 * 1024 * 1024


class PrivateAsrCorpus:
    """Persist only encrypted fixed-prompt PCM under one private boundary."""

    def __init__(
        self,
        path: Path,
        keychain: KeychainSecretStore,
        *,
        boundary: Path,
        random_bytes: Callable[[int], bytes] = secrets.token_bytes,
    ) -> None:
        self._path = path
        self._keychain = keychain
        self._random_bytes = random_bytes
        try:
            if boundary.is_symlink():
                raise ValueError
            self._boundary = boundary.resolve(strict=True)
            if not self._boundary.is_dir():
                raise ValueError
        except Exception:
            raise ValueError(ASR_CORPUS_UNAVAILABLE) from None

    def append(self, prompt_id: str, pcm: bytes) -> None:
        self.append_many(((prompt_id, pcm),))

    def append_many(self, values: tuple[tuple[str, bytes], ...]) -> None:
        key_created = False
        try:
            if type(values) is not tuple or not values:
                raise ValueError
            checked_values: list[tuple[str, bytes]] = []
            for value in values:
                if (
                    type(value) is not tuple
                    or len(value) != 2
                    or value[0] not in PRIVATE_ASR_PROMPTS
                ):
                    raise ValueError
                checked_values.append((value[0], _validated_pcm(value[1])))
            self._validate_boundary()
            existing = self._read_envelope()
            clips = [] if existing is None else list(existing["clips"])
            if len(clips) + len(checked_values) > _MAX_CLIPS:
                raise ValueError
            key = self._keychain.read(ASR_CORPUS_KEY_ACCOUNT, size=32)
            if key is None:
                if existing is not None:
                    raise ValueError
                key = self._keychain.get_or_create(ASR_CORPUS_KEY_ACCOUNT, size=32)
                key_created = True
            elif existing is not None:
                self._decrypt_clips(existing, key)
            used_nonces = {
                base64.b64decode(clip["nonce"], validate=True) for clip in clips
            }
            for prompt_id, checked_pcm in checked_values:
                nonce = self._random_bytes(12)
                if type(nonce) is not bytes or len(nonce) != 12 or nonce in used_nonces:
                    raise ValueError
                used_nonces.add(nonce)
                metadata = {"pcmBytes": len(checked_pcm), "promptId": prompt_id}
                ciphertext = AESGCM(key).encrypt(
                    nonce, checked_pcm, _canonical_json(metadata)
                )
                clips.append(
                    {
                        **metadata,
                        "ciphertext": base64.b64encode(ciphertext).decode("ascii"),
                        "nonce": base64.b64encode(nonce).decode("ascii"),
                    }
                )
            payload = _canonical_json(
                {"clips": clips, "schemaVersion": _SCHEMA_VERSION}
            )
            if len(payload) > _MAX_CORPUS_BYTES:
                raise ValueError
            self._publish(payload)
        except Exception:
            if key_created and not self._path.exists() and not self._path.is_symlink():
                try:
                    self._keychain.delete(ASR_CORPUS_KEY_ACCOUNT)
                except Exception:
                    pass
            raise ValueError(ASR_CORPUS_UNAVAILABLE) from None

    def read_all(self) -> tuple[tuple[str, bytes], ...]:
        try:
            self._validate_boundary()
            envelope = self._read_envelope()
            key = self._keychain.read(ASR_CORPUS_KEY_ACCOUNT, size=32)
            if envelope is None:
                if key is not None:
                    raise ValueError
                return ()
            if key is None:
                raise ValueError
            return self._decrypt_clips(envelope, key)
        except Exception:
            raise ValueError(ASR_CORPUS_UNAVAILABLE) from None

    def _decrypt_clips(
        self, envelope: dict[str, object], key: bytes
    ) -> tuple[tuple[str, bytes], ...]:
        values: list[tuple[str, bytes]] = []
        for clip in envelope["clips"]:
            metadata = {
                "pcmBytes": clip["pcmBytes"],
                "promptId": clip["promptId"],
            }
            nonce = base64.b64decode(clip["nonce"], validate=True)
            ciphertext = base64.b64decode(clip["ciphertext"], validate=True)
            if len(nonce) != 12 or len(ciphertext) < 16:
                raise ValueError
            pcm = AESGCM(key).decrypt(
                nonce, ciphertext, _canonical_json(metadata)
            )
            if len(pcm) != clip["pcmBytes"]:
                raise ValueError
            values.append((clip["promptId"], _validated_pcm(pcm)))
        return tuple(values)

    def _read_envelope(self) -> dict[str, object] | None:
        if not self._path.exists() and not self._path.is_symlink():
            return None
        descriptor = os.open(self._path, os.O_RDONLY | os.O_NOFOLLOW)
        try:
            value = os.fstat(descriptor)
            with os.fdopen(descriptor, "rb", closefd=True) as handle:
                descriptor = -1
                payload = handle.read(_MAX_CORPUS_BYTES + 1)
        finally:
            if descriptor >= 0:
                os.close(descriptor)
        if (
            not stat.S_ISREG(value.st_mode)
            or stat.S_IMODE(value.st_mode) != 0o600
            or not 0 < value.st_size <= _MAX_CORPUS_BYTES
            or len(payload) != value.st_size
        ):
            raise ValueError
        envelope = json.loads(payload.decode("ascii"))
        if (
            not isinstance(envelope, dict)
            or set(envelope) != {"clips", "schemaVersion"}
            or envelope["schemaVersion"] != _SCHEMA_VERSION
            or not isinstance(envelope["clips"], list)
            or not 0 < len(envelope["clips"]) <= _MAX_CLIPS
            or payload != _canonical_json(envelope)
        ):
            raise ValueError
        nonces: set[str] = set()
        for clip in envelope["clips"]:
            if (
                not isinstance(clip, dict)
                or set(clip) != {"ciphertext", "nonce", "pcmBytes", "promptId"}
                or clip["promptId"] not in PRIVATE_ASR_PROMPTS
                or type(clip["pcmBytes"]) is not int
                or not _MIN_PCM_BYTES <= clip["pcmBytes"] <= _MAX_PCM_BYTES
                or clip["pcmBytes"] % 2
                or type(clip["nonce"]) is not str
                or type(clip["ciphertext"]) is not str
                or clip["nonce"] in nonces
            ):
                raise ValueError
            nonces.add(clip["nonce"])
        return envelope

    def _publish(self, payload: bytes) -> None:
        parent = self._path.parent
        parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        self._validate_boundary()
        parent.chmod(0o700)
        descriptor, name = tempfile.mkstemp(prefix=".voice-asr-", dir=parent)
        temporary = Path(name)
        try:
            os.fchmod(descriptor, 0o600)
            with os.fdopen(descriptor, "wb") as output:
                descriptor = -1
                output.write(payload)
                output.flush()
                os.fsync(output.fileno())
            os.replace(temporary, self._path)
        finally:
            if descriptor >= 0:
                os.close(descriptor)
            if temporary.exists():
                temporary.unlink()

    def _validate_boundary(self) -> None:
        try:
            relative = self._path.relative_to(self._boundary)
            if not relative.parts or relative.is_absolute() or ".." in relative.parts:
                raise ValueError
            current = self._boundary
            for part in relative.parts[:-1]:
                current = current / part
                if current.is_symlink() or (current.exists() and not current.is_dir()):
                    raise ValueError
        except Exception:
            raise ValueError(ASR_CORPUS_UNAVAILABLE) from None


def _validated_pcm(pcm: bytes) -> bytes:
    if (
        type(pcm) is not bytes
        or not _MIN_PCM_BYTES <= len(pcm) <= _MAX_PCM_BYTES
        or len(pcm) % 2
    ):
        raise ValueError
    return pcm


def _canonical_json(value: object) -> bytes:
    return (json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n").encode(
        "ascii"
    )


__all__ = [
    "ASR_CORPUS_UNAVAILABLE",
    "PRIVATE_ASR_PROMPTS",
    "PrivateAsrCorpus",
]
