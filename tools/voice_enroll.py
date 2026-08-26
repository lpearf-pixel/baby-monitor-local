from __future__ import annotations

import argparse
import platform
import signal
import time
from collections.abc import Callable
from pathlib import Path
from typing import Protocol
from uuid import uuid4

from packages.contracts.settings import AudioSettings, VoiceCareSettings
from services.voice.artifacts import voice_artifact_spec
from services.voice.challenge import EnrollmentChallengeSession
from services.voice.ecapa import EcapaProcess
from services.voice.enrollment import VoiceEnrollment, VoiceProfileStore
from services.voice.helper_keychain import keychain_for_runtime
from services.voice.live_enrollment import (
    BoundedLivePcmCapture,
    ENROLLMENT_FAILED,
    EnrollmentFailure,
    EnrollmentRunReport,
    LiveEnrollmentCoordinator,
    VoiceProfileRegistry,
)
from services.voice.paraformer import ParaformerProcess
from services.voice.speaker_runtime import (
    EcapaObservationRunner,
    ecapa_model_version,
)


class _Coordinator(Protocol):
    def run(self) -> EnrollmentRunReport: ...


InputFunction = Callable[[str], str]
Printer = Callable[[str], None]
Closer = Callable[[], None]
Builder = Callable[[str, Path, InputFunction, Printer], tuple[_Coordinator, Closer]]
COUNTDOWN_SECONDS = 15


def main(
    argv: list[str] | None = None,
    *,
    project_root: Path | None = None,
    builder: Builder | None = None,
    input_fn: InputFunction = input,
    printer: Printer = print,
) -> int:
    parser = argparse.ArgumentParser(description="Enroll one private adult voice profile")
    parser.add_argument("--role", required=True, choices=("dad", "mom"))
    arguments = parser.parse_args(argv)
    close: Closer | None = None
    previous: dict[int, object] = {}

    def interrupt(_signal_number: int, _frame: object) -> None:
        raise InterruptedError

    try:
        previous = {
            number: signal.signal(number, interrupt)
            for number in (signal.SIGINT, signal.SIGTERM)
        }
        root = (project_root or Path.cwd()).resolve(strict=True)
        coordinator, close = (builder or _build_operator)(
            arguments.role, root, input_fn, printer
        )
        report = coordinator.run()
        if (
            report.role != arguments.role
            or report.sample_count != 3
            or report.profile_state != "created"
            or report.raw_audio_persisted is not False
        ):
            raise ValueError(ENROLLMENT_FAILED)
        printer("result=PASS")
        printer(f"role={report.role}")
        printer("sample_count=3")
        printer("profile_state=created")
        printer("raw_audio_persisted=false")
        return 0
    except (Exception, KeyboardInterrupt) as error:
        stage = error.stage if isinstance(error, EnrollmentFailure) else "preflight"
        printer("result=FAIL")
        printer(f"reason={ENROLLMENT_FAILED}")
        printer(f"failure_stage={stage}")
        printer("raw_audio_persisted=false")
        return 1
    finally:
        if close is not None:
            try:
                close()
            except Exception:
                pass
        for number, handler in previous.items():
            signal.signal(number, handler)


def _build_operator(
    role: str,
    project_root: Path,
    input_fn: InputFunction,
    printer: Printer,
) -> tuple[LiveEnrollmentCoordinator, Closer]:
    if platform.system() != "Darwin" or platform.machine() != "x86_64":
        raise ValueError(ENROLLMENT_FAILED)
    settings = _load_disabled_settings(project_root)
    paraformer = voice_artifact_spec(
        settings, "sherpa-onnx-paraformer-zh-2023-09-14"
    )
    ecapa = voice_artifact_spec(settings, "speechbrain-ecapa-voxceleb")
    asr = ParaformerProcess(paraformer, project_root=project_root)
    process: EcapaProcess | None = None
    runner: EcapaObservationRunner | None = None
    try:
        keychain = keychain_for_runtime(project_root)
        profile_id = str(uuid4())
        store = VoiceProfileStore(
            project_root / f"runtime/private/voice-profiles/{profile_id}.json",
            keychain,
            boundary=project_root,
            profile_id=profile_id,
        )
        registry = VoiceProfileRegistry(
            project_root / "runtime/private/voice-profile-bindings.json",
            boundary=project_root,
        )
        process = EcapaProcess(ecapa, project_root=project_root)
        runner = EcapaObservationRunner(
            process=process,
            supervised_single_speaker=True,
        )
        enrollment = VoiceEnrollment(
            runner=runner,
            store=store,
            model_version=ecapa_model_version(ecapa),
            profile_id_factory=lambda: profile_id,
        )
        capture = BoundedLivePcmCapture(AudioSettings())
        challenges = EnrollmentChallengeSession()

        def capture_phrase(phrase: str) -> bytes:
            return _capture_after_countdown(
                phrase,
                capture=capture,
                input_fn=input_fn,
                printer=printer,
            )

        coordinator = LiveEnrollmentCoordinator(
            role=role,
            capture=capture_phrase,
            asr=asr,
            challenges=challenges,
            enrollment=enrollment,
            registry=registry,
            store=store,
        )
    except Exception:
        if runner is not None:
            runner.close()
        elif process is not None:
            process.close()
        asr.close()
        raise

    def close() -> None:
        try:
            assert runner is not None
            runner.close()
        finally:
            asr.close()

    return coordinator, close


def _capture_after_countdown(
    phrase: str,
    *,
    capture: BoundedLivePcmCapture,
    input_fn: InputFunction,
    printer: Printer,
    sleeper: Callable[[float], None] = time.sleep,
) -> bytes:
    printer(f"challenge={phrase}")
    if input_fn("press_enter_then_speak=") != "":
        raise ValueError(ENROLLMENT_FAILED)
    for remaining in range(COUNTDOWN_SECONDS, 0, -1):
        printer(f"capture_starts_in_seconds={remaining}")
        sleeper(1.0)
    printer("capture_now=true")
    return capture.capture()


def _load_disabled_settings(project_root: Path) -> VoiceCareSettings:
    try:
        relative = Path("runtime/config/voice-care-models.json")
        current = project_root
        for index, part in enumerate(relative.parts):
            current = current / part
            if current.is_symlink():
                raise ValueError(ENROLLMENT_FAILED)
            if index < len(relative.parts) - 1 and (
                not current.exists() or not current.is_dir()
            ):
                raise ValueError(ENROLLMENT_FAILED)
        if not current.is_file():
            raise ValueError(ENROLLMENT_FAILED)
        settings = VoiceCareSettings.model_validate_json(
            current.read_text(encoding="ascii")
        )
        if settings.enabled:
            raise ValueError(ENROLLMENT_FAILED)
        return settings
    except Exception:
        raise ValueError(ENROLLMENT_FAILED) from None


if __name__ == "__main__":
    raise SystemExit(main())
