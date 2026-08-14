from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
from pathlib import Path
import re
import sqlite3
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


EvidenceState = Literal["collecting", "ready", "failed", "interrupted"]
EvidenceFailureCode = Literal[
    "snapshot_unavailable",
    "media_write_failed",
    "worker_restarted",
    "worker_stopped",
]
_EVIDENCE_KEY = re.compile(
    r"\Avisual-risk/[0-9a-f]{64}/(?:snapshot\.jpg|clip\.webp)\Z"
)


class StoredVisualRiskEvidence(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    event_id: str = Field(min_length=1, max_length=128)
    state: EvidenceState
    started_at: datetime
    updated_at: datetime
    capture_deadline: datetime
    snapshot_key: str | None = None
    clip_key: str | None = None
    frame_count: int = Field(ge=0, le=21)
    failure_code: EvidenceFailureCode | None = None

    _aware_started_at = field_validator("started_at")(_aware)
    _aware_updated_at = field_validator("updated_at")(_aware)
    _aware_capture_deadline = field_validator("capture_deadline")(_aware)

    @field_validator("snapshot_key", "clip_key")
    @classmethod
    def require_safe_relative_key(cls, value: str | None) -> str | None:
        if value is not None and _EVIDENCE_KEY.fullmatch(value) is None:
            raise ValueError("invalid evidence key")
        return value

    @model_validator(mode="after")
    def require_coherent_evidence(self) -> Self:
        if self.capture_deadline < self.started_at:
            raise ValueError("capture_deadline cannot precede started_at")
        if self.updated_at < self.started_at:
            raise ValueError("updated_at cannot precede started_at")
        if self.state == "collecting":
            if self.clip_key is not None or self.failure_code is not None:
                raise ValueError("collecting evidence cannot be terminal")
        elif self.state == "ready":
            if self.snapshot_key is None or self.clip_key is None:
                raise ValueError("ready evidence requires snapshot and clip")
            if self.failure_code is not None:
                raise ValueError("ready evidence cannot have failure_code")
            if self.updated_at < self.capture_deadline:
                raise ValueError("ready evidence cannot precede deadline")
        else:
            if self.clip_key is not None or self.failure_code is None:
                raise ValueError("incomplete evidence requires failure_code")
        return self


class StoredEvidenceRetentionEntry(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    event_id: str = Field(min_length=1, max_length=128)
    state: EvidenceState
    retention_at: datetime
    deletable: bool

    _aware_retention_at = field_validator("retention_at")(_aware)


NotificationStage = Literal[
    "risk_opened",
    "risk_recovered",
    "adult_intervention",
]
NotificationState = Literal["pending", "delivered", "rejected"]
NotificationResultCode = Literal[
    "ok",
    "payload_rejected",
    "ntfy_rejected",
    "ntfy_unavailable",
    "retry_exhausted",
]


class StoredVisualRiskNotification(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    notification_id: str = Field(min_length=1, max_length=128)
    event_id: str = Field(min_length=1, max_length=128)
    stage: NotificationStage
    intervention_id: str | None = Field(default=None, max_length=128)
    state: NotificationState
    queued_at: datetime
    updated_at: datetime
    next_attempt_at: datetime | None
    dispatch_count: int = Field(ge=0, le=3)
    result_code: NotificationResultCode | None = None

    _aware_queued_at = field_validator("queued_at")(_aware)
    _aware_updated_at = field_validator("updated_at")(_aware)

    @field_validator("next_attempt_at")
    @classmethod
    def require_aware_next_attempt_at(
        cls,
        value: datetime | None,
    ) -> datetime | None:
        return _aware(value) if value is not None else None

    @model_validator(mode="after")
    def require_coherent_notification(self) -> Self:
        if self.updated_at < self.queued_at:
            raise ValueError("updated_at cannot precede queued_at")
        if self.stage == "adult_intervention":
            if not self.intervention_id:
                raise ValueError("adult intervention requires intervention_id")
        elif self.intervention_id is not None:
            raise ValueError("risk notification cannot have intervention_id")
        if self.state == "pending":
            if self.next_attempt_at is None:
                raise ValueError("pending notification requires next_attempt_at")
            if self.next_attempt_at < self.queued_at:
                raise ValueError("next_attempt_at cannot precede queued_at")
            if self.result_code not in {None, "ntfy_unavailable"}:
                raise ValueError("pending notification has invalid result_code")
        else:
            if self.next_attempt_at is not None or self.result_code is None:
                raise ValueError("terminal notification requires a result")
            if self.state == "delivered" and self.result_code != "ok":
                raise ValueError("delivered notification requires ok")
            if self.state == "rejected" and self.result_code == "ok":
                raise ValueError("rejected notification cannot be ok")
        return self


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

                CREATE TABLE IF NOT EXISTS visual_risk_evidence (
                    event_id TEXT PRIMARY KEY,
                    state TEXT NOT NULL CHECK (
                        state IN ('collecting', 'ready', 'failed', 'interrupted')
                    ),
                    started_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    capture_deadline TEXT NOT NULL,
                    snapshot_key TEXT,
                    clip_key TEXT,
                    frame_count INTEGER NOT NULL CHECK (
                        frame_count >= 0 AND frame_count <= 21
                    ),
                    failure_code TEXT CHECK (
                        failure_code IS NULL OR failure_code IN (
                            'snapshot_unavailable',
                            'media_write_failed',
                            'worker_restarted',
                            'worker_stopped'
                        )
                    ),
                    FOREIGN KEY (event_id)
                        REFERENCES visual_risk_events(event_id) ON DELETE CASCADE
                );

                CREATE INDEX IF NOT EXISTS idx_visual_risk_evidence_state
                    ON visual_risk_evidence(state, updated_at DESC);

                CREATE TABLE IF NOT EXISTS visual_risk_notifications (
                    notification_id TEXT PRIMARY KEY,
                    event_id TEXT NOT NULL,
                    stage TEXT NOT NULL CHECK (
                        stage IN (
                            'risk_opened',
                            'risk_recovered',
                            'adult_intervention'
                        )
                    ),
                    intervention_id TEXT NOT NULL DEFAULT '',
                    state TEXT NOT NULL CHECK (
                        state IN ('pending', 'delivered', 'rejected')
                    ),
                    queued_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    next_attempt_at TEXT,
                    dispatch_count INTEGER NOT NULL CHECK (
                        dispatch_count >= 0 AND dispatch_count <= 3
                    ),
                    result_code TEXT CHECK (
                        result_code IS NULL OR result_code IN (
                            'ok',
                            'payload_rejected',
                            'ntfy_rejected',
                            'ntfy_unavailable',
                            'retry_exhausted'
                        )
                    ),
                    UNIQUE (event_id, stage, intervention_id),
                    FOREIGN KEY (event_id)
                        REFERENCES visual_risk_events(event_id) ON DELETE CASCADE
                );

                CREATE INDEX IF NOT EXISTS idx_visual_risk_notification_pending
                    ON visual_risk_notifications(
                        state, next_attempt_at, queued_at, notification_id
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

    def get_event(self, event_id: str) -> StoredVisualRiskEvent | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM visual_risk_events WHERE event_id = ?",
                (event_id,),
            ).fetchone()
        return self._event_from_row(row) if row is not None else None

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

    def begin_evidence(
        self,
        *,
        event_id: str,
        started_at: datetime,
        capture_deadline: datetime,
        snapshot_key: str | None,
        frame_count: int,
    ) -> StoredVisualRiskEvidence:
        proposed = StoredVisualRiskEvidence(
            event_id=event_id,
            state="collecting",
            started_at=started_at,
            updated_at=started_at,
            capture_deadline=capture_deadline,
            snapshot_key=snapshot_key,
            frame_count=frame_count,
        )
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT * FROM visual_risk_evidence WHERE event_id = ?",
                (event_id,),
            ).fetchone()
            if row is not None:
                return self._evidence_from_row(row)
            connection.execute(
                """
                INSERT INTO visual_risk_evidence (
                    event_id, state, started_at, updated_at, capture_deadline,
                    snapshot_key, clip_key, frame_count, failure_code
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                self._evidence_values(proposed),
            )
        return proposed

    def complete_evidence(
        self,
        *,
        event_id: str,
        completed_at: datetime,
        clip_key: str,
        frame_count: int,
    ) -> StoredVisualRiskEvidence:
        return self._finish_evidence(
            event_id=event_id,
            updated_at=completed_at,
            state="ready",
            clip_key=clip_key,
            frame_count=frame_count,
            failure_code=None,
        )

    def fail_evidence(
        self,
        *,
        event_id: str,
        failed_at: datetime,
        failure_code: EvidenceFailureCode,
        frame_count: int,
    ) -> StoredVisualRiskEvidence:
        if failure_code not in {"snapshot_unavailable", "media_write_failed"}:
            raise ValueError("invalid evidence failure code")
        return self._finish_evidence(
            event_id=event_id,
            updated_at=failed_at,
            state="failed",
            clip_key=None,
            frame_count=frame_count,
            failure_code=failure_code,
        )

    def interrupt_collecting_evidence(
        self,
        *,
        interrupted_at: datetime,
        failure_code: Literal["worker_restarted", "worker_stopped"] = (
            "worker_restarted"
        ),
    ) -> tuple[StoredVisualRiskEvidence, ...]:
        _aware(interrupted_at)
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            rows = connection.execute(
                """
                SELECT * FROM visual_risk_evidence
                WHERE state = 'collecting'
                ORDER BY event_id
                """
            ).fetchall()
            interrupted = tuple(
                StoredVisualRiskEvidence.model_validate(
                    {
                        **dict(row),
                        "state": "interrupted",
                        "updated_at": interrupted_at,
                        "failure_code": failure_code,
                    }
                )
                for row in rows
            )
            for evidence in interrupted:
                connection.execute(
                    """
                    UPDATE visual_risk_evidence
                    SET state = ?, updated_at = ?, failure_code = ?
                    WHERE event_id = ? AND state = 'collecting'
                    """,
                    (
                        evidence.state,
                        evidence.updated_at.isoformat(),
                        evidence.failure_code,
                        evidence.event_id,
                    ),
                )
        return interrupted

    def get_evidence(self, event_id: str) -> StoredVisualRiskEvidence | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM visual_risk_evidence WHERE event_id = ?",
                (event_id,),
            ).fetchone()
        return self._evidence_from_row(row) if row is not None else None

    def list_evidence_retention_entries(
        self,
    ) -> tuple[StoredEvidenceRetentionEntry, ...]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT
                    evidence.event_id,
                    evidence.state,
                    event.updated_at AS event_updated_at,
                    evidence.updated_at AS evidence_updated_at,
                    CASE
                        WHEN event.state = 'recovered'
                            AND evidence.state IN (
                                'ready', 'failed', 'interrupted'
                            )
                            AND NOT EXISTS (
                                SELECT 1
                                FROM visual_risk_notifications AS notification
                                WHERE notification.event_id = evidence.event_id
                                    AND notification.state = 'pending'
                            )
                            AND EXISTS (
                                SELECT 1
                                FROM visual_risk_notifications AS recovery
                                WHERE recovery.event_id = evidence.event_id
                                    AND recovery.stage = 'risk_recovered'
                                    AND recovery.state IN ('delivered', 'rejected')
                            )
                        THEN 1
                        ELSE 0
                    END AS deletable
                FROM visual_risk_evidence AS evidence
                JOIN visual_risk_events AS event
                    ON event.event_id = evidence.event_id
                """
            ).fetchall()
        entries = tuple(
            StoredEvidenceRetentionEntry(
                event_id=row["event_id"],
                state=row["state"],
                retention_at=max(
                    datetime.fromisoformat(row["event_updated_at"]),
                    datetime.fromisoformat(row["evidence_updated_at"]),
                ),
                deletable=bool(row["deletable"]),
            )
            for row in rows
        )
        return tuple(
            sorted(entries, key=lambda entry: (entry.retention_at, entry.event_id))
        )

    def delete_evidence_if_eligible(
        self,
        entry: StoredEvidenceRetentionEntry,
        delete_files: Callable[[], int],
    ) -> int | None:
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                """
                SELECT
                    evidence.state,
                    evidence.updated_at AS evidence_updated_at,
                    event.state AS event_state,
                    event.updated_at AS event_updated_at,
                    EXISTS (
                        SELECT 1
                        FROM visual_risk_notifications AS notification
                        WHERE notification.event_id = evidence.event_id
                            AND notification.state = 'pending'
                    ) AS has_pending_notification,
                    EXISTS (
                        SELECT 1
                        FROM visual_risk_notifications AS recovery
                        WHERE recovery.event_id = evidence.event_id
                            AND recovery.stage = 'risk_recovered'
                            AND recovery.state IN ('delivered', 'rejected')
                    ) AS has_terminal_recovery_notification
                FROM visual_risk_evidence AS evidence
                JOIN visual_risk_events AS event
                    ON event.event_id = evidence.event_id
                WHERE evidence.event_id = ?
                """,
                (entry.event_id,),
            ).fetchone()
            if row is None:
                return None
            retention_at = max(
                datetime.fromisoformat(row["event_updated_at"]),
                datetime.fromisoformat(row["evidence_updated_at"]),
            )
            if (
                row["state"] != entry.state
                or retention_at != entry.retention_at
                or row["event_state"] != "recovered"
                or row["state"] not in {"ready", "failed", "interrupted"}
                or bool(row["has_pending_notification"])
                or not bool(row["has_terminal_recovery_notification"])
            ):
                return None
            reclaimed_bytes = delete_files()
            cursor = connection.execute(
                """
                DELETE FROM visual_risk_evidence
                WHERE event_id = ? AND state = ? AND updated_at = ?
                    AND EXISTS (
                        SELECT 1 FROM visual_risk_events AS event
                        WHERE event.event_id = visual_risk_evidence.event_id
                            AND event.state = 'recovered'
                            AND event.updated_at = ?
                    )
                    AND NOT EXISTS (
                        SELECT 1
                        FROM visual_risk_notifications AS notification
                        WHERE notification.event_id = visual_risk_evidence.event_id
                            AND notification.state = 'pending'
                    )
                    AND EXISTS (
                        SELECT 1
                        FROM visual_risk_notifications AS recovery
                        WHERE recovery.event_id = visual_risk_evidence.event_id
                            AND recovery.stage = 'risk_recovered'
                            AND recovery.state IN ('delivered', 'rejected')
                    )
                """,
                (
                    entry.event_id,
                    entry.state,
                    row["evidence_updated_at"],
                    row["event_updated_at"],
                ),
            )
            if cursor.rowcount != 1:
                raise RuntimeError("evidence retention state changed")
        return reclaimed_bytes

    def queue_notification(
        self,
        *,
        notification_id: str,
        event_id: str,
        stage: NotificationStage,
        queued_at: datetime,
        intervention_id: str | None = None,
    ) -> StoredVisualRiskNotification:
        proposed = StoredVisualRiskNotification(
            notification_id=notification_id,
            event_id=event_id,
            stage=stage,
            intervention_id=intervention_id,
            state="pending",
            queued_at=queued_at,
            updated_at=queued_at,
            next_attempt_at=queued_at,
            dispatch_count=0,
        )
        intervention_key = intervention_id or ""
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                """
                SELECT * FROM visual_risk_notifications
                WHERE event_id = ? AND stage = ? AND intervention_id = ?
                """,
                (event_id, stage, intervention_key),
            ).fetchone()
            if row is not None:
                return self._notification_from_row(row)
            connection.execute(
                """
                INSERT INTO visual_risk_notifications (
                    notification_id, event_id, stage, intervention_id, state,
                    queued_at, updated_at, next_attempt_at, dispatch_count,
                    result_code
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    proposed.notification_id,
                    proposed.event_id,
                    proposed.stage,
                    intervention_key,
                    proposed.state,
                    proposed.queued_at.isoformat(),
                    proposed.updated_at.isoformat(),
                    proposed.next_attempt_at.isoformat(),
                    proposed.dispatch_count,
                    proposed.result_code,
                ),
            )
        return proposed

    def next_pending_notification(
        self,
        now: datetime,
    ) -> StoredVisualRiskNotification | None:
        _aware(now)
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT candidate.* FROM visual_risk_notifications AS candidate
                WHERE candidate.state = 'pending'
                    AND julianday(candidate.next_attempt_at) <= julianday(?)
                    AND NOT EXISTS (
                        SELECT 1
                        FROM visual_risk_notifications AS earlier
                        WHERE earlier.event_id = candidate.event_id
                            AND earlier.state = 'pending'
                            AND (
                                julianday(earlier.queued_at)
                                    < julianday(candidate.queued_at)
                                OR (
                                    julianday(earlier.queued_at)
                                        = julianday(candidate.queued_at)
                                    AND earlier.notification_id
                                        < candidate.notification_id
                                )
                            )
                    )
                ORDER BY julianday(candidate.next_attempt_at),
                    julianday(candidate.queued_at), candidate.notification_id
                LIMIT 1
                """,
                (now.isoformat(),),
            ).fetchone()
        return self._notification_from_row(row) if row is not None else None

    def get_notification(
        self,
        notification_id: str,
    ) -> StoredVisualRiskNotification | None:
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT * FROM visual_risk_notifications
                WHERE notification_id = ?
                """,
                (notification_id,),
            ).fetchone()
        return self._notification_from_row(row) if row is not None else None

    def record_notification_result(
        self,
        *,
        notification_id: str,
        attempted_at: datetime,
        result_code: Literal[
            "ok", "payload_rejected", "ntfy_rejected", "ntfy_unavailable"
        ],
        retry_at: datetime | None = None,
    ) -> StoredVisualRiskNotification:
        _aware(attempted_at)
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                """
                SELECT * FROM visual_risk_notifications
                WHERE notification_id = ?
                """,
                (notification_id,),
            ).fetchone()
            if row is None:
                raise ValueError("notification does not exist")
            current = self._notification_from_row(row)
            if current.state != "pending":
                return current
            dispatch_count = current.dispatch_count + 1
            if result_code == "ok":
                state: NotificationState = "delivered"
                stored_result: NotificationResultCode = "ok"
                next_attempt_at = None
            elif result_code in {"payload_rejected", "ntfy_rejected"}:
                state = "rejected"
                stored_result = result_code
                next_attempt_at = None
            elif dispatch_count >= 3:
                state = "rejected"
                stored_result = "retry_exhausted"
                next_attempt_at = None
            else:
                if retry_at is None:
                    raise ValueError("unavailable notification requires retry_at")
                _aware(retry_at)
                if retry_at <= attempted_at:
                    raise ValueError("retry_at must follow attempted_at")
                state = "pending"
                stored_result = "ntfy_unavailable"
                next_attempt_at = retry_at
            updated = StoredVisualRiskNotification(
                **{
                    **current.model_dump(),
                    "state": state,
                    "updated_at": attempted_at,
                    "next_attempt_at": next_attempt_at,
                    "dispatch_count": dispatch_count,
                    "result_code": stored_result,
                }
            )
            connection.execute(
                """
                UPDATE visual_risk_notifications
                SET state = ?, updated_at = ?, next_attempt_at = ?,
                    dispatch_count = ?, result_code = ?
                WHERE notification_id = ? AND state = 'pending'
                """,
                (
                    updated.state,
                    updated.updated_at.isoformat(),
                    (
                        updated.next_attempt_at.isoformat()
                        if updated.next_attempt_at is not None
                        else None
                    ),
                    updated.dispatch_count,
                    updated.result_code,
                    updated.notification_id,
                ),
            )
        return updated

    def _finish_evidence(
        self,
        *,
        event_id: str,
        updated_at: datetime,
        state: Literal["ready", "failed"],
        clip_key: str | None,
        frame_count: int,
        failure_code: EvidenceFailureCode | None,
    ) -> StoredVisualRiskEvidence:
        _aware(updated_at)
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT * FROM visual_risk_evidence WHERE event_id = ?",
                (event_id,),
            ).fetchone()
            if row is None:
                raise ValueError("evidence does not exist")
            current = self._evidence_from_row(row)
            if current.state != "collecting":
                raise ValueError("evidence is not collecting")
            finished = StoredVisualRiskEvidence(
                **{
                    **current.model_dump(),
                    "state": state,
                    "updated_at": updated_at,
                    "clip_key": clip_key,
                    "frame_count": frame_count,
                    "failure_code": failure_code,
                }
            )
            connection.execute(
                """
                UPDATE visual_risk_evidence
                SET state = ?, updated_at = ?, clip_key = ?, frame_count = ?,
                    failure_code = ?
                WHERE event_id = ? AND state = 'collecting'
                """,
                (
                    finished.state,
                    finished.updated_at.isoformat(),
                    finished.clip_key,
                    finished.frame_count,
                    finished.failure_code,
                    finished.event_id,
                ),
            )
        return finished

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

    @staticmethod
    def _evidence_values(evidence: StoredVisualRiskEvidence) -> tuple[object, ...]:
        return (
            evidence.event_id,
            evidence.state,
            evidence.started_at.isoformat(),
            evidence.updated_at.isoformat(),
            evidence.capture_deadline.isoformat(),
            evidence.snapshot_key,
            evidence.clip_key,
            evidence.frame_count,
            evidence.failure_code,
        )

    @staticmethod
    def _evidence_from_row(row: sqlite3.Row) -> StoredVisualRiskEvidence:
        return StoredVisualRiskEvidence(
            event_id=row["event_id"],
            state=row["state"],
            started_at=datetime.fromisoformat(row["started_at"]),
            updated_at=datetime.fromisoformat(row["updated_at"]),
            capture_deadline=datetime.fromisoformat(row["capture_deadline"]),
            snapshot_key=row["snapshot_key"],
            clip_key=row["clip_key"],
            frame_count=int(row["frame_count"]),
            failure_code=row["failure_code"],
        )

    @staticmethod
    def _notification_from_row(
        row: sqlite3.Row,
    ) -> StoredVisualRiskNotification:
        return StoredVisualRiskNotification(
            notification_id=row["notification_id"],
            event_id=row["event_id"],
            stage=row["stage"],
            intervention_id=row["intervention_id"] or None,
            state=row["state"],
            queued_at=datetime.fromisoformat(row["queued_at"]),
            updated_at=datetime.fromisoformat(row["updated_at"]),
            next_attempt_at=(
                datetime.fromisoformat(row["next_attempt_at"])
                if row["next_attempt_at"] is not None
                else None
            ),
            dispatch_count=int(row["dispatch_count"]),
            result_code=row["result_code"],
        )
