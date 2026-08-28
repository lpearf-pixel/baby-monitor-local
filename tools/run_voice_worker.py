from __future__ import annotations

import argparse
import signal
import sys
import threading
from collections.abc import Callable
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from packages.contracts.settings import AppSettings, VoiceCareSettings
from services.voice.worker import (
    VoicePreflightReport,
    VoiceStatusWriter,
    VoiceWorker,
    run_voice_preflight,
)


WorkerFactory = Callable[[AppSettings, Path], VoiceWorker]
RuntimeBuilder = Callable[[AppSettings, Path], object]
PreflightFactory = Callable[[VoiceCareSettings, Path], VoicePreflightReport]
Printer = Callable[[str], None]
_VOICE_MODELS_RELATIVE = Path("runtime/config/voice-care-models.json")
_MAX_VOICE_MODELS_BYTES = 16_384


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the independent Voice Care worker.")
    parser.add_argument("--settings", type=Path)
    parser.add_argument("--voice-models", type=Path)
    parser.add_argument("--preflight", action="store_true")
    return parser.parse_args(argv)


def main(
    argv: list[str] | None = None,
    *,
    project_root: Path = ROOT,
    worker_factory: WorkerFactory | None = None,
    runtime_builder: RuntimeBuilder | None = None,
    preflight_factory: PreflightFactory = run_voice_preflight,
    printer: Printer = print,
) -> int:
    root = Path(project_root)
    try:
        root = root.resolve(strict=True)
        args = parse_args(argv)
        if args.preflight:
            settings = _load_voice_models(root, args.voice_models)
            report = preflight_factory(settings, root)
            _print_preflight(report, printer)
            return 0 if report.available else 1
    except (Exception, KeyboardInterrupt):
        printer("result=FAIL")
        printer("operation=preflight")
        printer("voice_preflight=unavailable")
        printer("gate_passed=false")
        printer("reason=voice_preflight_unavailable")
        return 1

    status = VoiceStatusWriter(root / "runtime/status/voice.json")
    try:
        if args.settings is None:
            raise ValueError
        model_settings = (
            _load_voice_models(root, args.voice_models)
            if args.voice_models is not None
            else None
        )
        settings = AppSettings.load(args.settings, voice_models=model_settings)
        if not settings.voice_care.enabled and not settings.voice_care.listen_only_enabled:
            status.write(
                mode="disabled",
                worker_state="disabled",
                reason="voice_disabled",
                processed_count=0,
                last_latency_ms=None,
            )
            return 0
        if settings.voice_care.listen_only_enabled:
            if model_settings is None:
                raise ValueError
            if runtime_builder is None:
                from services.voice.listen_only_runtime import build_listen_only_worker

                runtime_builder = build_listen_only_worker
            worker = runtime_builder(settings, root)
        elif worker_factory is None:
            status.write(
                mode="care",
                worker_state="degraded",
                reason="voice_runtime_unavailable",
                processed_count=0,
                last_latency_ms=None,
            )
            return 2
        else:
            worker = worker_factory(settings, root)
    except Exception:
        try:
            status.write(
                mode="care" if settings.voice_care.enabled else "listen_only",
                worker_state="degraded",
                reason="voice_startup_failed",
                processed_count=0,
                last_latency_ms=None,
            )
        except Exception:
            pass
        return 2

    stop_event = threading.Event()
    restart_requested = threading.Event()

    def stop(signum: int, _frame: object) -> None:
        if signum == signal.SIGTERM:
            restart_requested.set()
        stop_event.set()

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    try:
        worker.run(stop_event)
    except Exception:
        return 2
    return 75 if restart_requested.is_set() else 0


def _load_voice_models(root: Path, supplied: Path | None) -> VoiceCareSettings:
    try:
        expected = root / _VOICE_MODELS_RELATIVE
        if supplied is None or Path(supplied) != expected:
            raise ValueError
        current = root
        for part in _VOICE_MODELS_RELATIVE.parts:
            current = current / part
            if current.is_symlink():
                raise ValueError
        payload = current.read_bytes()
        if not 0 < len(payload) <= _MAX_VOICE_MODELS_BYTES:
            raise ValueError
        settings = VoiceCareSettings.model_validate_json(payload)
        if settings.enabled:
            raise ValueError
        return settings
    except Exception:
        raise ValueError("voice_preflight_unavailable") from None


def _print_preflight(report: VoicePreflightReport, printer: Printer) -> None:
    if report.available:
        printer("result=PASS")
        printer("operation=preflight")
        printer("voice_preflight=available")
        printer("gate_passed=true")
        printer("asr_profile=paraformer")
        printer("keychain=available")
        printer("asr_artifact=available")
        printer("silero_artifact=available")
        return
    printer("result=FAIL")
    printer("operation=preflight")
    printer("voice_preflight=unavailable")
    printer("gate_passed=false")
    printer(f"reason={report.reason}")


if __name__ == "__main__":
    raise SystemExit(main())
