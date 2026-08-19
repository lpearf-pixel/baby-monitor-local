from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from packages.contracts.events import (
    CandidateEvent,
    EnvironmentReading,
    EventAcknowledgement,
    EventSeverity,
    HealthState,
    SystemHealth,
)


_SCHEMA_VERSION = 4


@dataclass(frozen=True, slots=True)
class EventNotification:
    notification_id: str
    event_id: str
    stage: str
    queued_at: datetime


def _iso(value: datetime) -> str:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("datetime must be timezone-aware")
    return value.isoformat()


def _datetime(value: str) -> datetime:
    return datetime.fromisoformat(value)


class EventStore:
    def __init__(self, database_path: Path) -> None:
        self._database_path = Path(database_path)

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self._database_path)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        return connection

    def migrate(self) -> None:
        self._database_path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS schema_migrations (
                    version INTEGER PRIMARY KEY,
                    applied_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS events (
                    event_id TEXT PRIMARY KEY,
                    kind TEXT NOT NULL,
                    severity TEXT NOT NULL,
                    occurred_at TEXT NOT NULL,
                    summary TEXT NOT NULL,
                    confidence REAL,
                    rule_version TEXT NOT NULL,
                    metadata_json TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS environment_readings (
                    reading_id TEXT PRIMARY KEY,
                    captured_at TEXT NOT NULL,
                    state TEXT NOT NULL,
                    temperature_c REAL,
                    humidity_rh REAL,
                    confidence REAL NOT NULL,
                    reason TEXT,
                    payload_json TEXT
                );

                CREATE TABLE IF NOT EXISTS legacy_environment_readings (
                    reading_id TEXT PRIMARY KEY,
                    captured_at TEXT NOT NULL,
                    state TEXT NOT NULL,
                    temperature_c REAL,
                    humidity_rh REAL,
                    confidence REAL NOT NULL,
                    reason TEXT,
                    archived_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS system_health (
                    health_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    component TEXT NOT NULL,
                    checked_at TEXT NOT NULL,
                    state TEXT NOT NULL,
                    detail TEXT
                );

                CREATE INDEX IF NOT EXISTS idx_system_health_component_time
                    ON system_health(component, checked_at);

                CREATE TABLE IF NOT EXISTS event_acknowledgements (
                    event_id TEXT NOT NULL,
                    parent_id TEXT NOT NULL,
                    acknowledged_at TEXT NOT NULL,
                    PRIMARY KEY (event_id, parent_id),
                    FOREIGN KEY (event_id) REFERENCES events(event_id) ON DELETE CASCADE
                );

                CREATE TABLE IF NOT EXISTS event_notifications (
                    notification_id TEXT PRIMARY KEY,
                    event_id TEXT NOT NULL UNIQUE,
                    stage TEXT NOT NULL CHECK(stage IN (
                        'audio_opened', 'audio_escalated',
                        'audio_merged', 'audio_recovered'
                    )),
                    queued_at TEXT NOT NULL,
                    state TEXT NOT NULL DEFAULT 'pending'
                        CHECK(state IN ('pending', 'delivered', 'rejected')),
                    FOREIGN KEY (event_id) REFERENCES events(event_id)
                        ON DELETE CASCADE
                );
                """
            )
            environment_columns = {
                str(row["name"])
                for row in connection.execute(
                    "PRAGMA table_info(environment_readings)"
                ).fetchall()
            }
            if "payload_json" not in environment_columns:
                connection.execute(
                    "ALTER TABLE environment_readings ADD COLUMN payload_json TEXT"
                )
            archived_at = datetime.now().astimezone().isoformat()
            connection.execute(
                """
                INSERT OR IGNORE INTO legacy_environment_readings (
                    reading_id, captured_at, state, temperature_c,
                    humidity_rh, confidence, reason, archived_at
                )
                SELECT reading_id, captured_at, state, temperature_c,
                       humidity_rh, confidence, reason, ?
                FROM environment_readings
                WHERE payload_json IS NULL
                """,
                (archived_at,),
            )
            connection.execute(
                "DELETE FROM environment_readings WHERE payload_json IS NULL"
            )
            connection.execute(
                """
                INSERT OR IGNORE INTO schema_migrations(version, applied_at)
                VALUES (?, ?)
                """,
                (_SCHEMA_VERSION, datetime.now().astimezone().isoformat()),
            )

    def schema_version(self) -> int:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT COALESCE(MAX(version), 0) AS version FROM schema_migrations"
            ).fetchone()
        return int(row["version"])

    def legacy_environment_reading_count(self) -> int:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT COUNT(*) AS count FROM legacy_environment_readings"
            ).fetchone()
        return int(row["count"])

    def integrity_check(self) -> str:
        with self._connect() as connection:
            row = connection.execute("PRAGMA integrity_check").fetchone()
        return str(row[0])

    def add_event(self, event: CandidateEvent) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO events(
                    event_id, kind, severity, occurred_at, summary,
                    confidence, rule_version, metadata_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    event.event_id,
                    event.kind,
                    event.severity.value,
                    _iso(event.occurred_at),
                    event.summary,
                    event.confidence,
                    event.rule_version,
                    json.dumps(event.metadata, ensure_ascii=False, sort_keys=True),
                ),
            )

    def add_event_with_notification(
        self,
        event: CandidateEvent,
        *,
        notification_id: str,
        stage: str,
    ) -> None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM events WHERE event_id = ?", (event.event_id,)
            ).fetchone()
            if row is not None:
                existing = self._event_from_row(row)
                if existing != event:
                    raise ValueError("event id conflicts with stored event")
                return
            connection.execute(
                """
                INSERT INTO events(
                    event_id, kind, severity, occurred_at, summary,
                    confidence, rule_version, metadata_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    event.event_id,
                    event.kind,
                    event.severity.value,
                    _iso(event.occurred_at),
                    event.summary,
                    event.confidence,
                    event.rule_version,
                    json.dumps(event.metadata, ensure_ascii=False, sort_keys=True),
                ),
            )
            connection.execute(
                """
                INSERT INTO event_notifications(
                    notification_id, event_id, stage, queued_at
                ) VALUES (?, ?, ?, ?)
                """,
                (notification_id, event.event_id, stage, _iso(event.occurred_at)),
            )

    def list_pending_event_notifications(self) -> tuple[EventNotification, ...]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT notification_id, event_id, stage, queued_at
                FROM event_notifications
                WHERE state = 'pending'
                ORDER BY julianday(queued_at), rowid
                """
            ).fetchall()
        return tuple(
            EventNotification(
                notification_id=row["notification_id"],
                event_id=row["event_id"],
                stage=row["stage"],
                queued_at=_datetime(row["queued_at"]),
            )
            for row in rows
        )

    def count_events(self, *, kind: str) -> int:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT COUNT(*) AS count FROM events WHERE kind = ?", (kind,)
            ).fetchone()
        return int(row["count"])

    def get_event(self, event_id: str) -> CandidateEvent | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM events WHERE event_id = ?",
                (event_id,),
            ).fetchone()
        if row is None:
            return None
        return self._event_from_row(row)

    @staticmethod
    def _event_from_row(row: sqlite3.Row) -> CandidateEvent:
        return CandidateEvent(
            event_id=row["event_id"],
            kind=row["kind"],
            severity=EventSeverity(row["severity"]),
            occurred_at=_datetime(row["occurred_at"]),
            summary=row["summary"],
            confidence=row["confidence"],
            rule_version=row["rule_version"],
            metadata=json.loads(row["metadata_json"]),
        )

    def add_environment_reading(self, reading: EnvironmentReading) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO environment_readings(
                    reading_id, captured_at, state, temperature_c,
                    humidity_rh, confidence, reason, payload_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    reading.reading_id,
                    _iso(reading.captured_at),
                    reading.state.value,
                    reading.temperature_c,
                    reading.humidity_rh,
                    reading.confidence,
                    (
                        reading.failure_reason.value
                        if reading.failure_reason is not None
                        else None
                    ),
                    reading.model_dump_json(),
                ),
            )

    def latest_environment_reading(self) -> EnvironmentReading | None:
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT * FROM environment_readings
                ORDER BY julianday(captured_at) DESC, rowid DESC
                LIMIT 1
                """
            ).fetchone()
        if row is None:
            return None
        return EnvironmentReading.model_validate_json(row["payload_json"])

    def acknowledge(
        self,
        event_id: str,
        parent_id: str,
        acknowledged_at: datetime,
    ) -> None:
        timestamp = _iso(acknowledged_at)
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO event_acknowledgements(event_id, parent_id, acknowledged_at)
                VALUES (?, ?, ?)
                ON CONFLICT(event_id, parent_id)
                DO UPDATE SET acknowledged_at = excluded.acknowledged_at
                """,
                (event_id, parent_id, timestamp),
            )

    def list_acknowledgements(self, event_id: str) -> list[EventAcknowledgement]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT event_id, parent_id, acknowledged_at
                FROM event_acknowledgements
                WHERE event_id = ?
                ORDER BY parent_id
                """,
                (event_id,),
            ).fetchall()
        return [
            EventAcknowledgement(
                event_id=row["event_id"],
                parent_id=row["parent_id"],
                acknowledged_at=_datetime(row["acknowledged_at"]),
            )
            for row in rows
        ]

    def record_system_health(self, health: SystemHealth) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO system_health(component, checked_at, state, detail)
                VALUES (?, ?, ?, ?)
                """,
                (
                    health.component,
                    _iso(health.checked_at),
                    health.state.value,
                    health.detail,
                ),
            )

    def latest_system_health(self, component: str) -> SystemHealth | None:
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT component, checked_at, state, detail
                FROM system_health
                WHERE component = ?
                ORDER BY julianday(checked_at) DESC, health_id DESC
                LIMIT 1
                """,
                (component,),
            ).fetchone()
        if row is None:
            return None
        return SystemHealth(
            component=row["component"],
            checked_at=_datetime(row["checked_at"]),
            state=HealthState(row["state"]),
            detail=row["detail"],
        )
