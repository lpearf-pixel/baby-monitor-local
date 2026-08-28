from __future__ import annotations

import json
from dataclasses import dataclass

from services.voice.asr import AsrResult
from services.voice.diagnostic import RetainedDiagnosticSample
from tools.voice_action_benchmark import ActionBenchmarkManifest, ActionBenchmarkSample
from tools.voice_contextual_ab import (
    MAX_CONTEXTUAL_RSS_BYTES,
    evaluate_contextual_ab,
    evaluate_retained_contextual,
)


def _manifest() -> ActionBenchmarkManifest:
    samples = tuple(
        ActionBenchmarkSample(
            pcm=(index + 1).to_bytes(2, "little"),
            fixture_id=f"positive-{index:02d}",
            expected_action_code="burping_complete",
            expected_match_kind="exact",
        )
        for index in range(24)
    ) + tuple(
        ActionBenchmarkSample(
            pcm=(index + 25).to_bytes(2, "little"),
            fixture_id=f"negative-{index:02d}",
            expected_action_code=None,
            expected_match_kind="rejected",
        )
        for index in range(48)
    )
    return ActionBenchmarkManifest(
        source_kind="generated", license="GENERATED", samples=samples
    )


@dataclass
class RecordingEngine:
    positive_text: str

    def __post_init__(self) -> None:
        self.pcm: list[bytes] = []

    def transcribe(self, pcm: bytes) -> AsrResult:
        self.pcm.append(pcm)
        index = int.from_bytes(pcm, "little")
        return AsrResult(self.positive_text if index <= 24 else "", "zh", 20)


def test_ab_uses_identical_pcm_order_and_serializes_aggregate_only() -> None:
    manifest = _manifest()
    baseline = RecordingEngine("")
    candidate = RecordingEngine("拍嗝结束")

    report = evaluate_contextual_ab(
        manifest,
        baseline,
        candidate,
        candidate_rss_peak_bytes=512 * 1024 * 1024,
    )

    assert baseline.pcm == candidate.pcm == [sample.pcm for sample in manifest.samples]
    assert report.baseline.evaluated == 72
    assert report.baseline.gate_passed is False
    assert report.candidate.evaluated == 72
    assert report.candidate.correct == 72
    assert report.candidate.negative_rejected == 48
    assert report.candidate.false_accepts == 0
    assert report.candidate.rss_peak_bytes == 512 * 1024 * 1024
    assert report.gate_passed is True
    serialized = json.dumps(report.to_dict(), ensure_ascii=False, sort_keys=True)
    assert "拍嗝" not in serialized
    assert "positive-" not in serialized
    assert "fixture" not in serialized
    assert "transcript" not in serialized


def test_ab_fails_closed_for_rss_or_candidate_error_without_hiding_baseline() -> None:
    manifest = _manifest()
    baseline = RecordingEngine("拍嗝结束")
    candidate = RecordingEngine("拍嗝结束")
    too_large = evaluate_contextual_ab(
        manifest,
        baseline,
        candidate,
        candidate_rss_peak_bytes=MAX_CONTEXTUAL_RSS_BYTES + 1,
    )
    assert too_large.baseline.gate_passed is True
    assert too_large.candidate.gate_passed is False
    assert too_large.gate_passed is False

    class FailedEngine:
        def transcribe(self, _pcm: bytes) -> AsrResult:
            raise RuntimeError("private transcript/path")

    failed = evaluate_contextual_ab(
        manifest,
        RecordingEngine("拍嗝结束"),
        FailedEngine(),
        candidate_rss_peak_bytes=None,
    )
    assert failed.baseline.gate_passed is True
    assert failed.candidate.available is False
    assert failed.candidate.evaluated == 0
    assert failed.gate_passed is False
    assert "private" not in json.dumps(failed.to_dict())


def test_private_gate_requires_public_pass_and_known_two_stage_shape() -> None:
    samples = (
        RetainedDiagnosticSample(
            pcm=b"\x01\x00",
            sequence=1,
            phase_before="idle",
            outcome_reason="listen_only_armed",
            action_code=None,
            match_kind=None,
        ),
        RetainedDiagnosticSample(
            pcm=b"\x02\x00",
            sequence=2,
            phase_before="armed",
            outcome_reason="listen_only_followup_far",
            action_code=None,
            match_kind=None,
        ),
    )
    baseline = RecordingEngine("")
    candidate = RecordingEngine("拍嗝结束")

    report = evaluate_retained_contextual(
        samples,
        baseline,
        candidate,
        public_gate_passed=True,
    )

    assert report.sample_count == 1
    assert report.baseline_exact == 0
    assert report.candidate_exact == 1
    assert report.gate_passed is True
    assert baseline.pcm == candidate.pcm == [b"\x02\x00"]
    assert "拍嗝" not in json.dumps(report.to_dict(), ensure_ascii=False)

    blocked = evaluate_retained_contextual(
        samples,
        RecordingEngine(""),
        RecordingEngine("拍嗝结束"),
        public_gate_passed=False,
    )
    assert blocked.sample_count == 0
    assert blocked.gate_passed is False
