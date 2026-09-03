from __future__ import annotations

import sqlite3
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from datetime import datetime, timedelta
from pathlib import Path
from statistics import median

from pydantic import ValidationError

from services.dashboard.contracts import (
    DashboardAlertV1,
    DashboardComponentV1,
    DashboardEvidenceCountsV1,
    DashboardGuardianAnalyticsV1,
    DashboardNotificationCountsV1,
    DashboardRiskCountsV1,
    DashboardWindow,
)


class GuardianDashboardQueryUnavailable(RuntimeError):
    pass


def window_start(window: DashboardWindow, now: datetime) -> datetime:
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("now must be timezone-aware")
    duration = (
        timedelta(hours=24)
        if window is DashboardWindow.HOURS_24
        else timedelta(days=7)
    )
    return now - duration


class GuardianDashboardQuery:
    def __init__(
        self,
        database_path: Path,
        *,
        connect: Callable[..., sqlite3.Connection] = sqlite3.connect,
    ) -> None:
        self._database_path = Path(database_path)
        self._connect = connect

    @contextmanager
    def _connection(self) -> Iterator[sqlite3.Connection]:
        if not self._database_path.is_file():
            raise GuardianDashboardQueryUnavailable
        uri = f"{self._database_path.resolve().as_uri()}?mode=ro"
        try:
            with self._connect(uri, uri=True, timeout=1.0) as connection:
                connection.row_factory = sqlite3.Row
                connection.execute("PRAGMA query_only = ON")
                yield connection
        except (sqlite3.Error, ValueError, ValidationError) as exc:
            raise GuardianDashboardQueryUnavailable from exc

    def alerts(self) -> tuple[DashboardAlertV1, ...]:
        with self._connection() as connection:
            rows = connection.execute(
                """
                SELECT
                    event.event_id,
                    event.risk_kind,
                    event.state,
                    event.opened_at,
                    event.updated_at,
                    event.recovered_at,
                    event.adult_intervention_count,
                    COALESCE(evidence.state, 'unavailable') AS evidence_state,
                    CASE
                        WHEN COUNT(notification.notification_id) = 0
                            THEN 'unavailable'
                        WHEN COUNT(DISTINCT notification.state) = 1
                            THEN MIN(notification.state)
                        ELSE 'mixed'
                    END AS notification_state
                FROM visual_risk_events AS event
                LEFT JOIN visual_risk_evidence AS evidence
                    ON evidence.event_id = event.event_id
                LEFT JOIN visual_risk_notifications AS notification
                    ON notification.event_id = event.event_id
                GROUP BY
                    event.event_id,
                    event.risk_kind,
                    event.state,
                    event.opened_at,
                    event.updated_at,
                    event.recovered_at,
                    event.adult_intervention_count,
                    evidence.state
                ORDER BY
                    CASE event.state WHEN 'open' THEN 0 ELSE 1 END,
                    CASE event.state WHEN 'open' THEN 0 ELSE 2 END,
                    julianday(event.updated_at) DESC,
                    event.event_id DESC
                LIMIT 100
                """
            ).fetchall()
            return tuple(
                DashboardAlertV1(
                    alert_id=f"guardian:{row['event_id']}",
                    source="guardian",
                    kind=row["risk_kind"],
                    state=row["state"],
                    priority="critical" if row["state"] == "open" else "info",
                    opened_at=datetime.fromisoformat(row["opened_at"]),
                    updated_at=datetime.fromisoformat(row["updated_at"]),
                    recovered_at=(
                        datetime.fromisoformat(row["recovered_at"])
                        if row["recovered_at"] is not None
                        else None
                    ),
                    reason_codes=(),
                    adult_intervention_count=row["adult_intervention_count"],
                    evidence_state=row["evidence_state"],
                    notification_state=row["notification_state"],
                    resolution_cause=None,
                )
                for row in rows
            )

    def analytics(
        self,
        window: DashboardWindow,
        now: datetime,
    ) -> DashboardGuardianAnalyticsV1:
        started_at = window_start(window, now)
        try:
            summary = self._event_summary(started_at, now)
            recovered_rows = self._recovered_rows(started_at, now)
            intervention_count = self._intervention_count(started_at, now)
            notification_counts = self._notification_counts(started_at, now)
            recovery_durations = [
                (
                    datetime.fromisoformat(row["recovered_at"])
                    - datetime.fromisoformat(row["opened_at"])
                ).total_seconds()
                for row in recovered_rows
            ]
            return DashboardGuardianAnalyticsV1(
                state="available",
                confirmed_count=int(summary["confirmed_count"]),
                recovered_count=len(recovered_rows),
                intervention_count=intervention_count,
                recovery_median_seconds=(
                    float(median(recovery_durations)) if recovery_durations else None
                ),
                risk_counts=DashboardRiskCountsV1(
                    face_not_visible=int(summary["face_not_visible"]),
                    prone_candidate=int(summary["prone_candidate"]),
                    outside_candidate=int(summary["outside_candidate"]),
                ),
                evidence_counts=DashboardEvidenceCountsV1(
                    collecting=int(summary["collecting"]),
                    ready=int(summary["ready"]),
                    failed=int(summary["failed"]),
                    interrupted=int(summary["interrupted"]),
                    retained_total=int(summary["retained_total"]),
                    missing=int(summary["missing"]),
                    ready_rate=(
                        int(summary["ready"]) / int(summary["retained_total"])
                        if int(summary["retained_total"])
                        else None
                    ),
                ),
                notification_counts=notification_counts,
            )
        except (ValueError, ValidationError) as exc:
            raise GuardianDashboardQueryUnavailable from exc

    def recovered_count(self, started_at: datetime, ended_at: datetime) -> int:
        self._require_window(started_at, ended_at)
        with self._connection() as connection:
            row = connection.execute(
                """
                SELECT COUNT(*) AS recovered_count
                FROM visual_risk_events
                WHERE recovered_at IS NOT NULL
                    AND julianday(recovered_at) >= julianday(?)
                    AND julianday(recovered_at) < julianday(?)
                """,
                (started_at.isoformat(), ended_at.isoformat()),
            ).fetchone()
        return int(row["recovered_count"])

    def notification_component(self, now: datetime) -> DashboardComponentV1:
        if now.tzinfo is None or now.utcoffset() is None:
            raise ValueError("now must be timezone-aware")
        with self._connection() as connection:
            row = connection.execute(
                """
                SELECT COUNT(*) AS pending_count
                FROM visual_risk_notifications
                WHERE state = 'pending'
                """
            ).fetchone()
        if int(row["pending_count"]):
            return DashboardComponentV1(
                component_id="notification_queue",
                state="degraded",
                reason_code="notification_queue_pending",
                updated_at=now,
            )
        return DashboardComponentV1(
            component_id="notification_queue",
            state="healthy",
            reason_code="notification_queue_empty",
            updated_at=now,
        )

    def _event_summary(self, started_at: datetime, ended_at: datetime) -> sqlite3.Row:
        with self._connection() as connection:
            row = connection.execute(
                """
                SELECT
                    COUNT(event.event_id) AS confirmed_count,
                    COALESCE(SUM(CASE WHEN event.risk_kind = 'face_not_visible'
                        THEN 1 ELSE 0 END), 0) AS face_not_visible,
                    COALESCE(SUM(CASE WHEN event.risk_kind = 'prone_candidate'
                        THEN 1 ELSE 0 END), 0) AS prone_candidate,
                    COALESCE(SUM(CASE WHEN event.risk_kind = 'outside_candidate'
                        THEN 1 ELSE 0 END), 0) AS outside_candidate,
                    COALESCE(SUM(CASE WHEN evidence.state = 'collecting'
                        THEN 1 ELSE 0 END), 0) AS collecting,
                    COALESCE(SUM(CASE WHEN evidence.state = 'ready'
                        THEN 1 ELSE 0 END), 0) AS ready,
                    COALESCE(SUM(CASE WHEN evidence.state = 'failed'
                        THEN 1 ELSE 0 END), 0) AS failed,
                    COALESCE(SUM(CASE WHEN evidence.state = 'interrupted'
                        THEN 1 ELSE 0 END), 0) AS interrupted,
                    COALESCE(SUM(CASE WHEN evidence.event_id IS NOT NULL
                        THEN 1 ELSE 0 END), 0) AS retained_total,
                    COALESCE(SUM(CASE WHEN evidence.event_id IS NULL
                        THEN 1 ELSE 0 END), 0) AS missing
                FROM visual_risk_events AS event
                LEFT JOIN visual_risk_evidence AS evidence
                    ON evidence.event_id = event.event_id
                WHERE julianday(event.opened_at) >= julianday(?)
                    AND julianday(event.opened_at) < julianday(?)
                """,
                (started_at.isoformat(), ended_at.isoformat()),
            ).fetchone()
        assert row is not None
        return row

    def _recovered_rows(
        self,
        started_at: datetime,
        ended_at: datetime,
    ) -> tuple[sqlite3.Row, ...]:
        with self._connection() as connection:
            rows = connection.execute(
                """
                SELECT opened_at, recovered_at
                FROM visual_risk_events
                WHERE recovered_at IS NOT NULL
                    AND julianday(recovered_at) >= julianday(?)
                    AND julianday(recovered_at) < julianday(?)
                """,
                (started_at.isoformat(), ended_at.isoformat()),
            ).fetchall()
        return tuple(rows)

    def _intervention_count(self, started_at: datetime, ended_at: datetime) -> int:
        with self._connection() as connection:
            row = connection.execute(
                """
                SELECT COUNT(*) AS intervention_count
                FROM visual_interventions
                WHERE julianday(observed_at) >= julianday(?)
                    AND julianday(observed_at) < julianday(?)
                """,
                (started_at.isoformat(), ended_at.isoformat()),
            ).fetchone()
        return int(row["intervention_count"])

    def _notification_counts(
        self,
        started_at: datetime,
        ended_at: datetime,
    ) -> DashboardNotificationCountsV1:
        with self._connection() as connection:
            row = connection.execute(
                """
                SELECT
                    COALESCE(SUM(CASE WHEN state = 'pending'
                        THEN 1 ELSE 0 END), 0) AS pending,
                    COALESCE(SUM(CASE
                        WHEN state = 'delivered'
                            AND julianday(updated_at) >= julianday(?)
                            AND julianday(updated_at) < julianday(?)
                        THEN 1 ELSE 0 END), 0) AS delivered,
                    COALESCE(SUM(CASE
                        WHEN state = 'rejected'
                            AND julianday(updated_at) >= julianday(?)
                            AND julianday(updated_at) < julianday(?)
                        THEN 1 ELSE 0 END), 0) AS rejected
                FROM visual_risk_notifications
                """,
                (
                    started_at.isoformat(),
                    ended_at.isoformat(),
                    started_at.isoformat(),
                    ended_at.isoformat(),
                ),
            ).fetchone()
        delivered = int(row["delivered"])
        rejected = int(row["rejected"])
        terminal_total = delivered + rejected
        return DashboardNotificationCountsV1(
            pending=int(row["pending"]),
            delivered=delivered,
            rejected=rejected,
            terminal_total=terminal_total,
            success_rate=delivered / terminal_total if terminal_total else None,
        )

    @staticmethod
    def _require_window(started_at: datetime, ended_at: datetime) -> None:
        if (
            started_at.tzinfo is None
            or started_at.utcoffset() is None
            or ended_at.tzinfo is None
            or ended_at.utcoffset() is None
        ):
            raise ValueError("started_at and ended_at must be timezone-aware")
        if ended_at <= started_at:
            raise ValueError("ended_at must follow started_at")
