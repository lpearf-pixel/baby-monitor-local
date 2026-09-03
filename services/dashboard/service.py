from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Protocol, get_args
from zoneinfo import ZoneInfo

from pydantic import BaseModel, ValidationError

from packages.contracts.events import ReadingState
from services.dashboard.contracts import (
    DashboardAlertListV1,
    DashboardAlertV1,
    DashboardAnalyticsV1,
    DashboardAttentionV1,
    DashboardComponentV1,
    DashboardEnvironmentAnalyticsV1,
    DashboardEnvironmentCurrentV1,
    DashboardEnvironmentIncidentCountsV1,
    DashboardEvidenceCountsV1,
    DashboardGuardianAnalyticsV1,
    DashboardNotificationCountsV1,
    DashboardOverviewV1,
    DashboardReasonCode,
    DashboardRiskCountsV1,
    DashboardSystemV1,
    DashboardTrendBucketV1,
    DashboardWindow,
)
from services.events.environment_state import EnvironmentIncident, EnvironmentSnapshot
from services.storage.environment import (
    EnvironmentIncidentCounts,
    EnvironmentTrend,
    EnvironmentTrendBucket,
    TrendWindow,
)


PRIORITY_ORDER = {"critical": 0, "warning": 1, "info": 2}
ACCEPTED_REASON_CODES = frozenset(get_args(DashboardReasonCode))
SYSTEM_ALERT_KINDS = {
    "camera": "camera_status",
    "guardian_query": "guardian_query_status",
    "environment": "environment_query_status",
    "gauge_calibration": "calibration_status",
    "notification_queue": "notification_queue_status",
}


class DashboardServiceUnavailable(RuntimeError):
    pass


class CameraStatusProvider(Protocol):
    def status(self) -> dict[str, object]: ...


class EnvironmentDashboardProvider(Protocol):
    def current(self, now: datetime) -> EnvironmentSnapshot: ...

    def trend(self, window: TrendWindow, now: datetime) -> EnvironmentTrend: ...

    def incidents(self) -> tuple[EnvironmentIncident, ...]: ...

    def incident_counts(
        self,
        *,
        started_at: datetime,
        ended_at: datetime,
    ) -> EnvironmentIncidentCounts: ...

    def calibration_status(self) -> dict[str, object]: ...


class GuardianDashboardProvider(Protocol):
    def alerts(self) -> tuple[DashboardAlertV1, ...]: ...

    def recovered_count(self, started_at: datetime, ended_at: datetime) -> int: ...

    def analytics(
        self,
        window: DashboardWindow,
        now: datetime,
    ) -> DashboardGuardianAnalyticsV1: ...

    def notification_component(self, now: datetime) -> DashboardComponentV1: ...


@dataclass(frozen=True)
class _CollectedDashboard:
    components: tuple[DashboardComponentV1, ...]
    alerts: tuple[DashboardAlertV1, ...]
    environment: DashboardEnvironmentCurrentV1
    guardian_alerts: tuple[DashboardAlertV1, ...]
    guardian_available: bool


def order_alerts(items: Iterable[DashboardAlertV1]) -> tuple[DashboardAlertV1, ...]:
    ordered = sorted(items, key=lambda item: item.alert_id, reverse=True)
    ordered.sort(key=lambda item: item.updated_at, reverse=True)
    ordered.sort(key=lambda item: PRIORITY_ORDER[item.priority])
    ordered.sort(key=lambda item: 0 if item.state == "open" else 1)
    return tuple(ordered)


class LocalDashboardService:
    def __init__(
        self,
        *,
        camera: CameraStatusProvider,
        guardian: GuardianDashboardProvider | None,
        environment: EnvironmentDashboardProvider | None,
        camera_reply_enabled: bool,
        timezone_name: str,
    ) -> None:
        self._camera = camera
        self._guardian = guardian
        self._environment = environment
        self._camera_reply_enabled = camera_reply_enabled
        self._timezone = ZoneInfo(timezone_name)

    def overview(self, now: datetime) -> DashboardOverviewV1:
        generated_at = _as_utc(now)
        collected = self._collect(generated_at, include_alerts=True)
        guardian_available = collected.guardian_available
        components = collected.components
        alerts = collected.alerts
        today_recovered_count: int | None = None
        if guardian_available and self._guardian is not None:
            local_now = generated_at.astimezone(self._timezone)
            local_day_start = local_now.replace(
                hour=0,
                minute=0,
                second=0,
                microsecond=0,
            )
            try:
                today_recovered_count = self._guardian.recovered_count(
                    local_day_start.astimezone(UTC),
                    generated_at,
                )
                if today_recovered_count < 0:
                    raise ValueError("recovered count cannot be negative")
            except Exception:
                guardian_available = False
                today_recovered_count = None
                unavailable = _unavailable_guardian_component(generated_at)
                components = tuple(
                    unavailable if item.component_id == "guardian_query" else item
                    for item in components
                )
                warning = _system_alert(unavailable)
                assert warning is not None
                alerts = order_alerts((*alerts, warning))

        open_items = tuple(item for item in alerts if item.state == "open")
        attention = _attention(open_items)
        try:
            return DashboardOverviewV1(
                schema_version=1,
                generated_at=generated_at,
                attention=attention,
                open_alert_count=len(open_items),
                guardian_open_count=(
                    sum(item.state == "open" for item in collected.guardian_alerts)
                    if guardian_available
                    else None
                ),
                today_recovered_count=today_recovered_count,
                environment=collected.environment,
                components=components,
                recent_activity=alerts[:10],
            )
        except (TypeError, ValueError, ValidationError) as exc:
            raise DashboardServiceUnavailable("dashboard_response_unavailable") from exc

    def alerts(self, now: datetime) -> DashboardAlertListV1:
        generated_at = _as_utc(now)
        collected = self._collect(generated_at, include_alerts=True)
        try:
            return DashboardAlertListV1(
                schema_version=1,
                generated_at=generated_at,
                alerts=_bounded_alerts(collected.alerts),
            )
        except (TypeError, ValueError, ValidationError) as exc:
            raise DashboardServiceUnavailable("dashboard_response_unavailable") from exc

    def analytics(
        self,
        window: DashboardWindow,
        now: datetime,
    ) -> DashboardAnalyticsV1:
        generated_at = _as_utc(now)
        if not isinstance(window, DashboardWindow):
            raise DashboardServiceUnavailable("dashboard_response_unavailable")
        duration = (
            timedelta(hours=24)
            if window is DashboardWindow.HOURS_24
            else timedelta(days=7)
        )
        started_at = generated_at - duration
        environment = self._environment_analytics(
            window,
            started_at=started_at,
            ended_at=generated_at,
        )
        guardian = self._guardian_analytics(window, generated_at)
        try:
            return DashboardAnalyticsV1(
                schema_version=1,
                generated_at=generated_at,
                window=window,
                started_at=started_at,
                ended_at=generated_at,
                environment=environment,
                guardian=guardian,
            )
        except (TypeError, ValueError, ValidationError) as exc:
            raise DashboardServiceUnavailable("dashboard_response_unavailable") from exc

    def system(self, now: datetime) -> DashboardSystemV1:
        generated_at = _as_utc(now)
        collected = self._collect(generated_at, include_alerts=False)
        try:
            return DashboardSystemV1(
                schema_version=1,
                generated_at=generated_at,
                components=collected.components,
            )
        except (TypeError, ValueError, ValidationError) as exc:
            raise DashboardServiceUnavailable("dashboard_response_unavailable") from exc

    def _collect(self, now: datetime, *, include_alerts: bool) -> _CollectedDashboard:
        camera_component = self._camera_component(now)
        guardian_alerts, guardian_component, guardian_available = (
            self._guardian_projection(now)
        )
        snapshot, environment_current, environment_component = (
            self._environment_projection(now)
        )
        environment_alerts: tuple[DashboardAlertV1, ...] = ()
        if include_alerts:
            environment_alerts, incident_query_available = (
                self._environment_alert_projection(snapshot)
            )
            if not incident_query_available:
                environment_component = DashboardComponentV1(
                    component_id="environment",
                    state="unavailable",
                    reason_code="environment_unavailable",
                    updated_at=now,
                )
        calibration_component = self._calibration_component(now)
        notification_component = self._notification_component(now)
        camera_reply_component = self._camera_reply_component(now)
        components = (
            camera_component,
            guardian_component,
            environment_component,
            calibration_component,
            notification_component,
            camera_reply_component,
        )

        alerts: tuple[DashboardAlertV1, ...] = ()
        if include_alerts:
            system_alerts = tuple(
                alert
                for component in components
                if (alert := _system_alert(component)) is not None
            )
            if incident_query_available and snapshot is not None and any(
                item.state == "open" and item.kind == "unreadable"
                for item in snapshot.open_incidents
            ):
                system_alerts = tuple(
                    item
                    for item in system_alerts
                    if item.alert_id != "system:environment"
                )
            alerts = order_alerts(
                (*guardian_alerts, *environment_alerts, *system_alerts)
            )
        return _CollectedDashboard(
            components=components,
            alerts=alerts,
            environment=environment_current,
            guardian_alerts=guardian_alerts,
            guardian_available=guardian_available,
        )

    def _camera_component(self, now: datetime) -> DashboardComponentV1:
        try:
            state = self._camera.status().get("camera")
        except Exception:
            state = None
        if state == "online":
            component_state = "healthy"
            reason = "camera_online"
        elif state == "offline":
            component_state = "unavailable"
            reason = "camera_offline"
        else:
            component_state = "unavailable"
            reason = "camera_unavailable"
        return DashboardComponentV1(
            component_id="camera",
            state=component_state,
            reason_code=reason,
            updated_at=now,
        )

    def _guardian_projection(
        self,
        now: datetime,
    ) -> tuple[tuple[DashboardAlertV1, ...], DashboardComponentV1, bool]:
        if self._guardian is None:
            return (), _unavailable_guardian_component(now), False
        try:
            alerts = tuple(
                _guardian_alert(item) for item in self._guardian.alerts()
            )
        except Exception:
            return (), _unavailable_guardian_component(now), False
        return (
            alerts,
            DashboardComponentV1(
                component_id="guardian_query",
                state="healthy",
                reason_code="guardian_query_available",
                updated_at=now,
            ),
            True,
        )

    def _environment_projection(
        self,
        now: datetime,
    ) -> tuple[
        EnvironmentSnapshot | None,
        DashboardEnvironmentCurrentV1,
        DashboardComponentV1,
    ]:
        if self._environment is None:
            return _unavailable_environment(now)
        try:
            snapshot = EnvironmentSnapshot.model_validate(
                _provider_payload(self._environment.current(now))
            )
            current = _environment_current(snapshot)
            component = DashboardComponentV1(
                component_id="environment",
                state=("healthy" if current.state == "available" else "unavailable"),
                reason_code=(
                    "environment_available"
                    if current.state == "available"
                    else current.failure_reason or "reading_unavailable"
                ),
                updated_at=now,
            )
            return snapshot, current, component
        except Exception:
            return _unavailable_environment(now)

    def _environment_alert_projection(
        self,
        snapshot: EnvironmentSnapshot | None,
    ) -> tuple[tuple[DashboardAlertV1, ...], bool]:
        incidents_by_id: dict[str, EnvironmentIncident] = {}
        query_available = self._environment is not None
        if self._environment is not None:
            try:
                incidents_by_id.update(
                    (
                        item.incident_id,
                        EnvironmentIncident.model_validate(_provider_payload(item)),
                    )
                    for item in self._environment.incidents()
                )
            except Exception:
                query_available = False
        if snapshot is not None:
            incidents_by_id.update(
                (item.incident_id, item) for item in snapshot.open_incidents
            )
        alerts: list[DashboardAlertV1] = []
        for item in incidents_by_id.values():
            try:
                alerts.append(_environment_alert(item))
            except (TypeError, ValueError, ValidationError):
                query_available = False
        return tuple(alerts), query_available

    def _calibration_component(self, now: datetime) -> DashboardComponentV1:
        try:
            state = (
                self._environment.calibration_status().get("state")
                if self._environment is not None
                else None
            )
        except Exception:
            state = None
        if state == "available":
            component_state = "healthy"
            reason = "calibration_available"
        elif state == "missing":
            component_state = "degraded"
            reason = "calibration_missing"
        else:
            component_state = "unavailable"
            reason = "calibration_invalid"
        return DashboardComponentV1(
            component_id="gauge_calibration",
            state=component_state,
            reason_code=reason,
            updated_at=now,
        )

    def _notification_component(self, now: datetime) -> DashboardComponentV1:
        if self._guardian is not None:
            try:
                upstream = DashboardComponentV1.model_validate(
                    _provider_payload(self._guardian.notification_component(now))
                )
                if (
                    upstream.component_id == "notification_queue"
                    and upstream.state == "degraded"
                    and upstream.reason_code == "notification_queue_pending"
                ):
                    return DashboardComponentV1(
                        component_id="notification_queue",
                        state="degraded",
                        reason_code="notification_queue_pending",
                        updated_at=upstream.updated_at.astimezone(UTC),
                    )
                if (
                    upstream.component_id == "notification_queue"
                    and upstream.state == "healthy"
                    and upstream.reason_code == "notification_queue_empty"
                ):
                    return DashboardComponentV1(
                        component_id="notification_queue",
                        state="healthy",
                        reason_code="notification_queue_empty",
                        updated_at=upstream.updated_at.astimezone(UTC),
                    )
            except Exception:
                pass
        return DashboardComponentV1(
            component_id="notification_queue",
            state="unavailable",
            reason_code="notification_query_unavailable",
            updated_at=now,
        )

    def _camera_reply_component(self, now: datetime) -> DashboardComponentV1:
        if self._camera_reply_enabled:
            return DashboardComponentV1(
                component_id="camera_reply",
                state="unavailable",
                reason_code="camera_reply_status_unavailable",
                updated_at=now,
            )
        return DashboardComponentV1(
            component_id="camera_reply",
            state="disabled",
            reason_code="camera_reply_disabled",
            updated_at=now,
        )

    def _environment_analytics(
        self,
        window: DashboardWindow,
        *,
        started_at: datetime,
        ended_at: datetime,
    ) -> DashboardEnvironmentAnalyticsV1:
        if self._environment is None:
            return _unavailable_environment_analytics()
        trend_window = (
            TrendWindow.HOURS_24
            if window is DashboardWindow.HOURS_24
            else TrendWindow.DAYS_7
        )
        try:
            trend = EnvironmentTrend.model_validate(
                _provider_payload(self._environment.trend(trend_window, ended_at))
            )
            counts = EnvironmentIncidentCounts.model_validate(
                _provider_payload(
                    self._environment.incident_counts(
                        started_at=started_at,
                        ended_at=ended_at,
                    )
                )
            )
            _require_expected_trend(
                trend,
                trend_window,
                started_at=started_at,
                ended_at=ended_at,
            )
            buckets = tuple(_trend_bucket(item) for item in trend.buckets)
            sample_count = sum(item.sample_count for item in buckets)
            available_count = sum(item.available_count for item in buckets)
            return DashboardEnvironmentAnalyticsV1(
                state="available",
                sample_count=sample_count,
                available_count=available_count,
                availability_rate=(
                    available_count / sample_count if sample_count else None
                ),
                incident_counts=DashboardEnvironmentIncidentCountsV1(
                    range_normal=counts.range_normal,
                    range_critical=counts.range_critical,
                    unreadable=counts.unreadable,
                ),
                buckets=buckets,
            )
        except Exception:
            return _unavailable_environment_analytics()

    def _guardian_analytics(
        self,
        window: DashboardWindow,
        now: datetime,
    ) -> DashboardGuardianAnalyticsV1:
        if self._guardian is None:
            return _unavailable_guardian_analytics()
        try:
            return DashboardGuardianAnalyticsV1.model_validate(
                _provider_payload(self._guardian.analytics(window, now))
            )
        except Exception:
            return _unavailable_guardian_analytics()


def _as_utc(now: datetime) -> datetime:
    if now.tzinfo is None or now.utcoffset() is None:
        raise DashboardServiceUnavailable("dashboard_response_unavailable")
    return now.astimezone(UTC)


def _environment_current(
    snapshot: EnvironmentSnapshot,
) -> DashboardEnvironmentCurrentV1:
    current = snapshot.current_reading
    last_valid = snapshot.last_valid_reading
    last_valid_values: dict[str, object] = {}
    if (
        last_valid is not None
        and last_valid.temperature_c is not None
        and last_valid.humidity_rh is not None
    ):
        last_valid_values = {
            "last_valid_temperature_c": last_valid.temperature_c,
            "last_valid_humidity_rh": last_valid.humidity_rh,
            "last_valid_captured_at": last_valid.captured_at.astimezone(UTC),
        }
    if (
        snapshot.current_available
        and current is not None
        and snapshot.temperature_c is not None
        and snapshot.humidity_rh is not None
    ):
        return DashboardEnvironmentCurrentV1(
            state="available",
            temperature_c=snapshot.temperature_c,
            humidity_rh=snapshot.humidity_rh,
            captured_at=current.captured_at.astimezone(UTC),
            fresh_until=current.fresh_until.astimezone(UTC),
            **last_valid_values,
        )
    if current is None:
        reason = "environment_no_reading"
    elif current.state is ReadingState.AVAILABLE:
        reason = "no_new_reading"
    else:
        raw_reason = getattr(current.failure_reason, "value", current.failure_reason)
        upstream_reason = (
            raw_reason
            if isinstance(raw_reason, str) and raw_reason in ACCEPTED_REASON_CODES
            else None
        )
        reason = upstream_reason or "reading_unavailable"
    return DashboardEnvironmentCurrentV1(
        state="unavailable",
        captured_at=(
            current.captured_at.astimezone(UTC) if current is not None else None
        ),
        fresh_until=(
            current.fresh_until.astimezone(UTC) if current is not None else None
        ),
        failure_reason=reason,
        **last_valid_values,
    )


def _unavailable_environment(
    now: datetime,
) -> tuple[None, DashboardEnvironmentCurrentV1, DashboardComponentV1]:
    return (
        None,
        DashboardEnvironmentCurrentV1(
            state="unavailable",
            failure_reason="environment_unavailable",
        ),
        DashboardComponentV1(
            component_id="environment",
            state="unavailable",
            reason_code="environment_unavailable",
            updated_at=now,
        ),
    )


def _unavailable_guardian_component(now: datetime) -> DashboardComponentV1:
    return DashboardComponentV1(
        component_id="guardian_query",
        state="unavailable",
        reason_code="guardian_query_unavailable",
        updated_at=now,
    )


def _environment_alert(item: EnvironmentIncident) -> DashboardAlertV1:
    return DashboardAlertV1(
        alert_id=f"environment:{item.incident_id}",
        source="environment",
        kind=(
            "environment_range" if item.kind == "range" else "environment_unreadable"
        ),
        state=item.state,
        priority=(
            "info"
            if item.state == "recovered"
            else "critical"
            if item.kind == "range" and item.severity == "critical"
            else "warning"
        ),
        opened_at=item.opened_at.astimezone(UTC),
        updated_at=item.updated_at.astimezone(UTC),
        recovered_at=(
            item.recovered_at.astimezone(UTC)
            if item.recovered_at is not None
            else None
        ),
        reason_codes=tuple(
            reason for reason in item.reasons if reason in ACCEPTED_REASON_CODES
        )[:8],
        resolution_cause=None,
    )


def _guardian_alert(item: object) -> DashboardAlertV1:
    payload = _provider_payload(item)
    if isinstance(payload, dict):
        payload = dict(payload)
        for field in ("opened_at", "updated_at", "recovered_at"):
            value = payload.get(field)
            if (
                isinstance(value, datetime)
                and value.tzinfo is not None
                and value.utcoffset() is not None
            ):
                payload[field] = value.astimezone(UTC)
    return DashboardAlertV1.model_validate(payload)


def _provider_payload(item: object) -> object:
    if isinstance(item, BaseModel):
        return item.model_dump(mode="python")
    return item


def _system_alert(component: DashboardComponentV1) -> DashboardAlertV1 | None:
    kind = SYSTEM_ALERT_KINDS.get(component.component_id)
    if kind is None or component.state not in {"degraded", "unavailable"}:
        return None
    return DashboardAlertV1(
        alert_id=f"system:{component.component_id}",
        source="system",
        kind=kind,
        state="open",
        priority="warning",
        opened_at=component.updated_at,
        updated_at=component.updated_at,
        reason_codes=(component.reason_code,),
    )


def _bounded_alerts(items: Iterable[DashboardAlertV1]) -> tuple[DashboardAlertV1, ...]:
    ordered = order_alerts(items)
    open_items = tuple(item for item in ordered if item.state == "open")
    recovered_items = tuple(item for item in ordered if item.state == "recovered")
    if len(open_items) >= 100:
        return open_items[:100]
    return (*open_items, *recovered_items[: 100 - len(open_items)])


def _attention(open_items: tuple[DashboardAlertV1, ...]) -> DashboardAttentionV1 | None:
    if not open_items:
        return None
    ordered = sorted(open_items, key=lambda item: item.alert_id, reverse=True)
    ordered.sort(key=lambda item: item.opened_at)
    ordered.sort(key=lambda item: PRIORITY_ORDER[item.priority])
    return DashboardAttentionV1(
        alert=ordered[0],
        additional_open_count=len(open_items) - 1,
    )


def _trend_bucket(bucket: EnvironmentTrendBucket) -> DashboardTrendBucketV1:
    return DashboardTrendBucketV1(
        started_at=bucket.started_at.astimezone(UTC),
        ended_at=bucket.ended_at.astimezone(UTC),
        sample_count=bucket.sample_count,
        available_count=bucket.available_count,
        availability_rate=(
            bucket.available_count / bucket.sample_count
            if bucket.sample_count
            else None
        ),
        temperature_min_c=bucket.temperature_min,
        temperature_median_c=bucket.temperature_median,
        temperature_max_c=bucket.temperature_max,
        humidity_min_rh=bucket.humidity_min,
        humidity_median_rh=bucket.humidity_median,
        humidity_max_rh=bucket.humidity_max,
    )


def _require_expected_trend(
    trend: EnvironmentTrend,
    window: TrendWindow,
    *,
    started_at: datetime,
    ended_at: datetime,
) -> None:
    expected_count = 288 if window is TrendWindow.HOURS_24 else 168
    expected_interval = (
        timedelta(minutes=5)
        if window is TrendWindow.HOURS_24
        else timedelta(hours=1)
    )
    if (
        trend.window is not window
        or trend.started_at.astimezone(UTC) != started_at
        or trend.ended_at.astimezone(UTC) != ended_at
        or len(trend.buckets) != expected_count
        or any(
            item.ended_at - item.started_at != expected_interval
            for item in trend.buckets
        )
        or trend.buckets[0].started_at.astimezone(UTC) != started_at
        or trend.buckets[-1].ended_at.astimezone(UTC) != ended_at
        or any(
            previous.ended_at != current.started_at
            for previous, current in zip(trend.buckets, trend.buckets[1:])
        )
    ):
        raise ValueError("environment trend does not match requested window")


def _unavailable_environment_analytics() -> DashboardEnvironmentAnalyticsV1:
    return DashboardEnvironmentAnalyticsV1(
        state="unavailable",
        sample_count=0,
        available_count=0,
        availability_rate=None,
        incident_counts=DashboardEnvironmentIncidentCountsV1(
            range_normal=0,
            range_critical=0,
            unreadable=0,
        ),
        buckets=(),
    )


def _unavailable_guardian_analytics() -> DashboardGuardianAnalyticsV1:
    return DashboardGuardianAnalyticsV1(
        state="unavailable",
        confirmed_count=0,
        recovered_count=0,
        intervention_count=0,
        recovery_median_seconds=None,
        risk_counts=DashboardRiskCountsV1(
            face_not_visible=0,
            prone_candidate=0,
            outside_candidate=0,
        ),
        evidence_counts=DashboardEvidenceCountsV1(
            collecting=0,
            ready=0,
            failed=0,
            interrupted=0,
            retained_total=0,
            missing=0,
            ready_rate=None,
        ),
        notification_counts=DashboardNotificationCountsV1(
            pending=0,
            delivered=0,
            rejected=0,
            terminal_total=0,
            success_rate=None,
        ),
    )
