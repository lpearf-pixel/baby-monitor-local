from __future__ import annotations

import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from packages.contracts.vision import VisualRiskKind


def _aware(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("datetime must be timezone-aware")
    return value


class StoredVisualRiskEvent(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    event_id: str = Field(min_length=1, max_length=128)
    risk_kind: VisualRiskKind
    state: Literal["open", "recovered"]
    severity: Literal["high"] = "high"
    opened_at: datetime
    updated_at: datetime
    recovered_at: datetime | None = None
    confidence: float = Field(ge=0, le=1)
    rule_version: str = Field(min_length=1, max_length=128)
    adult_intervention_count: int = Field(default=0, ge=0)

    _aware_opened_at = field_validator("opened_at")(_aware)
    _aware_updated_at = field_validator("updated_at")(_aware)

    @field_validator("recovered_at")
    @classmethod
    def require_aware_recovered_at(
        cls,
        value: datetime | None,
    ) -> datetime | None:
        return _aware(value) if value is not None else None

    @model_validator(mode="after")
    def require_coherent_lifecycle(self) -> Self:
        if self.updated_at < self.opened_at:
            raise ValueError("updated_at cannot precede opened_at")
        if self.state == "open":
            if self.recovered_at is not None:
                raise ValueError("open event cannot have recovered_at")
        elif self.recovered_at is None:
            raise ValueError("recovered event requires recovered_at")
        elif self.updated_at != self.recovered_at:
            raise ValueError("updated_at must equal recovered_at")
        return self


class StoredVisualIntervention(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    intervention_id: str = Field(min_length=1, max_length=128)
    observed_at: datetime
    confidence: float = Field(ge=0, le=1)
    rule_version: str = Field(min_length=1, max_length=128)

    _aware_observed_at = field_validator("observed_at")(_aware)


class VisualRiskEventStore:
    def __init__(self, path: Path) -> None:
        self._path = Path(path)

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self._path, timeout=1.0)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        return connection

    def migrate(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS visual_risk_events (
                    event_id TEXT PRIMARY KEY,
                    risk_kind TEXT NOT NULL CHECK (
                        risk_kind IN (
                            'face_not_visible',
                            'prone_candidate',
                            'outside_candidate'
                        )
                    ),
                    state TEXT NOT NULL CHECK (state IN ('open', 'recovered')),
                    severity TEXT NOT NULL CHECK (severity = 'high'),
                    opened_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    recovered_at TEXT,
                    confidence REAL NOT NULL CHECK (
                        confidence >= 0 AND confidence <= 1
                    ),
                    rule_version TEXT NOT NULL,
                    adult_intervention_count INTEGER NOT NULL DEFAULT 0 CHECK (
                        adult_intervention_count >= 0
                    )
                );

                CREATE UNIQUE INDEX IF NOT EXISTS idx_visual_risk_one_open
                    ON visual_risk_events(risk_kind)
                    WHERE state = 'open';

                CREATE INDEX IF NOT EXISTS idx_visual_risk_updated
                    ON visual_risk_events(updated_at DESC, event_id DESC);

                CREATE TABLE IF NOT EXISTS visual_interventions (
                    intervention_id TEXT PRIMARY KEY,
                    observed_at TEXT NOT NULL,
                    confidence REAL NOT NULL CHECK (
                        confidence >= 0 AND confidence <= 1
                    ),
                    rule_version TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS visual_risk_interventions (
                    event_id TEXT NOT NULL,
                    intervention_id TEXT NOT NULL,
                    PRIMARY KEY (event_id, intervention_id),
                    FOREIGN KEY (event_id)
                        REFERENCES visual_risk_events(event_id) ON DELETE CASCADE,
                    FOREIGN KEY (intervention_id)
                        REFERENCES visual_interventions(intervention_id)
                        ON DELETE CASCADE
                );
                """
            )

    def integrity_check(self) -> str:
        with self._connect() as connection:
            row = connection.execute("PRAGMA integrity_check").fetchone()
        return str(row[0])

    def open_event(
        self,
        *,
        event_id: str,
        risk_kind: VisualRiskKind,
        opened_at: datetime,
        confidence: float,
        rule_version: str,
    ) -> StoredVisualRiskEvent:
        proposed = StoredVisualRiskEvent(
            event_id=event_id,
            risk_kind=risk_kind,
            state="open",
            opened_at=opened_at,
            updated_at=opened_at,
            confidence=confidence,
            rule_version=rule_version,
        )
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                """
                SELECT * FROM visual_risk_events
                WHERE risk_kind = ? AND state = 'open'
                LIMIT 1
                """,
                (risk_kind.value,),
            ).fetchone()
            if row is not None:
                return self._event_from_row(row)
            connection.execute(
                """
                INSERT INTO visual_risk_events (
                    event_id, risk_kind, state, severity, opened_at, updated_at,
                    recovered_at, confidence, rule_version,
                    adult_intervention_count
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                self._event_values(proposed),
            )
        return proposed

    def recover_event(
        self,
        *,
        risk_kind: VisualRiskKind,
        recovered_at: datetime,
        confidence: float,
        rule_version: str,
    ) -> StoredVisualRiskEvent | None:
        _aware(recovered_at)
        if not 0 <= confidence <= 1:
            raise ValueError("confidence must be between 0 and 1")
        if not rule_version:
            raise ValueError("rule_version must not be empty")
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                """
                SELECT * FROM visual_risk_events
                WHERE risk_kind = ? AND state = 'open'
                LIMIT 1
                """,
                (risk_kind.value,),
            ).fetchone()
            if row is None:
                return None
            opened = self._event_from_row(row)
            recovered = opened.model_copy(
                update={
                    "state": "recovered",
                    "updated_at": recovered_at,
                    "recovered_at": recovered_at,
                    "confidence": confidence,
                    "rule_version": rule_version,
                }
            )
            recovered = StoredVisualRiskEvent.model_validate(recovered)
            connection.execute(
                """
                UPDATE visual_risk_events
                SET state = ?, updated_at = ?, recovered_at = ?,
                    confidence = ?, rule_version = ?
                WHERE event_id = ?
                """,
                (
                    recovered.state,
                    recovered.updated_at.isoformat(),
                    recovered.recovered_at.isoformat(),
                    recovered.confidence,
                    recovered.rule_version,
                    recovered.event_id,
                ),
            )
        return recovered

    def record_intervention(
        self,
        *,
        intervention_id: str,
        observed_at: datetime,
        confidence: float,
        rule_version: str,
    ) -> StoredVisualIntervention:
        proposed = StoredVisualIntervention(
            intervention_id=intervention_id,
            observed_at=observed_at,
            confidence=confidence,
            rule_version=rule_version,
        )
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            connection.execute(
                """
                INSERT OR IGNORE INTO visual_interventions (
                    intervention_id, observed_at, confidence, rule_version
                ) VALUES (?, ?, ?, ?)
                """,
                (
                    proposed.intervention_id,
                    proposed.observed_at.isoformat(),
                    proposed.confidence,
                    proposed.rule_version,
                ),
            )
            row = connection.execute(
                """
                SELECT * FROM visual_interventions
                WHERE intervention_id = ?
                """,
                (intervention_id,),
            ).fetchone()
            stored = self._intervention_from_row(row)
            open_rows = connection.execute(
                """
                SELECT event_id FROM visual_risk_events
                WHERE state = 'open' AND opened_at <= ?
                ORDER BY event_id
                """,
                (stored.observed_at.isoformat(),),
            ).fetchall()
            for open_row in open_rows:
                cursor = connection.execute(
                    """
                    INSERT OR IGNORE INTO visual_risk_interventions (
                        event_id, intervention_id
                    ) VALUES (?, ?)
                    """,
                    (open_row["event_id"], stored.intervention_id),
                )
                if cursor.rowcount:
                    connection.execute(
                        """
                        UPDATE visual_risk_events
                        SET adult_intervention_count = adult_intervention_count + 1
                        WHERE event_id = ?
                        """,
                        (open_row["event_id"],),
                    )
        return stored

    def load_open(self) -> tuple[StoredVisualRiskEvent, ...]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT * FROM visual_risk_events
                WHERE state = 'open'
                ORDER BY updated_at DESC, event_id DESC
                """
            ).fetchall()
        return tuple(self._event_from_row(row) for row in rows)

    def list_events(self, *, limit: int = 100) -> tuple[StoredVisualRiskEvent, ...]:
        if limit <= 0:
            raise ValueError("limit must be positive")
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT * FROM visual_risk_events
                ORDER BY updated_at DESC, event_id DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
        return tuple(self._event_from_row(row) for row in rows)

    def intervention_event_ids(self, intervention_id: str) -> tuple[str, ...]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT event_id FROM visual_risk_interventions
                WHERE intervention_id = ?
                ORDER BY event_id
                """,
                (intervention_id,),
            ).fetchall()
        return tuple(str(row["event_id"]) for row in rows)

    @staticmethod
    def _event_values(event: StoredVisualRiskEvent) -> tuple[object, ...]:
        return (
            event.event_id,
            event.risk_kind.value,
            event.state,
            event.severity,
            event.opened_at.isoformat(),
            event.updated_at.isoformat(),
            event.recovered_at.isoformat() if event.recovered_at else None,
            event.confidence,
            event.rule_version,
            event.adult_intervention_count,
        )

    @staticmethod
    def _event_from_row(row: sqlite3.Row) -> StoredVisualRiskEvent:
        return StoredVisualRiskEvent(
            event_id=row["event_id"],
            risk_kind=row["risk_kind"],
            state=row["state"],
            severity=row["severity"],
            opened_at=datetime.fromisoformat(row["opened_at"]),
            updated_at=datetime.fromisoformat(row["updated_at"]),
            recovered_at=(
                datetime.fromisoformat(row["recovered_at"])
                if row["recovered_at"] is not None
                else None
            ),
            confidence=float(row["confidence"]),
            rule_version=row["rule_version"],
            adult_intervention_count=int(row["adult_intervention_count"]),
        )

    @staticmethod
    def _intervention_from_row(row: sqlite3.Row) -> StoredVisualIntervention:
        return StoredVisualIntervention(
            intervention_id=row["intervention_id"],
            observed_at=datetime.fromisoformat(row["observed_at"]),
            confidence=float(row["confidence"]),
            rule_version=row["rule_version"],
        )
