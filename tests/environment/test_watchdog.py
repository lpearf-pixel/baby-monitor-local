from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

from packages.contracts.events import EnvironmentReading, EnvironmentSourceKind
from services.environment.watchdog import EnvironmentWatchdog
from services.events.environment_state import EnvironmentStatePolicy
from services.storage.environment import EnvironmentStore


NOW = datetime(2026, 8, 5, 12, 0, tzinfo=UTC)


class RecordingNotifier:
    def __init__(self) -> None:
        self.calls: list[tuple[object, EnvironmentReading]] = []

    def notify(self, transition: object, reading: EnvironmentReading) -> object:
        self.calls.append((transition, reading))
        return SimpleNamespace(delivered=True)


def available(captured_at: datetime) -> EnvironmentReading:
    return EnvironmentReading.available(
        reading_id=f"reading-{captured_at.timestamp()}",
        source_kind=EnvironmentSourceKind.WS2021_GAUGE,
        captured_at=captured_at,
        temperature_c=22,
        humidity_rh=48,
        confidence=0.9,
        calibration_version="calibration-1",
        sample_count=5,
        valid_temperature_samples=5,
        valid_humidity_samples=5,
    )


def test_watchdog_opens_no_record_incident_without_gauge_process(tmp_path: Path) -> None:
    store = EnvironmentStore(tmp_path / "environment.sqlite3")
    notifier = RecordingNotifier()
    watchdog = EnvironmentWatchdog(
        store=store,
        policy=EnvironmentStatePolicy(),
        notifier=notifier,
    )

    watchdog.tick(NOW)
    watchdog.tick(NOW + timedelta(seconds=601))

    incident = store.incidents()[0]
    assert incident.kind == "unreadable"
    assert incident.reasons == ("no_new_reading",)
    assert len(notifier.calls) == 1
    assert notifier.calls[0][1].temperature_c is None


def test_watchdog_does_nothing_while_gauge_reading_is_fresh(tmp_path: Path) -> None:
    store = EnvironmentStore(tmp_path / "environment.sqlite3")
    store.append(available(NOW))
    notifier = RecordingNotifier()
    watchdog = EnvironmentWatchdog(
        store=store,
        policy=EnvironmentStatePolicy(),
        notifier=notifier,
    )

    watchdog.tick(NOW + timedelta(seconds=30))

    assert store.incidents() == ()
    assert notifier.calls == []
    assert store.load_state_snapshot()["last_reading_id"] == available(NOW).reading_id


def test_watchdog_is_single_state_owner_for_gauge_appended_readings(
    tmp_path: Path,
) -> None:
    store = EnvironmentStore(tmp_path / "environment.sqlite3")
    first = available(NOW)
    second = available(NOW + timedelta(seconds=60))
    store.append(first)
    store.append(second)
    watchdog = EnvironmentWatchdog(
        store=store,
        policy=EnvironmentStatePolicy(),
        notifier=None,
    )

    watchdog.tick(NOW + timedelta(seconds=61))

    snapshot = store.load_state_snapshot()
    assert snapshot["last_reading_id"] == second.reading_id
    assert datetime.fromisoformat(snapshot["last_record_at"]) == second.captured_at
