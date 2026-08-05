from __future__ import annotations

from datetime import UTC, datetime, timedelta
import importlib

from packages.contracts.events import (
    EnvironmentReading,
    EnvironmentSourceKind,
    ReadingFailureReason,
)


NOW = datetime(2026, 8, 5, 12, 0, tzinfo=UTC)


def worker_module():
    return importlib.import_module("services.gauge.worker")


def unavailable(index: int) -> EnvironmentReading:
    return EnvironmentReading.unavailable(
        reading_id=f"reading-{index}",
        source_kind=EnvironmentSourceKind.WS2021_GAUGE,
        captured_at=NOW + timedelta(minutes=index),
        failure_reason=ReadingFailureReason.TOO_DARK,
        calibration_version="calibration-1",
        sample_count=5,
    )


class FakeClock:
    def __init__(self) -> None:
        self.value = 0.0

    def monotonic(self) -> float:
        return self.value


class AdvancingSource:
    def __init__(self, clock: FakeClock, elapsed: float) -> None:
        self.clock = clock
        self.elapsed = elapsed
        self.count = 0

    def read(self, requested_at: datetime) -> EnvironmentReading:
        self.count += 1
        self.clock.value += self.elapsed
        return unavailable(self.count)


class RecordingSink:
    def __init__(self, *, fail_first: bool = False) -> None:
        self.fail_first = fail_first
        self.readings: list[EnvironmentReading] = []
        self.attempts = 0

    def append(self, reading: EnvironmentReading) -> None:
        self.attempts += 1
        if self.fail_first and self.attempts == 1:
            raise RuntimeError("database at /private/family is busy")
        self.readings.append(reading)


class MonitoringSink(RecordingSink):
    def __init__(self) -> None:
        super().__init__()
        self.missing_checks: list[datetime] = []

    def check_missing(self, now: datetime) -> None:
        self.missing_checks.append(now)


class StopAfterWaits:
    def __init__(self, count: int) -> None:
        self.remaining = count
        self.waits: list[float] = []

    def is_set(self) -> bool:
        return False

    def wait(self, timeout: float) -> bool:
        self.waits.append(timeout)
        self.remaining -= 1
        return self.remaining == 0


def test_slow_read_does_not_enqueue_missed_periods() -> None:
    module = worker_module()
    clock = FakeClock()
    source = AdvancingSource(clock, elapsed=70)
    stop = StopAfterWaits(1)
    worker = module.GaugeWorker(
        source=source,
        sink=RecordingSink(),
        interval_seconds=60,
        monotonic=clock.monotonic,
        now=lambda: NOW,
    )

    worker.run(stop)

    assert source.count == 1
    assert stop.waits == [0]


def test_fast_read_waits_only_for_remaining_interval() -> None:
    module = worker_module()
    clock = FakeClock()
    source = AdvancingSource(clock, elapsed=5)
    stop = StopAfterWaits(1)
    worker = module.GaugeWorker(
        source=source,
        sink=RecordingSink(),
        interval_seconds=60,
        monotonic=clock.monotonic,
        now=lambda: NOW,
    )

    worker.run(stop)

    assert stop.waits == [55]


def test_sink_failure_degrades_health_but_next_cycle_continues() -> None:
    module = worker_module()
    clock = FakeClock()
    source = AdvancingSource(clock, elapsed=1)
    sink = RecordingSink(fail_first=True)
    stop = StopAfterWaits(2)
    worker = module.GaugeWorker(
        source=source,
        sink=sink,
        interval_seconds=60,
        monotonic=clock.monotonic,
        now=lambda: NOW,
    )

    worker.run(stop)

    assert source.count == 2
    assert sink.attempts == 2
    assert [reading.reading_id for reading in sink.readings] == ["reading-2"]
    assert worker.health().code == "ok"
    assert "/private" not in worker.health().model_dump_json()


def test_run_once_records_redacted_sink_failure() -> None:
    module = worker_module()
    clock = FakeClock()
    worker = module.GaugeWorker(
        source=AdvancingSource(clock, elapsed=0),
        sink=RecordingSink(fail_first=True),
        interval_seconds=60,
        monotonic=clock.monotonic,
        now=lambda: NOW,
    )

    reading = worker.run_once(NOW)

    assert reading.reading_id == "reading-1"
    assert worker.health().code == "reading_sink_unavailable"
    assert worker.health().state == "degraded"


def test_each_cycle_checks_missing_records_before_reading() -> None:
    clock = FakeClock()
    sink = MonitoringSink()
    worker = worker_module().GaugeWorker(
        source=AdvancingSource(clock, elapsed=0),
        sink=sink,
        now=lambda: NOW,
    )

    worker.run_once(NOW)

    assert sink.missing_checks == [NOW]
    assert len(sink.readings) == 1


def test_unexpected_source_crash_still_writes_fail_closed_reading() -> None:
    class BrokenSource:
        source_kind = EnvironmentSourceKind.WS2021_GAUGE

        def read(self, requested_at: datetime) -> EnvironmentReading:
            raise RuntimeError("private camera details")

    sink = RecordingSink()
    worker = worker_module().GaugeWorker(
        source=BrokenSource(),
        sink=sink,
        now=lambda: NOW,
    )

    reading = worker.run_once(NOW)

    assert reading.failure_reason is ReadingFailureReason.INTERNAL_ERROR
    assert reading.calibration_version == "worker-error"
    assert sink.readings == [reading]
    assert worker.health().code == "reading_source_unavailable"
