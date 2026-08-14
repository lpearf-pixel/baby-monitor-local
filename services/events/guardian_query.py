from __future__ import annotations

import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    ValidationError,
    field_validator,
    model_validator,
)

from packages.contracts.vision import VisualRiskKind


def _aware(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("datetime must be timezone-aware")
    return value


GuardianEvidenceState = Literal[
    "collecting", "ready", "failed", "interrupted", "unavailable"
]


class GuardianEventSummary(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    event_id: str = Field(min_length=1, max_length=128)
    risk_kind: VisualRiskKind
    state: Literal["open", "recovered"]
    severity: Literal["high"]
    opened_at: datetime
    updated_at: datetime
    recovered_at: datetime | None
    adult_intervention_count: int = Field(ge=0)
    evidence_state: GuardianEvidenceState

    _aware_opened_at = field_validator("opened_at")(_aware)
    _aware_updated_at = field_validator("updated_at")(_aware)

    @field_validator("recovered_at")
    @classmethod
    def require_aware_recovered_at(
        cls, value: datetime | None
    ) -> datetime | None:
        return _aware(value) if value is not None else None

    @model_validator(mode="after")
    def require_coherent_lifecycle(self) -> "GuardianEventSummary":
        if self.updated_at < self.opened_at:
            raise ValueError("updated_at cannot precede opened_at")
        if self.state == "open" and self.recovered_at is not None:
            raise ValueError("open event cannot have recovered_at")
        if self.state == "recovered" and self.recovered_at != self.updated_at:
            raise ValueError("recovered event requires matching recovered_at")
        return self


class GuardianEventList(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    generated_at: datetime
    events: tuple[GuardianEventSummary, ...] = Field(max_length=20)

    _aware_generated_at = field_validator("generated_at")(_aware)


class GuardianEventQueryUnavailable(RuntimeError):
    pass


class GuardianEventQueryService:
    def __init__(self, database_path: Path) -> None:
        self._database_path = Path(database_path)

    def recent_events(self) -> GuardianEventList:
        if not self._database_path.is_file():
            raise GuardianEventQueryUnavailable
        uri = f"{self._database_path.resolve().as_uri()}?mode=ro"
        try:
            with sqlite3.connect(uri, uri=True, timeout=1.0) as connection:
                connection.row_factory = sqlite3.Row
                connection.execute("PRAGMA query_only = ON")
                rows = connection.execute(
                    """
                    WITH recent AS (
                        SELECT
                            event.event_id,
                            event.risk_kind,
                            event.state,
                            event.severity,
                            event.opened_at,
                            event.updated_at,
                            event.recovered_at,
                            event.adult_intervention_count,
                            COALESCE(evidence.state, 'unavailable')
                                AS evidence_state
                        FROM visual_risk_events AS event
                        LEFT JOIN visual_risk_evidence AS evidence
                            ON evidence.event_id = event.event_id
                        ORDER BY
                            julianday(event.updated_at) DESC,
                            event.event_id DESC
                        LIMIT 20
                    )
                    SELECT * FROM recent
                    ORDER BY
                        CASE state WHEN 'open' THEN 0 ELSE 1 END,
                        julianday(updated_at) DESC,
                        event_id DESC
                    """
                ).fetchall()
            events = tuple(
                GuardianEventSummary.model_validate(dict(row)) for row in rows
            )
            return GuardianEventList(generated_at=datetime.now(UTC), events=events)
        except (sqlite3.Error, ValidationError, ValueError) as exc:
            raise GuardianEventQueryUnavailable from exc
