# Baby Monitor Local Environment Monitoring V1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [x]`) syntax for tracking.

**Goal:** 在 Intel i9 Mac 上把 WS2021 光学温湿度读取接入严格契约、SQLite 历史、确定性告警、鉴权 Dashboard 和纯文字 ntfy 通知，同时保持视觉复核与环境 worker 独立降级。

**Architecture:** 业务层只依赖 `EnvironmentReadingSource`；首个 `Ws2021GaugeSource` 通过固定 profile 的 `ControlledFrameSource` 取得一次连续五帧 burst，再由 `Ws2021Reader` 根据 schema v2 标定做透视校正、日间红针或夜间径向线检测并输出全有或全无的严格读数。读数事务性写入 SQLite，确定性状态机生成事件，FastAPI 只做有界查询与鉴权展示，ntfy 只接收脱敏文字负载。

**Tech Stack:** Python 3.11+、Pydantic 2、FastAPI、OpenCV 4、NumPy、SQLite WAL、pytest、原生浏览器 JavaScript、Node test runner、macOS launchd。

## Global Constraints

- 当前摄像头为小米智能摄像机 2 云台版 `MJSXJ17CM`；全天录像只写摄像头 256GB microSD。
- gauge worker 每 60 秒启动一次采样，同一连续会话取 5 帧、目标间隔 500ms、burst 最长 8 秒，不追赶错过周期。
- `available` 必须同时包含温度和湿度；任何质量门失败输出 `unavailable`，禁止旧值回填或部分读数。
- 默认新鲜期 90 秒；工程验收目标为温度 ±1℃、湿度 ±5%RH。
- 普通范围为 18–26℃、35–60%RH，持续 300 秒提醒；严重门限为 <15℃、>30℃、<25%RH、>75%RH，两次有效读数且跨度至少 60 秒才升级。
- 连续 600 秒不可读提醒；环境恢复持续 300 秒，不可读恢复需要两个连续有效读数；同一状态只通知一次。
- `visual-review worker` 与 `gauge worker` 独立进程、独立故障域；Qwen 离线不得影响环境读取。
- `gauge_roi`、`bed_zone`、`privacy_masks` 使用不同配置字段；表盘 ROI 不发送至 M2、Ollama 或任何第三方。
- 第三方 ntfy 只发送文字、读数、时间、稳定原因码和鉴权 HTTPS 链接，不发送图像、视频、私网数字地址、凭据、路径或堆栈。
- 当前模式固定 `monitor_only`；WS2021 单一光学源控制资格固定 `ineligible`；不得创建执行器接口或控制路由。
- 真实家庭影像、表盘截图、标定文件、SQLite 运行库、Token、凭据、私网地址和本地路径不得提交。
- 小步只运行定向测试；环境阶段集成后运行受影响集成测试，大版本前再运行完整门禁。

---

### Task 1: Strict reading and configuration contracts

**Files:**
- Modify: `packages/contracts/events.py`
- Modify: `packages/contracts/settings.py`
- Modify: `config/settings.example.yaml`
- Modify: `config/settings.schema.json`
- Create: `tests/contracts/test_environment_reading.py`
- Modify: `tests/contracts/test_settings.py`

**Interfaces:**
- Produces: `EnvironmentReading`, `EnvironmentSourceKind`, `ReadingFailureReason`, `ConfidenceState`, `EnvironmentSettings`, `EnvironmentPolicySettings`.
- `EnvironmentReading.available(...)` and `.unavailable(...)` are the only constructors used by later source code.

- [x] **Step 1: Write failing strict-reading tests**

```python
def test_available_reading_requires_both_values() -> None:
    with pytest.raises(ValidationError, match="both temperature and humidity"):
        EnvironmentReading(
            schema_version=1,
            reading_id="r1",
            source_kind="ws2021_gauge",
            captured_at=NOW,
            fresh_until=NOW + timedelta(seconds=90),
            state="available",
            temperature_c=22.0,
            humidity_rh=None,
            confidence=0.9,
            confidence_state="high",
            failure_reason=None,
            calibration_version="cal-1",
            sample_count=5,
            valid_temperature_samples=5,
            valid_humidity_samples=5,
        )

def test_unavailable_reading_rejects_values_and_requires_closed_reason() -> None:
    with pytest.raises(ValidationError):
        EnvironmentReading.unavailable(
            reading_id="r2",
            source_kind=EnvironmentSourceKind.WS2021_GAUGE,
            captured_at=NOW,
            failure_reason="free text",
            calibration_version="cal-1",
            sample_count=0,
        )
```

- [x] **Step 2: Run the tests and verify RED**

Run: `.venv-alpha/bin/python -m pytest tests/contracts/test_environment_reading.py -q`

Expected: FAIL because the new enums, fields, and constructors do not exist.

- [x] **Step 3: Implement the strict contract and settings**

```python
class EnvironmentReading(EventContract):
    schema_version: Literal[1] = 1
    reading_id: str = Field(min_length=1)
    source_kind: EnvironmentSourceKind
    captured_at: datetime
    fresh_until: datetime
    state: ReadingState
    temperature_c: float | None = Field(default=None, ge=-50, le=60)
    humidity_rh: float | None = Field(default=None, ge=0, le=100)
    confidence: float = Field(ge=0, le=1)
    confidence_state: ConfidenceState
    failure_reason: ReadingFailureReason | None = None
    calibration_version: str | None = None
    sample_count: int = Field(ge=0)
    valid_temperature_samples: int = Field(ge=0)
    valid_humidity_samples: int = Field(ge=0)
```

Add environment defaults exactly from the approved spec and validate:

```python
if not (
    self.temperature_critical_low_c < self.temperature_low_c
    < self.temperature_high_c < self.temperature_critical_high_c
):
    raise ValueError("temperature thresholds must be strictly nested")
```

- [x] **Step 4: Update example YAML and generated-equivalent strict JSON Schema**

The schema must reject extra fields, contain all environment defaults, and keep credential references as environment-variable names.

- [x] **Step 5: Run targeted tests and commit**

Run: `.venv-alpha/bin/python -m pytest tests/contracts/test_environment_reading.py tests/contracts/test_settings.py -q`

Commit: `feat: define strict environment contracts`

### Task 2: Schema v2 calibration geometry and atomic store

**Files:**
- Create: `services/gauge/__init__.py`
- Create: `services/gauge/calibration.py`
- Create: `tests/gauge/test_calibration.py`
- Create: `tests/gauge/test_calibration_store.py`

**Interfaces:**
- Produces: `Point`, `GaugeFace`, `GaugeQuadrilateral`, `Ws2021Calibration`, `GaugeCalibrationStore.current()`, `.save(calibration, reference_jpeg)`.
- `GaugeFace.value_for_angle(angle_degrees: float) -> float | None` performs circular unwrapping and never extrapolates.

- [x] **Step 1: Write failing geometry tests**

```python
def test_cross_zero_scale_interpolates_without_extrapolation() -> None:
    face = gauge_face([(350.0, 0.0), (10.0, 10.0), (30.0, 20.0)])
    assert face.value_for_angle(0.0) == pytest.approx(5.0)
    assert face.value_for_angle(40.0) is None

def test_viewport_points_are_reversed_to_source_coordinates() -> None:
    assert viewport_to_source(Point(x=0.5, y=0.5), zoom=2, center_x=0.25, center_y=0.5) == Point(x=0.25, y=0.5)
```

- [x] **Step 2: Run and verify RED**

Run: `.venv-alpha/bin/python -m pytest tests/gauge/test_calibration.py -q`

Expected: FAIL on missing `services.gauge.calibration`.

- [x] **Step 3: Implement immutable schema v2 models and geometry validation**

Require four ordered, non-degenerate quadrilateral points; two faces; centers, tips, radii, and at least three unique scale marks inside the outer ROI; source dimensions; orientation; zoom 2 or 3; and a non-empty unpredictable `calibration_id`.

- [x] **Step 4: Write RED store tests, then implement atomic save and three backups**

```python
def test_invalid_save_never_replaces_current_calibration(tmp_path: Path) -> None:
    store = GaugeCalibrationStore(tmp_path / "ws2021-v1.json")
    store.save(valid_calibration("first"), b"first-jpeg")
    with pytest.raises(ValidationError):
        store.save(invalid_calibration(), b"second-jpeg")
    assert store.current().calibration_id == "first"
```

Write JSON and JPEG to sibling temporary files, flush and `os.fsync`, back up the current pair, then use `os.replace`; API responses never return absolute paths.

- [x] **Step 5: Run targeted tests and commit**

Run: `.venv-alpha/bin/python -m pytest tests/gauge/test_calibration.py tests/gauge/test_calibration_store.py -q`

Commit: `feat: add ws2021 calibration v2 store`

### Task 3: Controlled high-resolution burst frame source

**Files:**
- Create: `services/stream/frame_source.py`
- Create: `tests/stream/test_frame_source.py`

**Interfaces:**
- Produces: `CapturedFrame(jpeg: bytes, captured_at: datetime)`, `FrameBurst(frames: tuple[CapturedFrame, ...])`, `ControlledFrameSource.capture_burst(frame_count, interval_ms, timeout_seconds)`.
- Only the fixed native-resolution `gauge` MJPEG profile is permitted; proxy environment variables are disabled for loopback access. The profile is `ffmpeg:source#video=mjpeg#width=2560#height=1440#raw=-r 2` and is inserted by the existing idempotent HD configuration transform.

- [x] **Step 1: Write a failing boundary test**

```python
def test_one_burst_uses_one_continuous_mjpeg_response() -> None:
    response = FakeMjpegResponse([jpeg_frame(i) for i in range(5)])
    source = Go2RtcControlledFrameSource(opener=RecordingOpener(response))
    burst = source.capture_burst(frame_count=5, interval_ms=0, timeout_seconds=8)
    assert len(burst.frames) == 5
    assert response.enter_count == 1
    assert response.exit_count == 1
```

- [x] **Step 2: Run and verify RED**

Run: `.venv-alpha/bin/python -m pytest tests/stream/test_frame_source.py -q`

Expected: FAIL on missing controlled frame source.

- [x] **Step 3: Implement bounded MJPEG parsing**

Enforce fixed loopback base URL, fixed stream name `gauge`, 16MiB maximum frame bytes, 4096×2160 and maximum-pixel checks, timezone-aware timestamps, five-frame maximum, and total burst deadline. Convert transport/parse failures into `FrameSourceUnavailable` without exposing URLs.

- [x] **Step 4: Add stale, oversized, malformed, and no-proxy tests**

Tests assert consumer-visible rejection codes and one connection per burst, not opener mock call internals.

- [x] **Step 5: Run targeted tests and commit**

Run: `.venv-alpha/bin/python -m pytest tests/stream/test_frame_source.py -q`

Commit: `feat: capture controlled gauge frame bursts`

### Task 4: WS2021 reader and robust five-frame aggregation

**Files:**
- Modify: `pyproject.toml`
- Create: `services/gauge/reader.py`
- Create: `tests/gauge/synthetic_dial.py`
- Create: `tests/gauge/test_reader_day.py`
- Create: `tests/gauge/test_reader_night.py`
- Create: `tests/gauge/test_reader_aggregation.py`

**Interfaces:**
- Produces: `Ws2021Reader.read(burst, calibration, requested_at) -> EnvironmentReading`.
- Internal per-frame output: `GaugeFrameResult(temperature_c, humidity_rh, temperature_confidence, humidity_confidence, captured_at)` or one closed `ReadingFailureReason`.

#### E2 real-device corrective slice: preserve calibrated quadrilateral aspect ratio

- **Status:** implemented and software-verified after the 2026-08-16 E1
  re-calibration reproduced `geometry_roi_out_of_bounds` on both faces. The private
  production probe now passes both ROI geometry gates and the temperature circle
  match; humidity remains fail-closed as `calibration_invalid`, so E2 is still pending.
- **Prerequisite:** schema-v2 calibration valid and fixed 2560×1440 five-frame
  `gauge` burst passing.
- **Codex work:** add a failing portrait/non-16:9 quadrilateral regression test;
  infer the bounded rectified aspect ratio from circular scale-mark geometry; add
  only enough bounded padding for the fixed 1.3-radius search window; keep source dimensions
  separate from rectified canvas dimensions through point transformation and face
  validation; run reader, environment, and production probes.
- **Human work:** none for implementation. A further calibration is required only if
  the corrected production geometry passes but scene quality still fails.
- **Acceptance:** the regression test changes from RED to GREEN; existing day, night,
  aggregation, skew and fail-closed tests remain green; a private production burst no
  longer fails because a non-16:9 gauge was stretched to 16:9. No threshold is reduced.
- **Next:** if a production reading is available, begin E2's 30 daylight comparisons;
  otherwise record the next stable fail-closed reason and diagnose that gate.

- [x] **Step 1: Add OpenCV dependency and write failing day-path test**

```python
def test_red_needles_produce_both_values() -> None:
    frames = five_day_frames(temperature_c=22.0, humidity_rh=48.0)
    reading = Ws2021Reader().read(frames, calibration(), requested_at=NOW)
    assert reading.state is ReadingState.AVAILABLE
    assert reading.temperature_c == pytest.approx(22.0, abs=1.0)
    assert reading.humidity_rh == pytest.approx(48.0, abs=5.0)
```

- [x] **Step 2: Run and verify RED, then implement perspective and day detection**

Run: `.venv-alpha/bin/python -m pytest tests/gauge/test_reader_day.py -q`

Use `cv2.getPerspectiveTransform`, `cv2.warpPerspective`, HSV red masks, center/radius constraints, center-cap exclusion, connected radial candidate scoring, and calibrated circular angle mapping.

- [x] **Step 3: Write RED night-path tests, then implement grayscale radial detection**

```python
def test_night_gray_needles_are_read_without_color() -> None:
    reading = Ws2021Reader().read(five_night_frames(20.0, 55.0), calibration(), NOW)
    assert reading.temperature_c == pytest.approx(20.0, abs=1.0)
    assert reading.humidity_rh == pytest.approx(55.0, abs=5.0)
```

Use CLAHE, center-neighborhood radial line candidates, length and edge symmetry scoring, and exclude the outer tick band.

- [x] **Step 4: Write RED aggregation/quality tests, then implement rejection gates**

Cover fewer than three valid samples, stale frames, darkness, glare, occlusion, multiple indistinguishable needles, no needle, temperature MAD >0.5℃, humidity MAD >2.5%RH, and confidence <0.75. Any one-face failure yields a whole-reading `unavailable` with no values.

- [x] **Step 5: Run targeted tests and commit**

Run: `.venv-alpha/bin/python -m pytest tests/gauge/test_reader_day.py tests/gauge/test_reader_night.py tests/gauge/test_reader_aggregation.py -q`

Commit: `feat: read ws2021 day and night dials`

### Task 5: Environment source adapter and no-backlog gauge worker

**Files:**
- Create: `services/gauge/source.py`
- Create: `services/gauge/worker.py`
- Create: `tests/gauge/test_source.py`
- Create: `tests/gauge/test_worker.py`

**Interfaces:**
- Produces: `EnvironmentReadingSource` protocol, `Ws2021GaugeSource.read(requested_at)`, `GaugeWorker.run_once(requested_at)`, `GaugeWorker.run(stop_event)`.
- Consumes: Tasks 1–4 contracts, calibration store, controlled frame source, reader, and a `ReadingSink.append(reading)` protocol.

- [x] **Step 1: Write failing source fail-closed tests**

```python
def test_missing_calibration_publishes_unavailable_without_opening_frames() -> None:
    source = Ws2021GaugeSource(frame_source=FailIfCalled(), calibration_store=EmptyStore(), reader=reader)
    reading = source.read(NOW)
    assert reading.failure_reason is ReadingFailureReason.CALIBRATION_MISSING
    assert reading.temperature_c is None
    assert reading.humidity_rh is None
```

- [x] **Step 2: Run RED, then implement source exception mapping**

Only closed public reasons cross the adapter. Unexpected exceptions become `internal_error`; no exception text, path, or frame bytes are copied into the contract.

- [x] **Step 3: Write failing worker scheduling tests**

Use a fake monotonic clock to prove a slow 70-second read schedules from completion and does not enqueue the missed 60-second run. Prove sink failure does not block the next cycle and visual-worker objects are never imported or controlled.

- [x] **Step 4: Implement worker and health state**

`run_once` performs read then append. `run` sleeps `max(0, interval - elapsed)` and tracks only stable health codes and the most recent successful write time.

- [x] **Step 5: Run targeted tests and commit**

Run: `.venv-alpha/bin/python -m pytest tests/gauge/test_source.py tests/gauge/test_worker.py -q`

Commit: `feat: run independent gauge worker`

### Task 6: SQLite history, bounded trends, and retention

**Files:**
- Create: `services/storage/__init__.py`
- Create: `services/storage/environment.py`
- Create: `tests/storage/test_environment_store.py`
- Create: `tests/storage/test_environment_trends.py`

**Interfaces:**
- Produces: `EnvironmentStore.append`, `.latest`, `.latest_available`, `.trend(window)`, `.save_incident`, `.load_state_snapshot`, `.cleanup`.
- `TrendWindow` is a closed enum: `HOURS_24` and `DAYS_7`; callers cannot submit SQL or arbitrary ranges.

- [x] **Step 1: Write failing migration and round-trip tests**

```python
def test_each_attempt_round_trips_including_unavailable(tmp_path: Path) -> None:
    store = EnvironmentStore(tmp_path / "events.sqlite3")
    store.append(available_reading("a", NOW))
    store.append(unavailable_reading("b", NOW + timedelta(minutes=1)))
    assert store.latest().reading_id == "b"
    assert store.latest_available().reading_id == "a"
    assert store.integrity_check() == "ok"
```

- [x] **Step 2: Run RED, then implement WAL schema and transactional writes**

Create indexed `environment_readings`, `environment_incidents`, and single-row `environment_state_snapshot`; use reading ID uniqueness and strict JSON serialization from Pydantic.

- [x] **Step 3: Write failing literal trend tests, then implement buckets**

24-hour queries use 5-minute buckets; 7-day queries use 1-hour buckets. Return literal min/median/max and availability ratio. Buckets with no available readings contain `null` statistics and are never forward-filled.

- [x] **Step 4: Write failing retention test, then protect open incidents**

Delete records older than 365 days only when no open incident references them. Use a bounded transaction and return the deleted row count.

- [x] **Step 5: Run targeted tests and commit**

Run: `.venv-alpha/bin/python -m pytest tests/storage/test_environment_store.py tests/storage/test_environment_trends.py -q`

Commit: `feat: persist environment history and trends`

### Task 7: Deterministic incidents and read-only control eligibility snapshot

**Files:**
- Create: `services/events/__init__.py`
- Create: `services/events/environment_state.py`
- Create: `tests/environment/test_environment_state.py`
- Create: `tests/environment/test_snapshot_provider.py`

**Interfaces:**
- Produces: `EnvironmentStateMachine.consume(reading) -> tuple[EnvironmentTransition, ...]`, `.observe_missing_record(now)`, `EnvironmentSnapshotProvider.current(now)`.
- Transition kinds: `opened`, `escalated`, `recovered`, `reasons_changed`; incident kinds: `range` and `unreadable`.

- [x] **Step 1: Write failing normal-range and critical tests**

```python
def test_range_incident_opens_only_after_five_continuous_minutes() -> None:
    machine = EnvironmentStateMachine(default_policy())
    assert machine.consume(reading_at(0, temperature=27)) == ()
    assert machine.consume(reading_at(299, temperature=27)) == ()
    assert machine.consume(reading_at(300, temperature=27))[0].kind == "opened"

def test_one_critical_sample_cannot_escalate() -> None:
    machine = open_range_machine()
    assert machine.consume(reading_at(0, temperature=31)) == ()
    assert machine.consume(reading_at(60, temperature=31))[0].kind == "escalated"
```

- [x] **Step 2: Run RED, then implement range and critical transitions**

Merge temperature and humidity reason codes into one incident; unavailable samples interrupt pending timers but do not close an open range incident.

- [x] **Step 3: Write RED unreadable/restart/dedup tests, then implement**

Cover 600 seconds unavailable or absent records, two valid samples to recover unreadable, 300 seconds normal to recover range, snapshot restore preserving open/notified state while clearing incomplete timers, and exactly one transition per level.

- [x] **Step 4: Implement read-only snapshot provider under RED tests**

For a single WS2021 optical source return `control_eligibility="ineligible"` with both `optical_source_only` and `actuator_api_disabled`; stale or unavailable current readings are never represented as current values.

- [x] **Step 5: Run targeted tests and commit**

Run: `.venv-alpha/bin/python -m pytest tests/environment -q`

Commit: `feat: evaluate deterministic environment incidents`

### Task 8: Redacted ntfy environment notifications

**Files:**
- Create: `services/notifications/__init__.py`
- Create: `services/notifications/ntfy.py`
- Create: `tests/notifications/test_ntfy.py`

**Interfaces:**
- Produces: `NtfyEnvironmentNotifier.notify(transition, reading) -> NotificationResult` and `TrustedDashboardLink` validation.
- Consumes stable incident reason codes only; exception text never enters payloads.

- [x] **Step 1: Write failing trusted-link and payload tests**

```python
@pytest.mark.parametrize("url", [
    "http://monitor.example.test/events",
    "https://127.0.0.1/events",
    "https://192.168.1.5/events",
    "https://user:pass@monitor.example.test/events",
    "https://monitor.example.test/events?token=secret",
    "file:///tmp/event",
])
def test_untrusted_dashboard_links_are_rejected(url: str) -> None:
    with pytest.raises(ValidationError):
        TrustedDashboardLink(url=url)
```

- [x] **Step 2: Run RED, then implement pure-text payload building**

Allow only HTTPS DNS hostnames with no credentials. Permit a fixed event path and opaque non-secret incident ID. Reject media fields, numeric private/loopback hosts, absolute paths, source URLs, calibration paths, and free-form stack text.

- [x] **Step 3: Write RED non-blocking retry tests, then implement bounded delivery**

Use fixed maximum attempts and bounded delays. Return stable local error codes; never raise delivery failures into the worker or replay recovered historical events.

- [x] **Step 4: Mutation-check notification privacy**

Verify tests fail if image bytes, local path, query credential, raw exception, or RFC1918 numeric host is reintroduced.

- [x] **Step 5: Run targeted tests and commit**

Run: `.venv-alpha/bin/python -m pytest tests/notifications/test_ntfy.py -q`

Commit: `feat: send redacted environment notifications`

### Task 9: Authenticated environment API, calibration wizard, and dashboard

**Files:**
- Modify: `apps/api/alpha.py`
- Create: `apps/api/environment_dashboard.js`
- Create: `apps/api/gauge_calibration.js`
- Modify: `tests/api/test_alpha_app.py`
- Create: `tests/frontend/environment_dashboard.test.mjs`
- Create: `tests/frontend/gauge_calibration.test.mjs`

**Interfaces:**
- Extend `AlphaRuntime` with an `EnvironmentDashboardService` protocol.
- Authenticated endpoints: `GET /api/environment/current`, `GET /api/environment/trends/{window}`, `GET /api/environment/incidents`, `GET /api/gauge-calibration`, `PUT /api/gauge-calibration`.
- No environment mutation or actuator endpoint exists.

- [x] **Step 1: Write failing authenticated API tests**

```python
def test_current_environment_never_falls_back_to_last_valid() -> None:
    service = FakeEnvironmentService(current=unavailable_reading(), last_valid=available_reading())
    response = client(environment=service).get("/api/environment/current", headers=auth())
    assert response.json()["current"]["state"] == "unavailable"
    assert response.json()["last_valid"]["state"] == "available"
```

Also assert every response uses `Cache-Control: no-store`, trends accept only `24h` or `7d`, and anonymous access is rejected before service access.

- [x] **Step 2: Run RED, then implement bounded API adapters**

FastAPI handlers call services only; they never capture five frames or invoke OpenCV. Responses return contract JSON and stable metadata without filesystem paths.

- [x] **Step 3: Write RED dashboard and wizard browser tests**

Assert an unavailable current reading stays visibly unavailable while last-valid is separate; chart gaps remain gaps; calibration collects four corners, two centers/tips, and at least three marks per face; undo and cancel do not save; submitted points are source-normalized.

- [x] **Step 4: Implement local dashboard card and schema v2 wizard**

Use repository-local JavaScript only, an inline SVG or canvas chart, `2×/3×` frozen current view, authenticated fetches, and no third-party CDN. Add no device-control button or route.

- [x] **Step 5: Run targeted tests and commit**

Run: `.venv-alpha/bin/python -m pytest tests/api/test_alpha_app.py -q && node --test tests/frontend/environment_dashboard.test.mjs tests/frontend/gauge_calibration.test.mjs`

Commit: `feat: expose authenticated environment dashboard`

### Task 10: Wiring, launchd isolation, documentation, and environment stage gate

**Files:**
- Modify: `apps/api/runtime.py`
- Create: `tools/run_gauge_worker.py`
- Create: `deploy/launchd/com.babymonitor.gauge.plist.example`
- Modify: `tools/install_alpha_macos.sh`
- Modify: `docs/STATUS.md`
- Modify: `docs/CHECKPOINT.md`
- Modify: `docs/runbooks/ALPHA_QUICKSTART.md`
- Modify: `docs/superpowers/plans/2026-08-04-baby-monitor-local-v1.md`
- Create: `tests/deploy/test_gauge_worker_deploy.py`
- Create: `tests/integration/test_environment_pipeline.py`

**Interfaces:**
- Runtime construction composes frame source → calibration store → reader → source → store/state/notifier without importing Qwen or visual-review code.
- launchd has an independent label, log paths, restart policy, and arguments; it does not restart go2rtc or the API.

- [x] **Step 1: Write failing composition and launchd isolation tests**

Prove Qwen/Ollama absence does not prevent gauge composition, an unreadable gauge result does not change visual state, worker configuration includes one 60-second interval, and no actuator/control route is registered.

- [x] **Step 2: Run RED, then wire runtime and worker entry point**

Load strict settings, create the SQLite database below configured `data_dir`, use fixed loopback go2rtc source, and map secrets only from named environment variables. Worker shutdown handles `SIGTERM` without killing sibling services.

- [x] **Step 3: Add launchd unit and installer integration**

Use `KeepAlive` for the gauge worker only. Do not place credentials, private addresses, calibration contents, or family paths in the plist example.

- [x] **Step 4: Correct stale project documents**

Mark the approved environment spec and this plan, replace old Task 8 CLI calibration with the Dashboard schema v2 wizard, record real branch/HEAD progression, keep PR #4 remote divergence explicit, and document i9 hardware acceptance as still pending.

- [x] **Step 5: Run environment stage gate and commit**

Run:

```bash
.venv-alpha/bin/python -m pytest \
  tests/contracts/test_environment_reading.py \
  tests/contracts/test_settings.py \
  tests/gauge tests/stream/test_frame_source.py \
  tests/storage tests/environment tests/notifications \
  tests/api/test_alpha_app.py tests/integration/test_environment_pipeline.py \
  tests/deploy/test_gauge_worker_deploy.py -q
node --test tests/frontend/*.test.mjs
.venv-alpha/bin/python -m compileall apps packages services tools
git diff --check
```

Then scan staged paths and content for media, database files, credentials, tokens, private addresses, absolute local paths, and calibration artifacts.

Commit: `feat: integrate local environment monitoring`

## Stage-completion evidence

Automated completion requires every targeted Python and Node test above, compilation, schema validation, privacy scan, and `git diff --check` to pass with fresh output. Real i9 completion remains separate and must record: one schema v2 calibration, 30 daylight comparisons, night/reflection/occlusion rejection, 24-hour no-backlog run, state/notification simulation, M2 outage isolation, load-shedding behavior, and two Android ntfy payload inspection. No software-only result may claim those hardware checks passed.

### Current real-device acceptance order

The software tasks above are complete. The current stage is the unfinished installed-i9
environment acceptance gate, executed in this order without changing business code:

- [x] **E1 — Private schema-v2 calibration:** complete one authenticated Dashboard
  calibration. Keep the reference image and calibration JSON only in ignored local
  runtime storage. Passed on the installed i9 on 2026-08-16; validation recorded only
  schema version, private modes and reference-JPEG validity.
- [ ] **E2 — Daylight accuracy:** record at least 30 operator comparisons. Every
  published `available` result must meet the ±1℃ and ±5%RH targets; otherwise it must
  be rejected as `unavailable`.
- [ ] **E3 — Fail-closed scenes:** verify darkness/infrared, glare, occlusion and gauge
  movement. Unreliable scenes and invalidated geometry must not publish values.
- [ ] **E4 — Independence:** take M2/Ollama offline and confirm gauge sampling, SQLite
  writes, environment state and notification handling continue independently.
- [ ] **E5 — 24-hour stability:** run the gauge/watchdog path for 24 hours, confirm
  60-second scheduling does not build a backlog, and inspect trend gaps and bounded
  health output. The state/notification, load-shedding and two-phone payload checks
  remain part of this same real-device gate.

After E1–E5 pass with redacted evidence, proceed to the existing three-browser HD gate
in `2026-08-04-dashboard-hybrid-hd-streaming.md`; only after that gate and the remaining
release prerequisites proceed to Task 16 in `2026-08-04-baby-monitor-local-v1.md`.

### Task 15: i9-local WS2021 automatic localization

**Status:** approved on 2026-08-16; implementation in progress before E2 resumes.

**Prerequisites:** fixed 2560×1440 five-frame `gauge` burst; schema-v2 scale mapping;
OpenVINO 2025.4.1 on Intel i9; private collection with no baby in frame and no adult
overlap with persisted crops.

**Files:**
- Create: `services/gauge/locator.py`
- Create: `services/gauge/relocation.py`
- Create: `packages/monitoring/ws2021_dataset.py`
- Create: `tools/ws2021_collect.py`
- Create: `tools/ws2021_dataset.py`
- Create: `tools/ws2021_model.py`
- Create: focused tests under `tests/gauge/` and `tests/monitoring/`
- Modify: `services/gauge/source.py`, `services/environment/bootstrap.py`, strict
  settings/schema/examples, Makefile, and existing environment documentation.

**Interfaces:**
- `GaugeLocator.locate(frame: CapturedFrame) -> GaugeLocation`
- `GaugeLocation(box: NormalizedRect, confidence: float, model_version: str)`
- `relocate_calibration(calibration, location) -> Ws2021Calibration`
- collection and training CLIs emit only stable codes and aggregate counts.

- [x] **15.1 Strict locator and relocation contracts:** one valid
  candidate, missing/ambiguous/out-of-bounds candidates, fixed 640×640 letterbox preprocessing,
  deterministic output decoding, and validated schema-v2 geometry migration are covered.
  Implemented without runtime model download or configurable output semantics.
- [x] **15.2 Privacy-safe collection:** tests prove full frames never reach persistence,
  overlapping person/skin candidates and privacy-backend failures are discarded,
  duplicates and poor quality are rejected, crop files are private/atomic, and the
  public result contains closed aggregate counts only.
- [x] **15.3 Dataset and augmentation:** deterministic digest-based split occurs before
  train-only augmentation; fixed 640×640 outputs use relative crop annotations and
  bounded transformations. Negative samples require HTTPS source and license metadata;
  tampered or full-frame private sources fail closed, and the CLI prints counts only.
- [x] **15.4a Explicit local training/export tooling:** an explicit command checks out
  Apache-2.0 YOLOX 0.3.0 at full commit
  `419778480ab6ec0590e5d3831b3afb3b46ab2aa3` into ignored runtime storage, trains
  `YOLOX-Tiny` at 640×640 for the single `ws2021` class through an Intel CPU loop without
  W&B or network logging, exports ONNX, converts it through the pinned OpenVINO Python
  API to FP16 IR, records only non-sensitive metadata/digests, and never commits source
  checkout or weights. The fixed checkout and independent environment are installed;
  a synthetic CPU forward/loss/backward step passes.
- [ ] **15.4b Private model artifact:** after private crops exist, run the explicit
  train/export/check sequence and require exact ONNX/XML/BIN digests. Random or
  synthetic smoke weights cannot satisfy this gate.
- [x] **15.5 Gauge-worker integration:** locate on the first frame of each burst, refine
  the box to an outer quadrilateral plus two-circle layout, migrate schema-v2 geometry,
  and apply the same migrated calibration to all five frames. Missing or ambiguous
  localization produces unavailable and never reuses an old location. The feature is
  disabled by default until a verified private model exists.
- [x] **15.6a Software gate:** focused settings/environment/gauge/dataset/model tests,
  compilation, Make dry-runs and `git diff --check` pass; collection commands expose
  counts only and persist crops only after person/face/skin-overlap rejection.
- [ ] **15.6b Installed-i9 gate:** run
  five 30-second daylight positions plus night/IR collection, review only uncertain
  crops, train locally, verify minimum 1/10-width detection, and resume E2 only after a
  private production reading passes all existing deterministic gates.
  Daylight position 1/5 (current schema-v2 location) completed on 2026-08-16 with 60
  private crop/metadata pairs and a passing aggregate integrity check; positions 2–5,
  night/IR, training/export and reading acceptance remain open.

**Human work:** first confirm no baby is present and collect the current calibrated
position, then place the gauge in five upright, front-facing positions for 30 seconds
each, repeat once under night/IR, and approve/reject only the bounded uncertain crop set.

**Acceptance:** no household full frame persists; no baby crop is accepted; adult
overlap is discarded; model absence and every detection ambiguity fail closed; moving
the upright gauge anywhere in frame re-localizes without manual coordinates; published
readings still satisfy all existing geometry, five-frame, confidence and physical gates.

**Next:** complete the 30 daylight E2 comparisons, then E3–E5 unchanged.
