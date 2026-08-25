from __future__ import annotations

import json
import wave
from pathlib import Path

import pytest

from services.voice.asr import AsrResult
from tools import voice_model_benchmark as benchmark
from tools.voice_model_benchmark import (
    BenchmarkSlot,
    evaluate_candidates,
    load_benchmark_manifest,
    parse_benchmark_slot,
)


POSITIVE_COMMANDS = (
    "我是爸爸",
    "我是妈妈",
    "我要开始喂奶",
    "我喂完奶了",
    "我要继续喂奶",
    "我要结束喂奶",
)
EXPECTED_SLOTS = (
    {"kind": "speaker_claim", "value": "dad"},
    {"kind": "speaker_claim", "value": "mom"},
    {"kind": "feeding_action", "value": "start"},
    {"kind": "feeding_action", "value": "complete"},
    {"kind": "feeding_action", "value": "continue"},
    {"kind": "feeding_action", "value": "end"},
)


def _write_wav(
    path: Path,
    *,
    channels: int = 1,
    sample_rate_hz: int = 16_000,
    frames: int = 160,
    sample: int = 1,
) -> None:
    with wave.open(str(path), "wb") as output:
        output.setnchannels(channels)
        output.setsampwidth(2)
        output.setframerate(sample_rate_hz)
        output.writeframes(
            sample.to_bytes(2, "little", signed=True) * frames * channels
        )


def _write_generated_manifest(
    root: Path, *, source_kind: str = "generated"
) -> Path:
    samples: list[dict[str, object]] = []
    sample_root = root / "samples"
    sample_root.mkdir(parents=True)
    for index in range(72):
        relative_path = Path("samples") / f"sample-{index:02d}.wav"
        _write_wav(root / relative_path, sample=index + 1)
        positive = index < 24
        samples.append(
            {
                "audio_file": relative_path.as_posix(),
                "expected_wake": positive,
                "expected_slot": EXPECTED_SLOTS[index % 6] if positive else None,
            }
        )
    manifest_path = root / "manifest.json"
    manifest_path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "source_kind": source_kind,
                "license": "GENERATED" if source_kind == "generated" else "CC0-1.0",
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


def test_macos_synthesizer_uses_the_installed_mandarin_voice_name(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    commands: list[tuple[str, ...]] = []

    def run(command: tuple[str, ...], **_options: object) -> None:
        commands.append(command)

    monkeypatch.setattr(benchmark.subprocess, "run", run)
    destination = tmp_path / "sample.wav"

    benchmark._synthesize("小小，我是爸爸", 170, destination)

    assert commands == [
        (
            "say",
            "--voice=Tingting",
            "--rate=170",
            "--file-format=WAVE",
            "--data-format=LEI16@16000",
            f"--output-file={destination}",
            "小小，我是爸爸",
        )
    ]

def _passing_transcripts() -> list[str]:
    return [f"小小，{command}" for command in POSITIVE_COMMANDS * 4] + [
        "嘿，小小，我是爸爸"
    ] * 48


@pytest.mark.parametrize(
    ("command", "expected"),
    [
        ("我是爸爸", BenchmarkSlot(kind="speaker_claim", value="dad")),
        ("我是妈妈", BenchmarkSlot(kind="speaker_claim", value="mom")),
        ("我要开始喂奶", BenchmarkSlot(kind="feeding_action", value="start")),
        ("我喂完奶了", BenchmarkSlot(kind="feeding_action", value="complete")),
        ("我要继续喂奶", BenchmarkSlot(kind="feeding_action", value="continue")),
        ("我要结束喂奶", BenchmarkSlot(kind="feeding_action", value="end")),
        ("我要结束 喂奶", BenchmarkSlot(kind="feeding_action", value="end")),
        ("我要\t继续喂奶", BenchmarkSlot(kind="feeding_action", value="continue")),
    ],
)
def test_benchmark_parser_returns_only_closed_typed_slots(
    command: str, expected: BenchmarkSlot
) -> None:
    assert parse_benchmark_slot(command) == expected


def test_benchmark_parser_rejects_non_corpus_command() -> None:
    assert parse_benchmark_slot("我是父亲") is None
    assert parse_benchmark_slot("我要结束未来") is None


def test_explicit_public_manifest_is_accepted(tmp_path: Path) -> None:
    manifest = load_benchmark_manifest(
        _write_generated_manifest(tmp_path, source_kind="public")
    )

    assert len(manifest.samples) == 72
    assert manifest.samples[0].expected_slot == BenchmarkSlot(
        kind="speaker_claim", value="dad"
    )


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
    assert "speaker_claim" not in serialized
    assert "feeding_action" not in serialized
    assert "sample-" not in serialized
    assert str(tmp_path) not in serialized


def test_small_is_selected_only_when_base_fails_the_same_gate(tmp_path: Path) -> None:
    manifest = load_benchmark_manifest(_write_generated_manifest(tmp_path))
    base_transcripts = _passing_transcripts()
    base_transcripts[0] = "晓晓，我是爸爸"

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


def test_manifest_rejects_symlinked_audio(tmp_path: Path) -> None:
    corpus = tmp_path / "corpus"
    manifest_path = _write_generated_manifest(corpus)
    audio_path = corpus / "samples/sample-00.wav"
    outside = tmp_path / "outside.wav"
    _write_wav(outside)
    audio_path.unlink()
    audio_path.symlink_to(outside)

    with pytest.raises(ValueError, match="^voice_benchmark_invalid$"):
        load_benchmark_manifest(manifest_path)


@pytest.mark.parametrize("invalid_audio", ["garbage", "stereo", "overlength"])
def test_manifest_rejects_bad_or_overlength_wav(
    tmp_path: Path, invalid_audio: str
) -> None:
    manifest_path = _write_generated_manifest(tmp_path)
    audio_path = tmp_path / "samples/sample-00.wav"
    if invalid_audio == "garbage":
        audio_path.write_bytes(b"not a wav")
    elif invalid_audio == "stereo":
        _write_wav(audio_path, channels=2)
    else:
        _write_wav(audio_path, frames=16_000 * 8 + 1)

    with pytest.raises(ValueError, match="^voice_benchmark_invalid$"):
        load_benchmark_manifest(manifest_path)


def test_generated_cli_loads_base_and_small_and_prints_aggregate_only(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    settings = tmp_path / "settings.json"
    settings.write_text(
        json.dumps(
            {
                "silero_vad_manifest_sha256": "1" * 64,
                "whisper_base_manifest_sha256": "2" * 64,
                    "whisper_small_manifest_sha256": "3" * 64,
                    "paraformer_zh_manifest_sha256": "5" * 64,
                    "speechbrain_ecapa_manifest_sha256": "4" * 64,
            }
        ),
        encoding="ascii",
    )
    loaded: list[str] = []
    synthesized: list[tuple[int, int]] = []

    class GeneratedEngine:
        def __init__(self, artifact: object, **_options: object) -> None:
            artifact_id = getattr(artifact, "artifact_id")
            loaded.append(artifact_id)

        def transcribe(self, pcm: bytes) -> AsrResult:
            index = int.from_bytes(pcm[:2], "little", signed=True) - 1
            if index < 24:
                text = f"小小，{POSITIVE_COMMANDS[index % 6]}"
            else:
                text = "嘿，小小，我是爸爸"
            return AsrResult(text=text, language="zh", duration_ms=100)

    def synthesize(_text: str, rate: int, destination: Path) -> None:
        index = int(destination.stem.split("-")[1])
        synthesized.append((index, rate))
        _write_wav(destination, sample=index + 1)

    monkeypatch.setattr(benchmark, "AsrEngine", GeneratedEngine)
    monkeypatch.setattr(benchmark, "_synthesize", synthesize)

    result = benchmark.main(["--settings", str(settings)])

    output = capsys.readouterr().out.strip()
    report = json.loads(output)
    assert result == 0
    assert loaded == ["openai-whisper-base", "openai-whisper-small"]
    assert len(synthesized) == 72
    assert {rate for _index, rate in synthesized} == {150, 170, 190, 210}
    assert report["selected_model"] == "base"
    assert [model["model"] for model in report["models"]] == ["base", "small"]
    assert "我是爸爸" not in output
    assert "sample-" not in output
    assert str(tmp_path) not in output
