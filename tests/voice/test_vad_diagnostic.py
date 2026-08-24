from __future__ import annotations

import numpy as np

from services.voice.silero_runtime import SileroAnalysis, SpeechSpan
from services.voice.vad_diagnostic import VadDiagnostic, VadGainPreprocessor


class Corpus:
    def __init__(self, clips: tuple[tuple[str, bytes], ...]) -> None:
        self.clips = clips

    def read_all(self) -> tuple[tuple[str, bytes], ...]:
        return self.clips


class Segmenter:
    def analyze(self, pcm: bytes) -> SileroAnalysis:
        peak = int(np.max(np.abs(np.frombuffer(pcm, dtype="<i2"))))
        spans = (SpeechSpan(0, len(pcm) // 2, 0.8),) if peak >= 2_000 else ()
        return SileroAnalysis(spans, 0.8 if spans else 0.2)


def _pcm(value: int) -> bytes:
    return np.full(8_000, value, dtype="<i2").tobytes()


def test_gain_is_capped_at_twelve_db_and_never_clips() -> None:
    result = VadGainPreprocessor().apply(
        np.asarray((20_000, -20_000), dtype="<i2").tobytes(),
        requested_gain_db=12.0,
    )

    values = np.frombuffer(result.pcm, dtype="<i2")
    assert 0.0 < result.applied_gain_db < 12.0
    assert int(values.max()) == 32_767
    assert int(values.min()) >= -32_768


def test_diagnostic_uses_gain_only_for_low_private_vad_input() -> None:
    clips = tuple(
        (prompt_id, _pcm(1_000))
        for prompt_id in (
            "feeding_start_dad",
            "feeding_start_mom",
            "feeding_amount",
            "feeding_finish",
            "care_cancel",
            "negative_weather",
        )
    )
    original = tuple(value for _prompt_id, value in clips)
    report = VadDiagnostic(
        segmenter=Segmenter(),
        corpus=Corpus(clips),
        control_pcm=lambda: _pcm(10_000),
    ).run()

    assert report.gate_passed is True
    assert report.control_span_count == 1
    assert len(report.private) == 6
    assert all(item.raw_span_count == 0 for item in report.private)
    assert all(item.final_span_count == 1 for item in report.private)
    assert all(item.applied_gain_db_milli == 12_000 for item in report.private)
    assert tuple(value for _prompt_id, value in clips) == original


def test_diagnostic_fails_closed_without_control_or_twelve_db_margin() -> None:
    clip = _pcm(3_000)
    prompt_ids = (
        "feeding_start_dad",
        "feeding_start_mom",
        "feeding_amount",
        "feeding_finish",
        "care_cancel",
        "negative_weather",
    )
    clips = tuple((prompt_id, clip) for prompt_id in prompt_ids)

    failed_control = VadDiagnostic(
        segmenter=Segmenter(),
        corpus=Corpus(clips),
        control_pcm=lambda: _pcm(1_000),
    ).run()
    no_margin = VadDiagnostic(
        segmenter=Segmenter(),
        corpus=Corpus(tuple((prompt_id, _pcm(1_000)) for prompt_id in prompt_ids)),
        control_pcm=lambda: _pcm(3_000),
    ).run()

    assert failed_control.gate_passed is False
    assert failed_control.reason == "vad_control_unavailable"
    assert no_margin.gate_passed is False
    assert no_margin.reason == "vad_candidate_unavailable"
    assert all(item.applied_gain_db_milli == 0 for item in no_margin.private)
