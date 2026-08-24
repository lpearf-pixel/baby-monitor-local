from __future__ import annotations

import subprocess
import tempfile
import wave
from collections.abc import Callable
from pathlib import Path
from typing import Protocol

from packages.contracts.settings import VoiceCareSettings
from services.voice.artifacts import voice_artifact_spec
from services.voice.silero_runtime import SileroOnnxSegmenter
from services.voice.vad_diagnostic import (
    VAD_DIAGNOSTIC_FAILED,
    VadDiagnostic,
    VadDiagnosticReport,
)
from tools.voice_asr_calibrate import _load_disabled_settings, _private_corpus


class _Diagnostic(Protocol):
    def run(self) -> VadDiagnosticReport: ...


DiagnosticBuilder = Callable[[Path], _Diagnostic]
Printer = Callable[[str], None]


def main(
    *,
    project_root: Path | None = None,
    diagnostic_builder: DiagnosticBuilder | None = None,
    printer: Printer = print,
) -> int:
    try:
        root = (project_root or Path.cwd()).resolve(strict=True)
        report = (diagnostic_builder or _build_diagnostic)(root).run()
        printer(f"result={'PASS' if report.gate_passed else 'FAIL'}")
        printer("operation=vad-diagnostic")
        printer(f"reason={report.reason}")
        printer(f"gate_passed={'true' if report.gate_passed else 'false'}")
        printer(f"control_rms_dbfs_milli={report.control_rms_dbfs_milli}")
        printer(f"control_peak_milli={report.control_peak_milli}")
        printer(f"control_span_count={report.control_span_count}")
        for index, item in enumerate(report.private, start=1):
            prefix = f"private_{index}"
            printer(f"{prefix}_prompt_id={item.prompt_id}")
            printer(f"{prefix}_rms_dbfs_milli={item.rms_dbfs_milli}")
            printer(f"{prefix}_raw_peak_milli={item.raw_peak_milli}")
            printer(f"{prefix}_raw_span_count={item.raw_span_count}")
            printer(f"{prefix}_applied_gain_db_milli={item.applied_gain_db_milli}")
            printer(f"{prefix}_final_span_count={item.final_span_count}")
        return 0 if report.gate_passed else 1
    except Exception:
        printer("result=FAIL")
        printer("operation=vad-diagnostic")
        printer(f"reason={VAD_DIAGNOSTIC_FAILED}")
        return 1


def _build_diagnostic(project_root: Path) -> VadDiagnostic:
    settings: VoiceCareSettings = _load_disabled_settings(project_root)
    artifact = voice_artifact_spec(settings, "silero-vad-v6.2")
    return VadDiagnostic(
        segmenter=SileroOnnxSegmenter(artifact, project_root=project_root),
        corpus=_private_corpus(project_root),
        control_pcm=_generated_control_pcm,
    )


def _generated_control_pcm() -> bytes:
    with tempfile.TemporaryDirectory(prefix="voice-vad-control-") as temporary:
        destination = Path(temporary) / "control.wav"
        subprocess.run(
            (
                "/usr/bin/say",
                "--voice=Tingting",
                "--rate=170",
                "--file-format=WAVE",
                "--data-format=LEI16@16000",
                f"--output-file={destination}",
                "这是公开的语音活动检测测试",
            ),
            check=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=20,
            env={
                "PATH": "/usr/bin:/bin",
                "TMPDIR": str(Path(tempfile.gettempdir()).resolve()),
            },
        )
        if destination.is_symlink() or not destination.is_file():
            raise ValueError(VAD_DIAGNOSTIC_FAILED)
        with wave.open(str(destination), "rb") as source:
            if (
                source.getframerate() != 16_000
                or source.getnchannels() != 1
                or source.getsampwidth() != 2
                or not 0 < source.getnframes() <= 16_000 * 8
            ):
                raise ValueError(VAD_DIAGNOSTIC_FAILED)
            return source.readframes(source.getnframes())


if __name__ == "__main__":
    raise SystemExit(main())
