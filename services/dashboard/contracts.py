from __future__ import annotations

from datetime import datetime, timedelta
from enum import StrEnum
from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class DashboardModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


def require_aware(value: datetime | None) -> datetime | None:
    if value is not None and (value.tzinfo is None or value.utcoffset() is None):
        raise ValueError("datetime must be timezone-aware")
    return value


class DashboardWindow(StrEnum):
    HOURS_24 = "24h"
    DAYS_7 = "7d"


DashboardSource = Literal["guardian", "environment", "system"]
DashboardPriority = Literal["critical", "warning", "info"]
DashboardAlertState = Literal["open", "recovered"]
DashboardSectionState = Literal["available", "unavailable"]
DashboardComponentState = Literal["healthy", "degraded", "unavailable", "disabled"]
DashboardEvidenceState = Literal[
    "collecting", "ready", "failed", "interrupted", "unavailable"
]
DashboardNotificationState = Literal[
    "pending", "delivered", "rejected", "mixed", "unavailable"
]
DashboardResolutionCause = Literal["explicit_safe", "subject_outside"]
DashboardAlertKind = Literal[
    "face_not_visible",
    "prone_candidate",
    "outside_candidate",
    "environment_range",
    "environment_unreadable",
    "camera_status",
    "guardian_query_status",
    "environment_query_status",
    "notification_queue_status",
    "calibration_status",
]
DashboardComponentId = Literal[
    "camera",
    "guardian_query",
    "environment",
    "gauge_calibration",
    "notification_queue",
    "visual",
    "voice",
    "camera_reply",
]
DashboardReasonCode = Literal[
    "temperature_low",
    "temperature_high",
    "temperature_critical_low",
    "temperature_critical_high",
    "humidity_low",
    "humidity_high",
    "humidity_critical_low",
    "humidity_critical_high",
    "reading_unavailable",
    "no_new_reading",
    "calibration_missing",
    "calibration_invalid",
    "frame_source_unavailable",
    "frame_stale",
    "roi_out_of_bounds",
    "too_dark",
    "glare",
    "occluded",
    "needle_not_found",
    "insufficient_valid_frames",
    "inconsistent_frames",
    "low_confidence",
    "internal_error",
    "environment_no_reading",
    "camera_online",
    "camera_offline",
    "camera_unavailable",
    "guardian_query_available",
    "guardian_query_unavailable",
    "environment_available",
    "environment_unavailable",
    "notification_queue_empty",
    "notification_queue_pending",
    "notification_query_unavailable",
    "calibration_available",
    "camera_reply_disabled",
    "camera_reply_status_unavailable",
]


class DashboardAlertV1(DashboardModel):
    alert_id: str = Field(min_length=1, max_length=160)
    source: DashboardSource
    kind: DashboardAlertKind
    state: DashboardAlertState
    priority: DashboardPriority
    opened_at: datetime
    updated_at: datetime
    recovered_at: datetime | None = None
    reason_codes: tuple[DashboardReasonCode, ...] = Field(max_length=8)
    adult_intervention_count: int | None = Field(default=None, ge=0)
    evidence_state: DashboardEvidenceState | None = None
    notification_state: DashboardNotificationState | None = None
    resolution_cause: DashboardResolutionCause | None = None

    _aware_times = field_validator(
        "opened_at", "updated_at", "recovered_at"
    )(require_aware)

    @model_validator(mode="after")
    def require_lifecycle(self) -> Self:
        if self.updated_at < self.opened_at:
            raise ValueError("updated_at cannot precede opened_at")
        if self.state == "open":
            if self.recovered_at is not None or self.resolution_cause is not None:
                raise ValueError("open alert cannot contain recovery data")
        elif self.recovered_at is None:
            raise ValueError("recovered alert requires recovered_at")
        elif not self.opened_at <= self.recovered_at <= self.updated_at:
            raise ValueError("recovery time must be inside the lifecycle")
        return self


class DashboardComponentV1(DashboardModel):
    component_id: DashboardComponentId
    state: DashboardComponentState
    reason_code: DashboardReasonCode
    updated_at: datetime

    _aware_updated_at = field_validator("updated_at")(require_aware)


class DashboardEnvironmentCurrentV1(DashboardModel):
    state: Literal["available", "unavailable"]
    temperature_c: float | None = Field(default=None, ge=-50, le=60)
    humidity_rh: float | None = Field(default=None, ge=0, le=100)
    captured_at: datetime | None = None
    fresh_until: datetime | None = None
    failure_reason: DashboardReasonCode | None = None
    last_valid_temperature_c: float | None = Field(default=None, ge=-50, le=60)
    last_valid_humidity_rh: float | None = Field(default=None, ge=0, le=100)
    last_valid_captured_at: datetime | None = None

    _aware_times = field_validator(
        "captured_at", "fresh_until", "last_valid_captured_at"
    )(require_aware)

    @model_validator(mode="after")
    def require_current_lifecycle(self) -> Self:
        current_values = (
            self.temperature_c,
            self.humidity_rh,
            self.captured_at,
            self.fresh_until,
        )
        if self.state == "available":
            if any(value is None for value in current_values):
                raise ValueError("available environment requires current values")
            if self.failure_reason is not None:
                raise ValueError("available environment cannot contain a failure reason")
            if self.fresh_until <= self.captured_at:
                raise ValueError("fresh_until must follow captured_at")
        elif any(value is not None for value in current_values[:2]):
            raise ValueError("unavailable environment cannot contain current values")

        last_valid_values = (
            self.last_valid_temperature_c,
            self.last_valid_humidity_rh,
            self.last_valid_captured_at,
        )
        if any(value is None for value in last_valid_values) and any(
            value is not None for value in last_valid_values
        ):
            raise ValueError("last-valid environment values must be all present or absent")
        return self


class DashboardAttentionV1(DashboardModel):
    alert: DashboardAlertV1
    additional_open_count: int = Field(ge=0)


class DashboardOverviewV1(DashboardModel):
    schema_version: Literal[1]
    generated_at: datetime
    attention: DashboardAttentionV1 | None = None
    open_alert_count: int = Field(ge=0)
    guardian_open_count: int | None = Field(default=None, ge=0)
    today_recovered_count: int | None = Field(default=None, ge=0)
    environment: DashboardEnvironmentCurrentV1
    components: tuple[DashboardComponentV1, ...] = Field(max_length=8)
    recent_activity: tuple[DashboardAlertV1, ...] = Field(max_length=10)

    _aware_generated_at = field_validator("generated_at")(require_aware)

    @model_validator(mode="after")
    def require_unique_response_items(self) -> Self:
        _require_unique_ids(self.components, "component_id")
        _require_unique_ids(self.recent_activity, "alert_id")
        return self


class DashboardAlertListV1(DashboardModel):
    schema_version: Literal[1]
    generated_at: datetime
    alerts: tuple[DashboardAlertV1, ...] = Field(max_length=100)

    _aware_generated_at = field_validator("generated_at")(require_aware)

    @model_validator(mode="after")
    def require_unique_alert_ids(self) -> Self:
        _require_unique_ids(self.alerts, "alert_id")
        return self


class DashboardTrendBucketV1(DashboardModel):
    started_at: datetime
    ended_at: datetime
    sample_count: int = Field(ge=0)
    available_count: int = Field(ge=0)
    availability_rate: float | None = Field(default=None, ge=0, le=1)
    temperature_min_c: float | None = Field(default=None, ge=-50, le=60)
    temperature_median_c: float | None = Field(default=None, ge=-50, le=60)
    temperature_max_c: float | None = Field(default=None, ge=-50, le=60)
    humidity_min_rh: float | None = Field(default=None, ge=0, le=100)
    humidity_median_rh: float | None = Field(default=None, ge=0, le=100)
    humidity_max_rh: float | None = Field(default=None, ge=0, le=100)

    _aware_times = field_validator("started_at", "ended_at")(require_aware)

    @model_validator(mode="after")
    def require_coherent_bucket(self) -> Self:
        if self.ended_at <= self.started_at:
            raise ValueError("bucket must end after it starts")
        if self.available_count > self.sample_count:
            raise ValueError("available_count cannot exceed sample_count")
        _require_rate(
            self.availability_rate,
            self.available_count,
            self.sample_count,
            "availability_rate",
        )
        _require_measurement_triple(
            self.temperature_min_c,
            self.temperature_median_c,
            self.temperature_max_c,
            self.available_count,
            "temperature",
        )
        _require_measurement_triple(
            self.humidity_min_rh,
            self.humidity_median_rh,
            self.humidity_max_rh,
            self.available_count,
            "humidity",
        )
        return self


class DashboardRiskCountsV1(DashboardModel):
    face_not_visible: int = Field(ge=0)
    prone_candidate: int = Field(ge=0)
    outside_candidate: int = Field(ge=0)


class DashboardEvidenceCountsV1(DashboardModel):
    collecting: int = Field(ge=0)
    ready: int = Field(ge=0)
    failed: int = Field(ge=0)
    interrupted: int = Field(ge=0)
    retained_total: int = Field(ge=0)
    missing: int = Field(ge=0)
    ready_rate: float | None = Field(default=None, ge=0, le=1)

    @model_validator(mode="after")
    def require_evidence_totals(self) -> Self:
        expected_total = self.collecting + self.ready + self.failed + self.interrupted
        if self.retained_total != expected_total:
            raise ValueError("retained_total must equal retained evidence states")
        _require_rate(self.ready_rate, self.ready, self.retained_total, "ready_rate")
        return self


class DashboardNotificationCountsV1(DashboardModel):
    pending: int = Field(ge=0)
    delivered: int = Field(ge=0)
    rejected: int = Field(ge=0)
    terminal_total: int = Field(ge=0)
    success_rate: float | None = Field(default=None, ge=0, le=1)

    @model_validator(mode="after")
    def require_notification_totals(self) -> Self:
        if self.terminal_total != self.delivered + self.rejected:
            raise ValueError("terminal_total must equal delivered plus rejected")
        _require_rate(
            self.success_rate,
            self.delivered,
            self.terminal_total,
            "success_rate",
        )
        return self


class DashboardEnvironmentIncidentCountsV1(DashboardModel):
    range_normal: int = Field(ge=0)
    range_critical: int = Field(ge=0)
    unreadable: int = Field(ge=0)


class DashboardGuardianAnalyticsV1(DashboardModel):
    state: DashboardSectionState
    confirmed_count: int = Field(ge=0)
    recovered_count: int = Field(ge=0)
    intervention_count: int = Field(ge=0)
    recovery_median_seconds: float | None = Field(default=None, ge=0)
    risk_counts: DashboardRiskCountsV1
    evidence_counts: DashboardEvidenceCountsV1
    notification_counts: DashboardNotificationCountsV1


class DashboardEnvironmentAnalyticsV1(DashboardModel):
    state: DashboardSectionState
    sample_count: int = Field(ge=0)
    available_count: int = Field(ge=0)
    availability_rate: float | None = Field(default=None, ge=0, le=1)
    incident_counts: DashboardEnvironmentIncidentCountsV1
    buckets: tuple[DashboardTrendBucketV1, ...] = Field(max_length=288)

    @model_validator(mode="after")
    def require_environment_analytics(self) -> Self:
        if self.available_count > self.sample_count:
            raise ValueError("available_count cannot exceed sample_count")
        if self.state == "unavailable":
            if (
                self.sample_count != 0
                or self.available_count != 0
                or self.availability_rate is not None
                or self.buckets
                or any(self.incident_counts.model_dump().values())
            ):
                raise ValueError("unavailable environment analytics must be empty")
            return self
        _require_rate(
            self.availability_rate,
            self.available_count,
            self.sample_count,
            "availability_rate",
        )
        if self.sample_count != sum(bucket.sample_count for bucket in self.buckets):
            raise ValueError("sample_count must equal the bucket sum")
        if self.available_count != sum(
            bucket.available_count for bucket in self.buckets
        ):
            raise ValueError("available_count must equal the bucket sum")
        return self


class DashboardAnalyticsV1(DashboardModel):
    schema_version: Literal[1]
    generated_at: datetime
    window: DashboardWindow
    started_at: datetime
    ended_at: datetime
    environment: DashboardEnvironmentAnalyticsV1
    guardian: DashboardGuardianAnalyticsV1

    _aware_times = field_validator(
        "generated_at", "started_at", "ended_at"
    )(require_aware)

    @model_validator(mode="after")
    def require_analytics_window(self) -> Self:
        duration = (
            timedelta(hours=24)
            if self.window is DashboardWindow.HOURS_24
            else timedelta(days=7)
        )
        if self.ended_at <= self.started_at:
            raise ValueError("analytics must end after it starts")
        if self.ended_at - self.started_at != duration:
            raise ValueError("analytics duration must match its window")
        if self.environment.state == "available":
            expected_bucket_count = (
                288 if self.window is DashboardWindow.HOURS_24 else 168
            )
            expected_interval = (
                timedelta(minutes=5)
                if self.window is DashboardWindow.HOURS_24
                else timedelta(hours=1)
            )
            if len(self.environment.buckets) != expected_bucket_count:
                raise ValueError(
                    "available environment analytics must have every window bucket"
                )
            if self.environment.buckets[0].started_at != self.started_at:
                raise ValueError("environment buckets must start at analytics start")
            if self.environment.buckets[-1].ended_at != self.ended_at:
                raise ValueError("environment buckets must end at analytics end")
            for previous, current in zip(
                self.environment.buckets, self.environment.buckets[1:]
            ):
                if previous.ended_at != current.started_at:
                    raise ValueError("environment buckets must be contiguous")
                if current.ended_at - current.started_at != expected_interval:
                    raise ValueError(
                        "environment buckets must have the selected interval"
                    )
            first = self.environment.buckets[0]
            if first.ended_at - first.started_at != expected_interval:
                raise ValueError(
                    "environment buckets must have the selected interval"
                )
        return self


class DashboardSystemV1(DashboardModel):
    schema_version: Literal[1]
    generated_at: datetime
    components: tuple[DashboardComponentV1, ...] = Field(max_length=8)

    _aware_generated_at = field_validator("generated_at")(require_aware)

    @model_validator(mode="after")
    def require_unique_component_ids(self) -> Self:
        _require_unique_ids(self.components, "component_id")
        return self


def _require_unique_ids(items: tuple[object, ...], attribute: str) -> None:
    identifiers = tuple(getattr(item, attribute) for item in items)
    if len(identifiers) != len(set(identifiers)):
        raise ValueError(f"{attribute} values must be unique")


def _require_rate(
    actual: float | None, numerator: int, denominator: int, name: str
) -> None:
    expected = numerator / denominator if denominator else None
    if actual != expected:
        raise ValueError(f"{name} must match its counts")


def _require_measurement_triple(
    minimum: float | None,
    median: float | None,
    maximum: float | None,
    available_count: int,
    name: str,
) -> None:
    values = (minimum, median, maximum)
    if available_count == 0:
        if any(value is not None for value in values):
            raise ValueError(f"{name} values require available samples")
    elif any(value is None for value in values) or not minimum <= median <= maximum:
        raise ValueError(f"{name} values must be complete and ordered")
