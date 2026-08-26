"""Closed loopback transport for fixed Xiaomi camera replies."""

from __future__ import annotations

import json
import os
import stat
import tempfile
import threading
from dataclasses import asdict, dataclass
from enum import StrEnum
from pathlib import Path
from typing import Any, Protocol
from urllib.parse import urlencode
from urllib.request import OpenerDirector, ProxyHandler, Request, build_opener


_ORIGIN = "http://127.0.0.1:1984"
_INSPECT_URL = f"{_ORIGIN}/api/streams?src=source"
_MAX_BYTES = 1_048_576
_TIMEOUT_SECONDS = 2.0
_PROTOCOL = "cs2+udp"
_VIDEO_MEDIA = "video, recvonly, H265"
_INCOMING_AUDIO_MEDIA = "audio, recvonly, OPUS/48000/2"
_SENDONLY_AUDIO_MEDIA = "audio, sendonly, OPUS/48000/2"
_UNAVAILABLE = "CAMERA_REPLY_UNAVAILABLE"


class CameraReplyCode(StrEnum):
    DISABLED = "CAMERA_REPLY_DISABLED"
    NOT_PROVEN = "CAMERA_REPLY_NOT_PROVEN"
    READY = "CAMERA_REPLY_READY"
    BUSY = "CAMERA_REPLY_BUSY"
    UNAVAILABLE = "CAMERA_REPLY_UNAVAILABLE"
    REJECTED = "CAMERA_REPLY_REJECTED"
    TIMEOUT = "CAMERA_REPLY_TIMEOUT"
    AMBIGUOUS = "CAMERA_REPLY_AMBIGUOUS"
    COMPLETE = "CAMERA_REPLY_COMPLETE"


@dataclass(frozen=True, slots=True)
class CameraReplyEvidence:
    source_ready: bool
    video_ready: bool
    incoming_audio_ready: bool
    sendonly_audio_ready: bool
    protocol: str
    video_codec: str
    incoming_audio_codec: str
    sendonly_audio_codec: str


@dataclass(frozen=True, slots=True)
class CameraReplyResult:
    code: CameraReplyCode
    delivery_started: bool


@dataclass(frozen=True, slots=True)
class CameraReplyStatus:
    backend: str
    ready: bool
    last_code: CameraReplyCode
    completed_count: int
    failed_count: int
    latency_ms: int

    def __post_init__(self) -> None:
        valid_count = lambda value: (  # noqa: E731 - local closed predicate
            type(value) is int and 0 <= value <= 1_000_000_000
        )
        if (
            self.backend not in {"camera", "i9", "none"}
            or type(self.ready) is not bool
            or not isinstance(self.last_code, CameraReplyCode)
            or not valid_count(self.completed_count)
            or not valid_count(self.failed_count)
            or type(self.latency_ms) is not int
            or not 0 <= self.latency_ms <= 120_000
        ):
            raise ValueError(_UNAVAILABLE)


class _Response(Protocol):
    status: int

    def read(self, size: int) -> bytes: ...

    def close(self) -> None: ...


class _Opener(Protocol):
    def open(self, request: Request, *, timeout: float) -> _Response: ...


def _closed_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    value: dict[str, Any] = {}
    for key, item in pairs:
        if key in value:
            raise ValueError(_UNAVAILABLE)
        value[key] = item
    return value


def parse_source_media(payload: bytes) -> CameraReplyEvidence:
    if type(payload) is not bytes or not 0 < len(payload) <= _MAX_BYTES:
        raise ValueError(_UNAVAILABLE)
    try:
        document = json.loads(payload, object_pairs_hook=_closed_object)
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError):
        raise ValueError(_UNAVAILABLE) from None
    if not isinstance(document, dict):
        raise ValueError(_UNAVAILABLE)

    if "source" in document:
        if set(document) != {"source"} or not isinstance(document["source"], dict):
            raise ValueError(_UNAVAILABLE)
        stream = document["source"]
    else:
        stream = document

    if set(stream) != {"producers", "consumers"}:
        raise ValueError(_UNAVAILABLE)
    producers = stream.get("producers")
    consumers = stream.get("consumers")
    if (
        not isinstance(producers, list)
        or len(producers) != 1
        or not isinstance(producers[0], dict)
        or not isinstance(consumers, list)
    ):
        raise ValueError(_UNAVAILABLE)
    producer = producers[0]
    protocol = producer.get("protocol")
    medias = producer.get("medias")
    if (
        protocol != _PROTOCOL
        or not isinstance(medias, list)
        or any(type(media) is not str for media in medias)
        or len(medias) != 3
        or set(medias)
        != {_VIDEO_MEDIA, _INCOMING_AUDIO_MEDIA, _SENDONLY_AUDIO_MEDIA}
    ):
        raise ValueError(_UNAVAILABLE)

    return CameraReplyEvidence(
        source_ready=True,
        video_ready=True,
        incoming_audio_ready=True,
        sendonly_audio_ready=True,
        protocol=_PROTOCOL,
        video_codec="HEVC",
        incoming_audio_codec="OPUS",
        sendonly_audio_codec="OPUS",
    )


class LoopbackCameraReplyTransport:
    def __init__(
        self,
        temporary_root: Path,
        *,
        origin: str = _ORIGIN,
        opener: _Opener | OpenerDirector | None = None,
    ) -> None:
        if type(origin) is not str or origin != _ORIGIN:
            raise ValueError(_UNAVAILABLE)
        self._temporary_root = temporary_root
        self._opener = opener or build_opener(ProxyHandler({}))
        self._lock = threading.Lock()

    def inspect(self) -> CameraReplyEvidence | None:
        if not self._lock.acquire(blocking=False):
            return None
        try:
            response = self._request(Request(_INSPECT_URL, method="GET"))
            try:
                return parse_source_media(response)
            except ValueError:
                return None
        except Exception:
            return None
        finally:
            self._lock.release()

    def start(self, media: Path) -> CameraReplyResult:
        if not self._lock.acquire(blocking=False):
            return CameraReplyResult(CameraReplyCode.BUSY, False)
        try:
            resolved = self._validated_media(media)
            if resolved is None:
                return CameraReplyResult(CameraReplyCode.REJECTED, False)
            query = urlencode(
                {
                    "dst": "source",
                    "src": f"ffmpeg:{resolved}#audio=opus#input=file",
                }
            )
            request = Request(
                f"{_ORIGIN}/api/streams?{query}", data=b"", method="POST"
            )
            try:
                self._request(request)
            except Exception:
                return CameraReplyResult(CameraReplyCode.AMBIGUOUS, True)
            return CameraReplyResult(CameraReplyCode.READY, True)
        finally:
            self._lock.release()

    def stop(self) -> CameraReplyResult:
        if not self._lock.acquire(blocking=False):
            return CameraReplyResult(CameraReplyCode.BUSY, False)
        try:
            request = Request(
                f"{_ORIGIN}/api/streams?dst=source&src=",
                data=b"",
                method="POST",
            )
            try:
                self._request(request)
            except Exception:
                return CameraReplyResult(CameraReplyCode.AMBIGUOUS, False)
            return CameraReplyResult(CameraReplyCode.COMPLETE, False)
        finally:
            self._lock.release()

    def _request(self, request: Request) -> bytes:
        response: _Response | None = None
        try:
            response = self._opener.open(request, timeout=_TIMEOUT_SECONDS)
            status_code = getattr(response, "status", None)
            if type(status_code) is not int or not 200 <= status_code < 300:
                raise ValueError(_UNAVAILABLE)
            chunks: list[bytes] = []
            remaining = _MAX_BYTES + 1
            while remaining > 0:
                chunk = response.read(remaining)
                if type(chunk) is not bytes:
                    raise ValueError(_UNAVAILABLE)
                if not chunk:
                    break
                chunks.append(chunk)
                remaining -= len(chunk)
            payload = b"".join(chunks)
            if len(payload) > _MAX_BYTES:
                raise ValueError(_UNAVAILABLE)
            return payload
        finally:
            if response is not None:
                try:
                    response.close()
                except OSError:
                    pass

    def _validated_media(self, media: Path) -> Path | None:
        try:
            if not isinstance(media, Path):
                return None
            root_lstat = self._temporary_root.lstat()
            if stat.S_ISLNK(root_lstat.st_mode):
                return None
            root = self._temporary_root.resolve(strict=True)
            root_stat = os.stat(root)
            if (
                not stat.S_ISDIR(root_stat.st_mode)
                or root_stat.st_uid != os.getuid()
                or stat.S_IMODE(root_stat.st_mode) != 0o700
            ):
                return None
            media_lstat = media.lstat()
            if stat.S_ISLNK(media_lstat.st_mode):
                return None
            resolved = media.resolve(strict=True)
            if not resolved.is_relative_to(root):
                return None
            current = resolved.parent
            while True:
                directory = os.stat(current, follow_symlinks=False)
                if (
                    not stat.S_ISDIR(directory.st_mode)
                    or directory.st_uid != os.getuid()
                    or stat.S_IMODE(directory.st_mode) != 0o700
                ):
                    return None
                if current == root:
                    break
                if not current.is_relative_to(root):
                    return None
                current = current.parent
            file_stat = os.stat(resolved, follow_symlinks=False)
            if (
                not stat.S_ISREG(file_stat.st_mode)
                or file_stat.st_uid != os.getuid()
                or stat.S_IMODE(file_stat.st_mode) != 0o600
                or file_stat.st_nlink != 1
                or not 0 < file_stat.st_size <= _MAX_BYTES
            ):
                return None
            return resolved
        except (OSError, RuntimeError, ValueError):
            return None


class CameraReplyStatusWriter:
    def __init__(self, path: Path, *, boundary: Path) -> None:
        self._path = path
        self._boundary = boundary

    def write(self, status: CameraReplyStatus) -> None:
        if not isinstance(status, CameraReplyStatus):
            raise ValueError(_UNAVAILABLE)
        parent = self._validated_parent()
        document = asdict(status)
        document["last_code"] = status.last_code.value
        payload = (
            json.dumps(document, sort_keys=True, separators=(",", ":")) + "\n"
        ).encode("utf-8")
        descriptor = -1
        temporary: Path | None = None
        try:
            descriptor, name = tempfile.mkstemp(
                prefix=".camera-reply-", suffix=".tmp", dir=parent
            )
            temporary = Path(name)
            os.fchmod(descriptor, 0o600)
            os.write(descriptor, payload)
            os.fsync(descriptor)
            os.close(descriptor)
            descriptor = -1
            self._validate_existing_destination()
            os.replace(temporary, self._path)
            temporary = None
            directory_fd = os.open(parent, os.O_RDONLY)
            try:
                os.fsync(directory_fd)
            finally:
                os.close(directory_fd)
        except OSError as exc:
            raise ValueError(_UNAVAILABLE) from exc
        finally:
            if descriptor >= 0:
                os.close(descriptor)
            if temporary is not None:
                try:
                    temporary.unlink()
                except OSError:
                    pass

    def _validated_parent(self) -> Path:
        try:
            boundary_lstat = self._boundary.lstat()
            if stat.S_ISLNK(boundary_lstat.st_mode):
                raise ValueError(_UNAVAILABLE)
            boundary = self._boundary.resolve(strict=True)
            boundary_stat = os.stat(boundary, follow_symlinks=False)
            if (
                not stat.S_ISDIR(boundary_stat.st_mode)
                or boundary_stat.st_uid != os.getuid()
                or stat.S_IMODE(boundary_stat.st_mode) != 0o700
            ):
                raise ValueError(_UNAVAILABLE)
            candidate = self._path.parent.resolve(strict=False)
            if not candidate.is_relative_to(boundary):
                raise ValueError(_UNAVAILABLE)
            if not candidate.exists():
                candidate.mkdir(mode=0o700)
            parent_lstat = candidate.lstat()
            if (
                stat.S_ISLNK(parent_lstat.st_mode)
                or not stat.S_ISDIR(parent_lstat.st_mode)
                or parent_lstat.st_uid != os.getuid()
                or stat.S_IMODE(parent_lstat.st_mode) != 0o700
            ):
                raise ValueError(_UNAVAILABLE)
            return candidate
        except OSError as exc:
            raise ValueError(_UNAVAILABLE) from exc

    def _validate_existing_destination(self) -> None:
        try:
            existing = self._path.lstat()
        except FileNotFoundError:
            return
        if (
            stat.S_ISLNK(existing.st_mode)
            or not stat.S_ISREG(existing.st_mode)
            or existing.st_uid != os.getuid()
            or stat.S_IMODE(existing.st_mode) != 0o600
            or existing.st_nlink != 1
        ):
            raise ValueError(_UNAVAILABLE)


__all__ = [
    "CameraReplyCode",
    "CameraReplyEvidence",
    "CameraReplyResult",
    "CameraReplyStatus",
    "CameraReplyStatusWriter",
    "LoopbackCameraReplyTransport",
    "parse_source_media",
]
