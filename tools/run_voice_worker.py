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

from packages.contracts.settings import AppSettings
from services.voice.worker import VoiceStatusWriter, VoiceWorker


WorkerFactory = Callable[[AppSettings, Path], VoiceWorker]


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run the independent Voice Care worker.")
    parser.add_argument("--settings", required=True, type=Path)
    return parser.parse_args(argv)


def main(
    argv: list[str] | None = None,
    *,
    project_root: Path = ROOT,
    worker_factory: WorkerFactory | None = None,
) -> int:
    status = VoiceStatusWriter(project_root / "runtime/status/voice.json")
    try:
        args = parse_args(argv)
        settings = AppSettings.load(args.settings)
        if not settings.voice_care.enabled:
            status.write(
                worker_state="disabled",
                reason="voice_disabled",
                processed_count=0,
                last_latency_ms=None,
            )
            return 0
        if worker_factory is None:
            status.write(
                worker_state="degraded",
                reason="voice_runtime_unavailable",
                processed_count=0,
                last_latency_ms=None,
            )
            return 2
        worker = worker_factory(settings, project_root)
    except Exception:
        try:
            status.write(
                worker_state="degraded",
                reason="voice_startup_failed",
                processed_count=0,
                last_latency_ms=None,
            )
        except Exception:
            pass
        return 2

    stop_event = threading.Event()

    def stop(_signum: int, _frame: object) -> None:
        stop_event.set()

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    try:
        worker.run(stop_event)
    except Exception:
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
