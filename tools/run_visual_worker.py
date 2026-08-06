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
    try:
        if args.env_file is not None:
            load_local_env_file(args.env_file)
        settings = AppSettings.load(args.settings)
        if not settings.visual.enabled:
            return 0
        resources = build_visual_runtime(settings)
    except Exception:
        print("visual_worker_startup_failed", file=sys.stderr)
        return 2

    stop_event = threading.Event()

    def stop(_signum: int, _frame: object) -> None:
        stop_event.set()

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    try:
        resources.worker.run(stop_event)
    except Exception:
        print("visual_worker_runtime_failed", file=sys.stderr)
        return 2
    finally:
        resources.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
