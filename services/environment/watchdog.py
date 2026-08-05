from __future__ import annotations

from datetime import UTC, datetime
from typing import Callable, Protocol

from services.events.environment_pipeline import (
    EnvironmentNotifier,
    EnvironmentPipelineSink,
)
from services.events.environment_state import EnvironmentStatePolicy
from services.storage.environment import EnvironmentStore


class StopEvent(Protocol):
    def is_set(self) -> bool: ...

    def wait(self, timeout: float) -> bool: ...


class EnvironmentWatchdog:
    """Checks missing SQLite records outside the gauge process failure domain."""

    def __init__(
        self,
        *,
        store: EnvironmentStore,
        policy: EnvironmentStatePolicy,
        notifier: EnvironmentNotifier | None,
        interval_seconds: float = 60,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        if interval_seconds <= 0:
            raise ValueError("interval_seconds must be positive")
        self._store = store
        self._policy = policy
        self._notifier = notifier
        self._interval_seconds = interval_seconds
        self._now = now or (lambda: datetime.now(UTC))
        self._pipeline = self._restore_pipeline()

    def _restore_pipeline(self) -> EnvironmentPipelineSink:
        return EnvironmentPipelineSink.restore(
            store=self._store,
            policy=self._policy,
            notifier=self._notifier,
        )

    def tick(self, now: datetime) -> None:
        while True:
            snapshot = self._pipeline.state_machine.snapshot()
            pending = self._store.readings_after(
                captured_at=snapshot.last_record_at,
                reading_id=snapshot.last_reading_id,
                limit=1_000,
            )
            for reading in pending:
                self._pipeline.process_stored(reading)
            if len(pending) < 1_000:
                break
        latest = self._store.latest()
        if latest is not None and latest.fresh_until >= now:
            return
        self._pipeline.check_missing(now)

    def run(self, stop_event: StopEvent) -> None:
        while not stop_event.is_set():
            self.tick(self._now())
            if stop_event.wait(self._interval_seconds):
                return
