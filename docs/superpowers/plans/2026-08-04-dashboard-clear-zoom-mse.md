# Dashboard Clear Zoom MSE Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Keep the lightweight 720p MJPEG viewer at 1x and use the verified 2560x1440 H.264 source through an authenticated, on-demand MSE relay at 2x/3x without exposing go2rtc or showing a black handoff.

**Architecture:** A focused Python HD stream service owns one-time tickets, same-origin checks, a two-connection gate, the fixed loopback go2rtc MSE request, and cleanup. A dependency-free browser HD player owns MediaSource buffering and the MJPEG/video layer handoff; the existing viewer only reports zoom changes to it.

**Tech Stack:** Python 3.11, FastAPI/Starlette WebSocket, `websockets` async client, pytest/TestClient, browser MediaSource/WebSocket APIs, dependency-free JavaScript, Node 20 test runner.

## Global Constraints

- `1x` uses the existing `1280x720 / 10 FPS` MJPEG stream; `2x/3x` use the verified `2560x1440` H.264 `source` stream.
- Normal playback and handoff target approximately one to two seconds of delay; the transition hard limit is eight seconds.
- go2rtc remains loopback-only; the browser cannot select a stream, URL, codec, duration, or upstream command.
- The Dashboard keeps HTTP Basic Auth; an HD ticket has at least 256 bits of randomness, expires after 10 seconds, is single-use, and never appears in a URL or log.
- At most 64 unconsumed tickets and two concurrent HD relay sockets are allowed; overload fails closed with `HD_BUSY` and does not evict a valid ticket.
- Only a ready target layer replaces the visible layer. Steady 1x has one MJPEG consumer; steady 2x/3x has one MSE consumer.
- Missing MSE/WebSocket support and all ticket, codec, append, autoplay, transport, and timeout failures preserve or restore usable MJPEG without a hidden retry loop.
- Public media states are limited to `HD_LOADING`, `HD_ACTIVE`, `HD_FALLBACK`, `HD_UNSUPPORTED`, and `HD_BUSY`.
- Physical PTZ stays `PTZ_DISABLED`; no Xiaomi motor payload or new camera network operation is added.
- Tailscale Serve HTTPS is the only planned external access; Funnel and router port forwarding remain prohibited.
- Tests and fixtures contain no real Xiaomi URI, credentials, token, UID, DID, MAC, private address, media, or household image.

---

### Task 1: One-time HD ticket store

**Files:**
- Create: `apps/api/hd_stream.py`
- Create: `tests/api/test_hd_stream.py`

**Interfaces:**
- Produces: `HdCode`, `HdTicket`, `HdBusyError`, and `HdTicketStore.issue() -> HdTicket`, `HdTicketStore.consume(ticket: str) -> bool`.
- `HdTicket` has `value: str` and `expires_in: int`; the opaque value is generated with `secrets.token_urlsafe(32)`.
- The store accepts injectable `clock: Callable[[], float]`, `ttl_seconds=10`, and `capacity=64` for deterministic boundary tests.

- [x] **Step 1: Write failing ticket behavior tests**

```python
def test_ticket_is_single_use_and_expires_after_ten_seconds():
    now = [100.0]
    store = HdTicketStore(clock=lambda: now[0])
    ticket = store.issue()
    assert ticket.expires_in == 10
    padding = "=" * (-len(ticket.value) % 4)
    assert len(base64.urlsafe_b64decode(ticket.value + padding)) >= 32
    assert store.consume(ticket.value) is True
    assert store.consume(ticket.value) is False

    expired = store.issue()
    now[0] = 110.0
    assert store.consume(expired.value) is False


def test_capacity_cleanup_never_evicts_a_valid_ticket():
    now = [10.0]
    store = HdTicketStore(clock=lambda: now[0], capacity=2)
    first = store.issue()
    store.issue()
    with pytest.raises(HdBusyError):
        store.issue()
    assert store.consume(first.value) is True
```

- [x] **Step 2: Run the ticket tests and verify RED**

Run: `../.venv/bin/python -m pytest tests/api/test_hd_stream.py -q`

Expected: collection fails because `apps.api.hd_stream` does not exist.

- [x] **Step 3: Implement the minimal locked ticket store**

```python
@dataclass(frozen=True)
class HdTicket:
    value: str
    expires_in: int


class HdTicketStore:
    def issue(self) -> HdTicket:
        with self._lock:
            self._purge_expired()
            if len(self._expires_at) >= self._capacity:
                raise HdBusyError
            value = secrets.token_urlsafe(32)
            self._expires_at[value] = self._clock() + self._ttl_seconds
            return HdTicket(value=value, expires_in=self._ttl_seconds)

    def consume(self, value: str) -> bool:
        with self._lock:
            self._purge_expired()
            return self._expires_at.pop(value, None) is not None
```

- [x] **Step 4: Run GREEN and mutation checks**

Run: `../.venv/bin/python -m pytest tests/api/test_hd_stream.py -q`

Verify that changing expiry comparison, removing the pop, or evicting the oldest valid entry would fail at least one test.

- [x] **Step 5: Commit the ticket domain**

```bash
git add apps/api/hd_stream.py tests/api/test_hd_stream.py
git commit -m "feat: add one-time HD stream tickets"
```

### Task 2: Fixed loopback MSE relay and WebSocket security

**Files:**
- Modify: `apps/api/hd_stream.py`
- Modify: `tests/api/test_hd_stream.py`
- Modify: `pyproject.toml`

**Interfaces:**
- Produces: `HdStreamService.issue_ticket() -> HdTicket` and `async HdStreamService.serve(socket: HdBrowserSocket) -> None`.
- `HdBrowserSocket` exposes request headers/peer host plus `accept`, `receive_ticket`, `send_text`, `send_bytes`, `send_public_code`, and `close` operations; the FastAPI route supplies an adapter.
- The upstream connector is injected in tests and defaults to `websockets.asyncio.client.connect` in production.
- The only upstream URI is derived from the configured loopback base plus `/api/ws?src=source`; the first upstream command is the fixed JSON MSE/H.264 request.

- [x] **Step 1: Write failing security and relay tests**

```python
def test_invalid_origin_and_ticket_never_open_upstream():
    connector = RecordingConnector()
    service = HdStreamService(connector=connector)
    socket = FakeBrowserSocket(origin="http://evil.invalid", host="monitor.local:8080")
    asyncio.run(service.serve(socket))
    assert connector.opened == []
    assert socket.close_code == 1008


def test_relay_uses_fixed_source_and_forwards_only_mse_then_binary():
    connector = RecordingConnector([
        json.dumps({"type": "mse", "value": 'video/mp4; codecs="avc1.640033"'}),
        b"init-and-media",
    ])
    service = HdStreamService(connector=connector)
    ticket = service.issue_ticket().value
    socket = FakeBrowserSocket(first_message=ticket)
    asyncio.run(service.serve(socket))
    assert connector.opened == ["ws://127.0.0.1:1984/api/ws?src=source"]
    assert connector.sent == [MSE_REQUEST]
    assert socket.text_messages == [
        json.dumps({"type": "mse", "value": 'video/mp4; codecs="avc1.640033"'}, separators=(",", ":"))
    ]
    assert socket.binary_messages == [b"init-and-media"]
    assert connector.closed is True
```

Add separate literal-outcome tests for missing, reused, late, binary, and over-1-KiB tickets; untrusted forwarded hosts; non-loopback base URLs; unsupported MIME/codec; binary-before-description; over-limit upstream messages; client disconnect; cleanup on every error; and the third simultaneous connection returning only `HD_BUSY`.

- [x] **Step 2: Run the relay tests and verify RED**

Run: `../.venv/bin/python -m pytest tests/api/test_hd_stream.py -q`

Expected: tests fail because `HdStreamService`, the origin policy, connection gate, and relay do not exist.

- [x] **Step 3: Add the explicit runtime dependency**

```toml
dependencies = [
  "fastapi>=0.116,<1",
  "pydantic>=2.10,<3",
  "PyYAML>=6.0,<7",
  "uvicorn[standard]>=0.35,<1",
  "websockets>=15,<18",
]
```

- [x] **Step 4: Implement origin validation, non-blocking gate, and fixed relay**

```python
MSE_REQUEST = json.dumps({"type": "mse", "value": H264_CODEC_REQUEST}, separators=(",", ":"))

async def serve(self, socket: HdBrowserSocket) -> None:
    if not self._origin_policy.allows(socket.headers, socket.peer_host):
        await socket.close(code=1008)
        return
    await socket.accept()
    ticket = await asyncio.wait_for(socket.receive_ticket(max_bytes=1024), timeout=3)
    if not self._tickets.consume(ticket):
        await socket.close(code=1008, reason=HdCode.FALLBACK.value)
        return
    if not await self._connections.try_acquire():
        await socket.send_public_code(HdCode.BUSY)
        await socket.close(code=1013, reason=HdCode.BUSY.value)
        return
    try:
        async with self._connector(self._upstream_uri, max_size=self._max_message_bytes) as upstream:
            await upstream.send(MSE_REQUEST)
            await self._forward_validated(upstream, socket)
    finally:
        await self._connections.release()
```

The implementation validates `http`/`https`, an IP-literal loopback hostname, fixed stream name `source`, exactly one H.264 `video/mp4` description before binary data, and bounded message sizes. It never relays browser messages after the ticket.

- [x] **Step 5: Run GREEN and the Python baseline**

Run: `../.venv/bin/python -m pytest tests/api/test_hd_stream.py -q`

Run: `../.venv/bin/python -m pytest -q`

- [x] **Step 6: Commit the server relay domain**

```bash
git add apps/api/hd_stream.py tests/api/test_hd_stream.py pyproject.toml
git commit -m "feat: relay fixed HD MSE stream"
```

### Task 3: Authenticated HD session API and WebSocket route

**Files:**
- Modify: `apps/api/alpha.py`
- Modify: `apps/api/runtime.py`
- Modify: `tests/api/test_alpha_app.py`
- Create: `tests/api/test_runtime.py`

**Interfaces:**
- `AlphaRuntime.hd_stream` implements the Task 2 service interface.
- `POST /api/hd-session` is Basic-authenticated and returns only `{"ticket": string, "expires_in": 10}` or `{"result":"HD_BUSY"}`.
- `/live-hd.ws` receives the ticket as its first message and delegates to the service; it has no query parameters.
- Runtime uses `GO2RTC_BASE_URL` and the server-owned literal stream name `source`; no browser or environment value can select another HD stream.

- [x] **Step 1: Write failing HTTP/WebSocket integration tests**

```python
def test_hd_session_requires_basic_auth_and_returns_only_ticket_metadata():
    runtime = make_runtime(hd_stream=FakeHdStream())
    with TestClient(create_app(runtime)) as client:
        assert client.post("/api/hd-session").status_code == 401
        response = client.post("/api/hd-session", headers=auth())
    assert response.status_code == 201
    assert response.json() == {"ticket": "opaque-ticket", "expires_in": 10}


def test_websocket_has_no_stream_selector_and_delegates_one_socket():
    service = FakeHdStream()
    with TestClient(create_app(make_runtime(hd_stream=service))) as client:
        with client.websocket_connect(
            "/live-hd.ws", headers={"origin": "http://testserver"}
        ) as websocket:
            websocket.send_text("opaque-ticket")
    assert service.served == 1
```

Add tests proving the page source and API responses contain no Basic password, upstream URL, stream inventory, private address, or ticket-in-URL; `HD_BUSY` maps to 429; and existing snapshot, MJPEG, PTZ, notification, and authentication behavior is unchanged.

- [x] **Step 2: Run route tests and verify RED**

Run: `../.venv/bin/python -m pytest tests/api/test_alpha_app.py -q`

Expected: route tests return 404 and `AlphaRuntime` has no `hd_stream` field.

- [x] **Step 3: Register minimal authenticated routes and runtime wiring**

```python
@app.post("/api/hd-session", status_code=status.HTTP_201_CREATED)
def hd_session(_parent: str = Depends(require_parent)) -> JSONResponse:
    ticket = runtime.hd_stream.issue_ticket()
    return JSONResponse(status_code=201, content={
        "ticket": ticket.value,
        "expires_in": ticket.expires_in,
    })


@app.websocket("/live-hd.ws")
async def live_hd(websocket: WebSocket) -> None:
    await runtime.hd_stream.serve(StarletteHdSocket(websocket))
```

`runtime_from_env` constructs `HdStreamService` with the existing loopback go2rtc base and fixed `stream_name="source"`; invalid non-loopback configuration fails at startup.

- [x] **Step 4: Run GREEN and runtime tests**

Run: `../.venv/bin/python -m pytest tests/api/test_alpha_app.py tests/api/test_hd_stream.py -q`

Run: `../.venv/bin/python -m pytest -q`

- [x] **Step 5: Commit the API boundary**

```bash
git add apps/api/alpha.py apps/api/runtime.py tests/api/test_alpha_app.py tests/api/test_runtime.py
git commit -m "feat: expose authenticated HD sessions"
```

### Task 4: Browser MSE player and no-black-frame layer handoff

**Files:**
- Create: `apps/api/hd_player.js`
- Create: `tests/frontend/hd_player.test.mjs`
- Modify: `apps/api/alpha.py`
- Modify: `tests/api/test_alpha_app.py`

**Interfaces:**
- Produces: `createHdPlayer(environment)` with `selectZoom(zoom: 1|2|3)`, `status()`, and `destroy()`.
- The environment supplies real or fake `MediaSource`, `WebSocket`, `URL`, `fetch`, timers, location, image, video, and status element.
- The player opens `/live-hd.ws` only after an authenticated ticket response and sends the ticket as the first message.
- The page contains overlapping `#live-image` and muted `#hd-video` layers, plus `#hd-status`; `/assets/hd-player.js` remains Basic-authenticated and `Cache-Control: no-store`.

- [x] **Step 1: Write failing page structure and asset tests**

```python
def test_dashboard_contains_inactive_muted_hd_layer_and_authenticated_asset():
    response = client.get("/", headers=auth())
    assert '<video id="hd-video"' in response.text
    assert "muted" in response.text and "playsinline" in response.text
    assert 'id="hd-status"' in response.text
    assert client.get("/assets/hd-player.js").status_code == 401
    assert client.get("/assets/hd-player.js", headers=auth()).status_code == 200
```

- [x] **Step 2: Write failing player behavior tests with real state transitions**

```javascript
test("1x opens no HD connection and 2x/3x reuse one socket", async () => {
  const fixture = createPlayerFixture();
  const player = createHdPlayer(fixture.environment);
  await player.selectZoom(1);
  assert.equal(fixture.sockets.length, 0);
  await player.selectZoom(2);
  fixture.completeHdHandoff();
  await player.selectZoom(3);
  assert.equal(fixture.sockets.length, 1);
  assert.equal(fixture.ticketRequests.length, 1);
});


test("HD becomes visible only after playing and then releases MJPEG", async () => {
  const fixture = createPlayerFixture();
  const player = createHdPlayer(fixture.environment);
  await player.selectZoom(2);
  fixture.announce('video/mp4; codecs="avc1.640033"');
  fixture.sendFragment(new Uint8Array([0, 1, 2]));
  assert.equal(fixture.visibleLayer(), "mjpeg");
  fixture.video.dispatch("playing");
  assert.equal(fixture.visibleLayer(), "hd");
  assert.equal(fixture.image.src, BLANK_IMAGE_SRC);
});
```

Add literal behavior tests for ticket-in-first-message only; unsupported APIs; unsupported codec; ticket/HTTP/WebSocket/append/autoplay failures; socket close after activation; ordered SourceBuffer appends; 20-second trimming; seeking when more than two seconds behind; eight-second timeout; 1x restoring MJPEG before closing HD; failed MJPEG restoration preserving the last HD frame; destroy/pagehide cleanup; and public status redaction.

- [x] **Step 3: Run browser tests and verify RED**

Run: `node --test tests/frontend/hd_player.test.mjs`

Expected: module load fails because `apps/api/hd_player.js` does not exist.

- [x] **Step 4: Implement the minimal HD player state machine**

```javascript
async function startHd() {
  if (!supported()) return setStatus("HD_UNSUPPORTED");
  if (mode === "loading" || mode === "active") return;
  mode = "loading";
  setStatus("HD_LOADING");
  const response = await environment.fetch("/api/hd-session", {method: "POST"});
  const payload = await response.json();
  socket = new environment.WebSocket(sameOriginWebSocketUrl(environment.location));
  socket.binaryType = "arraybuffer";
  socket.addEventListener("open", () => socket.send(payload.ticket));
  armTransitionTimeout();
}

function activateHdAfterPlaying() {
  show(video);
  hide(image);
  image.src = BLANK_IMAGE_SRC;
  mode = "active";
  setStatus("HD_ACTIVE");
}
```

Use one append/remove operation queue; process it from `SourceBuffer.updateend`. On 1x, set `image.src` back to `/live.mjpeg`, wait for `load`, then reveal MJPEG and close/revoke/reset HD resources. All cleanup functions are idempotent.

- [x] **Step 5: Run GREEN and mutation checks**

Run: `node --test tests/frontend/hd_player.test.mjs`

Verify tests fail if the video is shown before `playing`, MJPEG is blanked before activation, a second socket opens at 3x, HD closes before the MJPEG `load`, or raw errors become status text.

- [x] **Step 6: Run page integration tests and the complete current suites**

Run: `../.venv/bin/python -m pytest tests/api/test_alpha_app.py -q`

Run: `node --test tests/frontend/*.test.mjs`

- [x] **Step 7: Commit the browser player**

```bash
git add apps/api/hd_player.js tests/frontend/hd_player.test.mjs apps/api/alpha.py tests/api/test_alpha_app.py
git commit -m "feat: add on-demand clear zoom player"
```

### Task 5: Connect zoom/fullscreen state to HD lifecycle

**Files:**
- Modify: `apps/api/dashboard_viewer.js`
- Modify: `tests/frontend/dashboard_viewer.test.mjs`

**Interfaces:**
- `mountDashboardViewer(environment)` accepts `environment.hdPlayer` or creates one through `window.BabyMonitorHdPlayer.createHdPlayer`.
- Every rendered zoom change calls `hdPlayer.selectZoom(state.zoom)` once after the CSS transform is updated.
- A 2x-to-3x change preserves the active HD session; native fullscreen exit resets to 1x and starts the safe MJPEG return path.

- [x] **Step 1: Write failing viewer integration tests**

```javascript
test("zoom and fullscreen exit drive the HD player without changing pan semantics", async () => {
  const fixture = createViewerFixture();
  const requested = [];
  fixture.environment.hdPlayer = {selectZoom: zoom => requested.push(zoom)};
  mountDashboardViewer(fixture.environment);
  fixture.zoom2.click();
  fixture.zoom3.click();
  fixture.enterFullscreen();
  fixture.exitFullscreen();
  assert.deepEqual(requested, [1, 2, 3, 1]);
  assert.equal(fixture.liveImageReloads, 0);
});
```

Keep existing tests proving drag clamping, pointer capture, double-click fullscreen, `Esc` reset, Fullscreen API fallback, PTZ single-flight, and an unchanged live source on non-media failures.

- [x] **Step 2: Run viewer tests and verify RED**

Run: `node --test tests/frontend/dashboard_viewer.test.mjs`

Expected: the injected HD player records no zoom calls.

- [x] **Step 3: Add the minimal integration**

```javascript
const hdPlayer = environment.hdPlayer ||
  window.BabyMonitorHdPlayer?.createHdPlayer(buildHdEnvironment(environment));

function render(state) {
  renderTransformAndButtons(state);
  hdPlayer?.selectZoom(state.zoom);
}
```

Catch rejected `selectZoom` promises inside the player boundary so UI events never create unhandled rejections.

- [x] **Step 4: Run GREEN and all browser tests**

Run: `node --test tests/frontend/*.test.mjs`

- [x] **Step 5: Commit the viewer integration**

```bash
git add apps/api/dashboard_viewer.js tests/frontend/dashboard_viewer.test.mjs
git commit -m "feat: switch clear stream with dashboard zoom"
```

### Task 6: Documentation, CI, and release gate

**Files:**
- Modify: `README.md`
- Modify: `docs/runbooks/ALPHA_QUICKSTART.md`
- Modify: `.github/workflows/ci.yml` only if the existing Python/Node commands do not already execute the new tests.

**Interfaces:**
- Documents state that 1x uses MJPEG, 2x/3x request native H.264 MSE, a normal handoff may take one to two seconds, failures preserve MJPEG, and PTZ remains disabled.
- The i9 gate measures consumers without printing the Xiaomi URI or runtime credentials.

- [x] **Step 1: Update operator and acceptance documentation**

Document `make alpha-update`, `make alpha-install` to install the new explicit dependency, and `make alpha-restart`. Add a browser checklist for M2 Chrome/Safari and Android Chrome, plus go2rtc status checks that report only consumer type/count and FFmpeg process count.

- [x] **Step 2: Run fresh complete verification**

```bash
../.venv/bin/python -m pytest -q
node --test tests/frontend/*.test.mjs
python3 -m json.tool config/settings.schema.json >/dev/null
../.venv/bin/python -m compileall -q apps packages services
bash -n tools/*.sh
git diff --check origin/codex/basic-usable-alpha...HEAD
```

Also scan tracked source for hard-coded Xiaomi URI schemes, bearer values, private IPv4 literals outside documentation examples, ticket query parameters, and `tailscale funnel` instructions that are not explicit prohibitions.

- [x] **Step 3: Review the plan and spec line by line**

Confirm every automated verification item in `docs/superpowers/specs/2026-08-04-dashboard-clear-zoom-mse-design.md` maps to a passing test. Confirm the final diff contains no physical PTZ adapter, no 1440p FFmpeg encode, no generic proxy parameter, and no second permanent media consumer.

- [x] **Step 4: Commit documentation**

```bash
git add README.md docs/runbooks/ALPHA_QUICKSTART.md .github/workflows/ci.yml
git commit -m "docs: add clear zoom acceptance gate"
```

- [x] **Step 5: Publish without rewriting history**

Verify PR #4 is still Draft and its remote head is the expected ancestor. Push only by fast-forward, keep the PR Draft, wait for GitHub Actions, and do not ask the i9 to update until CI succeeds.

- [ ] **Step 6: Run the i9 real-device gate**

After CI success, update and reinstall on the i9, then verify native detail at 2x/3x, one-to-two-second normal delay, one HD socket across 2x/3x, MJPEG release in steady HD, MSE release in steady 1x, no H.264 FFmpeg encode, continuous visible video during repeated switching/fullscreen/drag, fallback after an interrupted HD socket, loopback-only go2rtc listeners, and `PTZ_DISABLED`.

PR #4 remains Draft until this real-device gate passes.
