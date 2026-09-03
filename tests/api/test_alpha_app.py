from __future__ import annotations

import base64
from datetime import UTC, datetime, timedelta
from html.parser import HTMLParser
import re
from dataclasses import dataclass, field
from typing import Iterator

from fastapi.testclient import TestClient
import pytest
from starlette.websockets import WebSocketDisconnect

import apps.api.alpha as alpha_module
from apps.api.alpha import AlphaRuntime, SnapshotViewport, create_app
from apps.api.hd_stream import HdBusyError, HdProfile, HdTicket
from apps.api.ptz import PtzCode, PtzDirection, StepPtzController
from packages.contracts.events import (
    EnvironmentReading,
    EnvironmentSourceKind,
    ReadingFailureReason,
)
from services.dashboard.contracts import (
    DashboardAlertListV1,
    DashboardAnalyticsV1,
    DashboardEnvironmentAnalyticsV1,
    DashboardEnvironmentCurrentV1,
    DashboardEnvironmentIncidentCountsV1,
    DashboardEvidenceCountsV1,
    DashboardGuardianAnalyticsV1,
    DashboardNotificationCountsV1,
    DashboardOverviewV1,
    DashboardRiskCountsV1,
    DashboardSystemV1,
    DashboardWindow,
)
from services.dashboard.service import DashboardServiceUnavailable
from services.events.environment_state import EnvironmentSnapshot
from services.events.guardian_query import (
    GuardianEventList,
    GuardianEventQueryUnavailable,
    GuardianEventSummary,
)
from services.storage.environment import EnvironmentTrend, TrendWindow
from tests.gauge.synthetic_dial import calibration as synthetic_calibration


NOW = datetime(2026, 8, 5, 12, 0, tzinfo=UTC)


class DashboardHtmlParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.elements: list[tuple[str, dict[str, str | None]]] = []
        self.ids: dict[str, list[dict[str, str | None]]] = {}
        self.scripts: list[str] = []
        self._in_script = False

    def handle_starttag(
        self,
        tag: str,
        attrs: list[tuple[str, str | None]],
    ) -> None:
        attributes = dict(attrs)
        self.elements.append((tag, attributes))
        if element_id := attributes.get("id"):
            self.ids.setdefault(element_id, []).append(attributes)
        if tag == "script":
            self._in_script = True

    def handle_endtag(self, tag: str) -> None:
        if tag == "script":
            self._in_script = False

    def handle_data(self, data: str) -> None:
        if self._in_script:
            self.scripts.append(data)


def parse_dashboard_html(markup: str) -> DashboardHtmlParser:
    parser = DashboardHtmlParser()
    parser.feed(markup)
    return parser


def css_declarations(stylesheet: str, selector: str) -> str:
    match = re.search(rf"{re.escape(selector)}\s*\{{([^}}]*)\}}", stylesheet)
    assert match is not None
    return match.group(1)


def auth(username: str = "parent", password: str = "secret") -> dict[str, str]:
    token = base64.b64encode(f"{username}:{password}".encode()).decode()
    return {"Authorization": f"Basic {token}"}


@dataclass
class FakeGateway:
    healthy: bool = True
    notification_count: int = 0
    snapshot_viewport: SnapshotViewport | None = None

    def status(self) -> dict[str, object]:
        return {"camera": "online" if self.healthy else "offline", "stream": "live"}

    def iter_mjpeg(self) -> Iterator[bytes]:
        yield b"--frame\r\nContent-Type: image/jpeg\r\n\r\nJPEG\r\n"

    def snapshot(self, viewport: SnapshotViewport) -> bytes:
        self.snapshot_viewport = viewport
        return b"JPEG-SNAPSHOT"

    def send_test_notification(self) -> None:
        self.notification_count += 1


@dataclass
class RecordingPtzAdapter:
    result: PtzCode = PtzCode.OK
    directions: list[PtzDirection] | None = None

    def __post_init__(self) -> None:
        if self.directions is None:
            self.directions = []

    def step(self, direction: PtzDirection, timeout_seconds: float) -> PtzCode:
        assert self.directions is not None
        self.directions.append(direction)
        return self.result


@dataclass
class FakeHdStream:
    busy: bool = False
    issue_count: int = 0
    issued_profiles: list[HdProfile] = field(default_factory=list)
    served_count: int = 0
    received: list[str | bytes] = field(default_factory=list)

    def issue_ticket(self, profile: HdProfile) -> HdTicket:
        self.issue_count += 1
        self.issued_profiles.append(profile)
        if self.busy:
            raise HdBusyError
        return HdTicket(value="opaque-ticket", expires_in=10)

    async def serve(self, socket: object) -> None:
        self.served_count += 1
        await socket.accept()  # type: ignore[attr-defined]
        self.received.append(await socket.receive())  # type: ignore[attr-defined]
        await socket.close(code=1000)  # type: ignore[attr-defined]


@dataclass
class FakeEnvironmentService:
    current_calls: int = 0
    trend_calls: list[TrendWindow] = field(default_factory=list)
    incident_calls: int = 0
    saved_calibrations: list[object] = field(default_factory=list)

    def current(self, now: datetime) -> EnvironmentSnapshot:
        self.current_calls += 1
        old = EnvironmentReading.available(
            reading_id="old-valid",
            source_kind=EnvironmentSourceKind.WS2021_GAUGE,
            captured_at=NOW - timedelta(minutes=1),
            temperature_c=22,
            humidity_rh=48,
            confidence=0.9,
            calibration_version="calibration-1",
            sample_count=5,
            valid_temperature_samples=5,
            valid_humidity_samples=5,
        )
        current = EnvironmentReading.unavailable(
            reading_id="current-unavailable",
            source_kind=EnvironmentSourceKind.WS2021_GAUGE,
            captured_at=NOW,
            failure_reason=ReadingFailureReason.GLARE,
            calibration_version="calibration-2",
            sample_count=5,
        )
        return EnvironmentSnapshot(
            generated_at=now,
            policy_version="environment-v1",
            current_reading=current,
            current_available=False,
            temperature_c=None,
            humidity_rh=None,
            last_valid_reading=old,
            open_incidents=(),
        )

    def trend(self, window: TrendWindow, now: datetime) -> EnvironmentTrend:
        self.trend_calls.append(window)
        return EnvironmentTrend(
            window=window,
            bucket_seconds=300 if window is TrendWindow.HOURS_24 else 3600,
            started_at=NOW - timedelta(hours=24),
            ended_at=NOW,
            buckets=(),
        )

    def incidents(self) -> tuple[object, ...]:
        self.incident_calls += 1
        return ()

    def calibration_status(self) -> dict[str, object]:
        return {"state": "missing", "schema_version": 2}

    def save_calibration(
        self,
        draft: object,
        reference_jpeg: bytes,
        now: datetime,
    ) -> dict[str, object]:
        self.saved_calibrations.append((draft, reference_jpeg, now))
        return {"state": "available", "schema_version": 2, "calibration_id": "server-id"}


@dataclass
class FakeGuardianEventService:
    unavailable: bool = False
    calls: int = 0

    def recent_events(self) -> GuardianEventList:
        self.calls += 1
        if self.unavailable:
            raise GuardianEventQueryUnavailable
        return GuardianEventList(
            generated_at=NOW,
            events=(
                GuardianEventSummary(
                    event_id="event-safe",
                    risk_kind="face_not_visible",
                    state="open",
                    severity="high",
                    opened_at=NOW - timedelta(minutes=2),
                    updated_at=NOW - timedelta(minutes=1),
                    recovered_at=None,
                    adult_intervention_count=1,
                    evidence_state="collecting",
                ),
            ),
        )


def dashboard_overview(now: datetime) -> DashboardOverviewV1:
    return DashboardOverviewV1(
        schema_version=1,
        generated_at=now,
        open_alert_count=0,
        environment=DashboardEnvironmentCurrentV1(state="unavailable"),
        components=(),
        recent_activity=(),
    )


def dashboard_alert_list(now: datetime) -> DashboardAlertListV1:
    return DashboardAlertListV1(schema_version=1, generated_at=now, alerts=())


def dashboard_analytics(
    window: DashboardWindow,
    now: datetime,
) -> DashboardAnalyticsV1:
    duration = timedelta(
        hours=24 if window is DashboardWindow.HOURS_24 else 24 * 7
    )
    return DashboardAnalyticsV1(
        schema_version=1,
        generated_at=now,
        window=window,
        started_at=now - duration,
        ended_at=now,
        environment=DashboardEnvironmentAnalyticsV1(
            state="unavailable",
            sample_count=0,
            available_count=0,
            incident_counts=DashboardEnvironmentIncidentCountsV1(
                range_normal=0,
                range_critical=0,
                unreadable=0,
            ),
            buckets=(),
        ),
        guardian=DashboardGuardianAnalyticsV1(
            state="unavailable",
            confirmed_count=0,
            recovered_count=0,
            intervention_count=0,
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
            ),
            notification_counts=DashboardNotificationCountsV1(
                pending=0,
                delivered=0,
                rejected=0,
                terminal_total=0,
            ),
        ),
    )


def dashboard_system(now: datetime) -> DashboardSystemV1:
    return DashboardSystemV1(schema_version=1, generated_at=now, components=())


@dataclass
class FakeDashboardService:
    unavailable_method: str | None = None
    calls: list[tuple[str, object]] = field(default_factory=list)

    def _record(self, method: str, value: object) -> None:
        self.calls.append((method, value))
        if self.unavailable_method == method:
            raise DashboardServiceUnavailable(
                "sqlite path ProviderExplosion known_streams token topic confidence "
                "rule_version evidence_key"
            )

    def overview(self, now: datetime) -> DashboardOverviewV1:
        self._record("overview", now)
        return dashboard_overview(now)

    def alerts(self, now: datetime) -> DashboardAlertListV1:
        self._record("alerts", now)
        return dashboard_alert_list(now)

    def analytics(
        self,
        window: DashboardWindow,
        now: datetime,
    ) -> DashboardAnalyticsV1:
        self._record("analytics", window)
        return dashboard_analytics(window, now)

    def system(self, now: datetime) -> DashboardSystemV1:
        self._record("system", now)
        return dashboard_system(now)


def calibration_draft() -> dict[str, object]:
    payload = synthetic_calibration().model_dump(mode="json")
    for server_field in ("schema_version", "calibration_id", "created_at", "reference_version"):
        payload.pop(server_field)
    return payload


def client(
    gateway: FakeGateway | None = None,
    *,
    ptz: StepPtzController | None = None,
    hd_stream: FakeHdStream | None = None,
    environment: FakeEnvironmentService | None = None,
    guardian_events: FakeGuardianEventService | None = None,
    dashboard: FakeDashboardService | None = None,
) -> tuple[TestClient, FakeGateway]:
    fake = gateway or FakeGateway()
    runtime_kwargs: dict[str, object] = dict(
        username="parent",
        password="secret",
        stream_name="live",
        gateway=fake,
    )
    if ptz is not None:
        runtime_kwargs["ptz"] = ptz
    if hd_stream is not None:
        runtime_kwargs["hd_stream"] = hd_stream
    if environment is not None:
        runtime_kwargs["environment"] = environment
    if guardian_events is not None:
        runtime_kwargs["guardian_events"] = guardian_events
    if dashboard is not None:
        runtime_kwargs["dashboard"] = dashboard
    runtime = AlphaRuntime(**runtime_kwargs)
    return TestClient(create_app(runtime)), fake


DASHBOARD_ROUTES = (
    ("/api/dashboard/overview", "overview"),
    ("/api/dashboard/alerts", "alerts"),
    ("/api/dashboard/analytics/24h", "analytics"),
    ("/api/dashboard/analytics/7d", "analytics"),
    ("/api/dashboard/system", "system"),
)

DASHBOARD_ASSETS = (
    ("/assets/dashboard.css", "_DASHBOARD_STYLE"),
    ("/assets/dashboard-views.js", "_DASHBOARD_VIEWS_SCRIPT"),
    ("/assets/dashboard-analytics.js", "_DASHBOARD_ANALYTICS_SCRIPT"),
    ("/assets/dashboard-shell.js", "_DASHBOARD_SHELL_SCRIPT"),
)


@dataclass
class RecordingDashboardAsset:
    reads: int = 0

    def read_text(self, *, encoding: str) -> str:
        assert encoding == "utf-8"
        self.reads += 1
        return "/* authenticated dashboard asset */"


@pytest.mark.parametrize(("route", "method"), DASHBOARD_ROUTES)
def test_dashboard_routes_require_authentication_before_provider_access(
    route: str,
    method: str,
) -> None:
    dashboard = FakeDashboardService()
    app, _ = client(dashboard=dashboard)

    response = app.get(route)

    assert response.status_code == 401
    assert response.headers["cache-control"] == "no-store"
    assert dashboard.calls == []


@pytest.mark.parametrize(
    ("route", "method", "expected_keys"),
    (
        (
            "/api/dashboard/overview",
            "overview",
            {
                "schema_version",
                "generated_at",
                "attention",
                "open_alert_count",
                "guardian_open_count",
                "today_recovered_count",
                "environment",
                "components",
                "recent_activity",
            },
        ),
        (
            "/api/dashboard/alerts",
            "alerts",
            {"schema_version", "generated_at", "alerts"},
        ),
        (
            "/api/dashboard/analytics/24h",
            "analytics",
            {
                "schema_version",
                "generated_at",
                "window",
                "started_at",
                "ended_at",
                "environment",
                "guardian",
            },
        ),
        (
            "/api/dashboard/system",
            "system",
            {"schema_version", "generated_at", "components"},
        ),
    ),
)
def test_authenticated_dashboard_routes_return_closed_models(
    route: str,
    method: str,
    expected_keys: set[str],
) -> None:
    dashboard = FakeDashboardService()
    app, _ = client(dashboard=dashboard)

    response = app.get(route, headers=auth())

    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    assert set(response.json()) == expected_keys
    assert len(dashboard.calls) == 1
    call_method, call_value = dashboard.calls[0]
    assert call_method == method
    if method == "analytics":
        assert call_value is DashboardWindow.HOURS_24
    else:
        assert isinstance(call_value, datetime)
        assert call_value.tzinfo is UTC


def test_dashboard_analytics_rejects_unknown_window_before_provider_access() -> None:
    dashboard = FakeDashboardService()
    app, _ = client(dashboard=dashboard)

    response = app.get("/api/dashboard/analytics/30d", headers=auth())

    assert response.status_code == 422
    assert response.headers["cache-control"] == "no-store"
    assert dashboard.calls == []


def test_dashboard_analytics_accepts_seven_day_window() -> None:
    dashboard = FakeDashboardService()
    app, _ = client(dashboard=dashboard)

    response = app.get("/api/dashboard/analytics/7d", headers=auth())

    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    assert response.json()["window"] == "7d"
    assert dashboard.calls == [("analytics", DashboardWindow.DAYS_7)]


@pytest.mark.parametrize(("route", "method"), DASHBOARD_ROUTES)
def test_dashboard_routes_without_provider_return_stable_unavailable_response(
    route: str,
    method: str,
) -> None:
    app, _ = client()

    response = app.get(route, headers=auth())

    assert response.status_code == 503
    assert response.headers["cache-control"] == "no-store"
    assert response.json() == {"detail": "DASHBOARD_DATA_UNAVAILABLE"}


@pytest.mark.parametrize(("route", "method"), DASHBOARD_ROUTES)
def test_dashboard_provider_failures_return_stable_unavailable_response(
    route: str,
    method: str,
) -> None:
    dashboard = FakeDashboardService(unavailable_method=method)
    app, _ = client(dashboard=dashboard)

    response = app.get(route, headers=auth())

    assert response.status_code == 503
    assert response.headers["cache-control"] == "no-store"
    assert response.json() == {"detail": "DASHBOARD_DATA_UNAVAILABLE"}
    for forbidden in (
        "sqlite",
        "path",
        "providerexplosion",
        "known_streams",
        "token",
        "topic",
        "confidence",
        "rule_version",
        "evidence_key",
    ):
        assert forbidden not in response.text.lower()
    assert dashboard.calls[0][0] == method


@pytest.mark.parametrize(("route", "module_attribute"), DASHBOARD_ASSETS)
def test_dashboard_assets_authenticate_before_file_access_and_never_cache(
    route: str,
    module_attribute: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    asset = RecordingDashboardAsset()
    monkeypatch.setattr(alpha_module, module_attribute, asset)
    app, _ = client()

    denied = app.get(route)

    assert denied.status_code == 401
    assert denied.headers["cache-control"] == "no-store"
    assert asset.reads == 0

    allowed = app.get(route, headers=auth())

    assert allowed.status_code == 200
    assert allowed.headers["cache-control"] == "no-store"
    assert asset.reads == 1


def test_dashboard_views_asset_requires_authentication_and_exposes_only_presenter_code() -> None:
    app, _ = client()

    assert app.get("/assets/dashboard-views.js").status_code == 401
    response = app.get("/assets/dashboard-views.js", headers=auth())

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/javascript")
    assert response.headers["cache-control"] == "no-store"
    assert "BabyMonitorDashboardViews" in response.text
    assert "/live.mjpeg" not in response.text
    assert "/snapshot.jpeg" not in response.text
    assert "sqlite" not in response.text.lower()
    assert "database" not in response.text.lower()
    assert "/evidence" not in response.text.lower()
    assert "file://" not in response.text.lower()
    assert "/users/" not in response.text.lower()


def test_dashboard_analytics_asset_requires_authentication_and_exposes_only_bounded_metrics() -> None:
    app, _ = client()

    assert app.get("/assets/dashboard-analytics.js").status_code == 401
    response = app.get("/assets/dashboard-analytics.js", headers=auth())

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/javascript")
    assert response.headers["cache-control"] == "no-store"
    assert "BabyMonitorDashboardAnalytics" in response.text
    assert "/api/dashboard/analytics/24h" not in response.text
    assert "/api/dashboard/analytics/${windowName}" in response.text
    assert "/live.mjpeg" not in response.text
    assert "/snapshot.jpeg" not in response.text
    assert "sqlite" not in response.text.lower()
    assert "database" not in response.text.lower()
    assert "/evidence" not in response.text.lower()
    assert "file://" not in response.text.lower()
    assert "/users/" not in response.text.lower()


def test_dashboard_shell_asset_requires_authentication_and_exposes_only_orchestration_code() -> None:
    app, _ = client()

    assert app.get("/assets/dashboard-shell.js").status_code == 401
    response = app.get("/assets/dashboard-shell.js", headers=auth())

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/javascript")
    assert response.headers["cache-control"] == "no-store"
    assert "BabyMonitorDashboardShell" in response.text
    assert "/api/dashboard/overview" in response.text
    assert "/api/dashboard/alerts" in response.text
    assert "/api/dashboard/system" in response.text
    assert "/api/test-notification" in response.text
    assert "mountDashboardAnalytics" in response.text
    assert "/live.mjpeg" not in response.text
    assert "/snapshot.jpeg" not in response.text
    assert "sqlite" not in response.text.lower()
    assert "database" not in response.text.lower()
    assert "/evidence" not in response.text.lower()
    assert "file://" not in response.text.lower()
    assert "/users/" not in response.text.lower()


def test_dashboard_no_store_middleware_leaves_unrelated_routes_unchanged() -> None:
    app, _ = client()

    response = app.get("/healthz")

    assert response.status_code == 200
    assert "cache-control" not in response.headers


def test_guardian_events_require_authentication_before_service_access() -> None:
    guardian_events = FakeGuardianEventService()
    app, _ = client(guardian_events=guardian_events)

    response = app.get("/api/guardian/events")

    assert response.status_code == 401
    assert guardian_events.calls == 0


def test_authenticated_guardian_events_return_only_validated_safe_fields() -> None:
    guardian_events = FakeGuardianEventService()
    app, _ = client(guardian_events=guardian_events)

    response = app.get("/api/guardian/events", headers=auth())

    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    assert guardian_events.calls == 1
    assert set(response.json()) == {"generated_at", "events"}
    assert set(response.json()["events"][0]) == {
        "event_id",
        "risk_kind",
        "state",
        "severity",
        "opened_at",
        "updated_at",
        "recovered_at",
        "adult_intervention_count",
        "evidence_state",
    }
    assert "snapshot" not in response.text.lower()
    assert "clip" not in response.text.lower()
    assert "path" not in response.text.lower()


@pytest.mark.parametrize(
    "guardian_events",
    [None, FakeGuardianEventService(unavailable=True)],
)
def test_guardian_event_query_failure_is_a_stable_redacted_503(
    guardian_events: FakeGuardianEventService | None,
) -> None:
    app, _ = client(guardian_events=guardian_events)

    response = app.get("/api/guardian/events", headers=auth())

    assert response.status_code == 503
    assert response.json() == {"detail": "GUARDIAN_EVENTS_UNAVAILABLE"}
    assert "sqlite" not in response.text.lower()


def test_dashboard_requires_basic_authentication() -> None:
    app, _ = client()
    response = app.get("/")
    assert response.status_code == 401
    assert response.headers["www-authenticate"] == "Basic"


def test_dashboard_loads_after_authentication() -> None:
    app, _ = client()
    response = app.get("/", headers=auth())
    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    assert "Baby Monitor Local Alpha" in response.text
    assert "/live.mjpeg" in response.text
    assert "/snapshot.jpeg" in response.text
    assert 'id="environment-current"' in response.text
    assert 'src="/assets/gauge-calibration.js"' in response.text
    assert 'src="/assets/environment-dashboard.js"' not in response.text
    assert 'src="/assets/guardian-events.js"' not in response.text
    assert "document.getElementById('notify').onclick" not in response.text
    scripts = (
        'src="/assets/hd-player.js"',
        'src="/assets/dashboard-viewer.js"',
        'src="/assets/gauge-calibration.js"',
        'src="/assets/dashboard-views.js"',
        'src="/assets/dashboard-analytics.js"',
        'src="/assets/dashboard-shell.js"',
    )
    assert [response.text.index(script) for script in scripts] == sorted(
        response.text.index(script) for script in scripts
    )


def test_dashboard_html_is_one_local_four_tab_shell_in_dependency_order() -> None:
    app, _ = client()

    response = app.get("/", headers=auth())

    assert response.status_code == 200
    document = parse_dashboard_html(response.text)
    assert response.text.count('src="/live.mjpeg"') == 1
    assert len(
        [
            attributes
            for tag, attributes in document.elements
            if tag == "button" and attributes.get("role") == "tab"
        ]
    ) == 4
    assert "status" not in document.ids
    assert 'src="/assets/guardian-events.js"' not in response.text
    assert 'src="/assets/environment-dashboard.js"' not in response.text

    resources = [
        value
        for _tag, attributes in document.elements
        for attribute in ("href", "src")
        if (value := attributes.get(attribute)) is not None
    ]
    assert resources
    assert all(value.startswith("/") for value in resources)
    assert not any(value.startswith(("http://", "https://")) for value in resources)
    assert [
        attributes["src"]
        for tag, attributes in document.elements
        if tag == "script" and attributes.get("src") is not None
    ] == [
        "/assets/hd-player.js",
        "/assets/dashboard-viewer.js",
        "/assets/gauge-calibration.js",
        "/assets/dashboard-views.js",
        "/assets/dashboard-analytics.js",
        "/assets/dashboard-shell.js",
    ]


def test_dashboard_uses_a_four_tab_shell_that_preserves_the_viewer() -> None:
    app, _ = client()

    response = app.get("/", headers=auth())

    assert response.status_code == 200
    document = parse_dashboard_html(response.text)
    required_ids = (
        "dashboard-health",
        "tab-overview",
        "tab-alerts",
        "tab-analytics",
        "tab-system",
        "alert-count",
        "global-attention",
        "dashboard-overview",
        "dashboard-alerts",
        "dashboard-analytics",
        "dashboard-system",
        "viewer",
        "media-plane",
        "live-image",
        "hd-video",
        "fullscreen",
        "fullscreen-help",
        "ptz-status",
        "hd-status",
        "snapshot-link",
        "notify",
        "gauge-calibration",
        "overview-environment",
        "overview-guardian",
        "overview-components",
        "overview-recent",
        "overview-updated",
        "overview-stale",
        "environment-current",
        "environment-detail",
        "environment-last-valid",
        "environment-trend-24h",
        "environment-trend-7d",
        "environment-trend",
        "environment-incidents",
        "guardian-events",
        "guardian-events-stale",
        "alerts-list",
        "alerts-announcement",
        "alerts-updated",
        "alerts-stale",
        "analytics-refresh",
        "analytics-environment-kpi",
        "analytics-guardian-kpi",
        "analytics-notification-kpi",
        "analytics-coverage-kpi",
        "analytics-trend",
        "analytics-summary",
        "analytics-table",
        "analytics-updated",
        "analytics-stale",
        "system-components",
        "system-refresh",
        "system-updated",
        "system-stale",
    )
    assert all(len(document.ids.get(element_id, ())) == 1 for element_id in required_ids)
    tablists = [
        attributes
        for tag, attributes in document.elements
        if tag == "nav" and attributes.get("role") == "tablist"
    ]
    assert tablists == [{"class": "dashboard-tabs", "role": "tablist", "aria-label": "监控页面"}]
    tabs = {
        attributes["id"]: attributes
        for tag, attributes in document.elements
        if tag == "button" and attributes.get("role") == "tab"
    }
    assert set(tabs) == {"tab-overview", "tab-alerts", "tab-analytics", "tab-system"}
    panels = [
        attributes
        for tag, attributes in document.elements
        if tag == "section" and attributes.get("role") == "tabpanel"
    ]
    assert {attributes.get("id") for attributes in panels} == {
        "dashboard-overview",
        "dashboard-alerts",
        "dashboard-analytics",
        "dashboard-system",
    }
    assert tabs["tab-overview"].get("tabindex") == "0"
    assert tabs["tab-overview"].get("aria-selected") == "true"
    for panel_id, tab_id in (
        ("dashboard-overview", "tab-overview"),
        ("dashboard-alerts", "tab-alerts"),
        ("dashboard-analytics", "tab-analytics"),
        ("dashboard-system", "tab-system"),
    ):
        tab = tabs[tab_id]
        panel = document.ids[panel_id][0]
        assert tab.get("aria-controls") == panel_id
        assert tab.get("aria-selected") == ("true" if tab_id == "tab-overview" else "false")
        assert tab.get("tabindex") == ("0" if tab_id == "tab-overview" else "-1")
        assert panel.get("role") == "tabpanel"
        assert panel.get("aria-labelledby") == tab_id
        assert ("hidden" in panel) is (panel_id != "dashboard-overview")
    assert [
        attributes
        for tag, attributes in document.elements
        if tag == "img" and attributes.get("src") == "/live.mjpeg"
    ] == [document.ids["live-image"][0]]
    assert "status" not in document.ids
    source_filters = {
        attributes["data-alert-source"]: attributes.get("aria-pressed")
        for tag, attributes in document.elements
        if tag == "button" and "data-alert-source" in attributes
    }
    assert source_filters == {
        "all": "true",
        "guardian": "false",
        "environment": "false",
        "system": "false",
    }
    state_filters = {
        attributes["data-alert-state"]: attributes.get("aria-pressed")
        for tag, attributes in document.elements
        if tag == "button" and "data-alert-state" in attributes
    }
    assert state_filters == {"all": "true", "open": "false", "recovered": "false"}
    assert document.ids["alerts-announcement"][0].get("aria-live") == "polite"
    assert document.ids["environment-trend"][0].get("width") == "900"
    assert "".join(document.scripts).strip() == ""
    assert "refreshStatus" not in "".join(document.scripts)


def test_dashboard_stylesheet_requires_authentication_and_is_compact() -> None:
    app, _ = client()

    assert app.get("/assets/dashboard.css").status_code == 401
    response = app.get("/assets/dashboard.css", headers=auth())

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/css")
    assert response.headers["cache-control"] == "no-store"
    assert "@media (max-width: 720px)" in response.text
    assert ":focus-visible" in response.text
    assert "@media (prefers-reduced-motion: reduce)" in response.text
    assert re.search(
        r"#environment-trend\s*\{[^}]*max-width:\s*100%\s*;[^}]*height:\s*auto\s*;",
        response.text,
        re.DOTALL,
    )


@pytest.mark.parametrize("viewport_width", (320, 390))
def test_dashboard_static_mobile_layout_contract(viewport_width: int) -> None:
    app, _ = client()

    stylesheet = app.get("/assets/dashboard.css", headers=auth()).text

    breakpoint = re.search(r"@media\s*\(max-width:\s*(\d+)px\)", stylesheet)
    assert breakpoint is not None
    assert viewport_width <= int(breakpoint.group(1)) == 720
    assert "grid-template-columns: repeat(4, minmax(0, 1fr))" in css_declarations(
        stylesheet,
        ".dashboard-tabs",
    )
    assert "min-height: 44px" in css_declarations(stylesheet, "button, a.button")
    shell = css_declarations(stylesheet, ".dashboard-shell")
    assert "width: min(1180px, 100%)" in shell
    assert "box-sizing: border-box" in css_declarations(stylesheet, "*")
    page_level = " ".join(
        css_declarations(stylesheet, selector)
        for selector in (
            ".dashboard-shell",
            '[role="tabpanel"]',
            ".overview-grid",
            ".card, .kpi-card, .chart-card",
        )
    )
    fixed_page_widths = [
        int(width)
        for width in re.findall(r"(?:^|;)\s*width:\s*(\d+)px", page_level)
    ]
    assert all(width <= viewport_width for width in fixed_page_widths)


def test_dashboard_exposes_guardian_event_list_without_media_access() -> None:
    app, _ = client()

    response = app.get("/", headers=auth())

    assert response.status_code == 200
    assert 'id="guardian-events"' in response.text
    assert 'id="guardian-events-stale"' in response.text
    assert 'src="/assets/guardian-events.js"' not in response.text
    assert 'href="/assets/dashboard.css"' in response.text
    assert "不提供图片或视频访问" in response.text


def test_dashboard_exposes_accessible_viewer_controls() -> None:
    app, _ = client()

    response = app.get("/", headers=auth())

    assert response.status_code == 200
    assert 'id="viewer"' in response.text
    assert 'id="media-plane"' in response.text
    assert 'id="live-image"' in response.text
    assert 'id="snapshot-link"' in response.text
    assert response.text.count('class="zoom-button"') == 3
    assert response.text.count('class="ptz-button"') == 4
    active_zoom_buttons = re.findall(
        r'<button class="zoom-button"[^>]*aria-pressed="true"', response.text
    )
    assert len(active_zoom_buttons) == 1
    assert 'aria-label="进入全屏"' in response.text
    assert 'aria-label="摄像头向上移动一步"' in response.text
    assert 'aria-label="摄像头向下移动一步"' in response.text
    assert 'aria-label="摄像头向左移动一步"' in response.text
    assert 'aria-label="摄像头向右移动一步"' in response.text
    assert 'src="/assets/dashboard-viewer.js"' in response.text


def test_dashboard_keeps_one_live_mjpeg_consumer() -> None:
    app, _ = client()

    response = app.get("/", headers=auth())

    assert response.text.count('src="/live.mjpeg"') == 1


def test_dashboard_contains_inactive_hd_video_layer_and_status() -> None:
    app, _ = client()

    response = app.get("/", headers=auth())

    assert '<video id="hd-video"' in response.text
    video_tag = re.search(r'<video id="hd-video"[^>]*>', response.text)
    assert video_tag is not None
    assert " muted" in video_tag.group(0)
    assert " playsinline" in video_tag.group(0)
    assert 'preload="none"' in video_tag.group(0)
    assert " src=" not in video_tag.group(0)
    assert 'id="hd-status"' in response.text
    assert "HD_READY" not in response.text
    assert 'src="/assets/hd-player.js"' in response.text
    assert response.text.index('src="/assets/hd-player.js"') < response.text.index(
        'src="/assets/dashboard-viewer.js"'
    )


def test_viewer_asset_requires_authentication() -> None:
    app, _ = client()

    unauthenticated = app.get("/assets/dashboard-viewer.js")
    response = app.get("/assets/dashboard-viewer.js", headers=auth())

    assert unauthenticated.status_code == 401
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/javascript")
    assert response.headers["cache-control"] == "no-store"
    assert "mountDashboardViewer" in response.text


def test_hd_player_asset_requires_authentication_and_disables_cache() -> None:
    app, _ = client()

    unauthenticated = app.get("/assets/hd-player.js")
    response = app.get("/assets/hd-player.js", headers=auth())

    assert unauthenticated.status_code == 401
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/javascript")
    assert response.headers["cache-control"] == "no-store"


@pytest.mark.parametrize(
    "asset",
    ["environment-dashboard.js", "gauge-calibration.js"],
)
def test_environment_assets_require_authentication_and_disable_cache(
    asset: str,
) -> None:
    app, _ = client()

    assert app.get(f"/assets/{asset}").status_code == 401
    response = app.get(f"/assets/{asset}", headers=auth())
    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"


def test_guardian_event_asset_requires_authentication_and_disables_cache() -> None:
    app, _ = client()

    assert app.get("/assets/guardian-events.js").status_code == 401
    response = app.get("/assets/guardian-events.js", headers=auth())

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/javascript")
    assert response.headers["cache-control"] == "no-store"
    assert "mountGuardianEvents" in response.text


def test_environment_current_requires_auth_before_service_access() -> None:
    environment = FakeEnvironmentService()
    app, _ = client(environment=environment)

    response = app.get("/api/environment/current")

    assert response.status_code == 401
    assert environment.current_calls == 0


def test_authenticated_incident_link_opens_dashboard_anchor() -> None:
    app, _ = client(environment=FakeEnvironmentService())

    denied = app.get("/incidents/incident-1", follow_redirects=False)
    response = app.get(
        "/incidents/incident-1",
        headers=auth(),
        follow_redirects=False,
    )

    assert denied.status_code == 401
    assert response.status_code == 303
    assert response.headers["location"] == "/#environment-incident=incident-1"


def test_environment_current_keeps_unavailable_and_last_valid_separate() -> None:
    environment = FakeEnvironmentService()
    app, _ = client(environment=environment)

    response = app.get("/api/environment/current", headers=auth())

    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    payload = response.json()
    assert payload["current_reading"]["state"] == "unavailable"
    assert payload["current_available"] is False
    assert payload["temperature_c"] is None
    assert payload["last_valid_reading"]["temperature_c"] == 22


@pytest.mark.parametrize(
    ("window", "expected"),
    [("24h", TrendWindow.HOURS_24), ("7d", TrendWindow.DAYS_7)],
)
def test_environment_trends_accept_only_closed_windows(
    window: str,
    expected: TrendWindow,
) -> None:
    environment = FakeEnvironmentService()
    app, _ = client(environment=environment)

    response = app.get(f"/api/environment/trends/{window}", headers=auth())

    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    assert environment.trend_calls == [expected]


def test_environment_trends_reject_arbitrary_window_before_service_access() -> None:
    environment = FakeEnvironmentService()
    app, _ = client(environment=environment)

    response = app.get("/api/environment/trends/365d", headers=auth())

    assert response.status_code == 422
    assert environment.trend_calls == []


def test_calibration_save_rejects_extra_client_path_before_snapshot() -> None:
    environment = FakeEnvironmentService()
    gateway = FakeGateway()
    app, _ = client(gateway, environment=environment)
    payload = calibration_draft()
    payload["reference_path"] = "/private/family/gauge.jpg"

    response = app.put("/api/gauge-calibration", headers=auth(), json=payload)

    assert response.status_code == 422
    assert gateway.snapshot_viewport is None
    assert environment.saved_calibrations == []


def test_calibration_save_uses_authenticated_fixed_snapshot_viewport() -> None:
    environment = FakeEnvironmentService()
    gateway = FakeGateway()
    app, _ = client(gateway, environment=environment)

    response = app.put(
        "/api/gauge-calibration",
        headers=auth(),
        json=calibration_draft(),
    )

    assert response.status_code == 201
    assert response.headers["cache-control"] == "no-store"
    assert response.json() == {
        "state": "available",
        "schema_version": 2,
        "calibration_id": "server-id",
    }
    assert gateway.snapshot_viewport == SnapshotViewport(
        zoom=2,
        center_x=0.5,
        center_y=0.5,
    )
    assert len(environment.saved_calibrations) == 1
    assert environment.saved_calibrations[0][1] == b"JPEG-SNAPSHOT"


def test_hd_session_requires_basic_authentication_before_ticket_issue() -> None:
    hd_stream = FakeHdStream()
    app, _ = client(hd_stream=hd_stream)

    response = app.post("/api/hd-session")

    assert response.status_code == 401
    assert response.headers["www-authenticate"] == "Basic"
    assert hd_stream.issue_count == 0


@pytest.mark.parametrize("profile", [HdProfile.NATIVE, HdProfile.COMPAT])
def test_authenticated_hd_session_returns_only_opaque_ticket_metadata(
    profile: HdProfile,
) -> None:
    hd_stream = FakeHdStream()
    app, _ = client(hd_stream=hd_stream)

    response = app.post(
        "/api/hd-session",
        headers=auth(),
        json={"profile": profile.value},
    )

    assert response.status_code == 201
    assert response.headers["cache-control"] == "no-store"
    assert response.json() == {"ticket": "opaque-ticket", "expires_in": 10}
    assert set(response.json()) == {"ticket", "expires_in"}
    assert hd_stream.issue_count == 1
    assert hd_stream.issued_profiles == [profile]


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"profile": "unknown"},
        {"profile": "native", "stream": "attacker-controlled"},
    ],
)
def test_hd_session_rejects_missing_unknown_or_extra_profile_fields(
    payload: dict[str, str],
) -> None:
    hd_stream = FakeHdStream()
    app, _ = client(hd_stream=hd_stream)

    response = app.post("/api/hd-session", headers=auth(), json=payload)

    assert response.status_code == 422
    assert hd_stream.issue_count == 0


def test_full_hd_ticket_store_returns_stable_busy_result() -> None:
    hd_stream = FakeHdStream(busy=True)
    app, _ = client(hd_stream=hd_stream)

    response = app.post(
        "/api/hd-session",
        headers=auth(),
        json={"profile": "compat"},
    )

    assert response.status_code == 429
    assert response.headers["cache-control"] == "no-store"
    assert response.json() == {"result": "HD_BUSY"}
    assert "opaque-ticket" not in response.text


def test_hd_websocket_delegates_ticket_as_first_message_without_url_secret() -> None:
    hd_stream = FakeHdStream()
    app, _ = client(hd_stream=hd_stream)

    with app.websocket_connect(
        "/live-hd.ws",
        headers={"origin": "http://testserver"},
    ) as websocket:
        websocket.send_text("opaque-ticket")

    assert hd_stream.served_count == 1
    assert hd_stream.received == ["opaque-ticket"]


def test_hd_websocket_rejects_query_selectors_before_service_access() -> None:
    hd_stream = FakeHdStream()
    app, _ = client(hd_stream=hd_stream)

    with pytest.raises(WebSocketDisconnect) as rejection:
        with app.websocket_connect(
            "/live-hd.ws?src=ignored&url=http://other.invalid",
            headers={"origin": "http://testserver"},
        ):
            pass

    assert rejection.value.code == 1008
    assert hd_stream.served_count == 0


def test_wrong_password_is_rejected() -> None:
    app, _ = client()
    response = app.get("/", headers=auth(password="wrong"))
    assert response.status_code == 401


def test_authenticated_status_returns_camera_state() -> None:
    app, _ = client(FakeGateway(healthy=False))
    response = app.get("/api/status", headers=auth())
    assert response.status_code == 200
    assert response.json() == {"camera": "offline", "stream": "live"}


def test_live_proxy_returns_mjpeg_stream() -> None:
    app, _ = client()
    response = app.get("/live.mjpeg", headers=auth())
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("multipart/x-mixed-replace")
    assert b"JPEG" in response.content


def test_default_snapshot_proxy_returns_centered_full_frame() -> None:
    app, gateway = client()

    response = app.get("/snapshot.jpeg", headers=auth())

    assert response.status_code == 200
    assert response.headers["content-type"] == "image/jpeg"
    assert response.content == b"JPEG-SNAPSHOT"
    assert gateway.snapshot_viewport == SnapshotViewport()


def test_zoomed_snapshot_proxy_forwards_the_current_viewport() -> None:
    app, gateway = client()
    response = app.get(
        "/snapshot.jpeg?zoom=2&center_x=0.375&center_y=0.4",
        headers=auth(),
    )
    assert response.status_code == 200
    assert response.headers["content-type"] == "image/jpeg"
    assert response.content == b"JPEG-SNAPSHOT"
    assert gateway.snapshot_viewport == SnapshotViewport(
        zoom=2,
        center_x=0.375,
        center_y=0.4,
    )


@pytest.mark.parametrize(
    "query",
    [
        "zoom=4&center_x=0.5&center_y=0.5",
        "zoom=2&center_x=-0.1&center_y=0.5",
        "zoom=2&center_x=0.5&center_y=1.1",
        "zoom=2&center_x=0.5&center_y=0.5&src=live",
    ],
)
def test_snapshot_rejects_an_invalid_viewport(query: str) -> None:
    app, gateway = client()

    response = app.get(f"/snapshot.jpeg?{query}", headers=auth())

    assert response.status_code == 422
    assert gateway.snapshot_viewport is None


def test_notification_test_endpoint_calls_notifier() -> None:
    app, gateway = client()
    response = app.post("/api/test-notification", headers=auth())
    assert response.status_code == 202
    assert response.json() == {"accepted": True}
    assert gateway.notification_count == 1


def test_local_health_endpoint_does_not_expose_credentials() -> None:
    app, _ = client()
    response = app.get("/healthz")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}
    assert "secret" not in response.text


def test_ptz_step_requires_basic_authentication_before_adapter_access() -> None:
    adapter = RecordingPtzAdapter()
    ptz = StepPtzController(adapter=adapter, minimum_interval_seconds=0)
    app, _ = client(ptz=ptz)

    response = app.post("/api/ptz/step", json={"direction": "left"})

    assert response.status_code == 401
    assert adapter.directions == []


def test_unknown_ptz_direction_is_rejected_before_adapter_access() -> None:
    adapter = RecordingPtzAdapter()
    ptz = StepPtzController(adapter=adapter, minimum_interval_seconds=0)
    app, _ = client(ptz=ptz)

    response = app.post(
        "/api/ptz/step", headers=auth(), json={"direction": "diagonal"}
    )

    assert response.status_code == 422
    assert adapter.directions == []


def test_ptz_request_rejects_unbounded_control_fields() -> None:
    adapter = RecordingPtzAdapter()
    ptz = StepPtzController(adapter=adapter, minimum_interval_seconds=0)
    app, _ = client(ptz=ptz)

    response = app.post(
        "/api/ptz/step",
        headers=auth(),
        json={"direction": "left", "duration": 30, "payload": "raw"},
    )

    assert response.status_code == 422
    assert adapter.directions == []


def test_one_ptz_request_causes_exactly_one_closed_step() -> None:
    adapter = RecordingPtzAdapter()
    ptz = StepPtzController(adapter=adapter, minimum_interval_seconds=0.75)
    app, _ = client(ptz=ptz)

    response = app.post(
        "/api/ptz/step", headers=auth(), json={"direction": "left"}
    )

    assert response.status_code == 200
    assert response.json() == {"result": "PTZ_OK", "cooldown_ms": 750}
    assert adapter.directions == [PtzDirection.LEFT]


def test_disabled_ptz_returns_stable_redacted_response() -> None:
    adapter = RecordingPtzAdapter(result=PtzCode.DISABLED)
    ptz = StepPtzController(adapter=adapter)
    app, _ = client(ptz=ptz)

    response = app.post(
        "/api/ptz/step", headers=auth(), json={"direction": "right"}
    )

    assert response.status_code == 503
    assert response.json() == {"result": "PTZ_DISABLED", "cooldown_ms": 0}
    assert adapter.directions == [PtzDirection.RIGHT]


@pytest.mark.parametrize(
    ("code", "expected_status", "expected_cooldown"),
    [
        (PtzCode.BUSY, 429, 750),
        (PtzCode.TIMEOUT, 504, 0),
        (PtzCode.UNAVAILABLE, 502, 0),
    ],
)
def test_ptz_fail_closed_results_use_stable_http_mapping(
    code: PtzCode,
    expected_status: int,
    expected_cooldown: int,
) -> None:
    adapter = RecordingPtzAdapter(result=code)
    ptz = StepPtzController(adapter=adapter)
    app, _ = client(ptz=ptz)

    response = app.post(
        "/api/ptz/step", headers=auth(), json={"direction": "up"}
    )

    assert response.status_code == expected_status
    assert response.json() == {
        "result": code.value,
        "cooldown_ms": expected_cooldown,
    }
    assert adapter.directions == [PtzDirection.UP]
