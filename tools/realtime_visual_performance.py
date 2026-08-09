from __future__ import annotations

import argparse
import math
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
PRODUCTION_DURATION_SECONDS = 600.0
PRODUCTION_INTERVAL_SECONDS = 10.0
STABLE_THREE_FPS_SECONDS = 60.0
FIVE_FPS_P95_BUDGET_MS = 180.0
THREE_FPS_P95_BUDGET_MS = 300.0


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Sample redacted realtime visual production metrics."
    )
    return parser.parse_args(argv)


def _production_reader() -> dict[str, object]:
    return read_realtime_visual_status(DEFAULT_STATUS_PATH)


def _sample_count(duration_seconds: float, interval_seconds: float) -> int:
    if (
        not math.isfinite(duration_seconds)
        or not math.isfinite(interval_seconds)
        or duration_seconds <= 0
        or interval_seconds <= 0
    ):
        raise ValueError("invalid sampling window")
    count = duration_seconds / interval_seconds
    if not count.is_integer():
        raise ValueError("sampling window must contain complete intervals")
    return int(count)


def _read_failure_reason(failure: Exception) -> str:
    if isinstance(failure, RealtimeVisualStatusUnavailableError):
        return "metrics_unavailable"
    if isinstance(failure, RealtimeVisualStatusStaleError):
        return "metrics_stale"
    if isinstance(failure, (TypeError, ValueError)):
        return "metrics_invalid"
    return "metrics_read_failed"


def _nearest_rank_median(values: list[float]) -> float:
    ordered = sorted(values)
    return ordered[math.ceil(len(ordered) * 0.5) - 1]


def _format_number(value: float) -> str:
    return format(value, ".15g")


def _print_report(samples: list[dict[str, object]]) -> None:
    fps_values = [int(sample["realtime_fps"]) for sample in samples]
    p50_values = [float(sample["processing_p50_ms"]) for sample in samples]
    p95_values = [float(sample["processing_p95_ms"]) for sample in samples]
    maximum_values = [float(sample["processing_max_ms"]) for sample in samples]
    model_state = (
        "degraded"
        if any(sample["realtime_model_state"] == "degraded" for sample in samples)
        else "available"
    )
    print(f"samples={len(samples)}")
    print(f"fps_5_count={fps_values.count(5)}")
    print(f"fps_3_count={fps_values.count(3)}")
    print(f"fps_1_count={fps_values.count(1)}")
    print(
        "processing_p50_ms="
        f"{_format_number(_nearest_rank_median(p50_values))}"
    )
    print(f"processing_p95_ms={_format_number(max(p95_values))}")
    print(f"processing_max_ms={_format_number(max(maximum_values))}")
    print(f"model_state={model_state}")


def _performance_result(
    samples: list[dict[str, object]],
    *,
    interval_seconds: float,
) -> tuple[bool, str]:
    fps_values = [int(sample["realtime_fps"]) for sample in samples]
    if any(sample["realtime_model_state"] == "degraded" for sample in samples):
        return False, "model_degraded"
    if 1 in fps_values:
        return False, "one_fps_observed"
    if all(fps == 5 for fps in fps_values):
        worst_p95 = max(float(sample["processing_p95_ms"]) for sample in samples)
        if worst_p95 <= FIVE_FPS_P95_BUDGET_MS:
            return True, "5fps"
        return False, "five_fps_budget_exceeded"

    required_tail = math.ceil(STABLE_THREE_FPS_SECONDS / interval_seconds)
    if len(samples) < required_tail or any(
        fps != 3 for fps in fps_values[-required_tail:]
    ):
        return False, "three_fps_unstable"
    three_fps_p95 = [
        float(sample["processing_p95_ms"])
        for sample in samples
        if sample["realtime_fps"] == 3
    ]
    if max(three_fps_p95) > THREE_FPS_P95_BUDGET_MS:
        return False, "three_fps_budget_exceeded"
    return True, "3fps"


def main(
    argv: list[str] | None = None,
    *,
    duration_seconds: float = PRODUCTION_DURATION_SECONDS,
    interval_seconds: float = PRODUCTION_INTERVAL_SECONDS,
    reader: Callable[[], dict[str, object]] = _production_reader,
    sleeper: Callable[[float], None] = time.sleep,
) -> int:
    parse_args([] if argv is None else argv)
    count = _sample_count(duration_seconds, interval_seconds)
    samples: list[dict[str, object]] = []
    for _index in range(count):
        sleeper(interval_seconds)
        try:
            samples.append(reader())
        except Exception as failure:
            reason = _read_failure_reason(failure)
            print(f"performance=FAIL reason={reason}")
            return 2

    _print_report(samples)
    passed, result = _performance_result(
        samples,
        interval_seconds=interval_seconds,
    )
    if passed:
        print(f"performance=PASS mode={result}")
        return 0
    print(f"performance=FAIL reason={result}")
    return 2


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
