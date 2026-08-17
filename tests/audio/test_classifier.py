from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pytest

from packages.contracts.audio import (
    AudioFailureReason,
    AudioObservation,
    AudioObservationState,
)
from packages.contracts.settings import AudioSettings
from services.audio.classifier import CryClassifier


NOW = datetime(2026, 8, 17, 14, tzinfo=timezone.utc)
PCM = np.zeros(16_000, dtype="<i2").tobytes()


def sound() -> AudioObservation:
    return AudioObservation(
        observed_at=NOW,
        state=AudioObservationState.SOUND,
        duration_ms=1_000,
        loudness_dbfs=-18.0,
        noise_floor_dbfs=-50.0,
    )


def settings_for(model: Path, content: bytes) -> AudioSettings:
    return AudioSettings(
        model_path=Path(model.name),
        model_sha256=hashlib.sha256(content).hexdigest(),
    )


class Runner:
    def __init__(self, result: object) -> None:
        self.result = result
        self.seen: np.ndarray | None = None

    def run(self, waveform: np.ndarray) -> object:
        self.seen = waveform
        return self.result


def test_missing_model_fails_closed_without_starting_runtime(tmp_path: Path) -> None:
    started = False

    def factory(_path: Path) -> Runner:
        nonlocal started
        started = True
        return Runner(np.array([[0.9]], dtype=np.float32))

    classifier = CryClassifier(
        settings_for(tmp_path / "missing.onnx", b"expected"),
        project_root=tmp_path,
        runner_factory=factory,
    )

    result = classifier.classify(PCM, sound())

    assert result.failure_reason is AudioFailureReason.MODEL_MISSING
    assert started is False


def test_digest_mismatch_fails_closed_before_runtime(tmp_path: Path) -> None:
    model = tmp_path / "model.onnx"
    model.write_bytes(b"unexpected")

    result = CryClassifier(
        settings_for(model, b"expected"),
        project_root=tmp_path,
        runner_factory=lambda _path: Runner(0.9),
    ).classify(PCM, sound())

    assert result.failure_reason is AudioFailureReason.MODEL_INVALID


def test_valid_model_receives_fixed_normalized_waveform(tmp_path: Path) -> None:
    content = b"synthetic model fixture"
    model = tmp_path / "model.onnx"
    model.write_bytes(content)
    runner = Runner(np.array([[0.8]], dtype=np.float32))
    classifier = CryClassifier(
        settings_for(model, content), project_root=tmp_path, runner_factory=lambda _: runner
    )

    result = classifier.classify(PCM, sound())

    assert result.state is AudioObservationState.CRY_CANDIDATE
    assert result.cry_confidence == pytest.approx(0.8)
    assert runner.seen is not None
    assert runner.seen.shape == (1, 16_000)
    assert runner.seen.dtype == np.float32


def test_low_probability_remains_sound_without_model_score(tmp_path: Path) -> None:
    content = b"synthetic model fixture"
    model = tmp_path / "model.onnx"
    model.write_bytes(content)
    classifier = CryClassifier(
        settings_for(model, content),
        project_root=tmp_path,
        runner_factory=lambda _: Runner(np.array([[0.2]], dtype=np.float32)),
    )

    result = classifier.classify(PCM, sound())

    assert result.state is AudioObservationState.SOUND
    assert result.cry_confidence is None


def test_malformed_or_failing_model_output_fails_closed(tmp_path: Path) -> None:
    content = b"synthetic model fixture"
    model = tmp_path / "model.onnx"
    model.write_bytes(content)

    malformed = CryClassifier(
        settings_for(model, content),
        project_root=tmp_path,
        runner_factory=lambda _: Runner(np.array([0.9, 0.1], dtype=np.float32)),
    ).classify(PCM, sound())

    assert malformed.failure_reason is AudioFailureReason.MODEL_FAILED


def test_wrong_pcm_window_fails_closed_without_running_model(tmp_path: Path) -> None:
    content = b"synthetic model fixture"
    model = tmp_path / "model.onnx"
    model.write_bytes(content)
    runner = Runner(np.array([[0.9]], dtype=np.float32))
    classifier = CryClassifier(
        settings_for(model, content), project_root=tmp_path, runner_factory=lambda _: runner
    )

    result = classifier.classify(PCM[:-2], sound())

    assert result.failure_reason is AudioFailureReason.MODEL_FAILED
    assert runner.seen is None


def test_model_symlink_cannot_escape_project_root(tmp_path: Path) -> None:
    outside = tmp_path.parent / "outside-cry-model.onnx"
    outside.write_bytes(b"synthetic external fixture")
    linked = tmp_path / "model.onnx"
    linked.symlink_to(outside)
    runner = Runner(np.array([[0.9]], dtype=np.float32))
    classifier = CryClassifier(
        settings_for(linked, outside.read_bytes()),
        project_root=tmp_path,
        runner_factory=lambda _: runner,
    )

    result = classifier.classify(PCM, sound())

    assert result.failure_reason is AudioFailureReason.MODEL_INVALID
    assert runner.seen is None
