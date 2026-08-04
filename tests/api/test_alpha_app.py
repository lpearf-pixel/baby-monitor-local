from __future__ import annotations

import base64
from dataclasses import dataclass
from typing import Iterator

from fastapi.testclient import TestClient

from apps.api.alpha import AlphaRuntime, create_app


def auth(username: str = "parent", password: str = "secret") -> dict[str, str]:
    token = base64.b64encode(f"{username}:{password}".encode()).decode()
    return {"Authorization": f"Basic {token}"}


@dataclass
class FakeGateway:
    healthy: bool = True
    notification_count: int = 0

    def status(self) -> dict[str, object]:
        return {"camera": "online" if self.healthy else "offline", "stream": "live"}

    def iter_mjpeg(self) -> Iterator[bytes]:
        yield b"--frame\r\nContent-Type: image/jpeg\r\n\r\nJPEG\r\n"

    def snapshot(self) -> bytes:
        return b"JPEG-SNAPSHOT"

    def send_test_notification(self) -> None:
        self.notification_count += 1


def client(gateway: FakeGateway | None = None) -> tuple[TestClient, FakeGateway]:
    fake = gateway or FakeGateway()
    runtime = AlphaRuntime(
        username="parent",
        password="secret",
        stream_name="live",
        gateway=fake,
    )
    return TestClient(create_app(runtime)), fake


def test_dashboard_requires_basic_authentication() -> None:
    app, _ = client()

    response = app.get("/")

    assert response.status_code == 401
    assert response.headers["www-authenticate"] == "Basic"


def test_dashboard_loads_after_authentication() -> None:
    app, _ = client()

    response = app.get("/", headers=auth())

    assert response.status_code == 200
    assert "Baby Monitor Local Alpha" in response.text
    assert "/live.mjpeg" in response.text
    assert "/snapshot.jpeg" in response.text


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


def test_snapshot_proxy_returns_jpeg() -> None:
    app, _ = client()

    response = app.get("/snapshot.jpeg", headers=auth())

    assert response.status_code == 200
    assert response.headers["content-type"] == "image/jpeg"
    assert response.content == b"JPEG-SNAPSHOT"


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
