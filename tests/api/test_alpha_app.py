from __future__ import annotations

import base64
import re
from dataclasses import dataclass, field
from typing import Iterator

from fastapi.testclient import TestClient
import pytest
from starlette.websockets import WebSocketDisconnect

from apps.api.alpha import AlphaRuntime, SnapshotViewport, create_app
from apps.api.hd_stream import HdBusyError, HdProfile, HdTicket
from apps.api.ptz import PtzCode, PtzDirection, StepPtzController


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


def client(
    gateway: FakeGateway | None = None,
    *,
    ptz: StepPtzController | None = None,
    hd_stream: FakeHdStream | None = None,
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
    runtime = AlphaRuntime(**runtime_kwargs)
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
