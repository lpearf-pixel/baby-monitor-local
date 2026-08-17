from __future__ import annotations

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
        return (
            "ffmpeg",
            "-nostdin",
            "-hide_banner",
            "-loglevel",
            "error",
            "-rtsp_transport",
            "tcp",
            "-rw_timeout",
            "5000000",
            "-i",
            "rtsp://127.0.0.1:8554/audio_analysis",
            "-map",
            "0:a:0",
            "-vn",
            "-ac",
            str(self._settings.channels),
            "-ar",
            str(self._settings.sample_rate_hz),
            "-f",
            "s16le",
            "pipe:1",
        )

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

    def read(self, max_bytes: int) -> DecoderRead:
        if max_bytes <= 0:
            raise ValueError("max_bytes must be positive")
        if self._process is None and not self._start():
            return DecoderRead(b"", AudioFailureReason.AUDIO_SOURCE_UNAVAILABLE)

        try:
            pcm = self._process.stdout.read(max_bytes)
        except OSError:
            return DecoderRead(b"", AudioFailureReason.DECODER_FAILED)
        if pcm and len(pcm) % self._settings.sample_width_bytes:
            return DecoderRead(b"", AudioFailureReason.DECODER_FAILED)
        if pcm:
            return DecoderRead(pcm)
        if self._process.poll() is None:
            return DecoderRead(b"", AudioFailureReason.AUDIO_STALE)
        return DecoderRead(b"", AudioFailureReason.DECODER_FAILED)
