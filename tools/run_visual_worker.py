from __future__ import annotations

import argparse
import signal
import sys
import threading
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from packages.contracts.settings import AppSettings
from services.environment.local_env import load_local_env_file
from services.vision.bootstrap import build_visual_runtime
from services.vision.realtime_status import (
    RealtimeVisualStatusPublisher,
    RealtimeVisualStatusWriter,
)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run the independent local Qwen visual-review worker."
    )
    parser.add_argument(
        "--settings",
        type=Path,
        required=True,
        help="Path to the strict local YAML settings file.",
    )
    parser.add_argument(
        "--env-file",
        type=Path,
        help="Optional mode-600 local environment file; values are never logged.",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    status_publisher: RealtimeVisualStatusPublisher | None = None
    try:
        if args.env_file is not None:
            load_local_env_file(args.env_file)
        settings = AppSettings.load(args.settings)
        if not settings.visual.enabled:
            return 0
        status_publisher = RealtimeVisualStatusPublisher(
            RealtimeVisualStatusWriter(
                ROOT / "runtime/status/realtime-visual.json"
            ),
            on_failure=lambda _code: print(
                "realtime_status_write_failed",
                file=sys.stderr,
            ),
        )
        resources = build_visual_runtime(
            settings,
            on_realtime_status=status_publisher,
        )
    except Exception:
        if status_publisher is not None:
            status_publisher.close()
        print("visual_worker_startup_failed", file=sys.stderr)
        return 2

    stop_event = threading.Event()

    def stop(_signum: int, _frame: object) -> None:
        stop_event.set()

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    runtime_failed = False
    try:
        resources.worker.run(stop_event)
    except Exception:
        runtime_failed = True
    finally:
        try:
            resources.close()
        except Exception:
            runtime_failed = True
        try:
            assert status_publisher is not None
            status_publisher.close()
        except Exception:
            runtime_failed = True
    if runtime_failed:
        print("visual_worker_runtime_failed", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
