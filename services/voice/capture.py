from __future__ import annotations

import math
from dataclasses import dataclass

from packages.contracts.settings import VoiceCareSettings
from services.voice.vad import VadResult


SAMPLE_RATE_HZ = 16_000
CHANNELS = 1
SAMPLE_WIDTH_BYTES = 2
BYTES_PER_SECOND = SAMPLE_RATE_HZ * CHANNELS * SAMPLE_WIDTH_BYTES
PcmBuffer = bytearray


@dataclass(frozen=True)
class UtteranceResult:
    pcm: bytes
    reason: str


class UtteranceCollector:
    """Capture one exact-duration, memory-only utterance from fixed PCM frames."""

    def __init__(self, settings: VoiceCareSettings) -> None:
        self._pre_roll_limit = _duration_bytes(settings.pre_roll_ms)
        self._terminal_silence_limit = _duration_bytes(settings.terminal_silence_ms)
        self._max_utterance_limit = _duration_bytes(settings.max_utterance_ms)
        self._frame_bytes: int | None = None
        self._pre_roll = PcmBuffer()
        self._utterance = PcmBuffer()
        self._terminal_silence_bytes = 0
        self._closed = False

    @property
    def buffered_bytes(self) -> int:
        return len(self._pre_roll) + len(self._utterance)

    def push(self, frame: bytes, vad: VadResult) -> UtteranceResult | None:
        if self._closed:
            raise RuntimeError("utterance collector is closed")
        try:
            self._validate(frame, vad)
        except ValueError:
            self.reset()
            raise

        if not self._utterance and not vad.speech:
            self._append_pre_roll(frame)
            return None
        if not self._utterance:
            self._utterance.extend(self._pre_roll)
            _zero_and_clear(self._pre_roll)

        self._append_utterance(frame)
        if vad.speech:
            self._terminal_silence_bytes = 0
        else:
            self._terminal_silence_bytes += len(frame)

        if self._terminal_silence_bytes == self._terminal_silence_limit:
            return self._take("terminal_silence")
        if len(self._utterance) == self._max_utterance_limit:
            return self._take("max_duration")
        return None

    def reset(self) -> None:
        _zero_and_clear(self._pre_roll)
        _zero_and_clear(self._utterance)
        self._terminal_silence_bytes = 0

    def close(self) -> None:
        if self._closed:
            return
        self.reset()
        self._closed = True

    def _validate(self, frame: bytes, vad: VadResult) -> None:
        if not isinstance(frame, bytes) or not frame or len(frame) % SAMPLE_WIDTH_BYTES:
            raise ValueError("PCM input must be frame aligned")
        if self._frame_bytes is None:
            self._require_exact_timing(frame)
            self._frame_bytes = len(frame)
        elif len(frame) != self._frame_bytes:
            raise ValueError("PCM frame size must remain fixed")
        if not math.isfinite(vad.probability):
            raise ValueError("VAD probability must be finite")
        if not 0.0 <= vad.probability <= 1.0:
            raise ValueError("VAD probability must be within range")
        if vad.reason is not None or not isinstance(vad.speech, bool):
            raise ValueError("VAD result must be available")

    def _require_exact_timing(self, frame: bytes) -> None:
        frame_bytes = len(frame)
        if any(
            limit % frame_bytes
            for limit in (
                self._pre_roll_limit,
                self._terminal_silence_limit,
                self._max_utterance_limit,
            )
        ):
            raise ValueError("PCM frame timing cannot preserve fixed voice bounds")

    def _append_pre_roll(self, frame: bytes) -> None:
        _append_bounded(self._pre_roll, frame, self._pre_roll_limit)

    def _append_utterance(self, frame: bytes) -> None:
        if len(self._utterance) + len(frame) > self._max_utterance_limit:
            raise RuntimeError("validated PCM frame exceeds utterance bound")
        self._utterance.extend(frame)

    def _take(self, reason: str) -> UtteranceResult:
        try:
            return UtteranceResult(pcm=bytes(self._utterance), reason=reason)
        finally:
            self.reset()


def _duration_bytes(duration_ms: int) -> int:
    bytes_for_duration = BYTES_PER_SECOND * duration_ms
    if bytes_for_duration % 1_000:
        raise ValueError("voice duration must resolve to complete PCM bytes")
    return bytes_for_duration // 1_000


def _append_bounded(buffer: bytearray, frame: bytes, limit: int) -> None:
    if len(frame) > limit:
        raise RuntimeError("validated PCM frame exceeds buffer bound")
    overflow = len(buffer) + len(frame) - limit
    if overflow > 0:
        del buffer[:overflow]
    buffer.extend(frame)


def _zero_and_clear(buffer: bytearray) -> None:
    for index in range(len(buffer)):
        buffer[index] = 0
    buffer.clear()
