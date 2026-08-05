from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

import pytest

from packages.contracts.events import EnvironmentReading, EnvironmentSourceKind
from services.events.environment_pipeline import EnvironmentPipelineSink
from services.events.environment_state import (
    EnvironmentStateMachine,
    EnvironmentStatePolicy,
)
from services.storage.environment import EnvironmentStore


NOW = datetime(2026, 8, 5, 12, 0, tzinfo=UTC)


class RecordingNotifier:
    def __init__(self, deliveries: list[bool] | None = None) -> None:
        self.calls: list[tuple[object, EnvironmentReading]] = []
        self.deliveries = deliveries or [True]

    def notify(self, transition: object, reading: EnvironmentReading) -> object:
        self.calls.append((transition, reading))
        index = min(len(self.calls) - 1, len(self.deliveries) - 1)
        return SimpleNamespace(delivered=self.deliveries[index])


def reading(reading_id: str, captured_at: datetime, temperature: float) -> EnvironmentReading:
    return EnvironmentReading.available(
        reading_id=reading_id,
        source_kind=EnvironmentSourceKind.WS2021_GAUGE,
        captured_at=captured_at,
        temperature_c=temperature,
        humidity_rh=48,
        confidence=0.92,
        calibration_version="calibration-1",
        sample_count=5,
        valid_temperature_samples=5,
        valid_humidity_samples=5,
    )


def test_pipeline_persists_reading_state_incident_then_notifies(tmp_path: Path) -> None:
    store = EnvironmentStore(tmp_path / "environment.sqlite3")
    notifier = RecordingNotifier()
    machine = EnvironmentStateMachine(
        EnvironmentStatePolicy(
            critical_confirmations=2,
            critical_min_span_seconds=60,
        )
    )
    sink = EnvironmentPipelineSink(store=store, state_machine=machine, notifier=notifier)

    sink.append(reading("first", NOW, 31))
    sink.append(reading("second", NOW + timedelta(seconds=60), 31))

    assert store.latest().reading_id == "second"
    snapshot = store.load_state_snapshot()
    assert snapshot is not None
    assert snapshot["range_incident"]["severity"] == "critical"
    incidents = store.incidents()
    assert len(incidents) == 1
    assert incidents[0].opening_reading_id == "second"
    assert incidents[0].notified_levels == ("critical",)
    assert len(notifier.calls) == 1
    transition, notified_reading = notifier.calls[0]
    assert transition.kind == "opened"
    assert notified_reading.reading_id == "second"


def test_pipeline_restores_open_incident_without_replaying_notification(
    tmp_path: Path,
) -> None:
    store = EnvironmentStore(tmp_path / "environment.sqlite3")
    first_notifier = RecordingNotifier()
    first = EnvironmentPipelineSink(
        store=store,
        state_machine=EnvironmentStateMachine(
            EnvironmentStatePolicy(
                critical_confirmations=2,
                critical_min_span_seconds=60,
            )
        ),
        notifier=first_notifier,
    )
    first.append(reading("first", NOW, 31))
    first.append(reading("second", NOW + timedelta(seconds=60), 31))

    restored_notifier = RecordingNotifier()
    restored = EnvironmentPipelineSink.restore(
        store=store,
        policy=EnvironmentStatePolicy(),
        notifier=restored_notifier,
    )

    assert len(restored.state_machine.open_incidents()) == 1
    assert restored_notifier.calls == []


def test_failed_notification_retries_on_later_reading_and_marks_only_success(
    tmp_path: Path,
) -> None:
    store = EnvironmentStore(tmp_path / "environment.sqlite3")
    notifier = RecordingNotifier([False, True])
    sink = EnvironmentPipelineSink(
        store=store,
        state_machine=EnvironmentStateMachine(
            EnvironmentStatePolicy(
                critical_confirmations=2,
                critical_min_span_seconds=60,
            )
        ),
        notifier=notifier,
    )

    sink.append(reading("first", NOW, 31))
    sink.append(reading("second", NOW + timedelta(seconds=60), 31))
    assert store.incidents()[0].notified_levels == ()

    sink.append(reading("third", NOW + timedelta(seconds=120), 31))

    assert len(notifier.calls) == 2
    assert store.incidents()[0].notified_levels == ("critical",)


def test_missing_record_check_is_persisted_and_notified_without_new_reading(
    tmp_path: Path,
) -> None:
    store = EnvironmentStore(tmp_path / "environment.sqlite3")
    notifier = RecordingNotifier()
    sink = EnvironmentPipelineSink(
        store=store,
        state_machine=EnvironmentStateMachine(EnvironmentStatePolicy()),
        notifier=notifier,
    )
    sink.append(reading("initial", NOW, 22))

    sink.check_missing(NOW + timedelta(seconds=601))

    incident = store.incidents()[0]
    assert incident.kind == "unreadable"
    assert incident.reasons == ("no_new_reading",)
    assert len(notifier.calls) == 1


def test_atomic_commit_failure_restores_in_memory_state(tmp_path: Path) -> None:
    store = EnvironmentStore(tmp_path / "environment.sqlite3")
    sink = EnvironmentPipelineSink(
        store=store,
        state_machine=EnvironmentStateMachine(
            EnvironmentStatePolicy(
                critical_confirmations=2,
                critical_min_span_seconds=60,
            )
        ),
    )
    sink.append(reading("first", NOW, 31))
    original_commit = store.commit_pipeline

    def fail_commit(*args: object, **kwargs: object) -> None:
        raise RuntimeError("injected transaction failure")

    store.commit_pipeline = fail_commit  # type: ignore[method-assign]
    try:
        with pytest.raises(RuntimeError, match="injected"):
            sink.append(reading("second", NOW + timedelta(seconds=60), 31))
    finally:
        store.commit_pipeline = original_commit  # type: ignore[method-assign]

    assert store.get("second") is None
    assert sink.state_machine.open_incidents() == ()


def test_pipeline_schedules_reading_retention_without_deleting_incident_evidence(
    tmp_path: Path,
) -> None:
    store = EnvironmentStore(tmp_path / "environment.sqlite3")
    old = reading("old", NOW - timedelta(days=400), 22)
    store.append(old)
    sink = EnvironmentPipelineSink(
        store=store,
        state_machine=EnvironmentStateMachine(EnvironmentStatePolicy()),
        retention_days=365,
    )

    sink.append(reading("current", NOW, 22))

    assert store.get("old") is None
    assert store.get("current") is not None
