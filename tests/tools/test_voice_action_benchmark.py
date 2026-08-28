from __future__ import annotations

import json
import wave
from pathlib import Path

import pytest

from services.voice.asr import AsrResult
from tools import voice_action_benchmark as benchmark
from tools.voice_action_benchmark import (
    ActionBenchmarkManifest,
    ActionBenchmarkSample,
    evaluate_action_candidate,
    load_action_manifest,
)


ACTION_CODES = (
    "feeding_command",
    "diaper_change_start",
    "diaper_change_complete",
    "burping_start",
    "burping_complete",
    "medication_start_candidate",
    "medication_complete_candidate",
)


def _write_wav(
    path: Path,
    *,
    channels: int = 1,
    sample_rate_hz: int = 16_000,
    frames: int = 160,
    sample: int = 1,
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as output:
        output.setnchannels(channels)
        output.setsampwidth(2)
        output.setframerate(sample_rate_hz)
        output.writeframes(
            sample.to_bytes(2, "little", signed=True) * frames * channels
        )


def _write_manifest(root: Path) -> Path:
    samples: list[dict[str, object]] = []
    for index in range(72):
        relative = Path("samples") / f"fixture-{index:02d}.wav"
        _write_wav(root / relative, sample=index + 1)
        if index < 24:
            action_code = ACTION_CODES[index % len(ACTION_CODES)]
            match_kind = (
                "high_risk_candidate"
                if action_code.startswith("medication_")
                else "exact"
            )
        else:
            action_code = None
            match_kind = "rejected"
        samples.append(
            {
                "fixture_id": f"generated-{index:02d}",
                "audio_file": relative.as_posix(),
                "expected_action_code": action_code,
                "expected_match_kind": match_kind,
            }
        )
    manifest = root / "manifest.json"
    manifest.write_text(
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
    return manifest


class _Engine:
    def __init__(
        self,
        results: list[str | Exception],
        latencies_ms: list[int] | None = None,
    ) -> None:
        self._results = iter(results)
        self._latencies_ms = iter(latencies_ms or [10] * len(results))
        self.closed = False

    def transcribe(self, _pcm: bytes) -> AsrResult:
        value = next(self._results)
        if isinstance(value, Exception):
            raise value
        return AsrResult(value, "zh", next(self._latencies_ms))

    def close(self) -> None:
        self.closed = True


def test_generated_speech_synthesis_is_bounded(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[dict[str, object]] = []

    def run(_command: tuple[str, ...], **options: object) -> None:
        calls.append(options)

    monkeypatch.setattr(benchmark.subprocess, "run", run)

    benchmark._synthesize("开始喂奶", 170, tmp_path / "sample.wav")

    assert calls == [
        {
            "check": True,
            "stdout": benchmark.subprocess.DEVNULL,
            "stderr": benchmark.subprocess.DEVNULL,
            "timeout": 15,
        }
    ]


def test_generated_manifest_loads_only_fixed_action_expectations(
    tmp_path: Path,
) -> None:
    manifest = load_action_manifest(_write_manifest(tmp_path))

    assert len(manifest.samples) == 72
    assert sum(sample.expected_action_code is not None for sample in manifest.samples) == 24
    assert sum(sample.expected_action_code is None for sample in manifest.samples) == 48
    assert {sample.expected_action_code for sample in manifest.samples} >= set(ACTION_CODES)


@pytest.mark.parametrize(
    "invalid",
    [
        "missing_license",
        "private_source",
        "traversal",
        "duplicate_audio",
        "invalid_pcm",
        "unknown_action",
        "free_form_text",
    ],
)
def test_manifest_rejects_private_unbounded_or_free_form_input(
    tmp_path: Path,
    invalid: str,
) -> None:
    manifest_path = _write_manifest(tmp_path)
    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    if invalid == "missing_license":
        payload["license"] = ""
    elif invalid == "private_source":
        payload["source_kind"] = "household"
    elif invalid == "traversal":
        payload["samples"][0]["audio_file"] = "../outside.wav"
    elif invalid == "duplicate_audio":
        payload["samples"][1]["audio_file"] = payload["samples"][0]["audio_file"]
    elif invalid == "invalid_pcm":
        (tmp_path / payload["samples"][0]["audio_file"]).write_bytes(b"invalid")
    elif invalid == "unknown_action":
        payload["samples"][0]["expected_action_code"] = "open_ended_action"
    else:
        payload["samples"][0]["expected_text"] = "free form"
    manifest_path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(ValueError, match="^voice_action_benchmark_invalid$"):
        load_action_manifest(manifest_path)


def test_manifest_rejects_symlinked_manifest_or_audio(tmp_path: Path) -> None:
    corpus = tmp_path / "corpus"
    manifest_path = _write_manifest(corpus)
    manifest_link = tmp_path / "manifest-link.json"
    manifest_link.symlink_to(manifest_path)

    with pytest.raises(ValueError, match="^voice_action_benchmark_invalid$"):
        load_action_manifest(manifest_link)

    audio = corpus / "samples/fixture-00.wav"
    outside = tmp_path / "outside.wav"
    _write_wav(outside)
    audio.unlink()
    audio.symlink_to(outside)
    with pytest.raises(ValueError, match="^voice_action_benchmark_invalid$"):
        load_action_manifest(manifest_path)


def test_evaluator_distinguishes_exact_corrected_high_risk_and_false_accepts() -> None:
    manifest = ActionBenchmarkManifest(
        source_kind="generated",
        license="GENERATED",
        samples=(
            ActionBenchmarkSample(b"\x01\x00", "p1", "feeding_command", "exact"),
            ActionBenchmarkSample(b"\x02\x00", "p2", "feeding_command", "corrected"),
            ActionBenchmarkSample(
                b"\x03\x00",
                "p3",
                "medication_start_candidate",
                "high_risk_candidate",
            ),
            ActionBenchmarkSample(b"\x04\x00", "n1", None, "rejected"),
        ),
    )
    engine = _Engine(
        ["开始喂奶", "开始为奶", "开始喂药", "开始换尿布"],
        [10, 20, 30, 40],
    )

    report = evaluate_action_candidate(
        manifest,
        engine,
        candidate="current-paraformer",
    )

    assert report.evaluated == 4
    assert report.correct == 3
    assert report.exact_matches == 1
    assert report.corrected_matches == 1
    assert report.high_risk_candidates == 1
    assert report.false_accepts == 1
    assert report.rejected == 0
    action_metrics = {item.action_code: item for item in report.action_metrics}
    assert action_metrics["feeding_command"].total == 2
    assert action_metrics["feeding_command"].correct == 2
    assert action_metrics["feeding_command"].exact_matches == 1
    assert action_metrics["feeding_command"].corrected_matches == 1
    assert action_metrics["medication_start_candidate"].total == 1
    assert action_metrics["medication_start_candidate"].high_risk_candidates == 1
    assert report.negative_total == 1
    assert report.negative_rejected == 0
    assert report.latency_p50_ms == 20
    assert report.latency_p95_ms == 40
    assert report.gate_passed is False
    serialized = json.dumps(report.to_dict(), ensure_ascii=False, sort_keys=True)
    assert "开始" not in serialized
    assert "fixture" not in serialized
    assert "transcript" not in serialized


def test_engine_failure_returns_fixed_unavailable_report() -> None:
    manifest = ActionBenchmarkManifest(
        source_kind="generated",
        license="GENERATED",
        samples=(ActionBenchmarkSample(b"\x01\x00", "p1", "feeding_command", "exact"),),
    )

    report = evaluate_action_candidate(
        manifest,
        _Engine([RuntimeError("private detail")]),
        candidate="current-paraformer",
    )

    assert report.available is False
    assert report.evaluated == 0
    assert report.latency_p50_ms is None
    assert report.latency_p95_ms is None
    assert report.gate_passed is False


def test_generated_cli_uses_private_temporary_corpus_and_removes_it(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    generated_text: list[str] = []
    generated_roots: set[Path] = set()

    class GeneratedEngine:
        def transcribe(self, pcm: bytes) -> AsrResult:
            index = int.from_bytes(pcm[:2], "little", signed=True) - 1
            return AsrResult(generated_text[index], "zh", 25)

        def close(self) -> None:
            return None

    def synthesize(text: str, _rate: int, destination: Path) -> None:
        generated_text.append(text)
        generated_roots.add(destination.parents[1])
        _write_wav(destination, sample=len(generated_text))

    monkeypatch.setattr(benchmark, "_build_current_paraformer", lambda _root: GeneratedEngine())
    monkeypatch.setattr(benchmark, "_synthesize", synthesize)

    result = benchmark.main(
        [
            "--candidate",
            "current-paraformer",
            "--project-root",
            str(tmp_path),
            "--json",
        ]
    )

    output = capsys.readouterr().out.strip()
    report = json.loads(output)
    assert result == 0
    assert report["gate_passed"] is True
    assert report["evaluated"] == 72
    assert report["false_accepts"] == 0
    assert len(generated_text) == 72
    assert all(not root.exists() for root in generated_roots)
    assert "fixture" not in output
    assert "transcript" not in output
