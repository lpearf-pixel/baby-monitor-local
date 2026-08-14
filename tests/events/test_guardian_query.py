from __future__ import annotations

import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from services.events.guardian_query import (
    GuardianEventQueryService,
    GuardianEventQueryUnavailable,
)
from services.storage.visual_risk import VisualRiskEventStore


NOW = datetime(2026, 8, 13, 12, 0, tzinfo=UTC)


def _insert_event(
    database: Path,
    *,
    event_id: str,
    updated_at: datetime,
    state: str = "recovered",
    evidence_state: str | None = None,
    risk_kind: str = "face_not_visible",
) -> None:
    opened_at = updated_at - timedelta(minutes=1)
    recovered_at = updated_at if state == "recovered" else None
    with sqlite3.connect(database) as connection:
        connection.execute(
            """
            INSERT INTO visual_risk_events (
                event_id, risk_kind, state, severity, opened_at, updated_at,
                recovered_at, confidence, rule_version,
                adult_intervention_count
            ) VALUES (?, ?, ?, 'high', ?, ?, ?, 0.9, 'v1', 0)
            """,
            (
                event_id,
                risk_kind,
                state,
                opened_at.isoformat(),
                updated_at.isoformat(),
                recovered_at.isoformat() if recovered_at else None,
            ),
        )
        if evidence_state is not None:
            failure_code = None
            clip_key = None
            snapshot_key = "visual-risk/" + "a" * 64 + "/snapshot.jpg"
            deadline = opened_at
            if evidence_state == "ready":
                clip_key = "visual-risk/" + "a" * 64 + "/clip.webp"
            elif evidence_state == "failed":
                failure_code = "media_write_failed"
            elif evidence_state == "interrupted":
                failure_code = "worker_restarted"
            connection.execute(
                """
                INSERT INTO visual_risk_evidence (
                    event_id, state, started_at, updated_at,
                    capture_deadline, snapshot_key, clip_key,
                    frame_count, failure_code
                ) VALUES (?, ?, ?, ?, ?, ?, ?, 1, ?)
                """,
                (
                    event_id,
                    evidence_state,
                    opened_at.isoformat(),
                    updated_at.isoformat(),
                    deadline.isoformat(),
                    snapshot_key,
                    clip_key,
                    failure_code,
                ),
            )


def _database(tmp_path: Path) -> Path:
    database = tmp_path / "events.sqlite3"
    VisualRiskEventStore(database).migrate()
    return database


def test_missing_database_fails_without_creating_it(tmp_path: Path) -> None:
    database = tmp_path / "missing.sqlite3"

    with pytest.raises(GuardianEventQueryUnavailable):
        GuardianEventQueryService(database).recent_events()

    assert not database.exists()


def test_selects_latest_twenty_before_pinning_open_events(tmp_path: Path) -> None:
    database = _database(tmp_path)
    _insert_event(
        database,
        event_id="old-open",
        updated_at=NOW - timedelta(hours=2),
        state="open",
        risk_kind="outside_candidate",
    )
    for index in range(21):
        _insert_event(
            database,
            event_id=f"recent-{index:02d}",
            updated_at=NOW + timedelta(minutes=index),
            state="open" if index == 3 else "recovered",
        )

    result = GuardianEventQueryService(database).recent_events()

    assert len(result.events) == 20
    assert result.events[0].event_id == "recent-03"
    assert "old-open" not in {event.event_id for event in result.events}
    assert "recent-00" not in {event.event_id for event in result.events}


def test_returns_closed_media_free_projection_and_all_evidence_states(
    tmp_path: Path,
) -> None:
    database = _database(tmp_path)
    states = ["collecting", "ready", "failed", "interrupted", None]
    for index, evidence_state in enumerate(states):
        _insert_event(
            database,
            event_id=f"event-{index}",
            updated_at=NOW + timedelta(minutes=index),
            evidence_state=evidence_state,
        )

    payload = GuardianEventQueryService(database).recent_events().model_dump(mode="json")

    assert {event["evidence_state"] for event in payload["events"]} == {
        "collecting",
        "ready",
        "failed",
        "interrupted",
        "unavailable",
    }
    assert set(payload["events"][0]) == {
        "event_id",
        "risk_kind",
        "state",
        "severity",
        "opened_at",
        "updated_at",
        "recovered_at",
        "adult_intervention_count",
        "evidence_state",
    }
    assert not any(
        key in str(payload).lower()
        for key in ("snapshot_key", "clip_key", "path", "confidence", "rule_version")
    )
