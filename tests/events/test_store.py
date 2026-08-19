from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path
import sqlite3

import pytest
from pydantic import ValidationError

from packages.contracts.events import (
    CandidateEvent,
    EnvironmentReading,
    EnvironmentSourceKind,
    EventSeverity,
    HealthState,
    ReadingFailureReason,
    ReadingState,
    SystemHealth,
)
from services.events.store import EventStore


NOW = datetime(2026, 8, 4, 8, 30, tzinfo=timezone(timedelta(hours=8)))


def build_event() -> CandidateEvent:
    return CandidateEvent(
        event_id="evt-001",
        kind="cry_candidate",
        severity=EventSeverity.HIGH,
        occurred_at=NOW,
        summary="持续哭声候选",
        confidence=0.87,
        rule_version="cry-v1",
        metadata={"duration_seconds": 12},
    )


def test_migration_creates_integrity_checked_database(tmp_path: Path) -> None:
    store = EventStore(tmp_path / "events.sqlite3")
    store.migrate()

    assert store.integrity_check() == "ok"
    assert store.schema_version() == 4


def test_migration_upgrades_legacy_environment_table_before_strict_write(
    tmp_path: Path,
) -> None:
    database = tmp_path / "events.sqlite3"
    with sqlite3.connect(database) as connection:
        connection.execute(
            """
            CREATE TABLE environment_readings (
                reading_id TEXT PRIMARY KEY,
                captured_at TEXT NOT NULL,
                state TEXT NOT NULL,
                temperature_c REAL,
                humidity_rh REAL,
                confidence REAL NOT NULL,
                reason TEXT
            )
            """
        )
        connection.execute(
            """
            INSERT INTO environment_readings (
                reading_id, captured_at, state, temperature_c,
                humidity_rh, confidence, reason
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "legacy-reading",
                NOW.isoformat(),
                "unavailable",
                None,
                None,
                0.1,
                "legacy free text",
            ),
        )
    store = EventStore(database)

    store.migrate()
    assert store.legacy_environment_reading_count() == 1
    assert store.latest_environment_reading() is None
    reading = EnvironmentReading.unavailable(
        reading_id="strict-after-upgrade",
        source_kind=EnvironmentSourceKind.WS2021_GAUGE,
        captured_at=NOW,
        failure_reason=ReadingFailureReason.GLARE,
        calibration_version="calibration-1",
        sample_count=5,
    )
    store.add_environment_reading(reading)

    assert store.latest_environment_reading() == reading


def test_round_trips_timezone_aware_candidate_event(tmp_path: Path) -> None:
    store = EventStore(tmp_path / "events.sqlite3")
    store.migrate()
    event = build_event()

    store.add_event(event)
    loaded = store.get_event(event.event_id)

    assert loaded == event
    assert loaded is not None
    assert loaded.occurred_at.utcoffset() == timedelta(hours=8)


def test_unavailable_environment_reading_is_explicitly_stored(tmp_path: Path) -> None:
    store = EventStore(tmp_path / "events.sqlite3")
    store.migrate()
    reading = EnvironmentReading.unavailable(
        reading_id="reading-001",
        source_kind=EnvironmentSourceKind.WS2021_GAUGE,
        captured_at=NOW,
        failure_reason=ReadingFailureReason.GLARE,
        calibration_version="calibration-1",
        sample_count=5,
        confidence=0.15,
    )

    store.add_environment_reading(reading)
    loaded = store.latest_environment_reading()

    assert loaded == reading
    assert loaded is not None
    assert loaded.state is ReadingState.UNAVAILABLE
    assert loaded.temperature_c is None
    assert loaded.humidity_rh is None


def test_two_parents_acknowledge_the_same_event_independently(tmp_path: Path) -> None:
    store = EventStore(tmp_path / "events.sqlite3")
    store.migrate()
    store.add_event(build_event())

    store.acknowledge("evt-001", "parent-a", NOW)
    store.acknowledge("evt-001", "parent-b", NOW + timedelta(seconds=3))

    acknowledgements = store.list_acknowledgements("evt-001")

    assert [item.parent_id for item in acknowledgements] == ["parent-a", "parent-b"]
    assert acknowledgements[0].acknowledged_at == NOW
    assert acknowledgements[1].acknowledged_at == NOW + timedelta(seconds=3)


def test_records_latest_component_health(tmp_path: Path) -> None:
    store = EventStore(tmp_path / "events.sqlite3")
    store.migrate()
    first = SystemHealth(
        component="camera",
        checked_at=NOW,
        state=HealthState.DEGRADED,
        detail="audio missing",
    )
    latest = SystemHealth(
        component="camera",
        checked_at=NOW + timedelta(minutes=1),
        state=HealthState.HEALTHY,
        detail=None,
    )

    store.record_system_health(first)
    store.record_system_health(latest)

    assert store.latest_system_health("camera") == latest


def test_contracts_reject_naive_datetimes() -> None:
    with pytest.raises(ValidationError, match="timezone-aware"):
        CandidateEvent(
            event_id="evt-naive",
            kind="movement_candidate",
            severity=EventSeverity.NORMAL,
            occurred_at=datetime(2026, 8, 4, 8, 30),
            summary="明显移动候选",
            rule_version="movement-v1",
        )


def test_available_reading_requires_a_value() -> None:
    with pytest.raises(ValidationError, match="available reading"):
        EnvironmentReading(
            reading_id="reading-empty",
            source_kind=EnvironmentSourceKind.WS2021_GAUGE,
            captured_at=NOW,
            fresh_until=NOW + timedelta(seconds=90),
            state=ReadingState.AVAILABLE,
            temperature_c=None,
            humidity_rh=None,
            confidence=0.8,
            confidence_state="acceptable",
            failure_reason=None,
            calibration_version="calibration-1",
            sample_count=5,
            valid_temperature_samples=0,
            valid_humidity_samples=0,
        )
