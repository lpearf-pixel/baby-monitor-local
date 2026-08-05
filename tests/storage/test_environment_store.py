from __future__ import annotations

from datetime import UTC, datetime, timedelta
import importlib
from pathlib import Path

import pytest

from packages.contracts.events import (
    EnvironmentReading,
    EnvironmentSourceKind,
    ReadingFailureReason,
)


NOW = datetime(2026, 8, 5, 12, 0, tzinfo=UTC)


def storage_module():
    return importlib.import_module("services.storage.environment")


def available(reading_id: str, captured_at: datetime) -> EnvironmentReading:
    return EnvironmentReading.available(
        reading_id=reading_id,
        source_kind=EnvironmentSourceKind.WS2021_GAUGE,
        captured_at=captured_at,
        temperature_c=22.0,
        humidity_rh=48.0,
        confidence=0.9,
        calibration_version="calibration-1",
        sample_count=5,
        valid_temperature_samples=5,
        valid_humidity_samples=5,
    )


def unavailable(reading_id: str, captured_at: datetime) -> EnvironmentReading:
    return EnvironmentReading.unavailable(
        reading_id=reading_id,
        source_kind=EnvironmentSourceKind.WS2021_GAUGE,
        captured_at=captured_at,
        failure_reason=ReadingFailureReason.TOO_DARK,
        calibration_version="calibration-1",
        sample_count=5,
    )


def test_each_attempt_round_trips_including_unavailable(tmp_path: Path) -> None:
    module = storage_module()
    store = module.EnvironmentStore(tmp_path / "events.sqlite3")
    store.append(available("a", NOW))
    store.append(unavailable("b", NOW + timedelta(minutes=1)))

    assert store.latest().reading_id == "b"
    assert store.latest_available().reading_id == "a"
    assert store.get("a") == available("a", NOW)
    assert store.integrity_check() == "ok"
    assert store.journal_mode() == "wal"


def test_duplicate_reading_id_is_rejected_without_changing_original(
    tmp_path: Path,
) -> None:
    module = storage_module()
    store = module.EnvironmentStore(tmp_path / "events.sqlite3")
    original = available("same", NOW)
    store.append(original)

    with pytest.raises(module.DuplicateReadingError):
        store.append(unavailable("same", NOW + timedelta(minutes=1)))

    assert store.get("same") == original


def test_empty_store_has_no_current_or_last_valid_reading(tmp_path: Path) -> None:
    module = storage_module()
    store = module.EnvironmentStore(tmp_path / "events.sqlite3")

    assert store.latest() is None
    assert store.latest_available() is None


def test_state_snapshot_round_trips_strict_json_without_paths(tmp_path: Path) -> None:
    module = storage_module()
    store = module.EnvironmentStore(tmp_path / "events.sqlite3")
    snapshot = {
        "schema_version": 1,
        "range_incident_id": "range-1",
        "notified_levels": ["normal"],
    }

    store.save_state_snapshot(snapshot, updated_at=NOW)

    assert store.load_state_snapshot() == snapshot


def test_cleanup_preserves_reading_referenced_by_open_incident(
    tmp_path: Path,
) -> None:
    module = storage_module()
    store = module.EnvironmentStore(tmp_path / "events.sqlite3")
    old_protected = available("protected", NOW - timedelta(days=400))
    old_unreferenced = available("expired", NOW - timedelta(days=400))
    recent = available("recent", NOW - timedelta(days=1))
    for reading in (old_protected, old_unreferenced, recent):
        store.append(reading)
    store.save_incident(
        module.StoredEnvironmentIncident(
            incident_id="incident-1",
            kind="range",
            state="open",
            severity="normal",
            opened_at=NOW - timedelta(days=400),
            updated_at=NOW,
            reasons=("temperature_high",),
            opening_reading_id="protected",
            notified_levels=("normal",),
        )
    )

    deleted = store.cleanup(now=NOW, retention_days=365)

    assert deleted == 1
    assert store.get("protected") is not None
    assert store.get("expired") is None
    assert store.get("recent") is not None


def test_cleanup_releases_old_opening_reading_after_incident_recovery(
    tmp_path: Path,
) -> None:
    module = storage_module()
    store = module.EnvironmentStore(tmp_path / "events.sqlite3")
    old = available("recovered-evidence", NOW - timedelta(days=400))
    store.append(old)
    store.save_incident(
        module.StoredEnvironmentIncident(
            incident_id="recovered-incident",
            kind="range",
            state="recovered",
            severity="normal",
            opened_at=NOW - timedelta(days=400),
            updated_at=NOW - timedelta(days=399),
            recovered_at=NOW - timedelta(days=399),
            reasons=(),
            opening_reading_id=old.reading_id,
            notified_levels=("normal", "recovered"),
        )
    )

    store.cleanup(now=NOW, retention_days=365)

    assert store.get(old.reading_id) is None
    assert store.incident("recovered-incident").opening_reading_id is None


def test_pipeline_transaction_rolls_back_reading_when_incident_write_fails(
    tmp_path: Path,
) -> None:
    module = storage_module()
    store = module.EnvironmentStore(tmp_path / "events.sqlite3")
    current = available("atomic-reading", NOW)
    invalid_incident = module.StoredEnvironmentIncident(
        incident_id="invalid-reference",
        kind="range",
        state="open",
        severity="normal",
        opened_at=NOW,
        updated_at=NOW,
        reasons=("temperature_high",),
        opening_reading_id="missing-reading",
    )

    with pytest.raises(Exception, match="FOREIGN KEY"):
        store.commit_pipeline(
            reading=current,
            incidents=(invalid_incident,),
            state_snapshot={"schema_version": 1},
            updated_at=NOW,
        )

    assert store.get(current.reading_id) is None
    assert store.load_state_snapshot() is None


def test_open_incident_query_is_not_starved_by_newer_recovered_history(
    tmp_path: Path,
) -> None:
    module = storage_module()
    store = module.EnvironmentStore(tmp_path / "events.sqlite3")
    store.save_incident(
        module.StoredEnvironmentIncident(
            incident_id="old-open",
            kind="range",
            state="open",
            severity="normal",
            opened_at=NOW - timedelta(days=10),
            updated_at=NOW - timedelta(days=10),
            reasons=("temperature_high",),
        )
    )
    for index in range(101):
        recovered_at = NOW + timedelta(seconds=index)
        store.save_incident(
            module.StoredEnvironmentIncident(
                incident_id=f"new-recovered-{index}",
                kind="unreadable",
                state="recovered",
                severity="normal",
                opened_at=recovered_at - timedelta(minutes=10),
                updated_at=recovered_at,
                recovered_at=recovered_at,
                reasons=(),
            )
        )

    assert [item.incident_id for item in store.open_incidents()] == ["old-open"]
