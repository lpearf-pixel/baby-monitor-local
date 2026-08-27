from __future__ import annotations

import argparse
import json
import math
import re
import subprocess
import tempfile
import wave
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Literal, Protocol

from packages.contracts.settings import VoiceCareSettings
from services.voice.asr import AsrResult
from services.voice.asr_correction import correct_armed_followup
from services.voice.artifacts import voice_artifact_spec
from services.voice.care_action import ActionCode, classify_exact_action
from services.voice.paraformer import ParaformerProcess


ACTION_BENCHMARK_INVALID = "voice_action_benchmark_invalid"
POSITIVE_TOTAL = 24
NEGATIVE_TOTAL = 48
MAX_LATENCY_MS = 3_000
_CANDIDATE = "current-paraformer"
_FIXTURE_ID = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")
_ACTION_CODE_ORDER: tuple[ActionCode, ...] = (
    "feeding_command",
    "diaper_change_start",
    "diaper_change_complete",
    "burping_start",
    "burping_complete",
    "medication_start_candidate",
    "medication_complete_candidate",
)
_ACTION_CODES = frozenset(_ACTION_CODE_ORDER)
MatchKind = Literal["exact", "corrected", "high_risk_candidate", "rejected"]


@dataclass(frozen=True, slots=True)
class ActionBenchmarkSample:
    pcm: bytes
    fixture_id: str
    expected_action_code: ActionCode | None
    expected_match_kind: MatchKind

    def __post_init__(self) -> None:
        if (
            type(self.pcm) is not bytes
            or not self.pcm
            or len(self.pcm) % 2
            or not _FIXTURE_ID.fullmatch(self.fixture_id)
            or not _valid_expected_pair(
                self.expected_action_code,
                self.expected_match_kind,
            )
        ):
            raise ValueError(ACTION_BENCHMARK_INVALID)


@dataclass(frozen=True, slots=True)
class ActionBenchmarkManifest:
    source_kind: Literal["generated", "public"]
    license: str
    samples: tuple[ActionBenchmarkSample, ...]

    def __post_init__(self) -> None:
        if (
            self.source_kind not in {"generated", "public"}
            or not isinstance(self.license, str)
            or not self.license.strip()
            or not self.samples
        ):
            raise ValueError(ACTION_BENCHMARK_INVALID)


@dataclass(frozen=True, slots=True)
class ActionAggregate:
    action_code: ActionCode
    total: int
    correct: int
    exact_matches: int
    corrected_matches: int
    high_risk_candidates: int
    rejected: int


@dataclass(frozen=True, slots=True)
class ActionBenchmarkReport:
    candidate: str
    available: bool
    evaluated: int
    positive_total: int
    negative_total: int
    negative_rejected: int
    correct: int
    exact_matches: int
    corrected_matches: int
    high_risk_candidates: int
    false_accepts: int
    rejected: int
    latency_p50_ms: int | None
    latency_p95_ms: int | None
    rss_peak_bytes: int | None
    gate_passed: bool
    action_metrics: tuple[ActionAggregate, ...]

    def to_dict(self) -> dict[str, object]:
        return {"schema_version": 1, **asdict(self)}


class _Engine(Protocol):
    def transcribe(self, pcm: bytes) -> AsrResult: ...


def load_action_manifest(manifest_path: Path) -> ActionBenchmarkManifest:
    """Load one fixed-cardinality generated/public corpus without retaining paths."""

    try:
        manifest_path = Path(manifest_path)
        if manifest_path.is_symlink() or not manifest_path.is_file():
            raise ValueError(ACTION_BENCHMARK_INVALID)
        manifest_path = manifest_path.resolve(strict=True)
        root = manifest_path.parent
        payload = json.loads(manifest_path.read_text(encoding="utf-8"))
        if (
            not isinstance(payload, dict)
            or set(payload) != {"schema_version", "source_kind", "license", "samples"}
            or payload["schema_version"] != 1
            or payload["source_kind"] not in {"generated", "public"}
            or not isinstance(payload["license"], str)
            or not payload["license"].strip()
            or not isinstance(payload["samples"], list)
        ):
            raise ValueError(ACTION_BENCHMARK_INVALID)
        samples = tuple(_load_sample(root, item) for item in payload["samples"])
        fixture_ids = [sample.fixture_id for sample in samples]
        audio_files = [item["audio_file"] for item in payload["samples"]]
        if (
            len(set(fixture_ids)) != len(fixture_ids)
            or len(set(audio_files)) != len(audio_files)
            or sum(sample.expected_action_code is not None for sample in samples)
            != POSITIVE_TOTAL
            or sum(sample.expected_action_code is None for sample in samples)
            != NEGATIVE_TOTAL
        ):
            raise ValueError(ACTION_BENCHMARK_INVALID)
        return ActionBenchmarkManifest(
            source_kind=payload["source_kind"],
            license=payload["license"],
            samples=samples,
        )
    except (
        OSError,
        EOFError,
        TypeError,
        ValueError,
        UnicodeDecodeError,
        json.JSONDecodeError,
        wave.Error,
    ):
        raise ValueError(ACTION_BENCHMARK_INVALID) from None


def evaluate_action_candidate(
    manifest: ActionBenchmarkManifest,
    engine: _Engine,
    *,
    candidate: str,
) -> ActionBenchmarkReport:
    """Return aggregate action metrics and immediately discard each ASR result."""

    if candidate != _CANDIDATE or not isinstance(manifest, ActionBenchmarkManifest):
        raise ValueError(ACTION_BENCHMARK_INVALID)
    positive_total = sum(
        sample.expected_action_code is not None for sample in manifest.samples
    )
    negative_total = len(manifest.samples) - positive_total
    negative_rejected = 0
    action_counts = {
        code: {
            "total": sum(sample.expected_action_code == code for sample in manifest.samples),
            "correct": 0,
            "exact_matches": 0,
            "corrected_matches": 0,
            "high_risk_candidates": 0,
            "rejected": 0,
        }
        for code in _ACTION_CODE_ORDER
    }
    correct = 0
    exact_matches = 0
    corrected_matches = 0
    high_risk_candidates = 0
    false_accepts = 0
    rejected = 0
    latencies: list[int] = []
    try:
        for sample in manifest.samples:
            result = engine.transcribe(sample.pcm)
            if (
                not isinstance(result, AsrResult)
                or result.language != "zh"
                or type(result.duration_ms) is not int
                or not 0 <= result.duration_ms <= 30_000
            ):
                raise ValueError(ACTION_BENCHMARK_INVALID)
            action_code, match_kind = _classify_armed_text(result.text)
            is_correct = (
                action_code == sample.expected_action_code
                and match_kind == sample.expected_match_kind
            )
            correct += int(is_correct)
            exact_matches += int(is_correct and match_kind == "exact")
            corrected_matches += int(is_correct and match_kind == "corrected")
            high_risk_candidates += int(
                is_correct and match_kind == "high_risk_candidate"
            )
            false_accepts += int(
                sample.expected_action_code is None and action_code is not None
            )
            rejected += int(match_kind == "rejected")
            negative_rejected += int(
                sample.expected_action_code is None and match_kind == "rejected"
            )
            if sample.expected_action_code is not None:
                action_bucket = action_counts[sample.expected_action_code]
                action_bucket["correct"] += int(is_correct)
                action_bucket["exact_matches"] += int(
                    is_correct and match_kind == "exact"
                )
                action_bucket["corrected_matches"] += int(
                    is_correct and match_kind == "corrected"
                )
                action_bucket["high_risk_candidates"] += int(
                    is_correct and match_kind == "high_risk_candidate"
                )
                action_bucket["rejected"] += int(match_kind == "rejected")
            latencies.append(result.duration_ms)
            del result
    except Exception:
        return _unavailable_report(candidate, manifest)
    p50 = _nearest_rank(latencies, 0.50)
    p95 = _nearest_rank(latencies, 0.95)
    return ActionBenchmarkReport(
        candidate=candidate,
        available=True,
        evaluated=len(manifest.samples),
        positive_total=positive_total,
        negative_total=negative_total,
        negative_rejected=negative_rejected,
        correct=correct,
        exact_matches=exact_matches,
        corrected_matches=corrected_matches,
        high_risk_candidates=high_risk_candidates,
        false_accepts=false_accepts,
        rejected=rejected,
        latency_p50_ms=p50,
        latency_p95_ms=p95,
        rss_peak_bytes=None,
        gate_passed=(
            correct == len(manifest.samples)
            and false_accepts == 0
            and p95 <= MAX_LATENCY_MS
        ),
        action_metrics=_action_aggregates(action_counts),
    )


def _load_sample(root: Path, payload: object) -> ActionBenchmarkSample:
    if (
        not isinstance(payload, dict)
        or set(payload)
        != {
            "fixture_id",
            "audio_file",
            "expected_action_code",
            "expected_match_kind",
        }
        or not isinstance(payload["fixture_id"], str)
        or not isinstance(payload["audio_file"], str)
        or not isinstance(payload["expected_match_kind"], str)
    ):
        raise ValueError(ACTION_BENCHMARK_INVALID)
    action_code = payload["expected_action_code"]
    match_kind = payload["expected_match_kind"]
    if action_code is not None and (
        not isinstance(action_code, str) or action_code not in _ACTION_CODES
    ):
        raise ValueError(ACTION_BENCHMARK_INVALID)
    if match_kind not in {"exact", "corrected", "high_risk_candidate", "rejected"}:
        raise ValueError(ACTION_BENCHMARK_INVALID)
    relative = Path(payload["audio_file"])
    if (
        relative.is_absolute()
        or ".." in relative.parts
        or relative.as_posix() != payload["audio_file"]
    ):
        raise ValueError(ACTION_BENCHMARK_INVALID)
    _reject_symlink_components(root, relative)
    audio_path = (root / relative).resolve(strict=True)
    if not audio_path.is_relative_to(root) or not audio_path.is_file():
        raise ValueError(ACTION_BENCHMARK_INVALID)
    with wave.open(str(audio_path), "rb") as source:
        if (
            source.getnchannels() != 1
            or source.getsampwidth() != 2
            or source.getframerate() != 16_000
            or source.getcomptype() != "NONE"
            or not 1 <= source.getnframes() <= 16_000 * 8
        ):
            raise ValueError(ACTION_BENCHMARK_INVALID)
        pcm = source.readframes(source.getnframes())
    return ActionBenchmarkSample(
        pcm=pcm,
        fixture_id=payload["fixture_id"],
        expected_action_code=action_code,
        expected_match_kind=match_kind,
    )


def _valid_expected_pair(action_code: object, match_kind: object) -> bool:
    if action_code is None:
        return match_kind == "rejected"
    if not isinstance(action_code, str) or action_code not in _ACTION_CODES:
        return False
    if action_code.startswith("medication_"):
        return match_kind == "high_risk_candidate"
    if action_code == "feeding_command":
        return match_kind in {"exact", "corrected"}
    return match_kind == "exact"


def _classify_armed_text(text: str) -> tuple[ActionCode | None, MatchKind]:
    if not isinstance(text, str):
        return None, "rejected"
    exact = classify_exact_action(text)
    if exact is not None:
        return (
            exact.action_code,
            "high_risk_candidate" if exact.risk == "high" else "exact",
        )
    correction = correct_armed_followup(text)
    if correction is None:
        return None, "rejected"
    corrected = classify_exact_action(correction.canonical_command)
    if corrected is None or corrected.action_code != "feeding_command":
        return None, "rejected"
    return corrected.action_code, "corrected"


def _unavailable_report(
    candidate: str,
    manifest: ActionBenchmarkManifest,
) -> ActionBenchmarkReport:
    positive_total = sum(
        sample.expected_action_code is not None for sample in manifest.samples
    )
    action_counts = {
        code: {
            "total": sum(sample.expected_action_code == code for sample in manifest.samples),
            "correct": 0,
            "exact_matches": 0,
            "corrected_matches": 0,
            "high_risk_candidates": 0,
            "rejected": 0,
        }
        for code in _ACTION_CODE_ORDER
    }
    return ActionBenchmarkReport(
        candidate=candidate,
        available=False,
        evaluated=0,
        positive_total=positive_total,
        negative_total=len(manifest.samples) - positive_total,
        negative_rejected=0,
        correct=0,
        exact_matches=0,
        corrected_matches=0,
        high_risk_candidates=0,
        false_accepts=0,
        rejected=0,
        latency_p50_ms=None,
        latency_p95_ms=None,
        rss_peak_bytes=None,
        gate_passed=False,
        action_metrics=_action_aggregates(action_counts),
    )


def _action_aggregates(
    counts: dict[ActionCode, dict[str, int]],
) -> tuple[ActionAggregate, ...]:
    return tuple(
        ActionAggregate(
            action_code=code,
            total=counts[code]["total"],
            correct=counts[code]["correct"],
            exact_matches=counts[code]["exact_matches"],
            corrected_matches=counts[code]["corrected_matches"],
            high_risk_candidates=counts[code]["high_risk_candidates"],
            rejected=counts[code]["rejected"],
        )
        for code in _ACTION_CODE_ORDER
    )


def _nearest_rank(values: list[int], quantile: float) -> int:
    ordered = sorted(values)
    return ordered[math.ceil(quantile * len(ordered)) - 1]


def _reject_symlink_components(root: Path, relative: Path) -> None:
    current = root
    for component in relative.parts:
        current = current / component
        if current.is_symlink():
            raise ValueError(ACTION_BENCHMARK_INVALID)


_GENERATED_POSITIVES = (
    "开始喂奶",
    "开始换尿布",
    "换好尿布了",
    "开始拍嗝",
    "拍嗝结束",
    "开始喂药",
    "喂药完成",
)
_GENERATED_NEGATIVES = (
    "不要开始喂奶",
    "还没开始喂奶",
    "停止喂奶",
    "取消开始喂奶",
    "开始喂奶吗",
    "开始断奶",
    "开始泡奶",
    "开始热奶",
    "开始换尿布然后开始拍嗝",
    "宝宝刚才喝了奶",
    "刚换过尿布",
    "今天天气如何",
)


def _generate_macos_corpus(root: Path) -> Path:
    samples: list[dict[str, object]] = []
    sample_root = root / "samples"
    sample_root.mkdir()
    rates = (150, 170, 190, 210)
    for index in range(POSITIVE_TOTAL):
        text = _GENERATED_POSITIVES[index % len(_GENERATED_POSITIVES)]
        exact = classify_exact_action(text)
        if exact is None:
            raise ValueError(ACTION_BENCHMARK_INVALID)
        relative = Path("samples") / f"positive-{index:02d}.wav"
        _synthesize(text, rates[index % len(rates)], root / relative)
        samples.append(
            {
                "fixture_id": f"generated-positive-{index:02d}",
                "audio_file": relative.as_posix(),
                "expected_action_code": exact.action_code,
                "expected_match_kind": (
                    "high_risk_candidate" if exact.risk == "high" else "exact"
                ),
            }
        )
    for index in range(NEGATIVE_TOTAL):
        text = _GENERATED_NEGATIVES[index % len(_GENERATED_NEGATIVES)]
        relative = Path("samples") / f"negative-{index:02d}.wav"
        _synthesize(text, rates[index % len(rates)], root / relative)
        samples.append(
            {
                "fixture_id": f"generated-negative-{index:02d}",
                "audio_file": relative.as_posix(),
                "expected_action_code": None,
                "expected_match_kind": "rejected",
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
            "--voice=Tingting",
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


def _build_current_paraformer(project_root: Path) -> ParaformerProcess:
    settings = VoiceCareSettings.model_validate_json(
        (project_root / "runtime/config/voice-care-models.json").read_text(
            encoding="utf-8"
        )
    )
    artifact = voice_artifact_spec(
        settings,
        "sherpa-onnx-paraformer-zh-2023-09-14",
    )
    return ParaformerProcess(artifact, project_root=project_root)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Run the aggregate-only closed Voice action benchmark"
    )
    parser.add_argument("--candidate", choices=(_CANDIDATE,), required=True)
    parser.add_argument("--manifest", type=Path)
    parser.add_argument("--project-root", type=Path, default=Path.cwd())
    parser.add_argument("--json", action="store_true")
    arguments = parser.parse_args(argv)
    engine: ParaformerProcess | None = None
    try:
        root = arguments.project_root.resolve(strict=True)
        engine = _build_current_paraformer(root)
        if arguments.manifest is not None:
            report = evaluate_action_candidate(
                load_action_manifest(arguments.manifest),
                engine,
                candidate=arguments.candidate,
            )
        else:
            with tempfile.TemporaryDirectory(prefix="voice-action-benchmark-") as temp:
                manifest = _generate_macos_corpus(Path(temp))
                report = evaluate_action_candidate(
                    load_action_manifest(manifest),
                    engine,
                    candidate=arguments.candidate,
                )
        output = report.to_dict()
        print(json.dumps(output, separators=(",", ":"), sort_keys=True))
        return 0 if report.gate_passed else 1
    except Exception:
        print(
            json.dumps(
                {
                    "available": False,
                    "candidate": _CANDIDATE,
                    "gate_passed": False,
                    "reason": ACTION_BENCHMARK_INVALID,
                    "schema_version": 1,
                },
                separators=(",", ":"),
                sort_keys=True,
            )
        )
        return 1
    finally:
        if engine is not None:
            engine.close()


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "ACTION_BENCHMARK_INVALID",
    "ActionAggregate",
    "ActionBenchmarkManifest",
    "ActionBenchmarkReport",
    "ActionBenchmarkSample",
    "evaluate_action_candidate",
    "load_action_manifest",
    "main",
]
