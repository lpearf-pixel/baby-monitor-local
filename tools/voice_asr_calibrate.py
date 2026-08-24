from __future__ import annotations

import argparse
import platform
from collections.abc import Callable
from pathlib import Path
from typing import Protocol

from packages.contracts.settings import AudioSettings, VoiceCareSettings
from services.voice.artifacts import voice_artifact_spec
from services.voice.asr import AsrEngine
from services.voice.asr_calibration import (
    ASR_CALIBRATION_FAILED,
    AsrCalibrationCapture,
    AsrCalibrationEvaluator,
    AsrCalibrationFailure,
    BoundedCalibrationPcmCapture,
    CalibrationCaptureReport,
    CalibrationGateReport,
    FixedWindowAsrCalibrationCapture,
    FixedWindowCaptureReport,
)
from services.voice.asr_corpus import PRIVATE_ASR_PROMPTS, PrivateAsrCorpus
from services.voice.keychain import KeychainSecretStore, MacOSSecurityKeychain
from services.voice.silero_runtime import SileroOnnxSegmenter


class _Capture(Protocol):
    def capture(self, prompt_id: str) -> CalibrationCaptureReport: ...

    def capture_all(
        self, prompt_ids: tuple[str, ...]
    ) -> tuple[CalibrationCaptureReport, ...]: ...


class _Evaluator(Protocol):
    def evaluate(self) -> CalibrationGateReport: ...


class _FixedCapture(Protocol):
    def capture(self, prompt_id: str) -> FixedWindowCaptureReport: ...


CaptureBuilder = Callable[[Path], _Capture]
FixedCaptureBuilder = Callable[[Path], _FixedCapture]
EvaluatorBuilder = Callable[[Path], _Evaluator]
InputFunction = Callable[[str], str]
Printer = Callable[[str], None]


def main(
    argv: list[str] | None = None,
    *,
    project_root: Path | None = None,
    capture_builder: CaptureBuilder | None = None,
    fixed_capture_builder: FixedCaptureBuilder | None = None,
    evaluator_builder: EvaluatorBuilder | None = None,
    input_fn: InputFunction = input,
    printer: Printer = print,
) -> int:
    parser = argparse.ArgumentParser(description="Run the private local ASR accuracy gate")
    subparsers = parser.add_subparsers(dest="operation", required=True)
    capture_parser = subparsers.add_parser("capture")
    capture_parser.add_argument(
        "--prompt-id", required=True, choices=tuple(PRIVATE_ASR_PROMPTS)
    )
    fixed_parser = subparsers.add_parser("capture-fixed")
    fixed_parser.add_argument(
        "--prompt-id", required=True, choices=tuple(PRIVATE_ASR_PROMPTS)
    )
    subparsers.add_parser("capture-all")
    subparsers.add_parser("evaluate")
    arguments = parser.parse_args(argv)
    operation = str(arguments.operation)
    try:
        root = (project_root or Path.cwd()).resolve(strict=True)
        if operation in {"capture", "capture-fixed"}:
            prompt_id = str(arguments.prompt_id)
            printer(f"prompt_id={prompt_id}")
            printer(f"prompt={PRIVATE_ASR_PROMPTS[prompt_id]}")
            if input_fn("press_enter_then_speak=") != "":
                raise ValueError
            selected_builder = (
                (fixed_capture_builder or _build_fixed_capture)
                if operation == "capture-fixed"
                else (capture_builder or _build_capture)
            )
            report = selected_builder(root).capture(prompt_id)
            if report.prompt_id != prompt_id or report.encrypted_clip_persisted is not True:
                raise ValueError
            printer("result=PASS")
            printer(f"operation={operation}")
            printer(f"duration_ms={report.duration_ms}")
            if operation == "capture":
                printer(f"vad_peak_milli={report.vad_peak_milli}")
            printer("encrypted_clip_persisted=true")
            return 0
        if operation == "capture-all":
            prompt_ids = tuple(PRIVATE_ASR_PROMPTS)
            for index, prompt_id in enumerate(prompt_ids, start=1):
                printer(f"prompt_{index}={PRIVATE_ASR_PROMPTS[prompt_id]}")
            printer("instruction=pause_two_seconds_between_phrases")
            if input_fn("press_enter_then_read_all=") != "":
                raise ValueError
            reports = (capture_builder or _build_batch_capture)(root).capture_all(
                prompt_ids
            )
            if (
                tuple(report.prompt_id for report in reports) != prompt_ids
                or not all(report.encrypted_clip_persisted for report in reports)
            ):
                raise ValueError
            printer("result=PASS")
            printer("operation=capture-all")
            printer(f"clip_count={len(reports)}")
            printer(f"duration_total_ms={sum(report.duration_ms for report in reports)}")
            printer(
                f"vad_peak_min_milli={min(report.vad_peak_milli for report in reports)}"
            )
            printer("encrypted_clip_persisted=true")
            return 0
        report = (evaluator_builder or _build_evaluator)(root).evaluate()
        printer(f"result={'PASS' if report.gate_passed else 'FAIL'}")
        printer("operation=evaluate")
        printer(f"gate_passed={_boolean(report.gate_passed)}")
        printer(f"selected_model={report.selected_model or 'none'}")
        for model in report.models:
            printer(f"{model.model}_available={_boolean(model.available)}")
            printer(f"{model.model}_samples_evaluated={model.samples_evaluated}")
            printer(f"{model.model}_exact_matches={model.exact_matches}")
            printer(f"{model.model}_wake_matches={model.wake_matches}")
            printer(
                f"{model.model}_latency_p50_ms="
                f"{model.latency_p50_ms if model.latency_p50_ms is not None else 'none'}"
            )
            printer(
                f"{model.model}_latency_p95_ms="
                f"{model.latency_p95_ms if model.latency_p95_ms is not None else 'none'}"
            )
            printer(f"{model.model}_passed={_boolean(model.passed)}")
        return 0 if report.gate_passed else 1
    except (Exception, KeyboardInterrupt) as error:
        printer("result=FAIL")
        printer(f"operation={operation}")
        printer(f"reason={ASR_CALIBRATION_FAILED}")
        if isinstance(error, AsrCalibrationFailure):
            printer(f"failure_stage={error.stage}")
            if error.detected_segment_count is not None:
                printer(f"detected_segment_count={error.detected_segment_count}")
            if error.captured_ms is not None:
                printer(f"captured_ms={error.captured_ms}")
        return 1


def _build_capture(project_root: Path) -> AsrCalibrationCapture:
    settings = _load_disabled_settings(project_root)
    silero = voice_artifact_spec(settings, "silero-vad-v6.2")
    return AsrCalibrationCapture(
        capture_window=BoundedCalibrationPcmCapture(AudioSettings()).capture,
        segmenter=SileroOnnxSegmenter(silero, project_root=project_root),
        corpus=_private_corpus(project_root),
    )


def _build_batch_capture(project_root: Path) -> AsrCalibrationCapture:
    settings = _load_disabled_settings(project_root)
    silero = voice_artifact_spec(settings, "silero-vad-v6.2")
    return AsrCalibrationCapture(
        capture_window=BoundedCalibrationPcmCapture(
            AudioSettings(), capture_seconds=30
        ).capture,
        segmenter=SileroOnnxSegmenter(silero, project_root=project_root),
        corpus=_private_corpus(project_root),
    )


def _build_fixed_capture(project_root: Path) -> FixedWindowAsrCalibrationCapture:
    _load_disabled_settings(project_root)
    return FixedWindowAsrCalibrationCapture(
        capture_window=BoundedCalibrationPcmCapture(
            AudioSettings(), capture_seconds=8
        ).capture,
        corpus=_private_corpus(project_root),
    )


def _build_evaluator(project_root: Path) -> AsrCalibrationEvaluator:
    settings = _load_disabled_settings(project_root)
    return AsrCalibrationEvaluator(
        corpus=_private_corpus(project_root),
        engines={
            "base": AsrEngine(
                voice_artifact_spec(settings, "openai-whisper-base"),
                project_root=project_root,
            ),
            "small": AsrEngine(
                voice_artifact_spec(settings, "openai-whisper-small"),
                project_root=project_root,
            ),
        },
    )


def _private_corpus(project_root: Path) -> PrivateAsrCorpus:
    return PrivateAsrCorpus(
        project_root / "runtime/private/voice-asr-calibration.json",
        KeychainSecretStore(MacOSSecurityKeychain()),
        boundary=project_root,
    )


def _load_disabled_settings(project_root: Path) -> VoiceCareSettings:
    try:
        if platform.system() != "Darwin" or platform.machine() != "x86_64":
            raise ValueError
        relative = Path("runtime/config/voice-care-models.json")
        current = project_root
        for index, part in enumerate(relative.parts):
            current = current / part
            if current.is_symlink():
                raise ValueError
            if index < len(relative.parts) - 1 and (
                not current.exists() or not current.is_dir()
            ):
                raise ValueError
        if not current.is_file():
            raise ValueError
        settings = VoiceCareSettings.model_validate_json(
            current.read_text(encoding="ascii")
        )
        if settings.enabled:
            raise ValueError
        return settings
    except Exception:
        raise ValueError(ASR_CALIBRATION_FAILED) from None


def _boolean(value: bool) -> str:
    return "true" if value else "false"


if __name__ == "__main__":
    raise SystemExit(main())
