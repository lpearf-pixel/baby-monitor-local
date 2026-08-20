from __future__ import annotations

import argparse
import json
import math
import subprocess
import tempfile
import wave
from collections.abc import Mapping
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Protocol

from packages.contracts.settings import VoiceCareSettings
from services.voice.artifacts import voice_artifact_specs
from services.voice.asr import AsrEngine, AsrResult
from services.voice.wake import validate_wake_prefix


BENCHMARK_INVALID = "voice_benchmark_invalid"
POSITIVE_TOTAL = 24
NEGATIVE_TOTAL = 48
MAX_LATENCY_MS = 3_000
_CANDIDATES = ("base", "small")
_ARTIFACT_BY_CANDIDATE = {
    "base": "openai-whisper-base",
    "small": "openai-whisper-small",
}


@dataclass(frozen=True)
class BenchmarkSample:
    pcm: bytes
    expected_wake: bool
    expected_command: str | None


@dataclass(frozen=True)
class BenchmarkManifest:
    samples: tuple[BenchmarkSample, ...]


@dataclass(frozen=True)
class ModelMetrics:
    model: str
    available: bool
    samples_evaluated: int
    wake_correct: int
    wake_total: int
    false_wakes: int
    negative_total: int
    slots_correct: int
    slots_total: int
    latency_p50_ms: int | None
    latency_p95_ms: int | None
    passed: bool


@dataclass(frozen=True)
class BenchmarkReport:
    models: tuple[ModelMetrics, ...]
    selected_model: str | None
    gate_passed: bool

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": 1,
            "models": [asdict(model) for model in self.models],
            "selected_model": self.selected_model,
            "gate_passed": self.gate_passed,
        }


class _Engine(Protocol):
    def transcribe(self, pcm: bytes) -> AsrResult: ...


class _UnavailableEngine:
    def transcribe(self, _pcm: bytes) -> AsrResult:
        raise ValueError("voice_model_unavailable")


def load_benchmark_manifest(manifest_path: Path) -> BenchmarkManifest:
    """Load only an explicit generated/public, fixed-cardinality local corpus."""

    try:
        if manifest_path.is_symlink() or not manifest_path.is_file():
            raise ValueError(BENCHMARK_INVALID)
        manifest_path = manifest_path.resolve(strict=True)
        root = manifest_path.parent
        payload = json.loads(manifest_path.read_text(encoding="utf-8"))
        if (
            not isinstance(payload, dict)
            or set(payload)
            != {"schema_version", "source_kind", "license", "samples"}
            or payload["schema_version"] != 1
            or payload["source_kind"] not in {"generated", "public"}
            or not isinstance(payload["license"], str)
            or not payload["license"].strip()
            or not isinstance(payload["samples"], list)
        ):
            raise ValueError(BENCHMARK_INVALID)
        samples = tuple(_load_sample(root, item) for item in payload["samples"])
        audio_files = [item["audio_file"] for item in payload["samples"]]
        if len(set(audio_files)) != len(audio_files):
            raise ValueError(BENCHMARK_INVALID)
        positive_total = sum(sample.expected_wake for sample in samples)
        negative_total = len(samples) - positive_total
        if positive_total != POSITIVE_TOTAL or negative_total != NEGATIVE_TOTAL:
            raise ValueError(BENCHMARK_INVALID)
    except (OSError, ValueError, UnicodeDecodeError, json.JSONDecodeError, wave.Error):
        raise ValueError(BENCHMARK_INVALID) from None
    return BenchmarkManifest(samples=samples)


def evaluate_candidates(
    manifest: BenchmarkManifest, engines: Mapping[str, _Engine]
) -> BenchmarkReport:
    """Evaluate base then small and return transcript-free aggregate metrics."""

    if set(engines) != set(_CANDIDATES):
        raise ValueError(BENCHMARK_INVALID)
    metrics = tuple(
        _evaluate_candidate(candidate, manifest, engines[candidate])
        for candidate in _CANDIDATES
    )
    selected = next((model.model for model in metrics if model.passed), None)
    return BenchmarkReport(
        models=metrics,
        selected_model=selected,
        gate_passed=selected is not None,
    )


def _load_sample(root: Path, payload: object) -> BenchmarkSample:
    if (
        not isinstance(payload, dict)
        or set(payload) != {"audio_file", "expected_wake", "expected_command"}
        or type(payload["expected_wake"]) is not bool
    ):
        raise ValueError(BENCHMARK_INVALID)
    expected_wake = payload["expected_wake"]
    expected_command = payload["expected_command"]
    if expected_wake:
        if not isinstance(expected_command, str) or not expected_command:
            raise ValueError(BENCHMARK_INVALID)
    elif expected_command is not None:
        raise ValueError(BENCHMARK_INVALID)
    audio_file = payload["audio_file"]
    if not isinstance(audio_file, str):
        raise ValueError(BENCHMARK_INVALID)
    relative = Path(audio_file)
    if relative.is_absolute() or ".." in relative.parts or relative.as_posix() != audio_file:
        raise ValueError(BENCHMARK_INVALID)
    _reject_symlink_components(root, relative)
    audio_path = (root / relative).resolve(strict=True)
    if not audio_path.is_relative_to(root) or not audio_path.is_file():
        raise ValueError(BENCHMARK_INVALID)
    with wave.open(str(audio_path), "rb") as source:
        if (
            source.getnchannels() != 1
            or source.getsampwidth() != 2
            or source.getframerate() != 16_000
            or source.getcomptype() != "NONE"
            or source.getnframes() < 1
            or source.getnframes() > 16_000 * 8
        ):
            raise ValueError(BENCHMARK_INVALID)
        pcm = source.readframes(source.getnframes())
    if len(pcm) % 2 != 0:
        raise ValueError(BENCHMARK_INVALID)
    return BenchmarkSample(
        pcm=pcm,
        expected_wake=expected_wake,
        expected_command=expected_command,
    )


def _evaluate_candidate(
    candidate: str, manifest: BenchmarkManifest, engine: _Engine
) -> ModelMetrics:
    wake_correct = 0
    false_wakes = 0
    slots_correct = 0
    latencies: list[int] = []
    try:
        for sample in manifest.samples:
            result = engine.transcribe(sample.pcm)
            if (
                not isinstance(result, AsrResult)
                or result.language != "zh"
                or type(result.duration_ms) is not int
                or result.duration_ms < 0
            ):
                raise ValueError(BENCHMARK_INVALID)
            wake = validate_wake_prefix(result.text)
            if sample.expected_wake:
                wake_correct += int(wake.accepted)
                slots_correct += int(
                    wake.accepted and wake.command == sample.expected_command
                )
            else:
                false_wakes += int(wake.accepted)
            latencies.append(result.duration_ms)
    except Exception:
        return ModelMetrics(
            model=candidate,
            available=False,
            samples_evaluated=0,
            wake_correct=0,
            wake_total=POSITIVE_TOTAL,
            false_wakes=0,
            negative_total=NEGATIVE_TOTAL,
            slots_correct=0,
            slots_total=POSITIVE_TOTAL,
            latency_p50_ms=None,
            latency_p95_ms=None,
            passed=False,
        )
    p50 = _nearest_rank(latencies, 0.50)
    p95 = _nearest_rank(latencies, 0.95)
    passed = (
        wake_correct == POSITIVE_TOTAL
        and false_wakes == 0
        and slots_correct == POSITIVE_TOTAL
        and p95 <= MAX_LATENCY_MS
    )
    return ModelMetrics(
        model=candidate,
        available=True,
        samples_evaluated=len(manifest.samples),
        wake_correct=wake_correct,
        wake_total=POSITIVE_TOTAL,
        false_wakes=false_wakes,
        negative_total=NEGATIVE_TOTAL,
        slots_correct=slots_correct,
        slots_total=POSITIVE_TOTAL,
        latency_p50_ms=p50,
        latency_p95_ms=p95,
        passed=passed,
    )


def _nearest_rank(values: list[int], quantile: float) -> int:
    ordered = sorted(values)
    return ordered[math.ceil(quantile * len(ordered)) - 1]


def _reject_symlink_components(root: Path, relative: Path) -> None:
    current = root
    for component in relative.parts:
        current = current / component
        if current.is_symlink():
            raise ValueError(BENCHMARK_INVALID)


def _generate_macos_corpus(root: Path) -> Path:
    positive_commands = (
        "我是爸爸",
        "我是妈妈",
        "我要开始喂奶",
        "我喂完奶了",
        "我要继续喂奶",
        "我要结束喂奶",
    )
    negative_utterances = (
        "嘿小小我是爸爸",
        "晓晓我是爸爸",
        "我叫小小",
        "宝宝睡着了",
        "现在几点了",
        "请打开窗帘",
        "今天晚上很安静",
        "奶瓶已经洗好了",
        "我在客厅说话",
        "记录本放在哪里",
        "明天记得买牛奶",
        "这是一个语音测试",
    )
    samples: list[dict[str, object]] = []
    rates = (150, 170, 190, 210)
    sample_root = root / "samples"
    sample_root.mkdir()
    index = 0
    for rate in rates:
        for command in positive_commands:
            relative = Path("samples") / f"sample-{index:02d}.wav"
            _synthesize("小小，" + command, rate, root / relative)
            samples.append(
                {
                    "audio_file": relative.as_posix(),
                    "expected_wake": True,
                    "expected_command": command,
                }
            )
            index += 1
    for rate in rates:
        for utterance in negative_utterances:
            relative = Path("samples") / f"sample-{index:02d}.wav"
            _synthesize(utterance, rate, root / relative)
            samples.append(
                {
                    "audio_file": relative.as_posix(),
                    "expected_wake": False,
                    "expected_command": None,
                }
            )
            index += 1
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
            separators=(",", ":"),
            sort_keys=True,
        ),
        encoding="utf-8",
    )
    return manifest


def _synthesize(text: str, rate: int, destination: Path) -> None:
    subprocess.run(
        (
            "say",
            "--voice=Ting-Ting",
            f"--rate={rate}",
            "--file-format=WAVE",
            "--data-format=LEI16@16000",
            f"--output-file={destination}",
            text,
        ),
        check=True,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the closed local Voice Care ASR gate")
    parser.add_argument(
        "--settings",
        type=Path,
        default=Path("runtime/config/voice-care-models.json"),
    )
    parser.add_argument("--manifest", type=Path)
    arguments = parser.parse_args()
    try:
        settings = VoiceCareSettings.model_validate_json(
            arguments.settings.read_text(encoding="utf-8")
        )
        specs = {spec.artifact_id: spec for spec in voice_artifact_specs(settings)}
        engines: dict[str, _Engine] = {}
        for candidate in _CANDIDATES:
            try:
                engines[candidate] = AsrEngine(
                    specs[_ARTIFACT_BY_CANDIDATE[candidate]], project_root=Path.cwd()
                )
            except Exception:
                engines[candidate] = _UnavailableEngine()
        if arguments.manifest is not None:
            report = evaluate_candidates(
                load_benchmark_manifest(arguments.manifest), engines
            )
        else:
            with tempfile.TemporaryDirectory(prefix="voice-benchmark-") as temporary:
                manifest_path = _generate_macos_corpus(Path(temporary))
                report = evaluate_candidates(
                    load_benchmark_manifest(manifest_path), engines
                )
        print(json.dumps(report.to_dict(), separators=(",", ":"), sort_keys=True))
        return 0 if report.gate_passed else 1
    except Exception:
        print(
            json.dumps(
                {
                    "gate_passed": False,
                    "reason": BENCHMARK_INVALID,
                    "schema_version": 1,
                    "selected_model": None,
                },
                separators=(",", ":"),
                sort_keys=True,
            )
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
