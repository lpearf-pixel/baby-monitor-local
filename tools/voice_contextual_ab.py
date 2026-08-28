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
        print(json.dumps(report.to_dict(), separators=(",", ":"), sort_keys=True))
        return 0 if report.gate_passed else 1
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
