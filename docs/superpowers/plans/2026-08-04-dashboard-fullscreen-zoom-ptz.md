# Dashboard Fullscreen, Digital Zoom, and Guarded PTZ Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add authenticated fullscreen viewing, bounded 1×/2×/3× browser zoom and drag, plus a fail-closed click-to-step PTZ API and Dashboard control surface without sending unverified commands to the Xiaomi MJSXJ17CM.

**Architecture:** Keep all viewer behavior client-side in one dependency-free JavaScript module served behind the existing Basic Auth boundary. Add a small Python PTZ domain controller between the FastAPI route and a device adapter; the only runtime adapter in this phase is disabled and performs no network I/O. A future evidence-backed adapter can implement the same closed interface after protocol-fixture and left/right recovery gates.

**Tech Stack:** Python 3.11, FastAPI, Pydantic, vanilla JavaScript, Pointer Events, browser Fullscreen API, Node 20 built-in test runner, pytest.

## Global Constraints

- PR #4 stays Draft and targets `codex/bootstrap-baby-monitor-v1`; do not merge to `main`.
- Xiaomi source, subtype `3`, FFmpeg, MJPEG proxy, microSD recording, and go2rtc listeners remain unchanged.
- Dashboard Basic Auth remains mandatory for the page, viewer asset, live stream, and PTZ endpoint.
- go2rtc stays loopback-only; external access remains Tailscale Serve HTTPS only.
- Never enable Tailscale Funnel or router port forwarding.
- Never expose Xiaomi credentials, URI fields, private addresses, identifiers, raw motor payloads, or household imagery in source, logs, responses, tests, or CI.
- PTZ accepts only `up`, `down`, `left`, or `right`; click-to-step only, with no hold, repeat, diagonal, cruise, preset, tracking, payload scan, or retry loop.
- The production PTZ adapter remains disabled in this plan and performs zero camera network calls.
- Touch targets are at least 44 CSS pixels and controls provide Chinese accessible labels and visible focus state.

---

### Task 1: Fail-closed PTZ domain and authenticated API

**Files:**
- Create: `apps/api/ptz.py`
- Modify: `apps/api/alpha.py`
- Modify: `apps/api/runtime.py`
- Test: `tests/api/test_ptz.py`
- Test: `tests/api/test_alpha_app.py`

**Interfaces:**
- Consumes: existing `AlphaRuntime` and `require_parent` Basic Auth dependency.
- Produces: `PtzDirection`, `PtzCode`, `PtzAdapter.step(direction, timeout_seconds)`, `DisabledPtzAdapter`, `StepPtzController.step(direction)`, and `POST /api/ptz/step` accepting `{"direction":"left"}`.

- [ ] **Step 1: Write failing controller tests**

```python
def test_disabled_adapter_never_performs_device_io() -> None:
    controller = StepPtzController(adapter=DisabledPtzAdapter())
    assert controller.step(PtzDirection.LEFT).code is PtzCode.DISABLED

def test_controller_serializes_in_flight_steps() -> None:
    adapter = BlockingAdapter()
    controller = StepPtzController(adapter=adapter, minimum_interval_seconds=0)
    first = Thread(target=lambda: controller.step(PtzDirection.LEFT))
    first.start()
    assert adapter.started.wait(1)
    assert controller.step(PtzDirection.RIGHT).code is PtzCode.BUSY
    adapter.release.set()
    first.join(1)

def test_controller_rate_limits_accepted_steps() -> None:
    clock = ManualClock()
    adapter = RecordingAdapter(PtzCode.OK)
    controller = StepPtzController(adapter=adapter, clock=clock, minimum_interval_seconds=0.75)
    assert controller.step(PtzDirection.LEFT).code is PtzCode.OK
    assert controller.step(PtzDirection.RIGHT).code is PtzCode.BUSY
    clock.advance(0.75)
    assert controller.step(PtzDirection.RIGHT).code is PtzCode.OK
```

- [ ] **Step 2: Run the PTZ unit tests and verify RED**

Run: `python -m pytest tests/api/test_ptz.py -q`

Expected: collection failure because `apps.api.ptz` does not exist.

- [ ] **Step 3: Implement the minimal closed PTZ domain**

```python
class PtzDirection(str, Enum):
    UP = "up"
    DOWN = "down"
    LEFT = "left"
    RIGHT = "right"

class PtzCode(str, Enum):
    OK = "PTZ_OK"
    BUSY = "PTZ_BUSY"
    DISABLED = "PTZ_DISABLED"
    UNAVAILABLE = "PTZ_UNAVAILABLE"
    TIMEOUT = "PTZ_TIMEOUT"

class DisabledPtzAdapter:
    def step(self, direction: PtzDirection, timeout_seconds: float) -> PtzCode:
        return PtzCode.DISABLED
```

`StepPtzController.step` must acquire a non-blocking `threading.Lock`, enforce a monotonic minimum interval, pass the bounded timeout to the adapter, accept only a returned `PtzCode`, map exceptions and unknown values to `PTZ_UNAVAILABLE`, and release the lock in `finally`. It must not log adapter arguments or exceptions.

- [ ] **Step 4: Run the PTZ unit tests and verify GREEN**

Run: `python -m pytest tests/api/test_ptz.py -q`

Expected: all PTZ controller tests pass.

- [ ] **Step 5: Write failing authenticated route tests**

```python
def test_ptz_step_requires_authentication() -> None:
    response = app.post("/api/ptz/step", json={"direction": "left"})
    assert response.status_code == 401

def test_unknown_direction_is_rejected_before_controller_access() -> None:
    response = app.post("/api/ptz/step", headers=auth(), json={"direction": "diagonal"})
    assert response.status_code == 422
    assert controller.directions == []

def test_one_request_causes_exactly_one_step() -> None:
    response = app.post("/api/ptz/step", headers=auth(), json={"direction": "left"})
    assert response.status_code == 200
    assert response.json() == {"result": "PTZ_OK", "cooldown_ms": 750}
    assert controller.directions == [PtzDirection.LEFT]
```

- [ ] **Step 6: Run route tests and verify RED**

Run: `python -m pytest tests/api/test_alpha_app.py tests/api/test_ptz.py -q`

Expected: `POST /api/ptz/step` returns 404 because the route is absent.

- [ ] **Step 7: Connect the route and disabled runtime adapter**

Add `ptz: StepPtzController` to `AlphaRuntime`. Define a Pydantic body model with `direction: PtzDirection`. Return only `result` and `cooldown_ms`; translate `PTZ_BUSY` to 429, `PTZ_DISABLED` to 503, `PTZ_TIMEOUT` to 504, and `PTZ_UNAVAILABLE` to 502. Build `runtime_from_env()` with `StepPtzController(adapter=DisabledPtzAdapter())`; do not add a real-adapter enable flag yet.

- [ ] **Step 8: Run route and existing API tests and verify GREEN**

Run: `python -m pytest tests/api/test_alpha_app.py tests/api/test_ptz.py -q`

Expected: all API and PTZ tests pass.

### Task 2: Authenticated viewer surface and asset

**Files:**
- Create: `apps/api/dashboard_viewer.js`
- Modify: `apps/api/alpha.py`
- Test: `tests/api/test_alpha_app.py`

**Interfaces:**
- Consumes: `GET /live.mjpeg`, `POST /api/ptz/step`, and the existing Basic Auth dependency.
- Produces: authenticated `GET /assets/dashboard-viewer.js` and Dashboard elements `#viewer`, `#media-plane`, `#live-image`, zoom buttons with `data-zoom`, `#fullscreen`, four PTZ buttons with `data-direction`, and `#ptz-status`.

- [ ] **Step 1: Write failing page and asset contract tests**

```python
def test_dashboard_exposes_accessible_viewer_controls() -> None:
    response = app.get("/", headers=auth())
    assert 'id="viewer"' in response.text
    assert response.text.count('class="zoom-button"') == 3
    assert response.text.count('class="ptz-button"') == 4
    assert 'aria-pressed="true"' in response.text
    assert 'src="/assets/dashboard-viewer.js"' in response.text

def test_viewer_asset_requires_authentication() -> None:
    assert app.get("/assets/dashboard-viewer.js").status_code == 401
    response = app.get("/assets/dashboard-viewer.js", headers=auth())
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/javascript")
```

- [ ] **Step 2: Run page tests and verify RED**

Run: `python -m pytest tests/api/test_alpha_app.py -q`

Expected: missing viewer controls and 404 asset route.

- [ ] **Step 3: Add the viewer markup, responsive CSS, and authenticated asset route**

The viewer uses a 16:9 clipped viewport, a centered 16:9 media plane, a controls overlay, separate PTZ direction pad, `touch-action: none` only on the zoomable viewport, 44-pixel controls, focus-visible outline, and fullscreen layout. Serve the JS file with `Cache-Control: no-store` after `require_parent` succeeds.

- [ ] **Step 4: Run page tests and verify GREEN**

Run: `python -m pytest tests/api/test_alpha_app.py -q`

Expected: all API page and asset contracts pass without changing `/live.mjpeg` behavior.

### Task 3: Dependency-free fullscreen, zoom, drag, and PTZ client behavior

**Files:**
- Modify: `apps/api/dashboard_viewer.js`
- Create: `tests/frontend/dashboard_viewer.test.mjs`
- Modify: `.github/workflows/ci.yml`

**Interfaces:**
- Consumes: DOM elements from Task 2 and JSON response `{result, cooldown_ms}` from Task 1.
- Produces: exported `clampPan`, `createViewerModel`, and `mountDashboardViewer` for Node tests; browser auto-mount on `DOMContentLoaded`.

- [ ] **Step 1: Write failing pure-state tests**

```javascript
test('1x always centers and a lower zoom clamps pan', () => {
  const model = createViewerModel(() => ({viewportWidth: 800, viewportHeight: 450, planeWidth: 800, planeHeight: 450}));
  model.setZoom(3);
  model.dragBy(900, 900);
  assert.deepEqual(model.state(), {zoom: 3, x: 800, y: 450});
  model.setZoom(2);
  assert.deepEqual(model.state(), {zoom: 2, x: 400, y: 225});
  model.setZoom(1);
  assert.deepEqual(model.state(), {zoom: 1, x: 0, y: 0});
});
```

- [ ] **Step 2: Run Node tests and verify RED**

Run: `node --test tests/frontend/dashboard_viewer.test.mjs`

Expected: module exports are absent.

- [ ] **Step 3: Implement zoom model and Pointer Events**

`clampPan` calculates `maxX = max(0, (planeWidth * zoom - viewportWidth) / 2)` and the equivalent Y limit. `createViewerModel` owns only zoom and pan state. `mountDashboardViewer` uses pointer capture, ignores drag at 1×, updates CSS `translate3d(...) scale(...)`, preserves pan when increasing zoom, clamps when decreasing, and resets at 1×.

- [ ] **Step 4: Add failing fullscreen behavior tests**

Simulate fullscreen availability, button click, image double-click, request rejection, and `fullscreenchange`. Assert the viewer element—not the document body—is requested; exiting resets zoom/pan; a rejected request preserves state; unavailable API disables the control with an accessible explanation.

- [ ] **Step 5: Run fullscreen tests and verify RED**

Run: `node --test tests/frontend/dashboard_viewer.test.mjs`

Expected: fullscreen event assertions fail because listeners are absent.

- [ ] **Step 6: Implement Fullscreen API behavior**

Use `viewer.requestFullscreen()` and `document.exitFullscreen()`. Toggle on the button or live-image `dblclick`. Update `aria-label` and visible label on `fullscreenchange`. When the viewer is no longer fullscreen, reset the model. Catch request rejection without resetting or replacing the image source.

- [ ] **Step 7: Add failing PTZ click tests**

Assert one click performs one POST with a closed direction, all direction buttons disable while in flight, accepted cooldown holds them disabled for the returned interval, stable result text is shown, failure does not change `liveImage.src`, and no pointer-hold listener or repeat timer exists.

- [ ] **Step 8: Run PTZ client tests and verify RED**

Run: `node --test tests/frontend/dashboard_viewer.test.mjs`

Expected: fetch/count/disable assertions fail because the PTZ click handler is absent.

- [ ] **Step 9: Implement PTZ click behavior and CI Node gate**

POST JSON to `/api/ptz/step`, accept only the five stable `PTZ_*` results, show `PTZ_UNAVAILABLE` for malformed/network responses, disable buttons while pending, apply only a bounded `cooldown_ms` from the response, and never alter the MJPEG `src`. Add `actions/setup-node@v6` with Node `20` and `node --test tests/frontend/*.test.mjs` to CI.

- [ ] **Step 10: Run frontend and API tests and verify GREEN**

Run: `node --test tests/frontend/dashboard_viewer.test.mjs && python -m pytest tests/api -q`

Expected: all frontend and API tests pass.

### Task 4: Operations documentation and complete gates

**Files:**
- Modify: `README.md`
- Modify: `docs/runbooks/ALPHA_QUICKSTART.md`
- Modify: `docs/superpowers/specs/2026-08-04-dashboard-fullscreen-zoom-design.md` only if implementation reveals a contradiction.
- Test: existing complete test suites.

**Interfaces:**
- Consumes: Tasks 1–3 behavior.
- Produces: operator instructions that distinguish browser digital pan from physical PTZ and state that real PTZ remains disabled pending protocol proof.

- [ ] **Step 1: Update operator documentation**

Document 1×/2×/3×, drag, fullscreen button/double-click/`Esc`, mobile one-finger drag, and stable PTZ result codes. State explicitly that the direction pad is present but `PTZ_DISABLED` is expected until the MJSXJ17CM protocol fixture and controlled left/right recovery gate pass; Mi Home remains the physical PTZ fallback during this phase.

- [ ] **Step 2: Run the fresh full verification gate**

Run:

```bash
python -m pytest -q
node --test tests/frontend/*.test.mjs
python -m compileall -q apps packages services
python -m json.tool config/settings.schema.json >/dev/null
bash -n tools/*.sh
```

Expected: zero failures and zero syntax errors.

- [ ] **Step 3: Review the final diff against the approved design**

Check that every design requirement is either implemented or explicitly remains behind the protocol and real-device gate. Search for prohibited values and runtime secrets, confirm `/live.mjpeg` is unchanged, and confirm the production PTZ adapter has no network implementation.

- [ ] **Step 4: Publish one fast-forward commit to the existing Draft branch**

Update `codex/basic-usable-alpha` only if remote HEAD is still the reviewed parent. Keep PR #4 Draft. Record the commit, local test counts, and GitHub Actions result without including credentials, private addresses, device identifiers, motor payloads, or imagery.

- [ ] **Step 5: Run the real-browser viewer gate before claiming UI completion**

On Intel i9/M2 and Android, verify continuous playback, 1×/2×/3×, mouse and one-finger drag, full screen enter/exit, `Esc`, normal/fullscreen control layout, and no new FFmpeg process or material server CPU increase. Do not run a physical PTZ command in this task.
