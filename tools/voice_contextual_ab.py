from __future__ import annotations

import argparse
import json
import subprocess
import tempfile
from collections.abc import Callable
from dataclasses import asdict, dataclass, replace
from pathlib import Path
from typing import Protocol

from services.voice.asr import AsrResult
from services.voice.contextual_paraformer import ContextualParaformerProcess
from services.voice.care_action import classify_exact_action
from services.voice.diagnostic import (
    RetainedDiagnosticSample,
    load_latest_retained_session,
    read_retained_diagnostic_sample,
    snapshot_session_artifacts,
)
from tools.voice_action_benchmark import (
    ActionBenchmarkManifest,
    ActionBenchmarkReport,
    _build_current_paraformer,
    _generate_macos_corpus,
    evaluate_action_candidate,
    load_action_manifest,
)


MAX_CONTEXTUAL_RSS_BYTES = 2 * 1024 * 1024 * 1024
INVALID = "voice_contextual_ab_invalid"


class _Engine(Protocol):
    def transcribe(self, pcm: bytes) -> AsrResult: ...


@dataclass(frozen=True, slots=True)
class ContextualAbReport:
    baseline: ActionBenchmarkReport
    candidate: ActionBenchmarkReport
    gate_passed: bool

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": 1,
            "baseline": asdict(self.baseline),
            "candidate": asdict(self.candidate),
            "gate_passed": self.gate_passed,
        }


@dataclass(frozen=True, slots=True)
class PrivateContextualReport:
    sample_count: int
    baseline_exact: int
    candidate_exact: int
    gate_passed: bool

    def to_dict(self) -> dict[str, object]:
        return {"schema_version": 1, **asdict(self)}


def evaluate_contextual_ab(
    manifest: ActionBenchmarkManifest,
    baseline: _Engine,
    candidate: _Engine,
    *,
    candidate_rss_peak_bytes: int | None | Callable[[], int | None],
) -> ContextualAbReport:
    if (
        not isinstance(manifest, ActionBenchmarkManifest)
        or len(manifest.samples) != 72
        or sum(item.expected_action_code is not None for item in manifest.samples) != 24
        or sum(item.expected_action_code is None for item in manifest.samples) != 48
    ):
        raise ValueError(INVALID)
    baseline_report = evaluate_action_candidate(
        manifest, baseline, candidate="current-paraformer"
    )
    candidate_report = evaluate_action_candidate(
        manifest, candidate, candidate="contextual-paraformer-hotword"
    )
    observed_rss = (
        candidate_rss_peak_bytes()
        if callable(candidate_rss_peak_bytes)
        else candidate_rss_peak_bytes
    )
    valid_rss = (
        type(observed_rss) is int
        and 0 < observed_rss <= MAX_CONTEXTUAL_RSS_BYTES
    )
    candidate_report = replace(
        candidate_report,
        rss_peak_bytes=observed_rss if valid_rss else None,
        gate_passed=candidate_report.gate_passed and valid_rss,
    )
    return ContextualAbReport(
        baseline=baseline_report,
        candidate=candidate_report,
        gate_passed=candidate_report.gate_passed,
    )


def evaluate_retained_contextual(
    samples: tuple[RetainedDiagnosticSample, ...],
    baseline: _Engine,
    candidate: _Engine,
    *,
    public_gate_passed: bool,
) -> PrivateContextualReport:
    if public_gate_passed is not True:
        return PrivateContextualReport(0, 0, 0, False)
    expected_shape = (
        (1, "idle", "listen_only_armed"),
        (2, "armed", "listen_only_followup_far"),
    )
    if (
        type(samples) is not tuple
        or len(samples) != 2
        or tuple(
            (sample.sequence, sample.phase_before, sample.outcome_reason)
            for sample in samples
        )
        != expected_shape
        or any(sample.action_code is not None or sample.match_kind is not None for sample in samples)
    ):
        return PrivateContextualReport(0, 0, 0, False)
    try:
        pcm = samples[1].pcm
        baseline_result = baseline.transcribe(pcm)
        baseline_match = classify_exact_action(baseline_result.text)
        baseline_exact = int(
            baseline_match is not None
            and baseline_match.action_code == "burping_complete"
        )
        del baseline_result
        candidate_result = candidate.transcribe(pcm)
        candidate_match = classify_exact_action(candidate_result.text)
        candidate_exact = int(
            candidate_match is not None
            and candidate_match.action_code == "burping_complete"
        )
        del candidate_result
        return PrivateContextualReport(
            sample_count=1,
            baseline_exact=baseline_exact,
            candidate_exact=candidate_exact,
            gate_passed=baseline_exact == 0 and candidate_exact == 1,
        )
    except Exception:
        return PrivateContextualReport(0, 0, 0, False)


class _MeasuredCandidate:
    def __init__(self, process: ContextualParaformerProcess) -> None:
        self._process = process
        self.rss_peak_bytes: int | None = None

    def transcribe(self, pcm: bytes) -> AsrResult:
        result = self._process.transcribe(pcm)
        pid = self._process.pid
        rss = None if pid is None else _rss_bytes(pid)
        if rss is not None:
            self.rss_peak_bytes = max(self.rss_peak_bytes or 0, rss)
        return result


class _UnavailableEngine:
    def transcribe(self, _pcm: bytes) -> AsrResult:
        raise ValueError(INVALID)


def _rss_bytes(pid: int) -> int | None:
    try:
        result = subprocess.run(
            ("/bin/ps", "-o", "rss=", "-p", str(pid)),
            check=False,
            capture_output=True,
            text=True,
            timeout=1,
        )
        value = result.stdout.strip()
        if result.returncode != 0 or not value.isdigit():
            return None
        return int(value) * 1024
    except (OSError, subprocess.SubprocessError, ValueError):
        return None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run fixed contextual ASR A/B")
    parser.add_argument("--project-root", type=Path, default=Path.cwd())
    parser.add_argument("--private", action="store_true")
    arguments = parser.parse_args(argv)
    baseline_process = None
    candidate_process = None
    try:
        root = arguments.project_root.resolve(strict=True)
        with tempfile.TemporaryDirectory(prefix="voice-contextual-ab-") as name:
            manifest = load_action_manifest(_generate_macos_corpus(Path(name)))
            try:
                baseline_process = _build_current_paraformer(root)
                baseline: _Engine = baseline_process
            except Exception:
                baseline = _UnavailableEngine()
            measured: _MeasuredCandidate | None = None
            try:
                candidate_process = ContextualParaformerProcess(project_root=root)
                measured = _MeasuredCandidate(candidate_process)
                candidate: _Engine = measured
            except Exception:
                candidate = _UnavailableEngine()
            report = evaluate_contextual_ab(
                manifest,
                baseline,
                candidate,
                candidate_rss_peak_bytes=(
                    None if measured is None else lambda: measured.rss_peak_bytes
                ),
            )
            if arguments.private:
                retained = (
                    load_latest_retained_session(root)
                    if report.gate_passed
                    else None
                )
                private_report = PrivateContextualReport(0, 0, 0, False)
                if retained is not None:
                    snapshot = snapshot_session_artifacts(retained)
                    if (
                        snapshot.complete_count == 2
                        and snapshot.incomplete_count == 0
                    ):
                        private_report = evaluate_retained_contextual(
                            (
                                read_retained_diagnostic_sample(retained, 1),
                                read_retained_diagnostic_sample(retained, 2),
                            ),
                            baseline,
                            candidate,
                            public_gate_passed=report.gate_passed,
                        )
                output = {
                    "schema_version": 1,
                    "public_gate_passed": report.gate_passed,
                    "private": private_report.to_dict(),
                    "gate_passed": private_report.gate_passed,
                }
                result = private_report.gate_passed
            else:
                output = report.to_dict()
                result = report.gate_passed
        print(json.dumps(output, separators=(",", ":"), sort_keys=True))
        return 0 if result else 1
    except Exception:
        print(
            json.dumps(
                {
                    "gate_passed": False,
                    "reason": INVALID,
                    "schema_version": 1,
                },
                separators=(",", ":"),
                sort_keys=True,
            )
        )
        return 1
    finally:
        if candidate_process is not None:
            candidate_process.close()
        if baseline_process is not None:
            baseline_process.close()


if __name__ == "__main__":
    raise SystemExit(main())
