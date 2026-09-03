from __future__ import annotations

import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from services.dashboard.contracts import DashboardWindow
from services.dashboard.guardian_query import (
    GuardianDashboardQuery,
    GuardianDashboardQueryUnavailable,
)
from services.storage.visual_risk import VisualRiskEventStore


NOW = datetime(2026, 9, 3, 1, 0, tzinfo=UTC)


def create_database(tmp_path: Path) -> Path:
    database = tmp_path / "events.sqlite3"
    VisualRiskEventStore(database).migrate()
    return database


def insert_event(
    database: Path,
    *,
    event_id: str,
    state: str,
    updated_at: datetime,
    opened_at: datetime | None = None,
    recovered_at: datetime | None = None,
    risk_kind: str = "face_not_visible",
) -> None:
    opened = opened_at or updated_at - timedelta(minutes=1)
    recovered = recovered_at if state == "recovered" else None
    if state == "recovered" and recovered is None:
        recovered = updated_at
    with sqlite3.connect(database) as connection:
        connection.execute(
            """
            INSERT INTO visual_risk_events (
                event_id, risk_kind, state, severity, opened_at, updated_at,
                recovered_at, confidence, rule_version, adult_intervention_count
            ) VALUES (?, ?, ?, 'high', ?, ?, ?, 0.9, 'v1', 0)
            """,
            (
                event_id,
                risk_kind,
                state,
                opened.isoformat(),
                updated_at.isoformat(),
                recovered.isoformat() if recovered is not None else None,
            ),
        )


def insert_ready_event_and_notifications(database: Path, *, now: datetime) -> None:
    insert_event(database, event_id="event-1", state="open", updated_at=now)
    digest = "a" * 64
    with sqlite3.connect(database) as connection:
        connection.execute(
            """
            INSERT INTO visual_risk_evidence (
                event_id, state, started_at, updated_at, capture_deadline,
                snapshot_key, clip_key, frame_count, failure_code
            ) VALUES (?, 'ready', ?, ?, ?, ?, ?, 1, NULL)
            """,
            (
                "event-1",
                now.isoformat(),
                now.isoformat(),
                now.isoformat(),
                f"visual-risk/{digest}/snapshot.jpg",
                f"visual-risk/{digest}/clip.webp",
            ),
        )
        for notification_id, state in (("notice-1", "pending"), ("notice-2", "delivered")):
            connection.execute(
                """
                INSERT INTO visual_risk_notifications (
                    notification_id, event_id, stage, intervention_id, state,
                    queued_at, updated_at, next_attempt_at, dispatch_count,
                    result_code
                ) VALUES (?, 'event-1', 'risk_opened', ?, ?, ?, ?, ?, 0, ?)
                """,
                (
                    notification_id,
                    notification_id,
                    state,
                    now.isoformat(),
                    now.isoformat(),
                    now.isoformat() if state == "pending" else None,
                    None if state == "pending" else "ok",
                ),
            )


def test_missing_database_fails_without_creating_it(tmp_path: Path) -> None:
    database = tmp_path / "missing.sqlite3"

    with pytest.raises(GuardianDashboardQueryUnavailable):
        GuardianDashboardQuery(database).alerts()

    assert not database.exists()


def test_alerts_return_all_open_then_fill_with_latest_recovered(tmp_path: Path) -> None:
    database = create_database(tmp_path)
    insert_event(database, event_id="old-open", state="open", updated_at=NOW)
    for index in range(105):
        insert_event(
            database,
            event_id=f"recovered-{index:03d}",
            state="recovered",
            updated_at=NOW + timedelta(minutes=index + 1),
        )

    alerts = GuardianDashboardQuery(database).alerts()

    assert len(alerts) == 100
    assert alerts[0].alert_id == "guardian:old-open"
    assert alerts[0].state == "open"
    assert {item.source for item in alerts} == {"guardian"}


def test_alert_projection_aggregates_notification_without_media_fields(
    tmp_path: Path,
) -> None:
    database = create_database(tmp_path)
    insert_ready_event_and_notifications(database, now=NOW)

    payload = GuardianDashboardQuery(database).alerts()[0].model_dump(mode="json")

    assert payload["notification_state"] == "mixed"
    assert payload["evidence_state"] == "ready"
    assert payload["resolution_cause"] is None
    assert not any(
        word in str(payload).lower()
        for word in ("confidence", "rule_version", "snapshot", "clip", "path")
    )


def test_queries_are_read_only_when_connection_is_injected(tmp_path: Path) -> None:
    database = create_database(tmp_path)
    insert_event(database, event_id="event-1", state="open", updated_at=NOW)
    statements: list[str] = []

    def tracing_connect(*args: object, **kwargs: object) -> sqlite3.Connection:
        connection = sqlite3.connect(*args, **kwargs)
        connection.set_trace_callback(statements.append)
        return connection

    GuardianDashboardQuery(database, connect=tracing_connect).alerts()

    prohibited = (
        "INSERT",
        "UPDATE",
        "DELETE",
        "CREATE",
        "DROP",
        "ALTER",
        "REPLACE",
        "VACUUM",
    )
    assert statements
    assert not any(
        statement.lstrip().upper().startswith(prohibited) for statement in statements
    )


def test_analytics_uses_half_open_windows_and_fixed_denominators(
    tmp_path: Path,
) -> None:
    database = create_database(tmp_path)
    started_at = NOW - timedelta(hours=24)
    insert_event(
        database,
        event_id="face",
        state="recovered",
        opened_at=started_at,
        recovered_at=started_at + timedelta(seconds=60),
        updated_at=started_at + timedelta(seconds=60),
        risk_kind="face_not_visible",
    )
    insert_event(
        database,
        event_id="prone",
        state="recovered",
        opened_at=started_at + timedelta(seconds=1),
        recovered_at=started_at + timedelta(seconds=121),
        updated_at=started_at + timedelta(seconds=121),
        risk_kind="prone_candidate",
    )
    insert_event(
        database,
        event_id="outside",
        state="open",
        opened_at=NOW - timedelta(seconds=1),
        updated_at=NOW - timedelta(seconds=1),
        risk_kind="outside_candidate",
    )
    insert_event(
        database,
        event_id="before",
        state="recovered",
        opened_at=started_at - timedelta(seconds=1),
        recovered_at=started_at - timedelta(seconds=1),
        updated_at=started_at - timedelta(seconds=1),
    )
    insert_event(
        database,
        event_id="after",
        state="recovered",
        opened_at=NOW,
        recovered_at=NOW,
        updated_at=NOW,
    )
    with sqlite3.connect(database) as connection:
        connection.executemany(
            """
            INSERT INTO visual_risk_evidence (
                event_id, state, started_at, updated_at, capture_deadline,
                snapshot_key, clip_key, frame_count, failure_code
            ) VALUES (?, ?, ?, ?, ?, NULL, NULL, 0, ?)
            """,
            (
                (
                    "face",
                    "ready",
                    started_at.isoformat(),
                    started_at.isoformat(),
                    started_at.isoformat(),
                    None,
                ),
                (
                    "outside",
                    "failed",
                    (NOW - timedelta(seconds=1)).isoformat(),
                    (NOW - timedelta(seconds=1)).isoformat(),
                    (NOW - timedelta(seconds=1)).isoformat(),
                    "media_write_failed",
                ),
            ),
        )
        connection.executemany(
            """
            INSERT INTO visual_interventions (
                intervention_id, observed_at, confidence, rule_version
            ) VALUES (?, ?, 0.9, 'v1')
            """,
            (
                ("at-start", started_at.isoformat()),
                ("before", (started_at - timedelta(seconds=1)).isoformat()),
                ("at-end", NOW.isoformat()),
                ("before-end", (NOW - timedelta(seconds=1)).isoformat()),
            ),
        )
        connection.executemany(
            """
            INSERT INTO visual_risk_notifications (
                notification_id, event_id, stage, intervention_id, state,
                queued_at, updated_at, next_attempt_at, dispatch_count, result_code
            ) VALUES (?, ?, 'risk_opened', ?, ?, ?, ?, ?, 0, ?)
            """,
            (
                (
                    "delivered",
                    "face",
                    "delivered",
                    "delivered",
                    started_at.isoformat(),
                    started_at.isoformat(),
                    None,
                    "ok",
                ),
                (
                    "rejected",
                    "prone",
                    "rejected",
                    "rejected",
                    (NOW - timedelta(seconds=1)).isoformat(),
                    (NOW - timedelta(seconds=1)).isoformat(),
                    None,
                    "payload_rejected",
                ),
                (
                    "terminal-at-end",
                    "outside",
                    "delivered",
                    "delivered",
                    NOW.isoformat(),
                    NOW.isoformat(),
                    None,
                    "ok",
                ),
                (
                    "pending",
                    "outside",
                    "pending",
                    "pending",
                    NOW.isoformat(),
                    NOW.isoformat(),
                    NOW.isoformat(),
                    None,
                ),
            ),
        )

    metrics = GuardianDashboardQuery(database).analytics(DashboardWindow.HOURS_24, NOW)

    assert metrics.state == "available"
    assert metrics.confirmed_count == 3
    assert metrics.recovered_count == 2
    assert metrics.recovery_median_seconds == 90.0
    assert metrics.intervention_count == 2
    assert metrics.risk_counts.model_dump() == {
        "face_not_visible": 1,
        "prone_candidate": 1,
        "outside_candidate": 1,
    }
    assert metrics.evidence_counts.ready_rate == 0.5
    assert metrics.evidence_counts.missing == 1
    assert metrics.notification_counts.pending == 1
    assert metrics.notification_counts.terminal_total == 2
    assert metrics.notification_counts.success_rate == 0.5


def test_recovered_count_has_half_open_boundaries_and_requires_aware_times(
    tmp_path: Path,
) -> None:
    database = create_database(tmp_path)
    started_at = NOW - timedelta(hours=24)
    for event_id, recovered_at in (
        ("before", started_at - timedelta(seconds=1)),
        ("at-start", started_at),
        ("before-end", NOW - timedelta(seconds=1)),
        ("at-end", NOW),
    ):
        insert_event(
            database,
            event_id=event_id,
            state="recovered",
            opened_at=recovered_at - timedelta(seconds=1),
            recovered_at=recovered_at,
            updated_at=recovered_at,
        )

    query = GuardianDashboardQuery(database)

    assert query.recovered_count(started_at, NOW) == 2
    with pytest.raises(ValueError, match="timezone-aware"):
        query.recovered_count(started_at.replace(tzinfo=None), NOW)
    with pytest.raises(ValueError, match="ended_at"):
        query.recovered_count(NOW, started_at)


def test_notification_component_reports_pending_and_empty_queues(tmp_path: Path) -> None:
    database = create_database(tmp_path)
    query = GuardianDashboardQuery(database)

    empty = query.notification_component(NOW)
    assert (empty.state, empty.reason_code) == ("healthy", "notification_queue_empty")

    insert_event(database, event_id="event-1", state="open", updated_at=NOW)
    with sqlite3.connect(database) as connection:
        connection.execute(
            """
            INSERT INTO visual_risk_notifications (
                notification_id, event_id, stage, intervention_id, state,
                queued_at, updated_at, next_attempt_at, dispatch_count, result_code
            ) VALUES ('pending', 'event-1', 'risk_opened', '', 'pending', ?, ?, ?, 0, NULL)
            """,
            (NOW.isoformat(), NOW.isoformat(), NOW.isoformat()),
        )

    pending = query.notification_component(NOW)
    assert (pending.state, pending.reason_code) == (
        "degraded",
        "notification_queue_pending",
    )
