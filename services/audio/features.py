from __future__ import annotations

import math
from datetime import datetime

import numpy as np

from packages.contracts.audio import AudioObservation, AudioObservationState
from packages.contracts.settings import AudioSettings


MIN_DBFS = -120.0


def pcm_loudness_dbfs(pcm: bytes) -> float:
    if not pcm or len(pcm) % 2:
        raise ValueError("PCM must contain complete signed 16-bit samples")
    samples = np.frombuffer(pcm, dtype="<i2").astype(np.float64)
    rms = float(np.sqrt(np.mean(np.square(samples)))) / 32_767.0
    if rms <= 0:
        return MIN_DBFS
    return max(MIN_DBFS, min(0.0, 20.0 * math.log10(rms)))


class DynamicLoudnessGate:
    def __init__(
        self,
        *,
        settings: AudioSettings = AudioSettings(),
    ) -> None:
        self._noise_floor_dbfs = settings.initial_noise_floor_dbfs
        self._gate_margin_db = settings.loudness_gate_margin_db
        self._adaptation = settings.noise_floor_adaptation
        self._sample_rate_hz = settings.sample_rate_hz

    def observe(
        self, pcm: bytes, *, observed_at: datetime | None = None
    ) -> AudioObservation:
        loudness = pcm_loudness_dbfs(pcm)
        is_loud = loudness > self._noise_floor_dbfs + self._gate_margin_db
        if not is_loud:
            self._noise_floor_dbfs += self._adaptation * (
                loudness - self._noise_floor_dbfs
            )
            self._noise_floor_dbfs = max(
                MIN_DBFS, min(0.0, self._noise_floor_dbfs)
            )
        duration_ms = len(pcm) * 1_000 // (self._sample_rate_hz * 2)
        return AudioObservation(
            observed_at=observed_at or datetime.now().astimezone(),
            state=(
                AudioObservationState.SOUND
                if is_loud
                else AudioObservationState.QUIET
            ),
            duration_ms=duration_ms,
            loudness_dbfs=loudness,
            noise_floor_dbfs=self._noise_floor_dbfs,
        )
