from __future__ import annotations

import numpy as np
import pytest

from services.voice.vad import VoiceActivityDetector


FRAME_100MS = b"\x00\x80" * 1_600


def test_vad_converts_fixed_s16le_frame_to_normalized_float32() -> None:
    observed: list[np.ndarray] = []

    def runner(waveform: np.ndarray) -> float:
        observed.append(waveform)
        return 0.9

    result = VoiceActivityDetector(runner).observe(FRAME_100MS)

    assert result.speech is True
    assert result.probability == pytest.approx(0.9)
    assert result.reason is None
    assert len(observed) == 1
    assert observed[0].dtype == np.float32
    assert observed[0].shape == (1_600,)
    assert observed[0][0] == -1.0


def test_vad_maps_runner_failure_to_stable_unavailable_result() -> None:
    def runner(_waveform: np.ndarray) -> float:
        raise RuntimeError("private model detail")

    result = VoiceActivityDetector(runner).observe(FRAME_100MS)

    assert result.speech is False
    assert result.probability == 0.0
    assert result.reason == "voice_model_unavailable"


def test_vad_rejects_non_finite_or_out_of_range_model_output_fail_closed() -> None:
    for output in (float("nan"), float("inf"), -0.1, 1.1):
        result = VoiceActivityDetector(lambda _waveform, raw=output: raw).observe(
            FRAME_100MS
        )

        assert result.speech is False
        assert result.probability == 0.0
        assert result.reason == "voice_model_unavailable"


def test_vad_rejects_malformed_or_changed_pcm_frame_fail_closed() -> None:
    detector = VoiceActivityDetector(lambda _waveform: 0.9)

    malformed = detector.observe(b"x")
    first = detector.observe(FRAME_100MS)
    changed = detector.observe(b"\x00\x00" * 800)

    assert malformed.reason == "voice_model_unavailable"
    assert first.reason is None
    assert changed.reason == "voice_model_unavailable"
