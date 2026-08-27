"""Fixed, bounded macOS speech output for closed Voice Care semantic codes."""

from __future__ import annotations

import os
import stat
import struct
import subprocess
import tempfile
import time
from dataclasses import dataclass
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Protocol


VOICE_TTS_UNAVAILABLE = "voice_tts_unavailable"
RESPONSE_PHRASES = {
    "accepted_pending": "好的，已经开始记录，结束后我会再确认。",
    "saved": "好的，已经记录。",
    "needs_identity": "请先确认是谁在照护。",
    "needs_confirmation": "请确认后再保存。",
    "identity_mismatch": "说话人身份不匹配，请人工确认。",
    "state_conflict": "当前记录状态有变化，请人工确认。",
    "temporarily_unavailable": "我听到了，但还没有保存，请稍后确认。",
    "rejected": "这次请求未被接受，请人工确认。",
    "listen_only_ready": "我在，请说。",
    "listen_only_received": "我听到了。",
}
_PLAYBACK_TIMEOUT_SECONDS = 10.0
_POST_PLAYBACK_GUARD_SECONDS = 0.5
_RENDER_TIMEOUT_SECONDS = 10.0
_MAX_RENDERED_BYTES = 1_048_576
_MIN_RENDERED_SECONDS = 0.20
_MAX_RENDERED_SECONDS = 4.00
_CAMERA_REPLY_CODES = frozenset(
    {"listen_only_ready", "listen_only_received"}
)
_ALL_FIXED_CODES = frozenset(RESPONSE_PHRASES)
_AIFF_16000_EXTENDED = b"\x40\x0c\xfa\x00\x00\x00\x00\x00\x00\x00"


class CancelEvent(Protocol):
    def is_set(self) -> bool: ...


class CaptureDucker(Protocol):
    def pause(self) -> None: ...

    def capture_tail(self) -> None: ...

    def discard_tail(self) -> None: ...

    def resume(self) -> None: ...


class CommandRunner(Protocol):
    def run(
        self,
        command: Sequence[str],
        *,
        input_bytes: bytes | None,
        timeout_seconds: float,
        cancelled: CancelEvent,
    ) -> bool: ...


class NoopCaptureDucker:
    def pause(self) -> None:
        return None

    def capture_tail(self) -> None:
        return None

    def discard_tail(self) -> None:
        return None

    def resume(self) -> None:
        return None


@dataclass(frozen=True, slots=True)
class RenderedReply:
    path: Path
    duration_seconds: float
    temporary_root: Path


class BoundedCommandRunner:
    """Run fixed local commands with cancellation and no inherited output."""

    def __init__(
        self,
        *,
        opener: Callable[..., subprocess.Popen[bytes]] = subprocess.Popen,
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        self._opener = opener
        self._monotonic = monotonic

    def run(
        self,
        command: Sequence[str],
        *,
        input_bytes: bytes | None,
        timeout_seconds: float,
        cancelled: CancelEvent,
    ) -> bool:
        if cancelled.is_set() or not command or not 0.1 <= timeout_seconds <= 30.0:
            return False
        process: subprocess.Popen[bytes] | None = None
        try:
            process = self._opener(
                tuple(command),
                stdin=subprocess.PIPE if input_bytes is not None else subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                start_new_session=True,
            )
            deadline = self._monotonic() + timeout_seconds
            pending = input_bytes
            while True:
                if cancelled.is_set() or self._monotonic() >= deadline:
                    _stop_process(process)
                    return False
                try:
                    process.communicate(input=pending, timeout=0.05)
                    return process.returncode == 0
                except subprocess.TimeoutExpired:
                    pending = None
        except (OSError, ValueError, subprocess.SubprocessError):
            if process is not None:
                _stop_process(process)
            return False


class FixedReplyRenderer:
    """Generate one bounded fixed phrase as validated linear-PCM AIFF."""

    def __init__(
        self,
        *,
        runner: CommandRunner,
        temporary_root: Path | None = None,
        _accepted_codes: frozenset[str] = _CAMERA_REPLY_CODES,
    ) -> None:
        if not _accepted_codes or not _accepted_codes.issubset(_ALL_FIXED_CODES):
            raise ValueError(VOICE_TTS_UNAVAILABLE)
        self._runner = runner
        self._temporary_root = temporary_root
        self._accepted_codes = _accepted_codes

    def render(
        self, code: str, cancelled: CancelEvent
    ) -> RenderedReply | None:
        if (
            type(code) is not str
            or code not in self._accepted_codes
            or cancelled.is_set()
        ):
            return None
        try:
            phrase = phrase_for_semantic_code(code)
        except ValueError:
            return None

        output: Path | None = None
        owned_root = False
        delivered = False
        root: Path | None = None
        try:
            root, owned_root = self._prepare_root()
            descriptor, name = tempfile.mkstemp(
                prefix="voice-camera-reply-", suffix=".aiff", dir=root
            )
            os.close(descriptor)
            output = Path(name)
            os.chmod(output, 0o600)
            command = (
                "/usr/bin/say",
                "-v",
                "Tingting",
                "-r",
                "180",
                "-f",
                "-",
                "-o",
                str(output),
                "--file-format=AIFF",
                "--data-format=BEI16@16000",
                "--channels=1",
            )
            if not self._runner.run(
                command,
                input_bytes=phrase.encode("utf-8"),
                timeout_seconds=_RENDER_TIMEOUT_SECONDS,
                cancelled=cancelled,
            ):
                return None
            duration = _validated_aiff_duration(output, root)
            if duration is None:
                return None
            rendered = RenderedReply(output.resolve(), duration, root.resolve())
            delivered = True
            output = None
            return rendered
        except Exception:
            return None
        finally:
            if output is not None:
                _unlink(output)
            if owned_root and root is not None and not delivered:
                _remove_empty_root(root)

    def _prepare_root(self) -> tuple[Path, bool]:
        if self._temporary_root is None:
            root = Path(tempfile.mkdtemp(prefix="voice-response-root-"))
            os.chmod(root, 0o700)
            return root, True
        root = self._temporary_root
        if not root.exists():
            root.mkdir(parents=True, mode=0o700)
        root_lstat = root.lstat()
        root_resolved = root.resolve(strict=True)
        root_stat = os.stat(root_resolved, follow_symlinks=False)
        if (
            stat.S_ISLNK(root_lstat.st_mode)
            or not stat.S_ISDIR(root_stat.st_mode)
            or root_stat.st_uid != os.getuid()
            or stat.S_IMODE(root_stat.st_mode) != 0o700
        ):
            raise ValueError(VOICE_TTS_UNAVAILABLE)
        return root_resolved, False


class FixedVoiceSynthesizer:
    def __init__(
        self,
        *,
        runner: CommandRunner,
        ducker: CaptureDucker,
        temporary_directory: Path | None = None,
        sleep: Callable[[float], None] = time.sleep,
        post_playback_guard_seconds: float = _POST_PLAYBACK_GUARD_SECONDS,
    ) -> None:
        if not 0.0 <= post_playback_guard_seconds <= _POST_PLAYBACK_GUARD_SECONDS:
            raise ValueError(VOICE_TTS_UNAVAILABLE)
        self._runner = runner
        self._ducker = ducker
        self._temporary_directory = temporary_directory
        self._sleep = sleep
        self._post_playback_guard_seconds = post_playback_guard_seconds
        self._renderer = FixedReplyRenderer(
            runner=runner,
            temporary_root=temporary_directory,
            _accepted_codes=_ALL_FIXED_CODES,
        )

    def speak_code(self, code: str, cancelled: CancelEvent) -> bool:
        phrase_for_semantic_code(code)
        rendered: RenderedReply | None = None
        self._ducker.pause()
        try:
            if cancelled.is_set():
                return False
            rendered = self._renderer.render(code, cancelled)
            if rendered is None:
                return False
            return self._runner.run(
                ("/usr/bin/afplay", "-v", "0.35", str(rendered.path)),
                input_bytes=None,
                timeout_seconds=_PLAYBACK_TIMEOUT_SECONDS,
                cancelled=cancelled,
            )
        except (OSError, ValueError):
            return False
        finally:
            if rendered is not None:
                _unlink(rendered.path)
                if self._temporary_directory is None:
                    _remove_empty_root(rendered.temporary_root)
            if self._post_playback_guard_seconds:
                self._sleep(self._post_playback_guard_seconds)
            self._ducker.resume()


def phrase_for_semantic_code(code: str) -> str:
    try:
        if type(code) is not str:
            raise KeyError
        return RESPONSE_PHRASES[code]
    except KeyError:
        raise ValueError(VOICE_TTS_UNAVAILABLE) from None


def _validated_aiff_duration(path: Path, root: Path) -> float | None:
    try:
        path_lstat = path.lstat()
        resolved = path.resolve(strict=True)
        file_stat = os.stat(resolved, follow_symlinks=False)
        if (
            stat.S_ISLNK(path_lstat.st_mode)
            or not resolved.is_relative_to(root.resolve(strict=True))
            or not stat.S_ISREG(file_stat.st_mode)
            or file_stat.st_uid != os.getuid()
            or stat.S_IMODE(file_stat.st_mode) != 0o600
            or file_stat.st_nlink != 1
            or not 0 < file_stat.st_size <= _MAX_RENDERED_BYTES
        ):
            return None
        data = resolved.read_bytes()
    except (OSError, RuntimeError, ValueError):
        return None
    if (
        len(data) < 12
        or data[:4] != b"FORM"
        or data[8:12] != b"AIFF"
        or struct.unpack(">I", data[4:8])[0] + 8 != len(data)
    ):
        return None

    comm: bytes | None = None
    sound: bytes | None = None
    offset = 12
    while offset + 8 <= len(data):
        chunk_type = data[offset : offset + 4]
        chunk_size = struct.unpack(">I", data[offset + 4 : offset + 8])[0]
        start = offset + 8
        end = start + chunk_size
        if end > len(data):
            return None
        chunk = data[start:end]
        if chunk_type == b"COMM":
            if comm is not None:
                return None
            comm = chunk
        elif chunk_type == b"SSND":
            if sound is not None:
                return None
            sound = chunk
        offset = end + (chunk_size & 1)
    if offset != len(data) or comm is None or sound is None:
        return None
    if len(comm) != 18 or len(sound) < 8:
        return None
    channels, frames, sample_bits = struct.unpack(">hIh", comm[:8])
    if (
        channels != 1
        or sample_bits != 16
        or comm[8:18] != _AIFF_16000_EXTENDED
        or frames < 1
        or struct.unpack(">II", sound[:8]) != (0, 0)
        or len(sound[8:]) != frames * 2
    ):
        return None
    duration = frames / 16_000.0
    if not _MIN_RENDERED_SECONDS <= duration <= _MAX_RENDERED_SECONDS:
        return None
    return duration


def _unlink(path: Path) -> None:
    try:
        path.unlink()
    except OSError:
        pass


def _remove_empty_root(path: Path) -> None:
    try:
        path.rmdir()
    except OSError:
        pass


def _stop_process(process: subprocess.Popen[bytes]) -> None:
    try:
        if process.poll() is not None:
            return
        process.terminate()
        process.wait(timeout=1.0)
    except (OSError, subprocess.TimeoutExpired):
        try:
            process.kill()
            process.wait(timeout=1.0)
        except (OSError, subprocess.TimeoutExpired):
            pass


__all__ = [
    "RESPONSE_PHRASES",
    "VOICE_TTS_UNAVAILABLE",
    "BoundedCommandRunner",
    "FixedReplyRenderer",
    "FixedVoiceSynthesizer",
    "NoopCaptureDucker",
    "RenderedReply",
    "phrase_for_semantic_code",
]
