# Visual Frame Health Alert Pipeline Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Persist camera offline/frozen incidents and deliver one privacy-safe ntfy notification when each incident opens and recovers.

**Architecture:** Keep the existing `VisualFrameHealthMonitor` as the only owner of 60-second failure and 20-second recovery decisions. Add a SQLite-backed incident sink that maps its transitions to one restart-safe incident, then attach a visual-only ntfy adapter at production bootstrap. Notification and persistence failures are isolated from the frame capture loop.

**Tech Stack:** Python 3.11, Pydantic v2, sqlite3, urllib, pytest, existing `VisualWorker`/`FrameHealthTransition` contracts.

## Global Constraints

- Do not change Xiaomi/go2rtc stream parameters or visual risk thresholds.
- Only `source_offline`, `frame_frozen`, and `recovered` are externally notified; `reconnect_required` remains an internal control transition.
- An open incident survives worker restart and must not be opened or notified twice.
- Mark a notification delivered only after a successful 2xx ntfy response; failed delivery remains pending for a later transition or startup retry.
- Notification payloads contain only fixed event codes, state, severity, wall-clock time, and duration. Never include images, stream URLs, camera identifiers, credentials, model output, or private addresses.
- Notification failure must not terminate capture, reconnect, or real-time analysis.
- Keep `main` unchanged. Use focused tests for this slice; reserve the full gate for stable integration.

---

### Task 1: Restart-safe visual health incident store and sink

**Files:**
- Create: `services/storage/visual_health.py`
- Create: `services/vision/frame_health_pipeline.py`
- Create: `tests/storage/test_visual_health_store.py`
- Create: `tests/vision/test_frame_health_pipeline.py`

**Interfaces:**
- Consumes: `FrameHealthTransition`, an aware `clock() -> datetime`, and optional `VisualHealthNotifier.notify(VisualHealthIncident, transition_kind)`.
- Produces: `StoredVisualHealthIncident`, `VisualHealthStore.migrate()`, `load_open()`, `save()`, and `VisualFrameHealthPipeline.restore(...).handle(transition)`.

- [x] **Step 1: Write failing store and pipeline tests**

```python
opened = FrameHealthTransition(
    state=FrameHealthState.OFFLINE,
    code=FrameHealthCode.SOURCE_OFFLINE,
    duration_seconds=60.0,
)
pipeline.handle(opened)
restored = VisualFrameHealthPipeline.restore(store=store, clock=clock)
restored.handle(opened)
assert len(store.incidents()) == 1
assert notifier.calls == [("source_offline", "opened")]
```

Cover migration/integrity, one open incident, restart restoration, no duplicate open, recovery of the same incident, successful-delivery markers, failed-delivery retry, and rejection of naive/decreasing wall-clock values.

- [x] **Step 2: Run tests to verify RED**

Run: `.venv-alpha/bin/python -m pytest -q tests/storage/test_visual_health_store.py tests/vision/test_frame_health_pipeline.py`

Expected: collection fails because the new modules do not exist.

- [x] **Step 3: Implement the minimal store and sink**

```python
class VisualFrameHealthPipeline:
    @classmethod
    def restore(cls, *, store, notifier=None, clock=datetime.now): ...

    def handle(self, transition: FrameHealthTransition) -> None:
        if transition.code is FrameHealthCode.RECONNECT_REQUIRED:
            return
        # Reuse one persisted open incident, update it on recovery, and
        # persist notification markers only after delivered=True.
```

Use a dedicated `visual_health_incidents` table with fixed code/state checks, aware ISO timestamps, duration, and `opened_notified`/`recovered_notified` flags. One transaction must make each incident update durable before notification is attempted.

- [x] **Step 4: Run focused tests to verify GREEN**

Run: `.venv-alpha/bin/python -m pytest -q tests/storage/test_visual_health_store.py tests/vision/test_frame_health_pipeline.py tests/vision/test_frame_health.py`

Expected: all tests pass.

- [x] **Step 5: Commit the persistence slice**

```bash
git add services/storage/visual_health.py services/vision/frame_health_pipeline.py tests/storage/test_visual_health_store.py tests/vision/test_frame_health_pipeline.py
git commit -m "feat: persist visual frame health incidents"
```

### Task 2: Privacy-safe visual ntfy adapter

**Files:**
- Create: `services/notifications/visual_ntfy.py`
- Create: `services/vision/notification_config.py`
- Create: `tests/notifications/test_visual_ntfy.py`
- Create: `tests/vision/test_notification_config.py`

**Interfaces:**
- Consumes: `StoredVisualHealthIncident`, transition kind `opened|recovered`, `NTFY_BASE_URL`, configured private topic, and token referenced by `settings.notifications.ntfy_token_env`.
- Produces: `NtfyVisualHealthNotifier.notify(...) -> NotificationResult` and `build_visual_health_notifier(settings, environ)`.

- [x] **Step 1: Write failing notification tests**

```python
result = notifier.notify(incident, "opened")
payload = json.loads(opener.request.data)
assert result.delivered is True
assert payload["topic"] == "private-topic"
assert "source_offline" in payload["message"]
assert "192.168." not in json.dumps(payload)
```

Cover open/recovered wording, fixed tags and priorities, optional bearer token, 2xx success, bounded retry for transport/5xx, no retry for non-429 4xx, invalid code rejection, private-topic placeholder rejection, and operation without a remote Dashboard URL.

- [x] **Step 2: Run tests to verify RED**

Run: `.venv-alpha/bin/python -m pytest -q tests/notifications/test_visual_ntfy.py tests/vision/test_notification_config.py`

Expected: collection fails because the new modules do not exist.

- [x] **Step 3: Implement the adapter and configuration builder**

```python
def build_visual_health_notifier(settings, environ):
    topic = resolve_notification_topic(settings, environ)
    token_name = settings.notifications.ntfy_token_env
    return NtfyVisualHealthNotifier(
        ntfy_base_url=environ.get("NTFY_BASE_URL", "https://ntfy.sh"),
        topic=topic,
        token=environ.get(token_name) or None,
    )
```

Reuse `NotificationResult` and the existing credential-free HTTPS validator. Do not require or add a Dashboard click URL in this slice.

- [x] **Step 4: Run focused notification tests**

Run: `.venv-alpha/bin/python -m pytest -q tests/notifications/test_visual_ntfy.py tests/vision/test_notification_config.py tests/notifications/test_ntfy.py`

Expected: all tests pass.

- [x] **Step 5: Commit the notification slice**

```bash
git add services/notifications/visual_ntfy.py services/vision/notification_config.py tests/notifications/test_visual_ntfy.py tests/vision/test_notification_config.py
git commit -m "feat: notify visual frame health incidents"
```

### Task 3: Production wiring and capture-loop isolation

**Files:**
- Modify: `services/vision/bootstrap.py`
- Modify: `services/vision/worker.py`
- Modify: `tools/run_visual_worker.py`
- Modify: `tests/vision/test_bootstrap.py`
- Modify: `tests/vision/test_worker.py`
- Modify: `tests/tools/test_run_visual_worker.py`

**Interfaces:**
- Consumes: `on_frame_health: Callable[[FrameHealthTransition], None]` passed through `build_visual_runtime` and the pipeline built from `settings.app.data_dir / "visual-health.sqlite3"`.
- Produces: a production worker that stores/notifies frame-health transitions and continues running if the callback raises.

- [ ] **Step 1: Write failing wiring and isolation tests**

```python
worker = build_worker(on_frame_health=lambda _transition: (_ for _ in ()).throw(RuntimeError()))
worker._handle_frame_transition(source_offline_transition())
assert worker.health().code == "source_offline"
```

Also prove bootstrap forwards the callback, the CLI migrates/restores the visual health store before running, relative `data_dir` resolves beneath repository root, and startup retries a pending notification without inventing a second incident.

- [ ] **Step 2: Run tests to verify RED**

Run: `.venv-alpha/bin/python -m pytest -q tests/vision/test_bootstrap.py tests/vision/test_worker.py tests/tools/test_run_visual_worker.py`

Expected: at least the callback-isolation and production-wiring assertions fail.

- [ ] **Step 3: Implement minimal production wiring**

```python
try:
    self._on_frame_health(transition)
except Exception:
    self._health = replace(self._health, state="degraded", code="frame_health_callback_failed")
# Continue applying the authoritative transition to worker state.
```

Build the store, notifier, and restored pipeline in `run_visual_worker.main`; pass `pipeline.handle` through `build_visual_runtime(on_frame_health=...)`. Emit only fixed stderr status codes when persistence or notification setup fails.

- [ ] **Step 4: Run the complete focused gate**

Run: `.venv-alpha/bin/python -m pytest -q tests/storage/test_visual_health_store.py tests/vision/test_frame_health_pipeline.py tests/notifications/test_visual_ntfy.py tests/vision/test_notification_config.py tests/vision/test_frame_health.py tests/vision/test_bootstrap.py tests/vision/test_worker.py tests/tools/test_run_visual_worker.py tests/notifications/test_ntfy.py`

Expected: all tests pass.

Run: `bash -n tools/start_alpha.sh tools/install_alpha_macos.sh && git diff --check`

Expected: exit 0.

- [ ] **Step 5: Commit the production wiring**

```bash
git add services/vision/bootstrap.py services/vision/worker.py tools/run_visual_worker.py tests/vision/test_bootstrap.py tests/vision/test_worker.py tests/tools/test_run_visual_worker.py
git commit -m "feat: activate visual frame health alerts"
```

- [ ] **Step 6: Record the Mac acceptance boundary**

On the i9 Mac, verify one controlled source outage lasts at least 60 seconds, produces one ntfy alert, reconnects without restarting the full Alpha stack, and produces one recovery notification only after 20 seconds of changing valid frames. Keep Dashboard video, gauge sampling, and real-time metrics visible during the test. Do not simulate a Baby posture or face-risk event in this slice.
