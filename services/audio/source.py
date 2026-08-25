from __future__ import annotations

import os
import selectors
import subprocess
from dataclasses import dataclass
from typing import Any, Callable

from packages.contracts.audio import AudioFailureReason
from packages.contracts.settings import AudioSettings


class BoundedPcmBuffer:
    def __init__(
        self,
        sample_rate_hz: int,
        channels: int,
        sample_width_bytes: int,
        buffer_seconds: int,
    ) -> None:
        self._bytes_per_frame = channels * sample_width_bytes
        self._bytes_per_second = sample_rate_hz * self._bytes_per_frame
        self.capacity_bytes = self._bytes_per_second * buffer_seconds
        self._data = bytearray()

    @property
    def size_bytes(self) -> int:
        return len(self._data)

    def append(self, pcm: bytes) -> None:
        if len(pcm) % self._bytes_per_frame:
            raise ValueError("PCM input must be frame aligned")
        if len(pcm) >= self.capacity_bytes:
            self._data[:] = pcm[-self.capacity_bytes :]
            return
        self._data.extend(pcm)
        overflow = len(self._data) - self.capacity_bytes
        if overflow > 0:
            del self._data[:overflow]

    def latest(self, duration_ms: int) -> bytes:
        if duration_ms <= 0:
            raise ValueError("duration must be positive")
        requested = self._bytes_per_second * duration_ms // 1_000
        requested -= requested % self._bytes_per_frame
        if requested <= 0 or requested > self.capacity_bytes:
            raise ValueError("duration exceeds buffer capacity")
        return bytes(self._data[-requested:])


@dataclass(frozen=True)
class DecoderRead:
    pcm: bytes
    failure_reason: AudioFailureReason | None = None


ProcessOpener = Callable[..., Any]


def fixed_audio_decoder_command(settings: AudioSettings) -> tuple[str, ...]:
    """Return the single fixed loopback audio-only FFmpeg command."""

    return (
        "ffmpeg",
        "-nostdin",
        "-hide_banner",
        "-loglevel",
        "error",
        "-rtsp_transport",
        "tcp",
        "-timeout",
        "5000000",
        "-i",
        "rtsp://127.0.0.1:8554/audio_analysis",
        "-map",
        "0:a:0",
        "-vn",
        "-ac",
        str(settings.channels),
        "-ar",
        str(settings.sample_rate_hz),
        "-f",
        "s16le",
        "pipe:1",
    )


class FixedAudioDecoder:
    def __init__(
        self,
        settings: AudioSettings,
        *,
        opener: ProcessOpener = subprocess.Popen,
    ) -> None:
        self._settings = settings
        self._opener = opener
        self._process: Any | None = None

    def _command(self) -> tuple[str, ...]:
        return fixed_audio_decoder_command(self._settings)

    def _start(self) -> bool:
        try:
            self._process = self._opener(
                self._command(),
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                bufsize=0,
            )
        except OSError:
            self._process = None
            return False
        return self._process.stdout is not None

    def read(
        self, max_bytes: int, *, timeout_seconds: float | None = None
    ) -> DecoderRead:
        if max_bytes <= 0:
            raise ValueError("max_bytes must be positive")
        if timeout_seconds is not None and not 0 < timeout_seconds <= 10.0:
            raise ValueError("timeout_seconds must be bounded")
        if self._process is None and not self._start():
            return DecoderRead(b"", AudioFailureReason.AUDIO_SOURCE_UNAVAILABLE)

        try:
            if timeout_seconds is None:
                pcm = self._process.stdout.read(max_bytes)
            else:
                descriptor = self._process.stdout.fileno()
                selector = selectors.DefaultSelector()
                try:
                    selector.register(descriptor, selectors.EVENT_READ)
                    if not selector.select(timeout_seconds):
                        self.close()
                        return DecoderRead(b"", AudioFailureReason.AUDIO_STALE)
                    pcm = os.read(descriptor, max_bytes)
                finally:
                    selector.close()
        except (OSError, ValueError):
            self.close()
            return DecoderRead(b"", AudioFailureReason.DECODER_FAILED)
        if pcm and len(pcm) % self._settings.sample_width_bytes:
            self.close()
            return DecoderRead(b"", AudioFailureReason.DECODER_FAILED)
        if pcm:
            return DecoderRead(pcm)
        if self._process.poll() is None:
            self.close()
            return DecoderRead(b"", AudioFailureReason.AUDIO_STALE)
        self._discard_exited_process()
        return DecoderRead(b"", AudioFailureReason.DECODER_FAILED)

    def _discard_exited_process(self) -> None:
        process, self._process = self._process, None
        stdout = getattr(process, "stdout", None)
        if stdout is not None:
            try:
                stdout.close()
            except OSError:
                pass

    def close(self) -> None:
        process = self._process
        self._process = None
        if process is None:
            return
        stdout = getattr(process, "stdout", None)
        if stdout is not None:
            try:
                stdout.close()
            except OSError:
                pass
        if process.poll() is not None:
            return
        try:
            process.terminate()
            process.wait(timeout=2.0)
        except (OSError, subprocess.TimeoutExpired):
            try:
                process.kill()
                process.wait(timeout=2.0)
            except (OSError, subprocess.TimeoutExpired):
                pass

    def __enter__(self) -> "FixedAudioDecoder":
        return self

    def __exit__(self, *_exc: object) -> None:
        self.close()
