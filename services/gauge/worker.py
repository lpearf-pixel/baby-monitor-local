from __future__ import annotations

import time
from datetime import UTC, datetime
from typing import Callable, Literal, Protocol
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, field_validator

from packages.contracts.events import (
    EnvironmentReading,
    EnvironmentSourceKind,
    ReadingFailureReason,
)
from services.gauge.source import EnvironmentReadingSource


class ReadingSink(Protocol):
    def append(self, reading: EnvironmentReading) -> None: ...

    def check_missing(self, now: datetime) -> None: ...


class StopEvent(Protocol):
    def is_set(self) -> bool: ...

    def wait(self, timeout: float) -> bool: ...


class GaugeWorkerHealth(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    state: Literal["healthy", "degraded"]
    code: Literal[
        "ok",
        "not_started",
        "reading_source_unavailable",
        "reading_sink_unavailable",
    ]
    checked_at: datetime
    last_write_at: datetime | None = None

    @field_validator("checked_at", "last_write_at")
    @classmethod
    def require_aware_time(cls, value: datetime | None) -> datetime | None:
        if value is not None and (value.tzinfo is None or value.utcoffset() is None):
            raise ValueError("worker health times must be timezone-aware")
        return value


class GaugeWorker:
    def __init__(
        self,
        *,
        source: EnvironmentReadingSource,
        sink: ReadingSink,
        interval_seconds: float = 60,
        monotonic: Callable[[], float] = time.monotonic,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        if interval_seconds <= 0:
            raise ValueError("interval_seconds must be positive")
        self._source = source
        self._sink = sink
        self._interval_seconds = interval_seconds
        self._monotonic = monotonic
        self._now = now or (lambda: datetime.now(UTC))
        checked_at = self._now()
        self._health = GaugeWorkerHealth(
            state="degraded",
            code="not_started",
            checked_at=checked_at,
        )

    def health(self) -> GaugeWorkerHealth:
        return self._health

    def run_once(self, requested_at: datetime) -> EnvironmentReading:
        check_missing = getattr(self._sink, "check_missing", None)
        if check_missing is not None:
            check_missing(requested_at)
        source_failed = False
        try:
            reading = self._source.read(requested_at)
        except Exception:
            source_failed = True
            source_kind = self._source.source_kind
            reading = EnvironmentReading.unavailable(
                reading_id=str(uuid4()),
                source_kind=source_kind,
                captured_at=requested_at,
                failure_reason=ReadingFailureReason.INTERNAL_ERROR,
                calibration_version=(
                    "worker-error"
                    if source_kind is EnvironmentSourceKind.WS2021_GAUGE
                    else None
                ),
                sample_count=0,
            )
        checked_at = self._now()
        try:
            self._sink.append(reading)
        except Exception:
            self._health = GaugeWorkerHealth(
                state="degraded",
                code="reading_sink_unavailable",
                checked_at=checked_at,
                last_write_at=self._health.last_write_at,
            )
        else:
            self._health = GaugeWorkerHealth(
                state="degraded" if source_failed else "healthy",
                code="reading_source_unavailable" if source_failed else "ok",
                checked_at=checked_at,
                last_write_at=checked_at,
            )
        return reading

    def run(self, stop_event: StopEvent) -> None:
        while not stop_event.is_set():
            started = self._monotonic()
            try:
                self.run_once(self._now())
            except Exception:
                self._health = GaugeWorkerHealth(
                    state="degraded",
                    code="reading_source_unavailable",
                    checked_at=self._now(),
                    last_write_at=self._health.last_write_at,
                )
            elapsed = self._monotonic() - started
            remaining = max(0.0, self._interval_seconds - elapsed)
            if stop_event.wait(remaining):
                return
