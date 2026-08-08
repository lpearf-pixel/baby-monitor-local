from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from pydantic import ValidationError

from services.storage.visual_health import (
    StoredVisualHealthIncident,
    VisualHealthStore,
)


NOW = datetime(2026, 8, 8, 18, 0, tzinfo=timezone(timedelta(hours=8)))


def incident(**updates: object) -> StoredVisualHealthIncident:
    values: dict[str, object] = {
        "incident_id": "visual-health-1",
        "code": "source_offline",
        "state": "open",
        "opened_at": NOW,
        "updated_at": NOW,
        "recovered_at": None,
        "duration_seconds": 60.0,
        "opened_notified": False,
        "recovered_notified": False,
    }
    values.update(updates)
    return StoredVisualHealthIncident.model_validate(values)


def test_migration_round_trips_one_open_visual_health_incident(
    tmp_path: Path,
) -> None:
    store = VisualHealthStore(tmp_path / "visual-health.sqlite3")
    store.migrate()
    opened = incident()

    store.save(opened)

    assert store.integrity_check() == "ok"
    assert store.load_open() == opened
    assert store.incidents() == (opened,)


def test_save_updates_the_same_incident_to_recovered(tmp_path: Path) -> None:
    store = VisualHealthStore(tmp_path / "visual-health.sqlite3")
    store.migrate()
    opened = incident(opened_notified=True)
    recovered = incident(
        state="recovered",
        updated_at=NOW + timedelta(seconds=90),
        recovered_at=NOW + timedelta(seconds=90),
        duration_seconds=20.0,
        opened_notified=True,
        recovered_notified=True,
    )

    store.save(opened)
    store.save(recovered)

    assert store.load_open() is None
    assert store.incidents() == (recovered,)


def test_incident_contract_rejects_invalid_recovery_and_naive_time() -> None:
    with pytest.raises(ValidationError, match="recovered_at"):
        incident(state="recovered")
    with pytest.raises(ValidationError, match="timezone-aware"):
        incident(opened_at=datetime(2026, 8, 8, 18, 0))

