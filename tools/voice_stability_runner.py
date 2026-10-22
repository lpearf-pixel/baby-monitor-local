"""Bounded, transcript-free software runner for the Voice Stability P0 loop."""

from __future__ import annotations

import argparse
import json
import re
import time
import wave
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from services.voice.stability import VoicePlaybackStatus, VoiceStabilitySession
from services.voice.tts import PlaybackResult, PlaybackStatus, phrase_for_semantic_code


@dataclass(frozen=True, slots=True)
class VoiceRegressionCase:
    test_id: str
    pcm: bytes
    expected_response: str
    push_to_talk: bool = False


@dataclass(frozen=True, slots=True)
class VoiceAudioManifest:
    source_kind: Literal["generated", "public"]
    license: str
    cases: tuple[VoiceRegressionCase, ...]


def load_voice_manifest(manifest_path: Path) -> VoiceAudioManifest:
    """Load fixed, non-private WAV inputs and retain PCM only in memory."""

    try:
        path = Path(manifest_path)
        if path.is_symlink() or not path.is_file():
            raise ValueError("voice_stability_runner_invalid")
        path = path.resolve(strict=True)
        payload = json.loads(path.read_text(encoding="utf-8"))
        if (
            not isinstance(payload, dict)
            or set(payload) != {"schema_version", "source_kind", "license", "samples"}
            or payload["schema_version"] != 1
            or payload["source_kind"] not in {"generated", "public"}
            or not isinstance(payload["license"], str)
            or not payload["license"].strip()
            or not isinstance(payload["samples"], list)
            or not payload["samples"]
        ):
            raise ValueError("voice_stability_runner_invalid")
        cases: list[VoiceRegressionCase] = []
        seen_ids: set[str] = set()
        seen_audio: set[str] = set()
        for item in payload["samples"]:
            if (
                not isinstance(item, dict)
                or set(item)
                != {
                    "test_id",
                    "audio_file",
                    "expected_text",
                    "expected_response",
                    "push_to_talk",
                }
                or not isinstance(item["test_id"], str)
                or not _VALID_ID.fullmatch(item["test_id"])
                or not isinstance(item["audio_file"], str)
                or not isinstance(item["expected_text"], str)
                or not item["expected_text"].strip()
                or not isinstance(item["expected_response"], str)
                or not isinstance(item["push_to_talk"], bool)
            ):
                raise ValueError("voice_stability_runner_invalid")
            relative = Path(item["audio_file"])
            if (
                relative.is_absolute()
                or str(relative) in seen_audio
                or item["test_id"] in seen_ids
                or not relative.parts
            ):
                raise ValueError("voice_stability_runner_invalid")
            seen_ids.add(item["test_id"])
            seen_audio.add(str(relative))
            audio = _load_wav(path.parent, relative)
            cases.append(
                VoiceRegressionCase(
                    test_id=item["test_id"],
                    pcm=audio,
                    expected_response=item["expected_response"],
                    push_to_talk=item["push_to_talk"],
                )
            )
        return VoiceAudioManifest(
            source_kind=payload["source_kind"],
            license=payload["license"],
            cases=tuple(cases),
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
        raise ValueError("voice_stability_runner_invalid") from None


@dataclass(frozen=True, slots=True)
class VoiceRegressionReport:
    evidence_kind: Literal["synthetic", "public", "real_audio"]
    total: int
    passed: int
    failed: int
    ambiguous: int
    residuals: int
    p50_ms: int
    p95_ms: int
    p99_ms: int

    @property
    def software_test_pass(self) -> bool:
        return (
            self.total > 0
            and self.passed == self.total
            and self.failed == 0
            and self.ambiguous == 0
            and self.residuals == 0
        )

    def to_dict(self) -> dict[str, object]:
        return {
            "schema_version": 1,
            "evidence_kind": self.evidence_kind,
            "total": self.total,
            "passed": self.passed,
            "failed": self.failed,
            "ambiguous": self.ambiguous,
            "residuals": self.residuals,
            "p50_ms": self.p50_ms,
            "p95_ms": self.p95_ms,
            "p99_ms": self.p99_ms,
            "software_test_pass": self.software_test_pass,
        }


class VoiceRegressionRunner:
    def __init__(
        self,
        *,
        cases: Sequence[VoiceRegressionCase],
        asr_factory: Callable[[VoiceRegressionCase], object],
        output_factory: Callable[[VoiceRegressionCase], object],
        evidence_kind: Literal["synthetic", "public", "real_audio"] = "synthetic",
    ) -> None:
        if (
            not cases
            or len({case.test_id for case in cases}) != len(cases)
            or evidence_kind not in {"synthetic", "public", "real_audio"}
        ):
            raise ValueError("voice_stability_runner_invalid")
        self._cases = tuple(cases)
        self._asr_factory = asr_factory
        self._output_factory = output_factory
        self._evidence_kind = evidence_kind

    def run(self, *, repetitions: int = 1_000) -> VoiceRegressionReport:
        if type(repetitions) is not int or not 1 <= repetitions <= 10_000:
            raise ValueError("voice_stability_runner_invalid")
        total = len(self._cases) * repetitions
        passed = failed = ambiguous = residuals = 0
        latencies: list[int] = []
        for _ in range(repetitions):
            for case in self._cases:
                output = self._output_factory(case)
                session = VoiceStabilitySession(
                    asr=self._asr_factory(case),
                    output=output,
                )
                started = time.perf_counter_ns()
                state = session.handle_pcm(
                    case.pcm,
                    _NeverCancelled(),
                    push_to_talk=case.push_to_talk,
                )
                latencies.append(max(0, (time.perf_counter_ns() - started) // 1_000_000))
                if state.playback_status is VoicePlaybackStatus.AMBIGUOUS:
                    ambiguous += 1
                elif (
                    state.phase.value == "IDLE"
                    and state.response_code == case.expected_response
                    and state.playback_status is VoicePlaybackStatus.COMPLETE
                ):
                    passed += 1
                else:
                    failed += 1
                residuals += int(getattr(output, "residual_count", 0) != 0)
        return VoiceRegressionReport(
            evidence_kind=self._evidence_kind,
            total=total,
            passed=passed,
            failed=failed,
            ambiguous=ambiguous,
            residuals=residuals,
            p50_ms=_percentile(latencies, 50),
            p95_ms=_percentile(latencies, 95),
            p99_ms=_percentile(latencies, 99),
        )


class _NeverCancelled:
    def is_set(self) -> bool:
        return False


class _RecordingVoiceOutput:
    """Exercise the semantic TTS boundary without touching household speakers."""

    residual_count = 0

    def speak_code_result(self, code: str, _cancelled: object) -> PlaybackResult:
        phrase_for_semantic_code(code)
        return PlaybackResult(PlaybackStatus.COMPLETE)


def _percentile(values: Sequence[int], percentile: int) -> int:
    if not values or percentile not in {50, 95, 99}:
        raise ValueError("voice_stability_runner_invalid")
    ordered = sorted(values)
    index = min(len(ordered) - 1, (len(ordered) * percentile + 99) // 100 - 1)
    return ordered[index]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run bounded Voice Stability software checks")
    parser.add_argument("--manifest", type=Path)
    parser.add_argument("--project-root", type=Path, default=Path.cwd())
    parser.add_argument("--repetitions", type=int, default=1_000)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    try:
        if args.manifest is None:
            raise ValueError("audio_manifest_required")
        manifest = load_voice_manifest(args.manifest)
        from tools.voice_action_benchmark import _build_current_paraformer

        asr = _build_current_paraformer(Path(args.project_root).resolve(strict=True))
        try:
            runner = VoiceRegressionRunner(
                cases=manifest.cases,
                asr_factory=lambda _case: asr,
                output_factory=lambda _case: _RecordingVoiceOutput(),
                evidence_kind=manifest.source_kind,
            )
            report = runner.run(repetitions=args.repetitions)
        finally:
            asr.close()
        payload = {
            **report.to_dict(),
            "license": manifest.license,
            "tts_device": "semantic_boundary_only",
            "audio_persistence": "none",
        }
        print(json.dumps(payload, ensure_ascii=False, separators=(",", ":"), sort_keys=True))
        return 0 if report.software_test_pass else 1
    except Exception as exc:
        reason = str(exc) if str(exc) in {
            "audio_manifest_required",
            "voice_stability_runner_invalid",
        } else "voice_stability_runner_unavailable"
        payload = {"available": False, "software_test_pass": False, "reason": reason}
        if args.json:
            print(json.dumps(payload, separators=(",", ":"), sort_keys=True))
        else:
            print("result=FAIL")
            print(f"reason={reason}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "VoiceRegressionCase",
    "VoiceAudioManifest",
    "VoiceRegressionReport",
    "VoiceRegressionRunner",
    "load_voice_manifest",
    "main",
]


_VALID_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,79}$")
_MAX_WAV_BYTES = 8 * 16_000 * 2 + 44


def _load_wav(root: Path, relative: Path) -> bytes:
    current = root
    for component in relative.parts:
        current = current / component
        if current.is_symlink():
            raise ValueError("voice_stability_runner_invalid")
    path = (root / relative).resolve(strict=True)
    if not path.is_relative_to(root.resolve(strict=True)):
        raise ValueError("voice_stability_runner_invalid")
    if path.stat().st_size > _MAX_WAV_BYTES:
        raise ValueError("voice_stability_runner_invalid")
    with wave.open(str(path), "rb") as source:
        if (
            source.getnchannels() != 1
            or source.getsampwidth() != 2
            or source.getframerate() != 16_000
            or source.getnframes() <= 0
            or source.getnframes() > 8 * 16_000
        ):
            raise ValueError("voice_stability_runner_invalid")
        pcm = source.readframes(source.getnframes())
    if not pcm or len(pcm) % 2:
        raise ValueError("voice_stability_runner_invalid")
    return pcm
