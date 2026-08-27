"""Bounded exact-frame audio assembly for the memory-only Voice listener."""

from __future__ import annotations

import threading
from dataclasses import dataclass
from typing import Protocol

from packages.contracts.audio import AudioFailureReason
from services.audio.source import DecoderRead


FRAME_BYTES = 3_200
READ_TIMEOUT_SECONDS = 1.0
WARMUP_FRAMES = 5
TAIL_REPLAY_FRAMES = 5


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
    replayed: bool = False


class ExactFrameAudioPump:
    """Keep decoder partial reads in one bounded, zeroized frame assembler."""

    def __init__(self, decoder: Decoder) -> None:
        self._decoder = decoder
        self._assembler = bytearray()
        self._ducked = False
        self._capture_tail = False
        self._replay: list[bytearray] = []
        self._closed = False
        self._state_lock = threading.Lock()

    @property
    def buffered_bytes(self) -> int:
        return len(self._assembler)

    @property
    def replay_buffered_frames(self) -> int:
        with self._state_lock:
            return len(self._replay)

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
        with self._state_lock:
            if self._closed:
                return PumpFrame(b"", AudioFailureReason.DECODER_FAILED)
            if not self._ducked and self._replay:
                replay = self._replay.pop(0)
                pcm = bytes(replay)
                replay[:] = b"\x00" * len(replay)
                return PumpFrame(pcm, replayed=True)
        while len(self._assembler) < FRAME_BYTES:
            remaining = FRAME_BYTES - len(self._assembler)
            read = self._decoder.read(
                remaining,
                timeout_seconds=READ_TIMEOUT_SECONDS,
            )
            if read.failure_reason is not None:
                self._zeroize()
                with self._state_lock:
                    self._zeroize_replay_locked()
                return PumpFrame(b"", read.failure_reason)
            if not read.pcm or len(read.pcm) > remaining or len(read.pcm) % 2:
                self._zeroize()
                with self._state_lock:
                    self._zeroize_replay_locked()
                return PumpFrame(b"", AudioFailureReason.DECODER_FAILED)
            self._assembler.extend(read.pcm)
        pcm = bytes(self._assembler)
        self._zeroize()
        with self._state_lock:
            if self._ducked:
                if self._capture_tail and len(self._replay) < TAIL_REPLAY_FRAMES:
                    self._replay.append(bytearray(pcm))
                return PumpFrame(b"", dropped=True)
        return PumpFrame(pcm)

    def begin_duck(self) -> None:
        with self._state_lock:
            self._ducked = True
            self._capture_tail = False
            self._zeroize_replay_locked()
        self._zeroize()

    def begin_tail_capture(self) -> None:
        with self._state_lock:
            if self._closed or not self._ducked:
                raise ValueError("voice_audio_unavailable")
            self._capture_tail = True

    def end_duck(self) -> None:
        self._zeroize()
        with self._state_lock:
            self._capture_tail = False
            self._ducked = False

    def discard_replay(self) -> None:
        with self._state_lock:
            self._zeroize_replay_locked()

    def close(self) -> None:
        with self._state_lock:
            if self._closed:
                return
            self._closed = True
            self._capture_tail = False
            self._ducked = False
            self._zeroize_replay_locked()
        self._zeroize()
        self._decoder.close()

    def _zeroize(self) -> None:
        self._assembler[:] = b"\x00" * len(self._assembler)
        self._assembler.clear()

    def _zeroize_replay_locked(self) -> None:
        for replay in self._replay:
            replay[:] = b"\x00" * len(replay)
        self._replay.clear()


__all__ = ["ExactFrameAudioPump", "PumpFrame"]
