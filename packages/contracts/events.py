from __future__ import annotations

from datetime import datetime, timedelta
from enum import StrEnum
from typing import Any, Literal, Self

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


class EnvironmentSourceKind(StrEnum):
    WS2021_GAUGE = "ws2021_gauge"
    BLUETOOTH = "bluetooth"
    MQTT = "mqtt"
    LAN_SENSOR = "lan_sensor"


class ConfidenceState(StrEnum):
    HIGH = "high"
    ACCEPTABLE = "acceptable"
    LOW = "low"
    UNAVAILABLE = "unavailable"


class ReadingFailureReason(StrEnum):
    CALIBRATION_MISSING = "calibration_missing"
    CALIBRATION_INVALID = "calibration_invalid"
    FRAME_SOURCE_UNAVAILABLE = "frame_source_unavailable"
    FRAME_STALE = "frame_stale"
    ROI_OUT_OF_BOUNDS = "roi_out_of_bounds"
    TOO_DARK = "too_dark"
    GLARE = "glare"
    OCCLUDED = "occluded"
    NEEDLE_NOT_FOUND = "needle_not_found"
    INSUFFICIENT_VALID_FRAMES = "insufficient_valid_frames"
    INCONSISTENT_FRAMES = "inconsistent_frames"
    LOW_CONFIDENCE = "low_confidence"
    INTERNAL_ERROR = "internal_error"


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
    schema_version: Literal[1] = 1
    reading_id: str = Field(min_length=1)
    source_kind: EnvironmentSourceKind
    captured_at: datetime
    fresh_until: datetime
    state: ReadingState
    temperature_c: float | None = Field(default=None, ge=-50, le=60)
    humidity_rh: float | None = Field(default=None, ge=0, le=100)
    confidence: float = Field(ge=0, le=1)
    confidence_state: ConfidenceState
    failure_reason: ReadingFailureReason | None = None
    calibration_version: str | None = Field(default=None, min_length=1)
    sample_count: int = Field(ge=0)
    valid_temperature_samples: int = Field(ge=0)
    valid_humidity_samples: int = Field(ge=0)

    _aware_captured_at = field_validator("captured_at")(_require_aware)
    _aware_fresh_until = field_validator("fresh_until")(_require_aware)

    @model_validator(mode="after")
    def require_values_matching_state(self) -> "EnvironmentReading":
        if self.fresh_until <= self.captured_at:
            raise ValueError("fresh_until must be later than captured_at")
        if self.valid_temperature_samples > self.sample_count:
            raise ValueError("valid_temperature_samples cannot exceed sample_count")
        if self.valid_humidity_samples > self.sample_count:
            raise ValueError("valid_humidity_samples cannot exceed sample_count")
        if (
            self.source_kind is EnvironmentSourceKind.WS2021_GAUGE
            and self.calibration_version is None
        ):
            raise ValueError("WS2021 reading requires calibration_version")

        has_both_values = (
            self.temperature_c is not None and self.humidity_rh is not None
        )
        has_any_value = (
            self.temperature_c is not None or self.humidity_rh is not None
        )
        if self.state is ReadingState.AVAILABLE:
            if not has_both_values:
                raise ValueError(
                    "available reading requires both temperature and humidity"
                )
            if self.failure_reason is not None:
                raise ValueError("available reading must not contain a failure reason")
            if self.confidence_state not in {
                ConfidenceState.HIGH,
                ConfidenceState.ACCEPTABLE,
            }:
                raise ValueError(
                    "available reading requires acceptable or high confidence"
                )
        else:
            if has_any_value:
                raise ValueError("unavailable reading must not contain measured values")
            if self.failure_reason is None:
                raise ValueError("unavailable reading requires a failure reason")
            if self.confidence_state not in {
                ConfidenceState.LOW,
                ConfidenceState.UNAVAILABLE,
            }:
                raise ValueError(
                    "unavailable reading requires low or unavailable confidence"
                )
        return self

    @classmethod
    def available(
        cls,
        *,
        reading_id: str,
        source_kind: EnvironmentSourceKind,
        captured_at: datetime,
        temperature_c: float,
        humidity_rh: float,
        confidence: float,
        calibration_version: str | None,
        sample_count: int,
        valid_temperature_samples: int,
        valid_humidity_samples: int,
        minimum_confidence: float = 0.75,
        freshness_seconds: int = 90,
    ) -> Self:
        if confidence < minimum_confidence:
            raise ValueError("reading does not meet minimum confidence")
        confidence_state = (
            ConfidenceState.HIGH
            if confidence >= 0.9
            else ConfidenceState.ACCEPTABLE
        )
        return cls(
            reading_id=reading_id,
            source_kind=source_kind,
            captured_at=captured_at,
            fresh_until=captured_at + timedelta(seconds=freshness_seconds),
            state=ReadingState.AVAILABLE,
            temperature_c=temperature_c,
            humidity_rh=humidity_rh,
            confidence=confidence,
            confidence_state=confidence_state,
            failure_reason=None,
            calibration_version=calibration_version,
            sample_count=sample_count,
            valid_temperature_samples=valid_temperature_samples,
            valid_humidity_samples=valid_humidity_samples,
        )

    @classmethod
    def unavailable(
        cls,
        *,
        reading_id: str,
        source_kind: EnvironmentSourceKind,
        captured_at: datetime,
        failure_reason: ReadingFailureReason,
        calibration_version: str | None,
        sample_count: int,
        valid_temperature_samples: int = 0,
        valid_humidity_samples: int = 0,
        confidence: float = 0,
        freshness_seconds: int = 90,
    ) -> Self:
        return cls(
            reading_id=reading_id,
            source_kind=source_kind,
            captured_at=captured_at,
            fresh_until=captured_at + timedelta(seconds=freshness_seconds),
            state=ReadingState.UNAVAILABLE,
            temperature_c=None,
            humidity_rh=None,
            confidence=confidence,
            confidence_state=(
                ConfidenceState.LOW
                if confidence > 0
                else ConfidenceState.UNAVAILABLE
            ),
            failure_reason=failure_reason,
            calibration_version=calibration_version,
            sample_count=sample_count,
            valid_temperature_samples=valid_temperature_samples,
            valid_humidity_samples=valid_humidity_samples,
        )


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
