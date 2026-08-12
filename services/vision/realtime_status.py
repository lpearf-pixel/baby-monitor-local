from __future__ import annotations

import json
import math
import os
import tempfile
import threading
import time
from collections.abc import Callable
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal, localcontext
from pathlib import Path
from typing import Literal


@dataclass(frozen=True)
class RealtimeVisualMetricsSnapshot:
    realtime_fps: Literal[1, 3, 5]
    sample_count: int
    processing_p50_ms: float
    processing_p95_ms: float
    processing_max_ms: float
    realtime_model_state: Literal["available", "degraded"]


class RealtimeVisualStatusUnavailableError(Exception):
    pass


class RealtimeVisualStatusStaleError(Exception):
    pass


class RealtimeVisualStatusPublisher:
    def __init__(
        self,
        writer: Callable[[RealtimeVisualMetricsSnapshot], None],
        *,
        on_failure: Callable[[str], None] | None = None,
    ) -> None:
        self._writer = writer
        self._on_failure = on_failure or (lambda _code: None)
        self._condition = threading.Condition()
        self._latest: RealtimeVisualMetricsSnapshot | None = None
        self._closing = False
        self._failure_pending = False
        self._thread = threading.Thread(
            target=self._run,
            name="realtime-visual-status",
            daemon=True,
        )
        self._thread.start()

    def __call__(self, snapshot: RealtimeVisualMetricsSnapshot) -> None:
        with self._condition:
            if self._closing:
                raise RuntimeError("realtime status publisher closed")
            self._latest = snapshot
            failure_pending = self._failure_pending
            self._failure_pending = False
            self._condition.notify()
        if failure_pending:
            raise RuntimeError("realtime status write failed")

    def close(self) -> None:
        with self._condition:
            self._closing = True
            self._condition.notify()
        self._thread.join()

    def _run(self) -> None:
        while True:
            with self._condition:
                self._condition.wait_for(
                    lambda: self._latest is not None or self._closing
                )
                if self._latest is None and self._closing:
                    return
                snapshot = self._latest
                self._latest = None
            assert snapshot is not None
            try:
                self._writer(snapshot)
            except Exception:
                with self._condition:
                    self._failure_pending = True
                try:
                    self._on_failure("realtime_status_write_failed")
                except Exception:
                    pass


class RealtimeVisualStatusWriter:
    def __init__(
        self,
        path: Path,
        *,
        wall_clock: Callable[[], float] = time.time,
    ) -> None:
        self._path = path
        self._wall_clock = wall_clock

    def __call__(self, snapshot: RealtimeVisualMetricsSnapshot) -> None:
        written_at_unix = self._wall_clock()
        _validate_snapshot(snapshot, written_at_unix=written_at_unix)
        payload = {
            "schema_version": 1,
            "written_at_unix": written_at_unix,
            "realtime_fps": snapshot.realtime_fps,
            "sample_count": snapshot.sample_count,
            "processing_p50_ms": _round_milliseconds(
                snapshot.processing_p50_ms
            ),
            "processing_p95_ms": _round_milliseconds(
                snapshot.processing_p95_ms
            ),
            "processing_max_ms": _round_milliseconds(
                snapshot.processing_max_ms
            ),
            "realtime_model_state": snapshot.realtime_model_state,
        }
        self._path.parent.mkdir(parents=True, exist_ok=True)
        descriptor, temporary_name = tempfile.mkstemp(
            prefix=f".{self._path.name}.",
            suffix=".tmp",
            dir=self._path.parent,
        )
        temporary_path = Path(temporary_name)
        try:
            os.fchmod(descriptor, 0o600)
            with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
                json.dump(payload, handle, separators=(",", ":"))
                handle.write("\n")
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary_path, self._path)
        except Exception:
            try:
                os.close(descriptor)
            except OSError:
                pass
            temporary_path.unlink(missing_ok=True)
            raise


def read_realtime_visual_status(
    path: Path,
    *,
    wall_clock: Callable[[], float] = time.time,
) -> dict[str, object]:
    try:
        payload = json.loads(
            path.read_text(encoding="utf-8"),
            object_pairs_hook=_reject_duplicate_object_pairs,
        )
    except FileNotFoundError as failure:
        raise RealtimeVisualStatusUnavailableError from failure
    _validate_payload(payload)
    now = wall_clock()
    if not _is_finite_non_negative(now):
        raise ValueError("invalid realtime metrics status")
    if now - payload["written_at_unix"] > 15.0:
        raise RealtimeVisualStatusStaleError
    return payload


def _validate_snapshot(
    snapshot: RealtimeVisualMetricsSnapshot,
    *,
    written_at_unix: float,
) -> None:
    processing_values = (
        snapshot.processing_p50_ms,
        snapshot.processing_p95_ms,
        snapshot.processing_max_ms,
    )
    valid = (
        _is_finite_non_negative(written_at_unix)
        and type(snapshot.realtime_fps) is int
        and snapshot.realtime_fps in (1, 3, 5)
        and type(snapshot.sample_count) is int
        and 1 <= snapshot.sample_count <= 51
        and all(_is_finite_non_negative(value) for value in processing_values)
        and snapshot.processing_p50_ms <= snapshot.processing_p95_ms
        and snapshot.processing_p95_ms <= snapshot.processing_max_ms
        and snapshot.realtime_model_state in ("available", "degraded")
    )
    if not valid:
        raise ValueError("invalid realtime metrics snapshot")


def _validate_payload(payload: object) -> None:
    expected_fields = {
        "schema_version",
        "written_at_unix",
        "realtime_fps",
        "sample_count",
        "processing_p50_ms",
        "processing_p95_ms",
        "processing_max_ms",
        "realtime_model_state",
    }
    if type(payload) is not dict or set(payload) != expected_fields:
        raise ValueError("invalid realtime metrics status")
    if type(payload["schema_version"]) is not int or payload["schema_version"] != 1:
        raise ValueError("invalid realtime metrics status")
    snapshot = RealtimeVisualMetricsSnapshot(
        realtime_fps=payload["realtime_fps"],
        sample_count=payload["sample_count"],
        processing_p50_ms=payload["processing_p50_ms"],
        processing_p95_ms=payload["processing_p95_ms"],
        processing_max_ms=payload["processing_max_ms"],
        realtime_model_state=payload["realtime_model_state"],
    )
    try:
        _validate_snapshot(
            snapshot,
            written_at_unix=payload["written_at_unix"],
        )
    except (TypeError, ValueError) as failure:
        raise ValueError("invalid realtime metrics status") from failure


def _reject_duplicate_object_pairs(
    pairs: list[tuple[str, object]],
) -> dict[str, object]:
    payload: dict[str, object] = {}
    for key, value in pairs:
        if key in payload:
            raise ValueError("invalid realtime metrics status")
        payload[key] = value
    return payload


def _is_finite_non_negative(value: object) -> bool:
    return (
        type(value) in (int, float)
        and math.isfinite(value)
        and value >= 0
    )


def _round_milliseconds(value: float) -> float:
    decimal_value = Decimal(str(value))
    with localcontext() as context:
        context.prec = max(28, decimal_value.adjusted() + 4)
        return float(
            decimal_value.quantize(
                Decimal("0.001"),
                rounding=ROUND_HALF_UP,
            )
        )
