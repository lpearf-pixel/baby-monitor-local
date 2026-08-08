from __future__ import annotations

import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


def _aware(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("datetime must be timezone-aware")
    return value


def _aware_optional(value: datetime | None) -> datetime | None:
    return _aware(value) if value is not None else None


class StoredVisualHealthIncident(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    incident_id: str = Field(min_length=1, max_length=128)
    code: Literal["source_offline", "frame_frozen"]
    state: Literal["open", "recovered"]
    opened_at: datetime
    updated_at: datetime
    recovered_at: datetime | None = None
    duration_seconds: float = Field(ge=0)
    opened_notified: bool = False
    recovered_notified: bool = False

    _aware_opened_at = field_validator("opened_at")(_aware)
    _aware_updated_at = field_validator("updated_at")(_aware)
    _aware_recovered_at = field_validator("recovered_at")(_aware_optional)

    @model_validator(mode="after")
    def require_coherent_state(self) -> Self:
        if self.updated_at < self.opened_at:
            raise ValueError("updated_at cannot precede opened_at")
        if self.state == "open":
            if self.recovered_at is not None:
                raise ValueError("open incident cannot have recovered_at")
            if self.recovered_notified:
                raise ValueError("open incident cannot be recovery-notified")
        else:
            if self.recovered_at is None:
                raise ValueError("recovered incident requires recovered_at")
            if self.recovered_at != self.updated_at:
                raise ValueError("recovered_at must equal updated_at")
        return self


class VisualHealthStore:
    def __init__(self, path: Path) -> None:
        self._path = Path(path)

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self._path, timeout=1.0)
        connection.row_factory = sqlite3.Row
        return connection

    def migrate(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS visual_health_incidents (
                    incident_id TEXT PRIMARY KEY,
                    code TEXT NOT NULL CHECK (
                        code IN ('source_offline', 'frame_frozen')
                    ),
                    state TEXT NOT NULL CHECK (state IN ('open', 'recovered')),
                    opened_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    recovered_at TEXT,
                    duration_seconds REAL NOT NULL CHECK (duration_seconds >= 0),
                    opened_notified INTEGER NOT NULL CHECK (
                        opened_notified IN (0, 1)
                    ),
                    recovered_notified INTEGER NOT NULL CHECK (
                        recovered_notified IN (0, 1)
                    )
                );

                CREATE UNIQUE INDEX IF NOT EXISTS idx_visual_health_one_open
                    ON visual_health_incidents(state)
                    WHERE state = 'open';

                CREATE INDEX IF NOT EXISTS idx_visual_health_updated
                    ON visual_health_incidents(updated_at, incident_id);
                """
            )

    def integrity_check(self) -> str:
        with self._connect() as connection:
            row = connection.execute("PRAGMA integrity_check").fetchone()
        return str(row[0])

    def save(self, incident: StoredVisualHealthIncident) -> None:
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO visual_health_incidents (
                    incident_id, code, state, opened_at, updated_at,
                    recovered_at, duration_seconds, opened_notified,
                    recovered_notified
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(incident_id) DO UPDATE SET
                    code = excluded.code,
                    state = excluded.state,
                    opened_at = excluded.opened_at,
                    updated_at = excluded.updated_at,
                    recovered_at = excluded.recovered_at,
                    duration_seconds = excluded.duration_seconds,
                    opened_notified = excluded.opened_notified,
                    recovered_notified = excluded.recovered_notified
                """,
                self._values(incident),
            )

    def load_open(self) -> StoredVisualHealthIncident | None:
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT * FROM visual_health_incidents
                WHERE state = 'open'
                LIMIT 1
                """
            ).fetchone()
        return self._from_row(row) if row is not None else None

    def incidents(self, *, limit: int = 100) -> tuple[StoredVisualHealthIncident, ...]:
        if limit <= 0:
            raise ValueError("limit must be positive")
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT * FROM visual_health_incidents
                ORDER BY updated_at DESC, incident_id DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
        return tuple(self._from_row(row) for row in rows)

    @staticmethod
    def _values(incident: StoredVisualHealthIncident) -> tuple[object, ...]:
        return (
            incident.incident_id,
            incident.code,
            incident.state,
            incident.opened_at.isoformat(),
            incident.updated_at.isoformat(),
            incident.recovered_at.isoformat() if incident.recovered_at else None,
            incident.duration_seconds,
            int(incident.opened_notified),
            int(incident.recovered_notified),
        )

    @staticmethod
    def _from_row(row: sqlite3.Row) -> StoredVisualHealthIncident:
        return StoredVisualHealthIncident(
            incident_id=row["incident_id"],
            code=row["code"],
            state=row["state"],
            opened_at=datetime.fromisoformat(row["opened_at"]),
            updated_at=datetime.fromisoformat(row["updated_at"]),
            recovered_at=(
                datetime.fromisoformat(row["recovered_at"])
                if row["recovered_at"] is not None
                else None
            ),
            duration_seconds=float(row["duration_seconds"]),
            opened_notified=bool(row["opened_notified"]),
            recovered_notified=bool(row["recovered_notified"]),
        )
