from __future__ import annotations

import json
import wave
from pathlib import Path

import pytest

from services.voice.asr import AsrResult
from tools.voice_model_benchmark import (
    evaluate_candidates,
    load_benchmark_manifest,
)


def _write_generated_manifest(root: Path) -> Path:
    samples: list[dict[str, object]] = []
    sample_root = root / "samples"
    sample_root.mkdir(parents=True)
    for index in range(72):
        relative_path = Path("samples") / f"sample-{index:02d}.wav"
        with wave.open(str(root / relative_path), "wb") as output:
            output.setnchannels(1)
            output.setsampwidth(2)
            output.setframerate(16_000)
            output.writeframes((index + 1).to_bytes(2, "little", signed=True) * 160)
        positive = index < 24
        samples.append(
            {
                "audio_file": relative_path.as_posix(),
                "expected_wake": positive,
                "expected_command": f"测试命令{index:02d}" if positive else None,
            }
        )
    manifest_path = root / "manifest.json"
    manifest_path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "source_kind": "generated",
                "license": "GENERATED",
                "samples": samples,
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    return manifest_path


class _Engine:
    def __init__(self, transcripts: list[str], latencies_ms: list[int]) -> None:
        self._transcripts = iter(transcripts)
        self._latencies_ms = iter(latencies_ms)

    def transcribe(self, _pcm: bytes) -> AsrResult:
        return AsrResult(
            text=next(self._transcripts),
            language="zh",
            duration_ms=next(self._latencies_ms),
        )


def _passing_transcripts() -> list[str]:
    return [f"小小，测试命令{index:02d}" for index in range(24)] + [
        f"嘿，小小，测试命令{index:02d}" for index in range(24, 72)
    ]


def test_generated_manifest_reports_only_aggregate_fixed_gate_metrics(
    tmp_path: Path,
) -> None:
    manifest = load_benchmark_manifest(_write_generated_manifest(tmp_path))
    report = evaluate_candidates(
        manifest,
        {
            "base": _Engine(_passing_transcripts(), list(range(1, 73))),
            "small": _Engine(_passing_transcripts(), [100] * 72),
        },
    )

    assert report.selected_model == "base"
    assert report.gate_passed is True
    assert report.models[0].model == "base"
    assert report.models[0].wake_correct == 24
    assert report.models[0].wake_total == 24
    assert report.models[0].false_wakes == 0
    assert report.models[0].negative_total == 48
    assert report.models[0].slots_correct == 24
    assert report.models[0].slots_total == 24
    assert report.models[0].latency_p50_ms == 36
    assert report.models[0].latency_p95_ms == 69
    serialized = json.dumps(report.to_dict(), ensure_ascii=False, sort_keys=True)
    assert "测试命令" not in serialized
    assert "sample-" not in serialized
    assert str(tmp_path) not in serialized


def test_small_is_selected_only_when_base_fails_the_same_gate(tmp_path: Path) -> None:
    manifest = load_benchmark_manifest(_write_generated_manifest(tmp_path))
    base_transcripts = _passing_transcripts()
    base_transcripts[0] = "晓晓，测试命令00"

    report = evaluate_candidates(
        manifest,
        {
            "small": _Engine(_passing_transcripts(), [2_999] * 72),
            "base": _Engine(base_transcripts, [1] * 72),
        },
    )

    assert [result.model for result in report.models] == ["base", "small"]
    assert report.models[0].passed is False
    assert report.models[1].passed is True
    assert report.selected_model == "small"


def test_neither_candidate_passing_leaves_gate_disabled(tmp_path: Path) -> None:
    manifest = load_benchmark_manifest(_write_generated_manifest(tmp_path))

    report = evaluate_candidates(
        manifest,
        {
            "base": _Engine(_passing_transcripts(), [3_001] * 72),
            "small": _Engine(["晓晓"] * 72, [1] * 72),
        },
    )

    assert report.selected_model is None
    assert report.gate_passed is False
    assert all(result.passed is False for result in report.models)


def test_unavailable_base_does_not_block_small_and_has_no_fabricated_latency(
    tmp_path: Path,
) -> None:
    manifest = load_benchmark_manifest(_write_generated_manifest(tmp_path))

    class UnavailableEngine:
        def transcribe(self, _pcm: bytes) -> AsrResult:
            raise RuntimeError("sensitive runner detail")

    report = evaluate_candidates(
        manifest,
        {
            "base": UnavailableEngine(),
            "small": _Engine(_passing_transcripts(), [100] * 72),
        },
    )

    assert report.models[0].available is False
    assert report.models[0].samples_evaluated == 0
    assert report.models[0].latency_p50_ms is None
    assert report.models[0].latency_p95_ms is None
    assert report.selected_model == "small"


@pytest.mark.parametrize("source_kind", ["private", "household", "unknown"])
def test_manifest_accepts_only_explicit_public_or_generated_sources(
    tmp_path: Path, source_kind: str
) -> None:
    manifest_path = _write_generated_manifest(tmp_path)
    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    payload["source_kind"] = source_kind
    manifest_path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(ValueError, match="^voice_benchmark_invalid$"):
        load_benchmark_manifest(manifest_path)


def test_manifest_rejects_paths_outside_corpus_and_wrong_gate_cardinality(
    tmp_path: Path,
) -> None:
    manifest_path = _write_generated_manifest(tmp_path)
    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    payload["samples"][0]["audio_file"] = "../outside.wav"
    manifest_path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(ValueError, match="^voice_benchmark_invalid$"):
        load_benchmark_manifest(manifest_path)


def test_manifest_rejects_duplicate_audio_members(tmp_path: Path) -> None:
    manifest_path = _write_generated_manifest(tmp_path)
    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    payload["samples"][1]["audio_file"] = payload["samples"][0]["audio_file"]
    manifest_path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(ValueError, match="^voice_benchmark_invalid$"):
        load_benchmark_manifest(manifest_path)


def test_manifest_rejects_wrong_gate_cardinality(tmp_path: Path) -> None:

    manifest_path = _write_generated_manifest(tmp_path / "short")
    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    payload["samples"].pop()
    manifest_path.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(ValueError, match="^voice_benchmark_invalid$"):
        load_benchmark_manifest(manifest_path)
