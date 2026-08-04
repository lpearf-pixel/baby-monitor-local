from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class EventContract(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


def _require_aware(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("datetime must be timezone-aware")
    return value


class EventSeverity(StrEnum):
    INFO = "info"
    NORMAL = "normal"
    HIGH = "high"
    CRITICAL = "critical"


class ReadingState(StrEnum):
    AVAILABLE = "available"
    UNAVAILABLE = "unavailable"


class HealthState(StrEnum):
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    OFFLINE = "offline"


class CandidateEvent(EventContract):
    event_id: str = Field(min_length=1)
    kind: str = Field(min_length=1)
    severity: EventSeverity
    occurred_at: datetime
    summary: str = Field(min_length=1)
    confidence: float | None = Field(default=None, ge=0, le=1)
    rule_version: str = Field(min_length=1)
    metadata: dict[str, Any] = Field(default_factory=dict)

    _aware_occurred_at = field_validator("occurred_at")(_require_aware)


class EnvironmentReading(EventContract):
    reading_id: str = Field(min_length=1)
    captured_at: datetime
    state: ReadingState
    temperature_c: float | None = None
    humidity_rh: float | None = Field(default=None, ge=0, le=100)
    confidence: float = Field(ge=0, le=1)
    reason: str | None = None

    _aware_captured_at = field_validator("captured_at")(_require_aware)

    @model_validator(mode="after")
    def require_values_matching_state(self) -> "EnvironmentReading":
        has_value = self.temperature_c is not None or self.humidity_rh is not None
        if self.state is ReadingState.AVAILABLE and not has_value:
            raise ValueError("available reading requires a temperature or humidity value")
        if self.state is ReadingState.UNAVAILABLE and has_value:
            raise ValueError("unavailable reading must not contain measured values")
        return self


class EventAcknowledgement(EventContract):
    event_id: str = Field(min_length=1)
    parent_id: str = Field(min_length=1)
    acknowledged_at: datetime

    _aware_acknowledged_at = field_validator("acknowledged_at")(_require_aware)


class SystemHealth(EventContract):
    component: str = Field(min_length=1)
    checked_at: datetime
    state: HealthState
    detail: str | None = None

    _aware_checked_at = field_validator("checked_at")(_require_aware)
