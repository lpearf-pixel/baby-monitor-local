from __future__ import annotations

import secrets
import re
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from collections.abc import Awaitable, Callable, Mapping
from typing import Annotated, Iterator, Literal, Protocol

from fastapi import Depends, FastAPI, HTTPException, Query, Request, WebSocket, status
from fastapi.encoders import jsonable_encoder
from fastapi.responses import (
    HTMLResponse,
    JSONResponse,
    RedirectResponse,
    Response,
    StreamingResponse,
)
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from pydantic import BaseModel, ConfigDict, Field
from starlette.websockets import WebSocketDisconnect

from apps.api.hd_stream import (
    HdBrowserSocket,
    HdBusyError,
    HdClientDisconnected,
    HdProfile,
    HdStreamService,
    HdTicket,
)

from apps.api.ptz import (
    DisabledPtzAdapter,
    PtzCode,
    PtzDirection,
    StepPtzController,
)
from services.dashboard.contracts import (
    DashboardAlertListV1,
    DashboardAnalyticsV1,
    DashboardOverviewV1,
    DashboardSystemV1,
    DashboardWindow,
)
from services.dashboard.service import DashboardServiceUnavailable
from services.events.environment_state import EnvironmentIncident, EnvironmentSnapshot
from services.events.guardian_query import (
    GuardianEventList,
    GuardianEventQueryUnavailable,
)
from services.gauge.calibration import (
    GaugeFace,
    GaugeQuadrilateral,
    NormalizedRect,
)
from services.storage.environment import EnvironmentTrend, TrendWindow


class AlphaGateway(Protocol):
    def status(self) -> dict[str, object]: ...

    def iter_mjpeg(self) -> Iterator[bytes]: ...

    def snapshot(self, viewport: "SnapshotViewport") -> bytes: ...

    def send_test_notification(self) -> None: ...


class AlphaHdStream(Protocol):
    def issue_ticket(self, profile: HdProfile) -> HdTicket: ...

    async def serve(self, socket: HdBrowserSocket) -> None: ...


class AlphaEnvironment(Protocol):
    def current(self, now: datetime) -> EnvironmentSnapshot: ...

    def trend(self, window: TrendWindow, now: datetime) -> EnvironmentTrend: ...

    def incidents(self) -> tuple[EnvironmentIncident, ...]: ...

    def calibration_status(self) -> dict[str, object]: ...

    def save_calibration(
        self,
        draft: "GaugeCalibrationSaveRequest",
        reference_jpeg: bytes,
        now: datetime,
    ) -> dict[str, object]: ...


class AlphaGuardianEvents(Protocol):
    def recent_events(self) -> GuardianEventList: ...


class AlphaDashboard(Protocol):
    def overview(self, now: datetime) -> DashboardOverviewV1: ...

    def alerts(self, now: datetime) -> DashboardAlertListV1: ...

    def analytics(
        self,
        window: DashboardWindow,
        now: datetime,
    ) -> DashboardAnalyticsV1: ...

    def system(self, now: datetime) -> DashboardSystemV1: ...


class StarletteHdSocket:
    def __init__(self, socket: WebSocket) -> None:
        self._socket = socket

    @property
    def headers(self) -> Mapping[str, str]:
        return self._socket.headers

    @property
    def peer_host(self) -> str | None:
        return self._socket.client.host if self._socket.client else None

    async def accept(self) -> None:
        await self._socket.accept()

    async def receive(self) -> str | bytes:
        try:
            message = await self._socket.receive()
        except WebSocketDisconnect as exc:
            raise HdClientDisconnected from exc
        if message["type"] == "websocket.disconnect":
            raise HdClientDisconnected
        if message.get("text") is not None:
            return message["text"]
        if message.get("bytes") is not None:
            return message["bytes"]
        raise HdClientDisconnected

    async def wait_for_disconnect(self) -> None:
        try:
            await self.receive()
        except HdClientDisconnected:
            raise
        await self.close(code=1008)
        raise HdClientDisconnected

    async def send_text(self, value: str) -> None:
        try:
            await self._socket.send_text(value)
        except (RuntimeError, WebSocketDisconnect) as exc:
            raise HdClientDisconnected from exc

    async def send_bytes(self, value: bytes) -> None:
        try:
            await self._socket.send_bytes(value)
        except (RuntimeError, WebSocketDisconnect) as exc:
            raise HdClientDisconnected from exc

    async def close(self, *, code: int, reason: str = "") -> None:
        try:
            await self._socket.close(code=code, reason=reason)
        except (RuntimeError, WebSocketDisconnect) as exc:
            raise HdClientDisconnected from exc


@dataclass(frozen=True)
class AlphaRuntime:
    username: str
    password: str
    stream_name: str
    gateway: AlphaGateway
    ptz: StepPtzController = field(
        default_factory=lambda: StepPtzController(adapter=DisabledPtzAdapter())
    )
    hd_stream: AlphaHdStream = field(default_factory=HdStreamService)
    environment: AlphaEnvironment | None = None
    guardian_events: AlphaGuardianEvents | None = None
    dashboard: AlphaDashboard | None = None


class SnapshotViewport(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    zoom: int = Field(default=1, ge=1, le=3)
    center_x: float = Field(default=0.5, ge=0.0, le=1.0)
    center_y: float = Field(default=0.5, ge=0.0, le=1.0)


class PtzStepRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    direction: PtzDirection


class HdSessionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    profile: HdProfile


class GaugeCalibrationSaveRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    source_width: int = Field(gt=0, le=4096)
    source_height: int = Field(gt=0, le=2160)
    orientation: Literal["landscape", "portrait"]
    zoom: Literal[2, 3]
    center_x: float = Field(ge=0, le=1)
    center_y: float = Field(ge=0, le=1)
    gauge_quadrilateral: GaugeQuadrilateral
    gauge_rect: NormalizedRect
    humidity: GaugeFace
    temperature: GaugeFace


_VIEWER_SCRIPT = Path(__file__).with_name("dashboard_viewer.js")
_HD_PLAYER_SCRIPT = Path(__file__).with_name("hd_player.js")
_ENVIRONMENT_SCRIPT = Path(__file__).with_name("environment_dashboard.js")
_GAUGE_CALIBRATION_SCRIPT = Path(__file__).with_name("gauge_calibration.js")
_GUARDIAN_EVENTS_SCRIPT = Path(__file__).with_name("guardian_events.js")
_DASHBOARD_STYLE = Path(__file__).with_name("dashboard.css")
_INCIDENT_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
_DASHBOARD_NO_STORE_ASSETS = frozenset(
    {
        "/assets/dashboard.css",
        "/assets/dashboard-views.js",
        "/assets/dashboard-analytics.js",
        "/assets/dashboard-shell.js",
    }
)


_DASHBOARD = """<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">
  <title>Baby Monitor Local Alpha</title>
  <link rel="stylesheet" href="/assets/dashboard.css">
</head>
<body>
<main class="dashboard-shell">
  <header class="dashboard-header">
    <h1>Baby Monitor Local</h1>
    <p id="dashboard-health" role="status">正在读取本地监控状态…</p>
  </header>
  <nav class="dashboard-tabs" role="tablist" aria-label="监控页面">
    <button id="tab-overview" type="button" role="tab" tabindex="0" aria-controls="dashboard-overview" aria-selected="true">总览</button>
    <button id="tab-alerts" type="button" role="tab" tabindex="-1" aria-controls="dashboard-alerts" aria-selected="false">警报 <span id="alert-count" hidden></span></button>
    <button id="tab-analytics" type="button" role="tab" tabindex="-1" aria-controls="dashboard-analytics" aria-selected="false">数据</button>
    <button id="tab-system" type="button" role="tab" tabindex="-1" aria-controls="dashboard-system" aria-selected="false">系统</button>
  </nav>
  <section id="global-attention" role="status" hidden></section>
  <section id="dashboard-overview" role="tabpanel" aria-labelledby="tab-overview">
    <div class="overview-grid">
      <section class="card viewer-card" aria-label="实时画面">
        <div id="viewer" class="viewer" aria-label="婴儿监控实时画面查看器">
          <div id="media-plane" class="media-plane">
            <img id="live-image" class="video media-layer" src="/live.mjpeg" alt="婴儿床实时画面" draggable="false" aria-hidden="false">
            <video id="hd-video" class="video media-layer" muted playsinline preload="none" aria-hidden="true"></video>
          </div>
          <div class="viewer-controls" role="toolbar" aria-label="画面显示控制">
            <button class="zoom-button" type="button" data-zoom="1" aria-pressed="true" aria-label="显示一倍画面">1×</button>
            <button class="zoom-button" type="button" data-zoom="2" aria-pressed="false" aria-label="显示两倍画面">2×</button>
            <button class="zoom-button" type="button" data-zoom="3" aria-pressed="false" aria-label="显示三倍画面">3×</button>
            <button id="fullscreen" type="button" aria-label="进入全屏" aria-describedby="fullscreen-help">全屏</button>
          </div>
          <div class="ptz-panel" role="group" aria-label="物理摄像头点按步进控制">
            <button class="ptz-button" type="button" data-direction="up" aria-label="摄像头向上移动一步">↑</button>
            <button class="ptz-button" type="button" data-direction="left" aria-label="摄像头向左移动一步">←</button>
            <button class="ptz-button" type="button" data-direction="right" aria-label="摄像头向右移动一步">→</button>
            <button class="ptz-button" type="button" data-direction="down" aria-label="摄像头向下移动一步">↓</button>
          </div>
          <p id="ptz-status" class="ptz-status" aria-live="polite">PTZ_DISABLED：真实云台协议尚未启用</p>
          <p id="hd-status" class="hd-status" aria-live="polite"></p>
          <span id="fullscreen-help" class="visually-hidden">全屏不可用时仍可使用数码变焦</span>
        </div>
      </section>
      <div class="overview-stack">
        <section id="overview-environment" class="card" aria-labelledby="environment-title">
          <h2 id="environment-title">环境监测</h2>
          <p id="environment-current" aria-live="polite">正在读取…</p>
          <p id="environment-detail" class="muted"></p>
          <p class="environment-last-valid"><span>最近一次有效：</span><span id="environment-last-valid">无</span></p>
          <p class="row"><button id="environment-trend-24h" type="button">24小时</button><button id="environment-trend-7d" type="button">7天</button></p>
          <canvas id="environment-trend" width="900" height="220" aria-label="24小时温湿度趋势"></canvas>
          <pre id="environment-incidents" aria-label="环境事件">无环境事件</pre>
        </section>
        <section id="overview-guardian" class="card" aria-labelledby="guardian-events-title">
          <div class="row"><h2 id="guardian-events-title">Guardian 事件</h2><span class="muted">最近 20 条</span></div>
          <p id="guardian-events-stale" class="stale-warning" role="status" hidden></p>
          <ol id="guardian-events" class="guardian-events" aria-live="polite"><li>正在读取…</li></ol>
          <p class="muted">本页面仅显示事件与证据状态，不提供图片或视频访问。</p>
        </section>
      </div>
    </div>
    <section id="overview-components" class="card compact-card"><h2>组件状态</h2><p class="muted">正在读取组件状态…</p></section>
    <section id="overview-recent" class="card compact-card"><h2>最近活动</h2><p class="muted">正在读取最近活动…</p></section>
    <p class="panel-meta"><span id="overview-updated">尚未更新</span><span id="overview-stale" class="is-stale" hidden>数据可能已过期</span></p>
  </section>
  <section id="dashboard-alerts" role="tabpanel" aria-labelledby="tab-alerts" hidden>
    <div class="card">
      <h2>警报</h2>
      <div class="filter-group" role="group" aria-label="警报来源"><button type="button" data-alert-source="all" aria-pressed="true">全部来源</button><button type="button" data-alert-source="guardian" aria-pressed="false">Guardian</button><button type="button" data-alert-source="environment" aria-pressed="false">环境</button><button type="button" data-alert-source="system" aria-pressed="false">系统</button></div>
      <div class="filter-group" role="group" aria-label="警报状态"><button type="button" data-alert-state="all" aria-pressed="true">全部状态</button><button type="button" data-alert-state="open" aria-pressed="false">处理中</button><button type="button" data-alert-state="recovered" aria-pressed="false">已恢复</button></div>
      <p id="alerts-announcement" class="visually-hidden" aria-live="polite"></p>
      <ol id="alerts-list" class="dashboard-list"><li>正在读取警报…</li></ol>
      <p class="panel-meta"><span id="alerts-updated">尚未更新</span><span id="alerts-stale" class="is-stale" hidden>数据可能已过期</span></p>
    </div>
  </section>
  <section id="dashboard-analytics" role="tabpanel" aria-labelledby="tab-analytics" hidden>
    <div class="card">
      <div class="row"><h2>数据</h2><button id="analytics-refresh" type="button">刷新数据</button></div>
      <div class="filter-group" role="group" aria-label="数据时间范围"><button type="button" data-analytics-window="24h" aria-pressed="true">24小时</button><button type="button" data-analytics-window="7d" aria-pressed="false">7天</button></div>
      <div class="kpi-grid"><article id="analytics-environment-kpi" class="kpi-card"><h3>环境</h3><p>正在读取…</p></article><article id="analytics-guardian-kpi" class="kpi-card"><h3>Guardian</h3><p>正在读取…</p></article><article id="analytics-notification-kpi" class="kpi-card"><h3>通知</h3><p>正在读取…</p></article><article id="analytics-coverage-kpi" class="kpi-card"><h3>覆盖率</h3><p>正在读取…</p></article></div>
      <section id="analytics-trend" class="chart-card" aria-label="数据趋势">正在读取趋势…</section>
      <p id="analytics-summary" class="muted">正在读取摘要…</p>
      <div id="analytics-table" class="data-table" aria-label="数据明细">正在读取明细…</div>
      <p class="panel-meta"><span id="analytics-updated">尚未更新</span><span id="analytics-stale" class="is-stale" hidden>数据可能已过期</span></p>
    </div>
  </section>
  <section id="dashboard-system" role="tabpanel" aria-labelledby="tab-system" hidden>
    <div class="card">
      <div class="row"><h2>系统</h2><button id="system-refresh" type="button">刷新系统状态</button></div>
      <div id="system-components" class="component-grid">正在读取组件状态…</div>
      <div class="row maintenance-controls"><a id="snapshot-link" class="button" href="/snapshot.jpeg?zoom=1&amp;center_x=0.500000&amp;center_y=0.500000" target="_blank" rel="noopener">打开当前截图</a><button id="notify" type="button">发送测试通知</button><button id="gauge-calibration" type="button">标定温湿度计</button></div>
      <p class="panel-meta"><span id="system-updated">尚未更新</span><span id="system-stale" class="is-stale" hidden>数据可能已过期</span></p>
    </div>
  </section>
</main>
<script>
document.getElementById('notify').onclick = async () => {
  const response = await fetch('/api/test-notification', {method: 'POST'});
  alert(response.ok ? '测试通知已发送' : '发送失败，请检查 ntfy 配置');
};
</script>
<script defer src="/assets/hd-player.js"></script>
<script defer src="/assets/dashboard-viewer.js"></script>
<script defer src="/assets/environment-dashboard.js"></script>
<script defer src="/assets/gauge-calibration.js"></script>
<script defer src="/assets/guardian-events.js"></script>
</body>
</html>
"""


def create_app(runtime: AlphaRuntime) -> FastAPI:
    app = FastAPI(title="Baby Monitor Local Alpha", docs_url=None, redoc_url=None)
    security = HTTPBasic(auto_error=False)

    @app.middleware("http")
    async def dashboard_no_store(
        request: Request,
        call_next: Callable[[Request], Awaitable[Response]],
    ) -> Response:
        response = await call_next(request)
        if (
            request.url.path.startswith("/api/dashboard/")
            or request.url.path in _DASHBOARD_NO_STORE_ASSETS
        ):
            response.headers["Cache-Control"] = "no-store"
        return response

    def require_parent(
        credentials: HTTPBasicCredentials | None = Depends(security),
    ) -> str:
        if credentials is None:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                headers={"WWW-Authenticate": "Basic"},
            )
        username_ok = secrets.compare_digest(
            credentials.username.encode("utf-8"), runtime.username.encode("utf-8")
        )
        password_ok = secrets.compare_digest(
            credentials.password.encode("utf-8"), runtime.password.encode("utf-8")
        )
        if not (username_ok and password_ok):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                headers={"WWW-Authenticate": "Basic"},
            )
        return credentials.username

    @app.get("/healthz")
    def healthz() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/", response_class=HTMLResponse)
    def dashboard(_parent: str = Depends(require_parent)) -> HTMLResponse:
        return HTMLResponse(
            content=_DASHBOARD,
            headers={"Cache-Control": "no-store"},
        )

    @app.get("/assets/dashboard.css")
    def dashboard_style(
        _parent: str = Depends(require_parent),
    ) -> Response:
        return Response(
            content=_DASHBOARD_STYLE.read_text(encoding="utf-8"),
            media_type="text/css",
            headers={"Cache-Control": "no-store"},
        )

    @app.get("/assets/dashboard-viewer.js")
    def dashboard_viewer_script(
        _parent: str = Depends(require_parent),
    ) -> Response:
        return Response(
            content=_VIEWER_SCRIPT.read_text(encoding="utf-8"),
            media_type="text/javascript",
            headers={"Cache-Control": "no-store"},
        )

    @app.get("/assets/hd-player.js")
    def hd_player_script(
        _parent: str = Depends(require_parent),
    ) -> Response:
        return Response(
            content=_HD_PLAYER_SCRIPT.read_text(encoding="utf-8"),
            media_type="text/javascript",
            headers={"Cache-Control": "no-store"},
        )

    @app.get("/assets/environment-dashboard.js")
    def environment_dashboard_script(
        _parent: str = Depends(require_parent),
    ) -> Response:
        return Response(
            content=_ENVIRONMENT_SCRIPT.read_text(encoding="utf-8"),
            media_type="text/javascript",
            headers={"Cache-Control": "no-store"},
        )

    @app.get("/assets/gauge-calibration.js")
    def gauge_calibration_script(
        _parent: str = Depends(require_parent),
    ) -> Response:
        return Response(
            content=_GAUGE_CALIBRATION_SCRIPT.read_text(encoding="utf-8"),
            media_type="text/javascript",
            headers={"Cache-Control": "no-store"},
        )

    @app.get("/assets/guardian-events.js")
    def guardian_events_script(
        _parent: str = Depends(require_parent),
    ) -> Response:
        return Response(
            content=_GUARDIAN_EVENTS_SCRIPT.read_text(encoding="utf-8"),
            media_type="text/javascript",
            headers={"Cache-Control": "no-store"},
        )

    def environment_service() -> AlphaEnvironment:
        if runtime.environment is None:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="ENVIRONMENT_DISABLED",
            )
        return runtime.environment

    def guardian_event_service() -> AlphaGuardianEvents:
        if runtime.guardian_events is None:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="GUARDIAN_EVENTS_UNAVAILABLE",
            )
        return runtime.guardian_events

    def dashboard_service() -> AlphaDashboard:
        if runtime.dashboard is None:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="DASHBOARD_DATA_UNAVAILABLE",
            )
        return runtime.dashboard

    @app.get("/api/dashboard/overview")
    def dashboard_overview(
        _parent: str = Depends(require_parent),
    ) -> JSONResponse:
        try:
            result = dashboard_service().overview(datetime.now(UTC))
        except DashboardServiceUnavailable:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="DASHBOARD_DATA_UNAVAILABLE",
            ) from None
        return JSONResponse(
            content=jsonable_encoder(result),
            headers={"Cache-Control": "no-store"},
        )

    @app.get("/api/dashboard/alerts")
    def dashboard_alerts(
        _parent: str = Depends(require_parent),
    ) -> JSONResponse:
        try:
            result = dashboard_service().alerts(datetime.now(UTC))
        except DashboardServiceUnavailable:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="DASHBOARD_DATA_UNAVAILABLE",
            ) from None
        return JSONResponse(
            content=jsonable_encoder(result),
            headers={"Cache-Control": "no-store"},
        )

    @app.get("/api/dashboard/analytics/{window}")
    def dashboard_analytics(
        window: Literal["24h", "7d"],
        _parent: str = Depends(require_parent),
    ) -> JSONResponse:
        try:
            result = dashboard_service().analytics(
                DashboardWindow(window),
                datetime.now(UTC),
            )
        except DashboardServiceUnavailable:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="DASHBOARD_DATA_UNAVAILABLE",
            ) from None
        return JSONResponse(
            content=jsonable_encoder(result),
            headers={"Cache-Control": "no-store"},
        )

    @app.get("/api/dashboard/system")
    def dashboard_system(
        _parent: str = Depends(require_parent),
    ) -> JSONResponse:
        try:
            result = dashboard_service().system(datetime.now(UTC))
        except DashboardServiceUnavailable:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="DASHBOARD_DATA_UNAVAILABLE",
            ) from None
        return JSONResponse(
            content=jsonable_encoder(result),
            headers={"Cache-Control": "no-store"},
        )

    @app.get("/api/guardian/events")
    def guardian_events(
        _parent: str = Depends(require_parent),
    ) -> JSONResponse:
        try:
            result = guardian_event_service().recent_events()
        except GuardianEventQueryUnavailable:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="GUARDIAN_EVENTS_UNAVAILABLE",
            ) from None
        return JSONResponse(
            content=jsonable_encoder(result),
            headers={"Cache-Control": "no-store"},
        )

    @app.get("/incidents/{incident_id}")
    def open_environment_incident(
        incident_id: str,
        _parent: str = Depends(require_parent),
    ) -> RedirectResponse:
        if not _INCIDENT_ID.fullmatch(incident_id):
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
        return RedirectResponse(
            url=f"/#environment-incident={incident_id}",
            status_code=status.HTTP_303_SEE_OTHER,
            headers={"Cache-Control": "no-store"},
        )

    @app.get("/api/environment/current")
    def environment_current(
        _parent: str = Depends(require_parent),
    ) -> JSONResponse:
        snapshot = environment_service().current(datetime.now(UTC))
        return JSONResponse(
            content=jsonable_encoder(snapshot),
            headers={"Cache-Control": "no-store"},
        )

    @app.get("/api/environment/trends/{window}")
    def environment_trend(
        window: Literal["24h", "7d"],
        _parent: str = Depends(require_parent),
    ) -> JSONResponse:
        trend = environment_service().trend(TrendWindow(window), datetime.now(UTC))
        return JSONResponse(
            content=jsonable_encoder(trend),
            headers={"Cache-Control": "no-store"},
        )

    @app.get("/api/environment/incidents")
    def environment_incidents(
        _parent: str = Depends(require_parent),
    ) -> JSONResponse:
        incidents = environment_service().incidents()
        return JSONResponse(
            content=jsonable_encoder({"incidents": incidents}),
            headers={"Cache-Control": "no-store"},
        )

    @app.get("/api/gauge-calibration")
    def gauge_calibration_status(
        _parent: str = Depends(require_parent),
    ) -> JSONResponse:
        return JSONResponse(
            content=jsonable_encoder(environment_service().calibration_status()),
            headers={"Cache-Control": "no-store"},
        )

    @app.put("/api/gauge-calibration", status_code=status.HTTP_201_CREATED)
    def save_gauge_calibration(
        request: GaugeCalibrationSaveRequest,
        _parent: str = Depends(require_parent),
    ) -> JSONResponse:
        reference = runtime.gateway.snapshot(
            SnapshotViewport(
                zoom=request.zoom,
                center_x=request.center_x,
                center_y=request.center_y,
            )
        )
        result = environment_service().save_calibration(
            request,
            reference,
            datetime.now(UTC),
        )
        return JSONResponse(
            status_code=status.HTTP_201_CREATED,
            content=jsonable_encoder(result),
            headers={"Cache-Control": "no-store"},
        )

    @app.get("/api/status")
    def camera_status(_parent: str = Depends(require_parent)) -> dict[str, object]:
        return runtime.gateway.status()

    @app.post("/api/ptz/step")
    def ptz_step(
        request: PtzStepRequest,
        _parent: str = Depends(require_parent),
    ) -> JSONResponse:
        result = runtime.ptz.step(request.direction)
        status_by_code = {
            PtzCode.OK: status.HTTP_200_OK,
            PtzCode.BUSY: status.HTTP_429_TOO_MANY_REQUESTS,
            PtzCode.DISABLED: status.HTTP_503_SERVICE_UNAVAILABLE,
            PtzCode.UNAVAILABLE: status.HTTP_502_BAD_GATEWAY,
            PtzCode.TIMEOUT: status.HTTP_504_GATEWAY_TIMEOUT,
        }
        return JSONResponse(
            status_code=status_by_code[result.code],
            content=result.as_dict(),
        )

    @app.post("/api/hd-session")
    def hd_session(
        request: HdSessionRequest,
        _parent: str = Depends(require_parent),
    ) -> JSONResponse:
        try:
            ticket = runtime.hd_stream.issue_ticket(request.profile)
        except HdBusyError:
            return JSONResponse(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                content={"result": "HD_BUSY"},
                headers={"Cache-Control": "no-store"},
            )
        return JSONResponse(
            status_code=status.HTTP_201_CREATED,
            content={"ticket": ticket.value, "expires_in": ticket.expires_in},
            headers={"Cache-Control": "no-store"},
        )

    @app.websocket("/live-hd.ws")
    async def live_hd(websocket: WebSocket) -> None:
        if websocket.url.query:
            await websocket.close(code=1008)
            return
        await runtime.hd_stream.serve(StarletteHdSocket(websocket))

    @app.get("/live.mjpeg")
    def live_mjpeg(_parent: str = Depends(require_parent)) -> StreamingResponse:
        return StreamingResponse(
            runtime.gateway.iter_mjpeg(),
            media_type="multipart/x-mixed-replace; boundary=frame",
            headers={"Cache-Control": "no-store"},
        )

    @app.get("/snapshot.jpeg")
    def snapshot(
        viewport: Annotated[SnapshotViewport, Query()],
        _parent: str = Depends(require_parent),
    ) -> Response:
        return Response(
            content=runtime.gateway.snapshot(viewport),
            media_type="image/jpeg",
            headers={"Cache-Control": "no-store"},
        )

    @app.post("/api/test-notification", status_code=status.HTTP_202_ACCEPTED)
    def test_notification(_parent: str = Depends(require_parent)) -> dict[str, bool]:
        runtime.gateway.send_test_notification()
        return {"accepted": True}

    return app
