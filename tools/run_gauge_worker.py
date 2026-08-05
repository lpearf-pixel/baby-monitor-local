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
from services.environment.bootstrap import build_gauge_worker
from services.environment.local_env import load_local_env_file


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run the independent WS2021 environment-reading worker."
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
    if args.env_file is not None:
        load_local_env_file(args.env_file)
    settings = AppSettings.load(args.settings)
    if not settings.environment.enabled:
        return 0
    worker = build_gauge_worker(settings, ROOT, os.environ)
    stop_event = threading.Event()

    def stop(_signum: int, _frame: object) -> None:
        stop_event.set()

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    worker.run(stop_event)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
