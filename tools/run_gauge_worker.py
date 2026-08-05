from __future__ import annotations

import argparse
import os
import signal
import sys
import threading
import shlex
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from packages.contracts.settings import AppSettings
from services.environment.bootstrap import build_gauge_worker


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


def load_env_file(path: Path) -> None:
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line.removeprefix("export ").lstrip()
        name, separator, raw_value = line.partition("=")
        if not separator or not name.replace("_", "A").isalnum():
            raise ValueError("environment file contains an invalid assignment")
        parsed = shlex.split(raw_value, comments=False, posix=True)
        if len(parsed) > 1:
            raise ValueError("environment file contains an invalid value")
        os.environ.setdefault(name, parsed[0] if parsed else "")


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    if args.env_file is not None:
        load_env_file(args.env_file)
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
