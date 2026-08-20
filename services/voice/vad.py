from __future__ import annotations

import math
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

import numpy as np


SAMPLE_WIDTH_BYTES = 2
SPEECH_THRESHOLD = 0.5
UNAVAILABLE_REASON = "voice_model_unavailable"

VadRunner = Callable[[np.ndarray], object]


@dataclass(frozen=True)
class VadResult:
    speech: bool
    probability: float
    reason: str | None = None


class VoiceActivityDetector:
    """Run one local VAD frame without retaining PCM or model failure details."""

    def __init__(self, runner: VadRunner) -> None:
        self._runner = runner
        self._frame_bytes: int | None = None

    def observe(self, frame: bytes) -> VadResult:
        if not self._is_fixed_pcm_frame(frame):
            return _unavailable()

        waveform = np.frombuffer(frame, dtype="<i2").astype(np.float32) / 32_768.0
        try:
            probability = _single_probability(self._runner(waveform))
        except Exception:
            return _unavailable()
        if not math.isfinite(probability) or not 0.0 <= probability <= 1.0:
            return _unavailable()
        return VadResult(
            speech=probability >= SPEECH_THRESHOLD,
            probability=probability,
        )

    def _is_fixed_pcm_frame(self, frame: bytes) -> bool:
        if not isinstance(frame, bytes) or not frame or len(frame) % SAMPLE_WIDTH_BYTES:
            return False
        if self._frame_bytes is None:
            self._frame_bytes = len(frame)
            return True
        return len(frame) == self._frame_bytes


def _single_probability(raw: Any) -> float:
    values = np.asarray(raw, dtype=np.float32)
    if values.size != 1:
        raise ValueError("VAD output must contain one probability")
    return float(values.reshape(-1)[0])


def _unavailable() -> VadResult:
    return VadResult(
        speech=False,
        probability=0.0,
        reason=UNAVAILABLE_REASON,
    )
