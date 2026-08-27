"""Closed loopback transport for fixed Xiaomi camera replies."""

from __future__ import annotations

import json
import os
import stat
import tempfile
import threading
import time
from collections.abc import Callable
from dataclasses import asdict, dataclass
from enum import StrEnum
from pathlib import Path
from typing import Any, Protocol
from urllib.parse import urlencode
from urllib.request import OpenerDirector, ProxyHandler, Request, build_opener

from packages.monitoring.go2rtc_build import BuildMetadata
from services.voice.tts import (
    CancelEvent,
    CaptureDucker,
    FixedReplyRenderer,
    RenderedReply,
)


_ORIGIN = "http://127.0.0.1:1984"
_INSPECT_URL = f"{_ORIGIN}/api/streams?src=source"
_MAX_BYTES = 1_048_576
_TIMEOUT_SECONDS = 2.0
_PROTOCOL = "cs2+udp"
_VIDEO_MEDIA = "video, recvonly, H265"
_INCOMING_AUDIO_MEDIA = "audio, recvonly, OPUS/48000/2"
_SENDONLY_AUDIO_MEDIA = "audio, sendonly, OPUS/48000/2"
_UNAVAILABLE = "CAMERA_REPLY_UNAVAILABLE"
_FIXED_REPLY_CODES = frozenset(
    {"listen_only_ready", "listen_only_received"}
)
_MAX_OPERATION_SECONDS = 10.0
_STOP_RESERVE_SECONDS = 2.0
_MAX_WAIT_INCREMENT_SECONDS = 0.05
_MAX_GUARD_SECONDS = 0.5
_ACCEPTANCE_RELATIVE = Path(
    "runtime/status/voice-camera-reply-acceptance.json"
)
_ACCEPTANCE_FIELDS = frozenset(
    {
        "schema_version",
        "accepted",
        "upstream_commit",
        "patch_sha256",
        "binary_sha256",
        "protocol",
        "audio_codec",
    }
)


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
    speaker_state: str = "closed"
    speaker_session_generation: int = 0
    speaker_start_requests: int = 0
    speaker_start_responses: int = 0
    speaker_stop_commands: int = 0
    speaker_write_failures: int = 0
    speaker_stop_failures: int = 0
    pending_command_responses: int = 0
    residual_sender_count: int = 0
    last_failure_stage: str = "none"
    producer_generation: int = 0


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


class CameraReplyAcceptance:
    @classmethod
    def load(
        cls, root: Path, build_metadata: BuildMetadata
    ) -> CameraReplyEvidence | None:
        path = root / _ACCEPTANCE_RELATIVE
        if not cls._secure_leaf(root, path):
            return None
        try:
            if path.stat().st_size > 4_096:
                return None
            payload = json.loads(
                path.read_text(encoding="ascii"),
                object_pairs_hook=_closed_object,
            )
        except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValueError):
            return None
        if (
            not isinstance(payload, dict)
            or set(payload) != _ACCEPTANCE_FIELDS
            or payload["schema_version"] != 1
            or payload["accepted"] is not True
            or payload["upstream_commit"] != build_metadata.upstream_commit
            or payload["patch_sha256"] != build_metadata.patch_sha256
            or payload["binary_sha256"] != build_metadata.binary_sha256
            or payload["protocol"] != _PROTOCOL
            or payload["audio_codec"] != "opus"
        ):
            return None
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

    @classmethod
    def publish(cls, root: Path, build_metadata: BuildMetadata) -> bool:
        path = root / _ACCEPTANCE_RELATIVE
        try:
            root = root.resolve(strict=True)
            parent = path.parent
            if not parent.exists():
                runtime = root / "runtime"
                if not runtime.exists():
                    runtime.mkdir(mode=0o700)
                parent.mkdir(mode=0o700)
            if not cls._secure_parents(root, parent):
                return False
            if path.exists() or path.is_symlink():
                leaf = path.lstat()
                if (
                    stat.S_ISLNK(leaf.st_mode)
                    or not stat.S_ISREG(leaf.st_mode)
                    or leaf.st_uid != os.getuid()
                    or stat.S_IMODE(leaf.st_mode) != 0o600
                    or leaf.st_nlink != 1
                ):
                    return False
            document = {
                "schema_version": 1,
                "accepted": True,
                "upstream_commit": build_metadata.upstream_commit,
                "patch_sha256": build_metadata.patch_sha256,
                "binary_sha256": build_metadata.binary_sha256,
                "protocol": _PROTOCOL,
                "audio_codec": "opus",
            }
            payload = (
                json.dumps(document, sort_keys=True, separators=(",", ":"))
                + "\n"
            ).encode("ascii")
            descriptor, temporary_name = tempfile.mkstemp(
                prefix=".voice-camera-acceptance-",
                suffix=".tmp",
                dir=parent,
            )
            temporary = Path(temporary_name)
            try:
                os.fchmod(descriptor, 0o600)
                os.write(descriptor, payload)
                os.fsync(descriptor)
            finally:
                os.close(descriptor)
            os.replace(temporary, path)
            directory_fd = os.open(parent, os.O_RDONLY)
            try:
                os.fsync(directory_fd)
            finally:
                os.close(directory_fd)
            return True
        except (OSError, RuntimeError, ValueError):
            try:
                temporary.unlink()
            except (NameError, OSError):
                pass
            return False

    @staticmethod
    def _secure_parents(root: Path, parent: Path) -> bool:
        try:
            root = root.resolve(strict=True)
            current = parent
            while True:
                item = current.lstat()
                if (
                    stat.S_ISLNK(item.st_mode)
                    or not stat.S_ISDIR(item.st_mode)
                    or item.st_uid != os.getuid()
                ):
                    return False
                if current.resolve(strict=True) == root:
                    return True
                if not current.resolve(strict=True).is_relative_to(root):
                    return False
                current = current.parent
        except (OSError, RuntimeError):
            return False

    @classmethod
    def _secure_leaf(cls, root: Path, path: Path) -> bool:
        try:
            if not cls._secure_parents(root, path.parent):
                return False
            leaf = path.lstat()
            return bool(
                not stat.S_ISLNK(leaf.st_mode)
                and stat.S_ISREG(leaf.st_mode)
                and leaf.st_uid == os.getuid()
                and stat.S_IMODE(leaf.st_mode) == 0o600
                and leaf.st_nlink == 1
            )
        except OSError:
            return False


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
    return _parse_source_media_lifecycle(
        payload, expected_state="closed", expected_generation=None
    )


def _parse_source_media_lifecycle(
    payload: bytes,
    *,
    expected_state: str,
    expected_generation: int | None,
) -> CameraReplyEvidence:
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

    lifecycle_fields = {
        "speaker_session_generation",
        "speaker_start_requests",
        "speaker_start_responses",
        "speaker_stop_commands",
        "speaker_write_failures",
        "speaker_stop_failures",
        "pending_command_responses",
        "residual_sender_count",
        "producer_generation",
    }
    if any(
        type(producer.get(field)) is not int
        or not 0 <= producer[field] <= 1_000_000_000
        for field in lifecycle_fields
    ):
        raise ValueError(_UNAVAILABLE)
    generation = producer["speaker_session_generation"]
    if expected_state == "active":
        expected_stop_commands = generation - 1
        expected_residual_senders = 1
    elif expected_state == "closed":
        expected_stop_commands = generation
        expected_residual_senders = 0
    else:
        raise ValueError(_UNAVAILABLE)
    if (
        producer.get("speaker_state") != expected_state
        or (expected_state == "active" and generation == 0)
        or (
            expected_generation is not None
            and generation != expected_generation
        )
        or producer.get("last_failure_stage") != "none"
        or producer["pending_command_responses"] != 0
        or producer["residual_sender_count"] != expected_residual_senders
        or producer["producer_generation"] != generation
        or producer["speaker_start_requests"] != generation
        or producer["speaker_start_responses"] != generation
        or producer["speaker_stop_commands"] != expected_stop_commands
        or producer["speaker_write_failures"] != 0
        or producer["speaker_stop_failures"] != 0
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
        speaker_state=producer["speaker_state"],
        speaker_session_generation=producer["speaker_session_generation"],
        speaker_start_requests=producer["speaker_start_requests"],
        speaker_start_responses=producer["speaker_start_responses"],
        speaker_stop_commands=producer["speaker_stop_commands"],
        speaker_write_failures=producer["speaker_write_failures"],
        speaker_stop_failures=producer["speaker_stop_failures"],
        pending_command_responses=producer["pending_command_responses"],
        residual_sender_count=producer["residual_sender_count"],
        last_failure_stage=producer["last_failure_stage"],
        producer_generation=producer["producer_generation"],
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
        self._active_generation: int | None = None

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
            if self._active_generation is not None:
                return CameraReplyResult(CameraReplyCode.BUSY, False)
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
                payload = self._request(request)
                evidence = _parse_source_media_lifecycle(
                    payload,
                    expected_state="active",
                    expected_generation=None,
                )
            except Exception:
                return CameraReplyResult(CameraReplyCode.AMBIGUOUS, True)
            self._active_generation = evidence.speaker_session_generation
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
                payload = self._request(request)
                if self._active_generation is None:
                    raise ValueError(_UNAVAILABLE)
                _parse_source_media_lifecycle(
                    payload,
                    expected_state="closed",
                    expected_generation=self._active_generation,
                )
            except Exception:
                return CameraReplyResult(CameraReplyCode.AMBIGUOUS, False)
            self._active_generation = None
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


class _CameraTransport(Protocol):
    def inspect(self) -> CameraReplyEvidence | None: ...

    def start(self, media: Path) -> CameraReplyResult: ...

    def stop(self) -> CameraReplyResult: ...


class _ReplyRenderer(Protocol):
    def render(
        self, code: str, cancelled: CancelEvent
    ) -> RenderedReply | None: ...


class _StatusWriter(Protocol):
    def write(self, status: CameraReplyStatus) -> None: ...


class _CameraOutput(Protocol):
    def deliver_code(
        self, code: str, cancelled: CancelEvent
    ) -> CameraReplyResult: ...


class _FallbackOutput(Protocol):
    def speak_code(self, code: str, cancelled: CancelEvent) -> bool: ...


class CameraPreferredVoiceOutput:
    """Use i9 fallback only when the camera send has certainly not begun."""

    def __init__(
        self, camera: _CameraOutput, fallback: _FallbackOutput
    ) -> None:
        self._camera = camera
        self._fallback = fallback

    def speak_code(self, code: str, cancelled: CancelEvent) -> bool:
        if cancelled.is_set():
            return False
        try:
            result = self._camera.deliver_code(code, cancelled)
        except Exception:
            return False
        if result.code is CameraReplyCode.COMPLETE and result.delivery_started:
            return True
        if (
            not result.delivery_started
            and result.code
            in {
                CameraReplyCode.DISABLED,
                CameraReplyCode.NOT_PROVEN,
                CameraReplyCode.UNAVAILABLE,
            }
        ):
            if cancelled.is_set():
                return False
            try:
                return bool(self._fallback.speak_code(code, cancelled))
            except Exception:
                return False
        return False


class CameraReplyOutput:
    """Settle one fixed camera reply without overlapping or retrying."""

    def __init__(
        self,
        *,
        transport: _CameraTransport,
        renderer: _ReplyRenderer,
        ducker: CaptureDucker,
        status_writer: _StatusWriter | None = None,
        monotonic: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
        post_playback_guard_seconds: float = _MAX_GUARD_SECONDS,
    ) -> None:
        if not 0.0 <= post_playback_guard_seconds <= _MAX_GUARD_SECONDS:
            raise ValueError(_UNAVAILABLE)
        self._transport = transport
        self._renderer = renderer
        self._ducker = ducker
        self._status_writer = status_writer
        self._monotonic = monotonic
        self._sleep = sleep
        self._guard_seconds = post_playback_guard_seconds
        self._operation_lock = threading.Lock()
        self._completed_count = 0
        self._failed_count = 0

    def speak_code(self, code: str, cancelled: CancelEvent) -> bool:
        return self.deliver_code(code, cancelled).code is CameraReplyCode.COMPLETE

    def deliver_code(
        self, code: str, cancelled: CancelEvent
    ) -> CameraReplyResult:
        started_at = self._monotonic()
        if type(code) is not str or code not in _FIXED_REPLY_CODES:
            return self._record(
                CameraReplyResult(CameraReplyCode.REJECTED, False), started_at
            )
        if not self._operation_lock.acquire(blocking=False):
            return self._record(
                CameraReplyResult(CameraReplyCode.BUSY, False), started_at
            )

        paused = False
        rendered: RenderedReply | None = None
        result = CameraReplyResult(CameraReplyCode.UNAVAILABLE, False)
        try:
            self._ducker.pause()
            paused = True
            evidence = self._transport.inspect()
            if evidence is None:
                result = CameraReplyResult(CameraReplyCode.UNAVAILABLE, False)
            else:
                rendered = self._renderer.render(code, cancelled)
                if rendered is None:
                    result = CameraReplyResult(CameraReplyCode.UNAVAILABLE, False)
                else:
                    result = self._deliver_rendered(
                        rendered, cancelled, started_at
                    )
        except Exception:
            result = CameraReplyResult(CameraReplyCode.UNAVAILABLE, False)
        finally:
            settlement_failed = False
            try:
                if rendered is not None:
                    try:
                        rendered.path.unlink()
                    except OSError:
                        pass
                if paused:
                    if self._guard_seconds:
                        try:
                            remaining = max(
                                0.0,
                                started_at
                                + _MAX_OPERATION_SECONDS
                                - self._monotonic(),
                            )
                            self._sleep(min(self._guard_seconds, remaining))
                        except Exception:
                            settlement_failed = True
                    try:
                        self._ducker.resume()
                    except Exception:
                        settlement_failed = True
                if settlement_failed:
                    result = CameraReplyResult(
                        CameraReplyCode.AMBIGUOUS
                        if result.delivery_started
                        else CameraReplyCode.UNAVAILABLE,
                        result.delivery_started,
                    )
            finally:
                self._operation_lock.release()
        return self._record(result, started_at)

    def _deliver_rendered(
        self,
        rendered: RenderedReply,
        cancelled: CancelEvent,
        started_at: float,
    ) -> CameraReplyResult:
        start_result = self._transport.start(rendered.path)
        if not start_result.delivery_started:
            return start_result

        waited = False
        try:
            if start_result.code is CameraReplyCode.READY:
                waited = self._wait_for_reply(
                    rendered.duration_seconds, cancelled, started_at
                )
        except Exception:
            waited = False
        finally:
            try:
                stop_result = self._transport.stop()
            except Exception:
                stop_result = CameraReplyResult(
                    CameraReplyCode.AMBIGUOUS, False
                )
        if (
            start_result.code is CameraReplyCode.READY
            and waited
            and stop_result.code is CameraReplyCode.COMPLETE
        ):
            return CameraReplyResult(CameraReplyCode.COMPLETE, True)
        return CameraReplyResult(CameraReplyCode.AMBIGUOUS, True)

    def _wait_for_reply(
        self,
        duration_seconds: float,
        cancelled: CancelEvent,
        started_at: float,
    ) -> bool:
        duration_deadline = self._monotonic() + duration_seconds
        reserved_deadline = (
            started_at
            + _MAX_OPERATION_SECONDS
            - _STOP_RESERVE_SECONDS
            - self._guard_seconds
        )
        while self._monotonic() < duration_deadline:
            if cancelled.is_set() or self._monotonic() >= reserved_deadline:
                return False
            remaining = min(
                duration_deadline - self._monotonic(),
                reserved_deadline - self._monotonic(),
                _MAX_WAIT_INCREMENT_SECONDS,
            )
            if remaining <= 0:
                return False
            self._sleep(remaining)
        return not cancelled.is_set()

    def _record(
        self, result: CameraReplyResult, started_at: float
    ) -> CameraReplyResult:
        if result.code is CameraReplyCode.COMPLETE:
            self._completed_count += 1
        elif result.code is not CameraReplyCode.BUSY:
            self._failed_count += 1
        writer = self._status_writer
        if writer is not None:
            latency_ms = min(
                120_000,
                max(0, int((self._monotonic() - started_at) * 1000)),
            )
            try:
                writer.write(
                    CameraReplyStatus(
                        backend="camera",
                        ready=result.code is CameraReplyCode.COMPLETE,
                        last_code=result.code,
                        completed_count=self._completed_count,
                        failed_count=self._failed_count,
                        latency_ms=latency_ms,
                    )
                )
            except Exception:
                pass
        return result


__all__ = [
    "CameraReplyAcceptance",
    "CameraReplyCode",
    "CameraReplyEvidence",
    "CameraReplyOutput",
    "CameraPreferredVoiceOutput",
    "CameraReplyResult",
    "CameraReplyStatus",
    "CameraReplyStatusWriter",
    "FixedReplyRenderer",
    "LoopbackCameraReplyTransport",
    "RenderedReply",
    "parse_source_media",
]
