from __future__ import annotations

import time
from datetime import UTC, datetime
from typing import Callable, Literal, Protocol

from pydantic import BaseModel, ConfigDict, field_validator

from packages.contracts.events import EnvironmentReading
from services.gauge.source import EnvironmentReadingSource


class ReadingSink(Protocol):
    def append(self, reading: EnvironmentReading) -> None: ...


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
        reading = self._source.read(requested_at)
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
                state="healthy",
                code="ok",
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
