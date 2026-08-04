from __future__ import annotations

import secrets
from dataclasses import dataclass, field
from pathlib import Path
from collections.abc import Mapping
from typing import Iterator, Protocol

from fastapi import Depends, FastAPI, HTTPException, WebSocket, status
from fastapi.responses import HTMLResponse, JSONResponse, Response, StreamingResponse
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from pydantic import BaseModel, ConfigDict
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


class AlphaGateway(Protocol):
    def status(self) -> dict[str, object]: ...

    def iter_mjpeg(self) -> Iterator[bytes]: ...

    def snapshot(self) -> bytes: ...

    def send_test_notification(self) -> None: ...


class AlphaHdStream(Protocol):
    def issue_ticket(self, profile: HdProfile) -> HdTicket: ...

    async def serve(self, socket: HdBrowserSocket) -> None: ...


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


class PtzStepRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    direction: PtzDirection


class HdSessionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    profile: HdProfile


_VIEWER_SCRIPT = Path(__file__).with_name("dashboard_viewer.js")
_HD_PLAYER_SCRIPT = Path(__file__).with_name("hd_player.js")


_DASHBOARD = """<!doctype html>
<html lang="zh-CN">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">
  <title>Baby Monitor Local Alpha</title>
  <style>
    :root { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; color-scheme: dark; }
    body { margin: 0; background: #101114; color: #f5f5f5; }
    main { max-width: 980px; margin: auto; padding: 16px; }
    .card { background: #1a1c21; border-radius: 16px; padding: 14px; margin-bottom: 14px; box-shadow: 0 8px 30px #0005; }
    .viewer { position: relative; width: 100%; aspect-ratio: 16 / 9; overflow: hidden; background: #000; border-radius: 12px; touch-action: pan-y; user-select: none; }
    .viewer.is-zoomed { touch-action: none; cursor: grab; }
    .viewer.is-dragging { cursor: grabbing; }
    .media-plane { position: absolute; left: 50%; top: 50%; width: 100%; aspect-ratio: 16 / 9; transform: translate3d(-50%, -50%, 0) scale(1); transform-origin: center; will-change: transform; }
    .video { display: block; width: 100%; height: 100%; object-fit: cover; background: #000; -webkit-user-drag: none; }
    .media-layer { position: absolute; inset: 0; }
    .media-layer[aria-hidden="true"] { visibility: hidden; }
    .viewer-controls { position: absolute; z-index: 2; top: 10px; left: 10px; display: flex; flex-wrap: wrap; gap: 8px; max-width: calc(100% - 20px); }
    .ptz-panel { position: absolute; z-index: 2; right: 10px; bottom: 10px; display: grid; grid-template-columns: repeat(3, 44px); grid-template-rows: repeat(3, 44px); gap: 4px; }
    .ptz-button[data-direction="up"] { grid-column: 2; grid-row: 1; }
    .ptz-button[data-direction="left"] { grid-column: 1; grid-row: 2; }
    .ptz-button[data-direction="right"] { grid-column: 3; grid-row: 2; }
    .ptz-button[data-direction="down"] { grid-column: 2; grid-row: 3; }
    .viewer button { min-width: 44px; min-height: 44px; padding: 8px 12px; background: #15171dcc; color: #fff; border: 1px solid #ffffff55; backdrop-filter: blur(8px); }
    .viewer button[aria-pressed="true"] { background: #fff; color: #111; }
    .viewer button:disabled { opacity: .55; }
    .viewer button:focus-visible, button:focus-visible, a.button:focus-visible { outline: 3px solid #74b9ff; outline-offset: 2px; }
    .ptz-status, .hd-status { position: absolute; z-index: 2; left: 12px; max-width: calc(100% - 174px); margin: 0; padding: 7px 10px; border-radius: 9px; color: #eef2f7; background: #111b; font-size: .82rem; }
    .ptz-status { bottom: 48px; }
    .hd-status { bottom: 10px; }
    .sr-only { position: absolute; width: 1px; height: 1px; padding: 0; margin: -1px; overflow: hidden; clip: rect(0, 0, 0, 0); white-space: nowrap; border: 0; }
    .viewer:fullscreen { width: 100vw; height: 100vh; aspect-ratio: auto; border-radius: 0; }
    @media (min-aspect-ratio: 16 / 9) { .viewer:fullscreen .media-plane { width: auto; height: 100%; } }
    .row { display: flex; flex-wrap: wrap; gap: 10px; align-items: center; }
    button, a.button { border: 0; border-radius: 12px; padding: 12px 16px; font-weight: 650; background: #e8e8e8; color: #111; text-decoration: none; }
    .muted { color: #aeb4bf; }
    pre { white-space: pre-wrap; overflow-wrap: anywhere; }
  </style>
</head>
<body>
<main>
  <section class="card">
    <h1>Baby Monitor Local Alpha</h1>
    <p class="muted">基础可用版：实时画面、截图、在线状态、通知测试。双向语音暂时使用米家 App。</p>
  </section>
  <section class="card">
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
      <span id="fullscreen-help" class="sr-only">全屏不可用时仍可使用数码变焦</span>
    </div>
  </section>
  <section class="card row">
    <a class="button" href="/snapshot.jpeg" target="_blank" rel="noopener">打开当前截图</a>
    <button id="notify" type="button">发送测试通知</button>
    <button id="refresh" type="button">刷新状态</button>
  </section>
  <section class="card">
    <strong>系统状态</strong>
    <pre id="status">正在读取…</pre>
  </section>
</main>
<script>
async function refreshStatus() {
  const target = document.getElementById('status');
  try {
    const response = await fetch('/api/status');
    target.textContent = JSON.stringify(await response.json(), null, 2);
  } catch (error) {
    target.textContent = String(error);
  }
}
document.getElementById('refresh').onclick = refreshStatus;
document.getElementById('notify').onclick = async () => {
  const response = await fetch('/api/test-notification', {method: 'POST'});
  alert(response.ok ? '测试通知已发送' : '发送失败，请检查 ntfy 配置');
};
refreshStatus();
setInterval(refreshStatus, 15000);
</script>
<script defer src="/assets/hd-player.js"></script>
<script defer src="/assets/dashboard-viewer.js"></script>
</body>
</html>
"""


def create_app(runtime: AlphaRuntime) -> FastAPI:
    app = FastAPI(title="Baby Monitor Local Alpha", docs_url=None, redoc_url=None)
    security = HTTPBasic(auto_error=False)

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
    def dashboard(_parent: str = Depends(require_parent)) -> str:
        return _DASHBOARD

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
    def snapshot(_parent: str = Depends(require_parent)) -> Response:
        return Response(
            content=runtime.gateway.snapshot(),
            media_type="image/jpeg",
            headers={"Cache-Control": "no-store"},
        )

    @app.post("/api/test-notification", status_code=status.HTTP_202_ACCEPTED)
    def test_notification(_parent: str = Depends(require_parent)) -> dict[str, bool]:
        runtime.gateway.send_test_notification()
        return {"accepted": True}

    return app
