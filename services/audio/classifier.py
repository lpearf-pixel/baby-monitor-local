from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any, Callable

import numpy as np

from packages.contracts.audio import (
    AudioFailureReason,
    AudioObservation,
    AudioObservationState,
)
from packages.contracts.settings import AudioSettings


RunnerFactory = Callable[[Path], Any]


class CryClassifier:
    def __init__(
        self,
        settings: AudioSettings,
        *,
        project_root: Path,
        runner_factory: RunnerFactory,
    ) -> None:
        self._settings = settings
        self._project_root = project_root.resolve()
        self._model_path = project_root / settings.model_path
        self._runner_factory = runner_factory
        self._runner: Any | None = None
        self._load_failure: AudioFailureReason | None = None

    def _unavailable(
        self, source: AudioObservation, reason: AudioFailureReason
    ) -> AudioObservation:
        return AudioObservation(
            observed_at=source.observed_at,
            state=AudioObservationState.UNAVAILABLE,
            duration_ms=0,
            failure_reason=reason,
        )

    def _load(self) -> AudioFailureReason | None:
        if self._runner is not None:
            return None
        if self._load_failure is not None:
            return self._load_failure
        try:
            model_path = self._model_path.resolve(strict=True)
        except OSError:
            self._load_failure = AudioFailureReason.MODEL_MISSING
            return self._load_failure
        if not model_path.is_relative_to(self._project_root) or not model_path.is_file():
            self._load_failure = AudioFailureReason.MODEL_INVALID
            return self._load_failure
        expected = self._settings.model_sha256
        if expected is None:
            self._load_failure = AudioFailureReason.MODEL_INVALID
            return self._load_failure
        hasher = hashlib.sha256()
        try:
            with model_path.open("rb") as model_file:
                for chunk in iter(lambda: model_file.read(1024 * 1024), b""):
                    hasher.update(chunk)
        except OSError:
            self._load_failure = AudioFailureReason.MODEL_INVALID
            return self._load_failure
        digest = hasher.hexdigest()
        if digest != expected:
            self._load_failure = AudioFailureReason.MODEL_INVALID
            return self._load_failure
        try:
            self._runner = self._runner_factory(model_path)
        except Exception:
            self._load_failure = AudioFailureReason.MODEL_INVALID
            return self._load_failure
        return None

    def classify(
        self, pcm: bytes, source: AudioObservation
    ) -> AudioObservation:
        failure = self._load()
        if failure is not None:
            return self._unavailable(source, failure)
        if len(pcm) != self._settings.sample_rate_hz * 2:
            return self._unavailable(source, AudioFailureReason.MODEL_FAILED)
        waveform = (
            np.frombuffer(pcm, dtype="<i2")
            .astype(np.float32)
            .reshape(1, self._settings.sample_rate_hz)
            / 32_768.0
        )
        try:
            raw = np.asarray(self._runner.run(waveform), dtype=np.float32)
        except Exception:
            return self._unavailable(source, AudioFailureReason.MODEL_FAILED)
        if raw.shape != (1, 1) or not np.isfinite(raw[0, 0]):
            return self._unavailable(source, AudioFailureReason.MODEL_FAILED)
        probability = float(raw[0, 0])
        if not 0 <= probability <= 1:
            return self._unavailable(source, AudioFailureReason.MODEL_FAILED)
        if probability < self._settings.cry_confidence_threshold:
            return source
        return AudioObservation(
            observed_at=source.observed_at,
            state=AudioObservationState.CRY_CANDIDATE,
            duration_ms=source.duration_ms,
            loudness_dbfs=source.loudness_dbfs,
            noise_floor_dbfs=source.noise_floor_dbfs,
            cry_confidence=probability,
        )
