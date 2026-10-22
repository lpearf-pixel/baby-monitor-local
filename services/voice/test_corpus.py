"""Opt-in encrypted storage for bounded local Voice test sessions."""

from __future__ import annotations

import hashlib
import json
import os
import re
import stat
import tempfile
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path

from cryptography.fernet import Fernet, InvalidToken


_ERROR = "voice_test_corpus_unavailable"
_CONSENT_REQUIRED = "voice_test_consent_required"
_MAX_AUDIO_BYTES = 2 * 1024 * 1024
_RETENTION = timedelta(days=7)
_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,79}$")
_FIELDS = frozenset(
    {
        "test_id",
        "session_id",
        "created_at",
        "audio_file",
        "audio_sha256",
        "recognized_text",
        "expected_text",
        "actual_reply",
        "expected_reply",
        "latency_ms",
        "playback_status",
        "error_code",
        "consent_reference",
    }
)


class VoiceTestCorpusStore:
    def __init__(
        self,
        root: Path,
        *,
        key_provider: Callable[[], bytes],
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._root = Path(root)
        self._key_provider = key_provider
        self._clock = clock or (lambda: datetime.now(UTC))
        self._ensure_layout()

    def enable(self, consent_reference: str) -> None:
        if not _valid_reference(consent_reference):
            raise ValueError(_ERROR)
        self._write_json(
            self._root / "consent.json",
            {
                "enabled": True,
                "consent_reference": consent_reference,
                "updated_at": _timestamp(self._clock()),
            },
        )

    def disable(self) -> None:
        current = self._consent()
        self._write_json(
            self._root / "consent.json",
            {
                "enabled": False,
                "consent_reference": current.get("consent_reference"),
                "updated_at": _timestamp(self._clock()),
            },
        )

    def consent_status(self) -> dict[str, object]:
        return dict(self._consent())

    def record(
        self,
        *,
        test_id: str,
        session_id: str,
        created_at: datetime,
        audio: bytes,
        recognized_text: str,
        expected_text: str,
        actual_reply: str,
        expected_reply: str,
        latency_ms: int,
        playback_status: str,
        error_code: str | None,
    ) -> dict[str, object]:
        consent = self._consent()
        if consent.get("enabled") is not True:
            raise ValueError(_CONSENT_REQUIRED)
        if (
            not _valid_id(test_id)
            or not _valid_id(session_id)
            or not isinstance(created_at, datetime)
            or created_at.tzinfo is None
            or type(audio) is not bytes
            or not 0 < len(audio) <= _MAX_AUDIO_BYTES
            or not all(isinstance(value, str) for value in (
                recognized_text,
                expected_text,
                actual_reply,
                expected_reply,
                playback_status,
            ))
            or type(latency_ms) is not int
            or not 0 <= latency_ms <= 120_000
            or (error_code is not None and not isinstance(error_code, str))
        ):
            raise ValueError(_ERROR)
        key = self._key()
        relative_audio = f"audio/{test_id}.bin.enc"
        audio_path = self._root / relative_audio
        metadata_path = self._root / "records" / f"{test_id}.json"
        if audio_path.exists() or metadata_path.exists():
            raise ValueError(_ERROR)
        document: dict[str, object] = {
            "test_id": test_id,
            "session_id": session_id,
            "created_at": _timestamp(created_at),
            "audio_file": relative_audio,
            "audio_sha256": hashlib.sha256(audio).hexdigest(),
            "recognized_text": recognized_text,
            "expected_text": expected_text,
            "actual_reply": actual_reply,
            "expected_reply": expected_reply,
            "latency_ms": latency_ms,
            "playback_status": playback_status,
            "error_code": error_code,
            "consent_reference": consent["consent_reference"],
        }
        try:
            self._write_bytes(audio_path, Fernet(key).encrypt(audio))
            self._write_json(metadata_path, document)
        except Exception:
            _unlink(audio_path)
            _unlink(metadata_path)
            raise ValueError(_ERROR) from None
        return document

    def list_records(self) -> list[dict[str, object]]:
        records: list[dict[str, object]] = []
        for path in sorted((self._root / "records").glob("*.json")):
            try:
                self._require_private_file(path)
                payload = json.loads(path.read_text(encoding="ascii"))
                if not isinstance(payload, dict) or set(payload) != _FIELDS:
                    raise ValueError
                records.append(payload)
            except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValueError):
                raise ValueError(_ERROR) from None
        return records

    def read_audio(self, test_id: str) -> bytes:
        record = next(
            (item for item in self.list_records() if item["test_id"] == test_id),
            None,
        )
        if record is None:
            raise ValueError(_ERROR)
        try:
            audio_path = self._safe_relative(record["audio_file"])
            decrypted = Fernet(self._key()).decrypt(audio_path.read_bytes())
        except (OSError, InvalidToken, ValueError):
            raise ValueError(_ERROR) from None
        if hashlib.sha256(decrypted).hexdigest() != record["audio_sha256"]:
            raise ValueError(_ERROR)
        return decrypted

    def delete(self, test_id: str) -> bool:
        if not _valid_id(test_id):
            raise ValueError(_ERROR)
        paths = (
            self._root / "records" / f"{test_id}.json",
            self._root / "audio" / f"{test_id}.bin.enc",
        )
        existed = any(path.exists() for path in paths)
        for path in paths:
            _unlink(path)
        return existed

    def delete_all(self) -> int:
        records = self.list_records()
        for record in records:
            self.delete(str(record["test_id"]))
        return len(records)

    def purge_expired(self, now: datetime | None = None) -> tuple[str, ...]:
        current = now or self._clock()
        if current.tzinfo is None:
            raise ValueError(_ERROR)
        deleted: list[str] = []
        for record in self.list_records():
            created = _parse_timestamp(record["created_at"])
            if current - created > _RETENTION:
                test_id = str(record["test_id"])
                self.delete(test_id)
                deleted.append(test_id)
        return tuple(deleted)

    def _ensure_layout(self) -> None:
        self._mkdir_private(self._root)
        self._mkdir_private(self._root / "audio")
        self._mkdir_private(self._root / "records")
        for path in (self._root, self._root / "audio", self._root / "records"):
            self._require_private_dir(path)

    def _consent(self) -> dict[str, object]:
        path = self._root / "consent.json"
        if not path.exists():
            return {"enabled": False, "consent_reference": None}
        try:
            payload = json.loads(path.read_text(encoding="ascii"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError):
            raise ValueError(_ERROR) from None
        if (
            not isinstance(payload, dict)
            or set(payload) != {"enabled", "consent_reference", "updated_at"}
            or type(payload["enabled"]) is not bool
            or (
                payload["consent_reference"] is not None
                and not _valid_reference(payload["consent_reference"])
            )
        ):
            raise ValueError(_ERROR)
        return payload

    def _key(self) -> bytes:
        try:
            key = self._key_provider()
            Fernet(key)
        except Exception:
            raise ValueError(_ERROR) from None
        return key

    def _safe_relative(self, relative: object) -> Path:
        if not isinstance(relative, str):
            raise ValueError(_ERROR)
        current = self._root
        relative_path = Path(relative)
        if relative_path.is_absolute() or not relative_path.parts:
            raise ValueError(_ERROR)
        for component in relative_path.parts:
            current = current / component
            if current.is_symlink():
                raise ValueError(_ERROR)
        path = (self._root / relative).resolve(strict=True)
        if not path.is_relative_to(self._root.resolve(strict=True)):
            raise ValueError(_ERROR)
        self._require_private_file(path)
        return path

    @staticmethod
    def _mkdir_private(path: Path) -> None:
        path.mkdir(parents=True, exist_ok=True, mode=0o700)
        os.chmod(path, 0o700)

    @staticmethod
    def _require_private_dir(path: Path) -> None:
        item = path.lstat()
        if (
            stat.S_ISLNK(item.st_mode)
            or not stat.S_ISDIR(item.st_mode)
            or item.st_uid != os.getuid()
            or stat.S_IMODE(item.st_mode) != 0o700
        ):
            raise ValueError(_ERROR)

    @staticmethod
    def _require_private_file(path: Path) -> None:
        item = path.lstat()
        if (
            stat.S_ISLNK(item.st_mode)
            or not stat.S_ISREG(item.st_mode)
            or item.st_uid != os.getuid()
            or stat.S_IMODE(item.st_mode) != 0o600
        ):
            raise ValueError(_ERROR)

    @staticmethod
    def _write_bytes(path: Path, data: bytes) -> None:
        descriptor, name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
        temporary = Path(name)
        try:
            os.fchmod(descriptor, 0o600)
            os.write(descriptor, data)
            os.fsync(descriptor)
            os.close(descriptor)
            descriptor = -1
            os.replace(temporary, path)
        finally:
            if descriptor >= 0:
                os.close(descriptor)
            _unlink(temporary)

    @classmethod
    def _write_json(cls, path: Path, payload: dict[str, object]) -> None:
        encoded = (json.dumps(payload, ensure_ascii=True, sort_keys=True) + "\n").encode(
            "ascii"
        )
        cls._write_bytes(path, encoded)


def _valid_id(value: object) -> bool:
    return isinstance(value, str) and _ID.fullmatch(value) is not None


def _valid_reference(value: object) -> bool:
    return (
        isinstance(value, str)
        and 1 <= len(value) <= 128
        and not any(character.isspace() for character in value)
    )


def _timestamp(value: datetime) -> str:
    if not isinstance(value, datetime) or value.tzinfo is None:
        raise ValueError(_ERROR)
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _parse_timestamp(value: object) -> datetime:
    if not isinstance(value, str):
        raise ValueError(_ERROR)
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        raise ValueError(_ERROR) from None


def _unlink(path: Path) -> None:
    try:
        path.unlink()
    except FileNotFoundError:
        pass


__all__ = ["VoiceTestCorpusStore"]
