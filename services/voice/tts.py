"""Fixed, bounded macOS speech output for closed Voice Care semantic codes."""

from __future__ import annotations

import os
import subprocess
import tempfile
import time
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
_SAY_TIMEOUT_SECONDS = 10.0
_PLAYBACK_TIMEOUT_SECONDS = 10.0
_POST_PLAYBACK_GUARD_SECONDS = 0.5


class CancelEvent(Protocol):
    def is_set(self) -> bool: ...


class CaptureDucker(Protocol):
    def pause(self) -> None: ...

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

    def resume(self) -> None:
        return None


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


class FixedVoiceSynthesizer:
    def __init__(
        self,
        *,
        runner: CommandRunner,
        ducker: CaptureDucker,
        temporary_directory: Path | None = None,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self._runner = runner
        self._ducker = ducker
        self._temporary_directory = temporary_directory
        self._sleep = sleep

    def speak_code(self, code: str, cancelled: CancelEvent) -> bool:
        phrase = phrase_for_semantic_code(code)
        output: Path | None = None
        self._ducker.pause()
        try:
            if cancelled.is_set():
                return False
            directory = self._temporary_directory
            if directory is not None:
                directory.mkdir(parents=True, exist_ok=True)
            descriptor, name = tempfile.mkstemp(
                prefix="voice-response-",
                suffix=".aiff",
                dir=directory,
            )
            os.close(descriptor)
            output = Path(name)
            os.chmod(output, 0o600)
            if not self._runner.run(
                ("/usr/bin/say", "-f", "-", "-o", str(output)),
                input_bytes=phrase.encode("utf-8"),
                timeout_seconds=_SAY_TIMEOUT_SECONDS,
                cancelled=cancelled,
            ):
                return False
            return self._runner.run(
                ("/usr/bin/afplay", "-v", "0.35", str(output)),
                input_bytes=None,
                timeout_seconds=_PLAYBACK_TIMEOUT_SECONDS,
                cancelled=cancelled,
            )
        except (OSError, ValueError):
            return False
        finally:
            if output is not None:
                try:
                    output.unlink()
                except OSError:
                    pass
            self._sleep(_POST_PLAYBACK_GUARD_SECONDS)
            self._ducker.resume()


def phrase_for_semantic_code(code: str) -> str:
    try:
        if type(code) is not str:
            raise KeyError
        return RESPONSE_PHRASES[code]
    except KeyError:
        raise ValueError(VOICE_TTS_UNAVAILABLE) from None


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
    "FixedVoiceSynthesizer",
    "NoopCaptureDucker",
    "phrase_for_semantic_code",
]
