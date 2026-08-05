from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

from packages.contracts.events import EnvironmentReading, EnvironmentSourceKind
from services.events.environment_pipeline import EnvironmentPipelineSink
from services.events.environment_state import (
    EnvironmentStateMachine,
    EnvironmentStatePolicy,
)
from services.storage.environment import EnvironmentStore


NOW = datetime(2026, 8, 5, 12, 0, tzinfo=UTC)


class RecordingNotifier:
    def __init__(self) -> None:
        self.calls: list[tuple[object, EnvironmentReading]] = []

    def notify(self, transition: object, reading: EnvironmentReading) -> None:
        self.calls.append((transition, reading))


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
