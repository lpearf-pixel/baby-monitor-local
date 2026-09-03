from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from packages.contracts.events import (
    EnvironmentReading,
    EnvironmentSourceKind,
    ReadingFailureReason,
)
from services.dashboard.contracts import (
    DashboardAlertV1,
    DashboardComponentV1,
    DashboardEnvironmentIncidentCountsV1,
    DashboardEvidenceCountsV1,
    DashboardGuardianAnalyticsV1,
    DashboardNotificationCountsV1,
    DashboardRiskCountsV1,
    DashboardWindow,
)
from services.dashboard.service import LocalDashboardService
from services.events.environment_state import EnvironmentIncident, EnvironmentSnapshot
from services.storage.environment import (
    EnvironmentIncidentCounts,
    EnvironmentTrend,
    EnvironmentTrendBucket,
    TrendWindow,
)


NOW = datetime(2026, 8, 5, 12, 0, tzinfo=UTC)


def reading(
    reading_id: str,
    captured_at: datetime,
    *,
    temperature_c: float = 22.0,
    humidity_rh: float = 48.0,
) -> EnvironmentReading:
    return EnvironmentReading.available(
        reading_id=reading_id,
        source_kind=EnvironmentSourceKind.WS2021_GAUGE,
        captured_at=captured_at,
        temperature_c=temperature_c,
        humidity_rh=humidity_rh,
        confidence=0.9,
        calibration_version="calibration-1",
        sample_count=5,
        valid_temperature_samples=5,
        valid_humidity_samples=5,
    )


def incident(
    incident_id: str,
    *,
    kind: str = "range",
    state: str = "open",
    severity: str = "normal",
    opened_at: datetime = NOW - timedelta(minutes=10),
    updated_at: datetime = NOW - timedelta(minutes=5),
    reasons: tuple[str, ...] = ("temperature_high",),
) -> EnvironmentIncident:
    recovered_at = updated_at if state == "recovered" else None
    return EnvironmentIncident(
        incident_id=incident_id,
        kind=kind,
        state=state,
        severity=severity,
        opened_at=opened_at,
        updated_at=updated_at,
        recovered_at=recovered_at,
        reasons=reasons,
        data_available=(kind == "range" or state == "recovered"),
    )


def available_snapshot(
    *,
    open_incidents: tuple[EnvironmentIncident, ...] = (),
) -> EnvironmentSnapshot:
    current = reading("current", NOW - timedelta(seconds=30))
    return EnvironmentSnapshot(
        generated_at=NOW,
        policy_version="environment-v1",
        current_reading=current,
        current_available=True,
        temperature_c=current.temperature_c,
        humidity_rh=current.humidity_rh,
        last_valid_reading=current,
        open_incidents=open_incidents,
    )


def unavailable_snapshot(
    *,
    reason: ReadingFailureReason = ReadingFailureReason.TOO_DARK,
    open_incidents: tuple[EnvironmentIncident, ...] = (),
) -> EnvironmentSnapshot:
    current = EnvironmentReading.unavailable(
        reading_id="unavailable",
        source_kind=EnvironmentSourceKind.WS2021_GAUGE,
        captured_at=NOW - timedelta(seconds=30),
        failure_reason=reason,
        calibration_version="calibration-1",
        sample_count=5,
    )
    last_valid = reading("last-valid", NOW - timedelta(hours=1))
    return EnvironmentSnapshot(
        generated_at=NOW,
        policy_version="environment-v1",
        current_reading=current,
        current_available=False,
        temperature_c=None,
        humidity_rh=None,
        last_valid_reading=last_valid,
        open_incidents=open_incidents,
    )


def stale_snapshot() -> EnvironmentSnapshot:
    current = reading("stale", NOW - timedelta(minutes=5))
    return EnvironmentSnapshot(
        generated_at=NOW,
        policy_version="environment-v1",
        current_reading=current,
        current_available=False,
        temperature_c=None,
        humidity_rh=None,
        last_valid_reading=current,
        open_incidents=(),
    )


def empty_snapshot() -> EnvironmentSnapshot:
    return EnvironmentSnapshot(
        generated_at=NOW,
        policy_version="environment-v1",
        current_reading=None,
        current_available=False,
        temperature_c=None,
        humidity_rh=None,
        last_valid_reading=None,
        open_incidents=(),
    )


def guardian_alert(
    alert_id: str = "guardian:event-open",
    *,
    priority: str = "critical",
    state: str = "open",
    opened_at: datetime = NOW - timedelta(minutes=15),
    updated_at: datetime = NOW - timedelta(minutes=1),
) -> DashboardAlertV1:
    recovered_at = updated_at if state == "recovered" else None
    return DashboardAlertV1(
        alert_id=alert_id,
        source="guardian",
        kind="face_not_visible",
        state=state,
        priority=priority,
        opened_at=opened_at,
        updated_at=updated_at,
        recovered_at=recovered_at,
        reason_codes=("occluded",),
    )


def guardian_analytics() -> DashboardGuardianAnalyticsV1:
    return DashboardGuardianAnalyticsV1(
        state="available",
        confirmed_count=3,
        recovered_count=2,
        intervention_count=1,
        recovery_median_seconds=30,
        risk_counts=DashboardRiskCountsV1(
            face_not_visible=2,
            prone_candidate=1,
            outside_candidate=0,
        ),
        evidence_counts=DashboardEvidenceCountsV1(
            collecting=0,
            ready=2,
            failed=0,
            interrupted=0,
            retained_total=2,
            missing=1,
            ready_rate=1,
        ),
        notification_counts=DashboardNotificationCountsV1(
            pending=0,
            delivered=2,
            rejected=0,
            terminal_total=2,
            success_rate=1,
        ),
    )


def trend(window: TrendWindow, *, zero_samples: bool = False) -> EnvironmentTrend:
    duration = timedelta(hours=24) if window is TrendWindow.HOURS_24 else timedelta(days=7)
    interval = timedelta(minutes=5) if window is TrendWindow.HOURS_24 else timedelta(hours=1)
    count = 288 if window is TrendWindow.HOURS_24 else 168
    started_at = NOW - duration
    buckets: list[EnvironmentTrendBucket] = []
    for index in range(count):
        bucket_start = started_at + interval * index
        populated = index == 0 and not zero_samples
        buckets.append(
            EnvironmentTrendBucket(
                started_at=bucket_start,
                ended_at=bucket_start + interval,
                sample_count=10 if populated else 0,
                available_count=7 if populated else 0,
                availability_rate=0.7 if populated else 0,
                temperature_min=20 if populated else None,
                temperature_median=22 if populated else None,
                temperature_max=24 if populated else None,
                humidity_min=40 if populated else None,
                humidity_median=45 if populated else None,
                humidity_max=50 if populated else None,
            )
        )
    return EnvironmentTrend(
        window=window,
        bucket_seconds=int(interval.total_seconds()),
        started_at=started_at,
        ended_at=NOW,
        buckets=tuple(buckets),
    )


class FakeCamera:
    def __init__(self, payload: dict[str, object]) -> None:
        self.payload = payload

    def status(self) -> dict[str, object]:
        return self.payload


class FakeGuardian:
    def __init__(
        self,
        *,
        alerts: tuple[DashboardAlertV1, ...] = (),
        recoveries: tuple[datetime, ...] = (),
        analytics_result: DashboardGuardianAnalyticsV1 | None = None,
        notification: DashboardComponentV1 | None = None,
        fail_alerts: bool = False,
        fail_recovered: bool = False,
        fail_analytics: bool = False,
    ) -> None:
        self._alerts = alerts
        self._recoveries = recoveries
        self._analytics = analytics_result or guardian_analytics()
        self._notification = notification
        self._fail_alerts = fail_alerts
        self._fail_recovered = fail_recovered
        self._fail_analytics = fail_analytics
        self.recovered_boundaries: list[tuple[datetime, datetime]] = []

    def alerts(self) -> tuple[DashboardAlertV1, ...]:
        if self._fail_alerts:
            raise RuntimeError("sqlite private failure")
        return self._alerts

    def recovered_count(self, started_at: datetime, ended_at: datetime) -> int:
        if self._fail_recovered:
            raise RuntimeError("sqlite recovered count failure")
        self.recovered_boundaries.append((started_at, ended_at))
        return sum(started_at <= item < ended_at for item in self._recoveries)

    def analytics(
        self,
        window: DashboardWindow,
        now: datetime,
    ) -> DashboardGuardianAnalyticsV1:
        if self._fail_analytics:
            raise RuntimeError("sqlite analytics failure")
        return self._analytics

    def notification_component(self, now: datetime) -> DashboardComponentV1:
        if self._notification is not None:
            return self._notification
        return DashboardComponentV1(
            component_id="notification_queue",
            state="healthy",
            reason_code="notification_queue_empty",
            updated_at=now,
        )


class FakeEnvironment:
    def __init__(
        self,
        *,
        snapshot: EnvironmentSnapshot | None = None,
        incidents: tuple[EnvironmentIncident, ...] = (),
        trend_result: EnvironmentTrend | None = None,
        counts: EnvironmentIncidentCounts | None = None,
        calibration_state: str = "available",
        fail_current: bool = False,
        fail_trend: bool = False,
    ) -> None:
        self._snapshot = snapshot or available_snapshot()
        self._incidents = incidents
        self._trend = trend_result or trend(TrendWindow.HOURS_24)
        self._counts = counts or EnvironmentIncidentCounts(
            range_normal=4,
            range_critical=2,
            unreadable=1,
        )
        self._calibration_state = calibration_state
        self._fail_current = fail_current
        self._fail_trend = fail_trend
        self.count_boundaries: list[tuple[datetime, datetime]] = []

    def current(self, now: datetime) -> EnvironmentSnapshot:
        if self._fail_current:
            raise RuntimeError("sqlite environment failure")
        return self._snapshot

    def trend(self, window: TrendWindow, now: datetime) -> EnvironmentTrend:
        if self._fail_trend:
            raise RuntimeError("sqlite trend failure")
        return self._trend

    def incidents(self) -> tuple[EnvironmentIncident, ...]:
        if self._fail_current:
            raise RuntimeError("sqlite incidents failure")
        return self._incidents

    def incident_counts(
        self,
        *,
        started_at: datetime,
        ended_at: datetime,
    ) -> EnvironmentIncidentCounts:
        if self._fail_trend:
            raise RuntimeError("sqlite count failure")
        self.count_boundaries.append((started_at, ended_at))
        return self._counts

    def calibration_status(self) -> dict[str, object]:
        return {
            "state": self._calibration_state,
            "calibration_id": "must-not-leak-calibration",
            "path": "must-not-leak-path",
        }


def dashboard(
    *,
    camera: FakeCamera | None = None,
    guardian: FakeGuardian | None = None,
    environment: FakeEnvironment | None = None,
    camera_reply_enabled: bool = False,
) -> LocalDashboardService:
    return LocalDashboardService(
        camera=camera or FakeCamera({"camera": "online"}),
        guardian=guardian if guardian is not None else FakeGuardian(),
        environment=environment if environment is not None else FakeEnvironment(),
        camera_reply_enabled=camera_reply_enabled,
        timezone_name="Asia/Shanghai",
    )


def test_overview_keeps_unavailable_current_separate_and_selects_critical_attention() -> None:
    service = dashboard(
        camera=FakeCamera({"camera": "online", "detail": "must-not-leak-value"}),
        guardian=FakeGuardian(alerts=(guardian_alert(),)),
        environment=FakeEnvironment(snapshot=unavailable_snapshot()),
    )

    result = service.overview(NOW)

    assert result.attention is not None
    assert result.attention.alert.alert_id == "guardian:event-open"
    assert result.environment.state == "unavailable"
    assert result.environment.temperature_c is None
    assert result.environment.last_valid_temperature_c == 22.0
    assert "must-not-leak" not in str(result.model_dump())
    assert not any(item.alert_id == "system:camera_reply" for item in result.recent_activity)


def test_guardian_failure_preserves_environment_and_emits_stable_system_warning() -> None:
    room_alert = incident("room-hot")
    service = dashboard(
        guardian=FakeGuardian(fail_alerts=True),
        environment=FakeEnvironment(
            snapshot=available_snapshot(open_incidents=(room_alert,)),
            incidents=(room_alert,),
        ),
    )

    alerts = service.alerts(NOW)
    overview = service.overview(NOW)

    assert any(item.kind == "guardian_query_status" for item in alerts.alerts)
    assert any(item.source == "environment" for item in alerts.alerts)
    assert overview.guardian_open_count is None
    assert overview.today_recovered_count is None
    assert "sqlite" not in str(alerts.model_dump()).lower()
    assert "RuntimeError" not in str(alerts.model_dump())


def test_successful_empty_guardian_query_reports_known_zero_counts() -> None:
    result = dashboard(guardian=FakeGuardian()).overview(NOW)

    assert result.guardian_open_count == 0
    assert result.today_recovered_count == 0


def test_recovered_count_failure_marks_guardian_unavailable_without_losing_alerts() -> None:
    result = dashboard(
        guardian=FakeGuardian(
            alerts=(guardian_alert(),),
            fail_recovered=True,
        )
    ).overview(NOW)

    guardian_component = next(
        item for item in result.components if item.component_id == "guardian_query"
    )
    assert guardian_component.state == "unavailable"
    assert result.guardian_open_count is None
    assert result.today_recovered_count is None
    assert any(item.alert_id == "guardian:event-open" for item in result.recent_activity)
    assert any(
        item.alert_id == "system:guardian_query" for item in result.recent_activity
    )


def test_environment_failure_preserves_guardian_alert() -> None:
    result = dashboard(
        guardian=FakeGuardian(alerts=(guardian_alert(),)),
        environment=FakeEnvironment(fail_current=True),
    ).alerts(NOW)

    assert any(item.alert_id == "guardian:event-open" for item in result.alerts)
    assert any(item.alert_id == "system:environment" for item in result.alerts)
    assert "sqlite" not in str(result.model_dump()).lower()


@pytest.mark.parametrize(
    ("snapshot", "reason"),
    [
        (stale_snapshot(), "no_new_reading"),
        (empty_snapshot(), "environment_no_reading"),
    ],
)
def test_unavailable_current_distinguishes_stale_from_absent(
    snapshot: EnvironmentSnapshot,
    reason: str,
) -> None:
    result = dashboard(
        environment=FakeEnvironment(snapshot=snapshot)
    ).overview(NOW)

    assert result.environment.state == "unavailable"
    assert result.environment.failure_reason == reason
    assert result.environment.temperature_c is None
    environment_component = next(
        item for item in result.components if item.component_id == "environment"
    )
    assert environment_component.reason_code == reason


def test_open_critical_environment_precedes_warning_system_alert() -> None:
    critical = incident("critical-room", severity="critical")
    result = dashboard(
        guardian=FakeGuardian(fail_alerts=True),
        environment=FakeEnvironment(
            snapshot=available_snapshot(open_incidents=(critical,)),
            incidents=(critical,),
        ),
    ).alerts(NOW)

    assert [item.alert_id for item in result.alerts[:2]] == [
        "environment:critical-room",
        "system:guardian_query",
    ]


def test_all_open_items_are_retained_before_bounded_recovered_history() -> None:
    old_open = incident(
        "old-open",
        opened_at=NOW - timedelta(days=20),
        updated_at=NOW - timedelta(days=20),
    )
    recovered = tuple(
        incident(
            f"recovered-{index:03d}",
            state="recovered",
            opened_at=NOW - timedelta(days=10),
            updated_at=NOW - timedelta(seconds=index),
            reasons=(),
        )
        for index in range(101)
    )
    result = dashboard(
        guardian=FakeGuardian(alerts=(guardian_alert(priority="warning"),)),
        environment=FakeEnvironment(
            snapshot=available_snapshot(open_incidents=(old_open,)),
            incidents=recovered,
        ),
    ).alerts(NOW)

    assert len(result.alerts) == 100
    assert result.alerts[0].state == "open"
    assert result.alerts[1].alert_id == "environment:old-open"
    assert all(item.state == "recovered" for item in result.alerts[2:])


def test_overview_counts_and_selects_attention_before_the_display_bound() -> None:
    alerts = tuple(
        guardian_alert(
            f"guardian:{index:03d}",
            opened_at=NOW - timedelta(minutes=index + 1),
            updated_at=NOW - timedelta(seconds=index),
        )
        for index in range(101)
    )

    result = dashboard(guardian=FakeGuardian(alerts=alerts)).overview(NOW)

    assert result.open_alert_count == 101
    assert result.attention is not None
    assert result.attention.alert.alert_id == "guardian:100"
    assert result.attention.additional_open_count == 100
    assert len(result.recent_activity) == 10


def test_components_are_closed_ordered_and_ignore_private_provider_fields() -> None:
    result = dashboard(
        camera=FakeCamera(
            {
                "camera": "offline",
                "detail": "must-not-leak-value",
                "streams": ["must-not-leak-stream"],
            }
        ),
        environment=FakeEnvironment(calibration_state="missing"),
    ).system(NOW)

    assert [item.component_id for item in result.components] == [
        "camera",
        "guardian_query",
        "environment",
        "gauge_calibration",
        "notification_queue",
        "camera_reply",
    ]
    assert result.components[0].model_dump(exclude={"updated_at"}) == {
        "component_id": "camera",
        "state": "unavailable",
        "reason_code": "camera_offline",
    }
    assert result.components[3].reason_code == "calibration_missing"
    assert result.components[-1].state == "disabled"
    assert "must-not-leak" not in str(result.model_dump())


def test_enabled_camera_reply_is_visible_as_unavailable_not_healthy() -> None:
    service = dashboard(camera_reply_enabled=True)
    result = service.system(NOW)

    camera_reply = result.components[-1]
    assert camera_reply.component_id == "camera_reply"
    assert camera_reply.state == "unavailable"
    assert camera_reply.reason_code == "camera_reply_status_unavailable"
    assert not any(
        item.alert_id == "system:camera_reply" for item in service.alerts(NOW).alerts
    )


@pytest.mark.parametrize(
    ("payload", "state", "reason"),
    [
        ({"camera": "online"}, "healthy", "camera_online"),
        ({"camera": "offline"}, "unavailable", "camera_offline"),
        ({"camera": "starting"}, "unavailable", "camera_unavailable"),
        ({"camera": 123}, "unavailable", "camera_unavailable"),
    ],
)
def test_camera_status_uses_only_the_closed_gateway_state(
    payload: dict[str, object], state: str, reason: str
) -> None:
    component = dashboard(camera=FakeCamera(payload)).system(NOW).components[0]

    assert component.state == state
    assert component.reason_code == reason


def test_system_alert_ids_are_stable_across_refreshes() -> None:
    service = dashboard(camera=FakeCamera({"camera": "offline"}))

    first = service.alerts(NOW)
    second = service.alerts(NOW + timedelta(minutes=1))

    first_camera = next(item for item in first.alerts if item.kind == "camera_status")
    second_camera = next(item for item in second.alerts if item.kind == "camera_status")
    assert first_camera.alert_id == second_camera.alert_id == "system:camera"
    assert first_camera.opened_at == first_camera.updated_at == NOW
    assert second_camera.opened_at == second_camera.updated_at == NOW + timedelta(minutes=1)


def test_current_unreadable_incident_omits_duplicate_environment_system_alert() -> None:
    unreadable = incident(
        "unreadable-open",
        kind="unreadable",
        reasons=("too_dark",),
    )
    result = dashboard(
        environment=FakeEnvironment(
            snapshot=unavailable_snapshot(open_incidents=(unreadable,)),
            incidents=(unreadable,),
        )
    ).alerts(NOW)

    assert any(item.alert_id == "environment:unreadable-open" for item in result.alerts)
    assert not any(item.alert_id == "system:environment" for item in result.alerts)


def test_historical_unreadable_does_not_hide_a_distinct_current_failure() -> None:
    old_unreadable = incident(
        "historical-unreadable",
        kind="unreadable",
        reasons=("too_dark",),
    )
    result = dashboard(
        environment=FakeEnvironment(
            snapshot=empty_snapshot(),
            incidents=(old_unreadable,),
        )
    ).alerts(NOW)

    assert any(
        item.alert_id == "environment:historical-unreadable" for item in result.alerts
    )
    assert any(item.alert_id == "system:environment" for item in result.alerts)


def test_attention_uses_priority_then_earliest_open_time_not_list_order() -> None:
    older = guardian_alert(
        "guardian:older",
        opened_at=NOW - timedelta(hours=2),
        updated_at=NOW - timedelta(minutes=1),
    )
    newer = guardian_alert(
        "guardian:newer",
        opened_at=NOW - timedelta(hours=1),
        updated_at=NOW,
    )
    result = dashboard(guardian=FakeGuardian(alerts=(newer, older))).overview(NOW)

    assert result.attention is not None
    assert result.attention.alert.alert_id == "guardian:older"
    assert result.attention.additional_open_count == 1


def test_today_recovered_count_uses_the_natural_shanghai_day() -> None:
    now = datetime(2026, 8, 5, 16, 30, tzinfo=UTC)  # 00:30 on August 6 in Shanghai
    guardian = FakeGuardian(
        recoveries=(
            datetime(2026, 8, 5, 15, 59, tzinfo=UTC),
            datetime(2026, 8, 5, 16, 0, tzinfo=UTC),
        )
    )

    result = dashboard(guardian=guardian).overview(now)

    assert result.today_recovered_count == 1
    assert guardian.recovered_boundaries == [
        (datetime(2026, 8, 5, 16, 0, tzinfo=UTC), now)
    ]
    assert result.generated_at.tzinfo is UTC


def test_guardian_alert_timestamps_are_normalized_to_utc() -> None:
    offset = datetime.fromisoformat("2026-08-05T20:00:00+08:00")
    alert = guardian_alert(opened_at=offset - timedelta(minutes=1), updated_at=offset)

    result = dashboard(guardian=FakeGuardian(alerts=(alert,))).alerts(NOW)

    projected = next(item for item in result.alerts if item.alert_id == alert.alert_id)
    assert projected.opened_at.tzinfo is UTC
    assert projected.updated_at.tzinfo is UTC


def test_analytics_projects_weighted_environment_availability() -> None:
    environment = FakeEnvironment(
        trend_result=trend(TrendWindow.HOURS_24),
        counts=EnvironmentIncidentCounts(
            range_normal=4,
            range_critical=2,
            unreadable=1,
        ),
    )
    result = dashboard(environment=environment).analytics(DashboardWindow.HOURS_24, NOW)

    assert result.environment.sample_count == 10
    assert result.environment.available_count == 7
    assert result.environment.availability_rate == 0.7
    assert result.environment.buckets[1].availability_rate is None
    assert result.environment.buckets[1].temperature_median_c is None
    assert result.environment.incident_counts == DashboardEnvironmentIncidentCountsV1(
        range_normal=4,
        range_critical=2,
        unreadable=1,
    )
    assert result.guardian.confirmed_count == 3
    assert environment.count_boundaries == [(NOW - timedelta(hours=24), NOW)]


def test_zero_sample_analytics_uses_null_bucket_and_aggregate_rates() -> None:
    environment = FakeEnvironment(
        trend_result=trend(TrendWindow.HOURS_24, zero_samples=True)
    )

    result = dashboard(environment=environment).analytics(DashboardWindow.HOURS_24, NOW)

    assert result.environment.availability_rate is None
    assert result.environment.buckets[0].availability_rate is None


def test_seven_day_analytics_has_exact_hourly_buckets() -> None:
    result = dashboard(
        environment=FakeEnvironment(trend_result=trend(TrendWindow.DAYS_7))
    ).analytics(DashboardWindow.DAYS_7, NOW)

    assert len(result.environment.buckets) == 168
    assert result.environment.buckets[0].ended_at - result.environment.buckets[0].started_at == timedelta(hours=1)


def test_environment_analytics_failure_preserves_guardian_section() -> None:
    result = dashboard(
        environment=FakeEnvironment(fail_trend=True)
    ).analytics(DashboardWindow.HOURS_24, NOW)

    assert result.environment.state == "unavailable"
    assert result.environment.sample_count == 0
    assert result.environment.availability_rate is None
    assert result.environment.buckets == ()
    assert result.guardian.state == "available"
    assert "sqlite" not in str(result.model_dump()).lower()


def test_noncontiguous_environment_trend_only_degrades_that_section() -> None:
    valid = trend(TrendWindow.HOURS_24)
    buckets = list(valid.buckets)
    buckets[1] = buckets[1].model_copy(
        update={
            "started_at": buckets[1].started_at + timedelta(minutes=1),
            "ended_at": buckets[1].ended_at + timedelta(minutes=1),
        }
    )
    malformed = valid.model_copy(update={"buckets": tuple(buckets)})

    result = dashboard(
        environment=FakeEnvironment(trend_result=malformed)
    ).analytics(DashboardWindow.HOURS_24, NOW)

    assert result.environment.state == "unavailable"
    assert result.guardian.state == "available"


def test_guardian_analytics_failure_preserves_environment_section() -> None:
    result = dashboard(
        guardian=FakeGuardian(fail_analytics=True)
    ).analytics(DashboardWindow.HOURS_24, NOW)

    assert result.guardian.state == "unavailable"
    assert result.guardian.confirmed_count == 0
    assert result.environment.state == "available"
    assert "sqlite" not in str(result.model_dump()).lower()
