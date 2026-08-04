from __future__ import annotations

import secrets
from dataclasses import dataclass
from typing import Iterator, Protocol

from fastapi import Depends, FastAPI, HTTPException, status
from fastapi.responses import HTMLResponse, Response, StreamingResponse
from fastapi.security import HTTPBasic, HTTPBasicCredentials


class AlphaGateway(Protocol):
    def status(self) -> dict[str, object]: ...

    def iter_mjpeg(self) -> Iterator[bytes]: ...

    def snapshot(self) -> bytes: ...

    def send_test_notification(self) -> None: ...


@dataclass(frozen=True)
class AlphaRuntime:
    username: str
    password: str
    stream_name: str
    gateway: AlphaGateway


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
    .video { width: 100%; min-height: 220px; object-fit: contain; background: #000; border-radius: 12px; }
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
    <img class="video" src="/live.mjpeg" alt="婴儿床实时画面">
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

    @app.get("/api/status")
    def camera_status(_parent: str = Depends(require_parent)) -> dict[str, object]:
        return runtime.gateway.status()

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
