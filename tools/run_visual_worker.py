from __future__ import annotations

import argparse
import os
import signal
import sys
import threading
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from packages.contracts.settings import AppSettings
from services.environment.local_env import load_local_env_file
from services.storage.visual_health import VisualHealthStore
from services.vision.bootstrap import build_visual_runtime
from services.vision.frame_health import FrameHealthTransition
from services.vision.frame_health_pipeline import VisualFrameHealthPipeline
from services.vision.notification_config import build_visual_health_notifier
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
        data_dir = settings.app.data_dir
        if not data_dir.is_absolute():
            data_dir = ROOT / data_dir
        visual_health_store = VisualHealthStore(
            data_dir / "visual-health.sqlite3"
        )
        visual_health_store.migrate()
        try:
            visual_health_notifier = build_visual_health_notifier(
                settings,
                os.environ,
            )
        except ValueError:
            visual_health_notifier = None
            print("visual_health_notification_disabled", file=sys.stderr)
        visual_health_pipeline = VisualFrameHealthPipeline.restore(
            store=visual_health_store,
            notifier=visual_health_notifier,
        )

        def handle_frame_health(transition: FrameHealthTransition) -> None:
            try:
                visual_health_pipeline.handle(transition)
            except Exception:
                print("visual_health_pipeline_failed", file=sys.stderr)
                raise

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
            initial_frame_health_code=visual_health_pipeline.open_code,
            on_frame_health=handle_frame_health,
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
