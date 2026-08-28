from __future__ import annotations

import json
from dataclasses import dataclass

from services.voice.asr import AsrResult
from tools.voice_action_benchmark import ActionBenchmarkManifest, ActionBenchmarkSample
from tools.voice_contextual_ab import MAX_CONTEXTUAL_RSS_BYTES, evaluate_contextual_ab


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
