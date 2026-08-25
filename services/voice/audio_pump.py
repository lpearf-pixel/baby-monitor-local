"""Bounded exact-frame audio assembly for the memory-only Voice listener."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from packages.contracts.audio import AudioFailureReason
from services.audio.source import DecoderRead


FRAME_BYTES = 3_200
READ_TIMEOUT_SECONDS = 1.0
WARMUP_FRAMES = 5


class Decoder(Protocol):
    def read(
        self, max_bytes: int, *, timeout_seconds: float | None = None
    ) -> DecoderRead: ...

    def close(self) -> None: ...


class StopEvent(Protocol):
    def is_set(self) -> bool: ...


@dataclass(frozen=True)
class PumpFrame:
    pcm: bytes
    failure_reason: AudioFailureReason | None = None
    dropped: bool = False


class ExactFrameAudioPump:
    """Keep decoder partial reads in one bounded, zeroized frame assembler."""

    def __init__(self, decoder: Decoder) -> None:
        self._decoder = decoder
        self._assembler = bytearray()
        self._ducked = False
        self._closed = False

    @property
    def buffered_bytes(self) -> int:
        return len(self._assembler)

    def warm_up(self, cancelled: StopEvent) -> bool:
        for _ in range(WARMUP_FRAMES):
            if cancelled.is_set():
                self._zeroize()
                return False
            frame = self.read_frame()
            if frame.failure_reason is not None:
                return False
        return True

    def read_frame(self) -> PumpFrame:
        if self._closed:
            return PumpFrame(b"", AudioFailureReason.DECODER_FAILED)
        while len(self._assembler) < FRAME_BYTES:
            remaining = FRAME_BYTES - len(self._assembler)
            read = self._decoder.read(
                remaining,
                timeout_seconds=READ_TIMEOUT_SECONDS,
            )
            if read.failure_reason is not None:
                self._zeroize()
                return PumpFrame(b"", read.failure_reason)
            if not read.pcm or len(read.pcm) > remaining or len(read.pcm) % 2:
                self._zeroize()
                return PumpFrame(b"", AudioFailureReason.DECODER_FAILED)
            self._assembler.extend(read.pcm)
        pcm = bytes(self._assembler)
        self._zeroize()
        if self._ducked:
            return PumpFrame(b"", dropped=True)
        return PumpFrame(pcm)

    def begin_duck(self) -> None:
        self._ducked = True
        self._zeroize()

    def end_duck(self) -> None:
        self._zeroize()
        self._ducked = False

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        self._zeroize()
        self._decoder.close()

    def _zeroize(self) -> None:
        self._assembler[:] = b"\x00" * len(self._assembler)
        self._assembler.clear()


__all__ = ["ExactFrameAudioPump", "PumpFrame"]
