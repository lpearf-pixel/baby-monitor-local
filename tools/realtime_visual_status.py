from __future__ import annotations

import argparse
import sys
import time
from collections.abc import Callable
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from services.vision.realtime_status import (
    RealtimeVisualStatusStaleError,
    RealtimeVisualStatusUnavailableError,
    read_realtime_visual_status,
)


DEFAULT_STATUS_PATH = ROOT / "runtime/status/realtime-visual.json"


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Read redacted realtime visual production metrics."
    )
    parser.add_argument(
        "--path",
        type=Path,
        default=DEFAULT_STATUS_PATH,
        help=argparse.SUPPRESS,
    )
    return parser.parse_args(argv)


def main(
    argv: list[str] | None = None,
    *,
    wall_clock: Callable[[], float] = time.time,
) -> int:
    args = parse_args(argv)
    try:
        payload = read_realtime_visual_status(
            args.path,
            wall_clock=wall_clock,
        )
    except RealtimeVisualStatusUnavailableError:
        print("realtime_metrics=unavailable")
        return 2
    except RealtimeVisualStatusStaleError:
        print("realtime_metrics=stale")
        return 3
    except Exception:
        print("realtime_metrics=invalid")
        return 4

    print("realtime_metrics=available")
    for key in (
        "realtime_fps",
        "sample_count",
        "processing_p50_ms",
        "processing_p95_ms",
        "processing_max_ms",
        "realtime_model_state",
    ):
        print(f"{key}={payload[key]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
