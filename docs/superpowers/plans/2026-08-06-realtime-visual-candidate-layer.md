# Realtime Visual Candidate Layer Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add an opt-in 5 FPS local visual candidate path that opens deterministic `realtime_watch` candidates within two seconds and requests the existing Qwen four-frame review without bypassing the existing risk state machine.

**Architecture:** The existing visual worker remains the single owner of the camera analysis stream. When `visual.realtime.enabled` is false it preserves the current two-second sampling behavior; when true it prepares safe frames at a load-controlled 5/3/1 FPS, runs OpenCV plus optional pinned YuNet/OpenVINO signals, evaluates a pure candidate state machine, and samples the Qwen ring independently every two seconds. Missing or invalid models degrade only semantic candidates; motion, camera-obstruction checks, frame health, and regular Qwen review continue.

**Tech Stack:** Python 3.11+, Pydantic 2, NumPy 2, OpenCV 4, OpenVINO 2025.4.1 on Intel macOS, Pillow, pytest, go2rtc MJPEG, Bash/Make.

## Global Constraints

- Work only on `/workspace/scratch/d27ee149a7d7/baby-monitor-local-repo`, branch `codex/xiaomi-alpha-visual-risk-core`, starting from `60c15cc`.
- Do not implement audio, event media, formal notifications, medical claims, Dashboard feedback, multi-camera control, or automatic device control.
- The realtime layer may emit `watch_opened` and `candidate_cleared`; it must never create or clear `RiskTransitionKind.ALERT_OPENED` or `RECOVERED`.
- Apply `VisionFramePolicy` before any realtime analyzer, model backend, or callback sees a frame.
- Keep images, boxes, keypoints, model tensors, private addresses, model paths, and household coordinates out of logs, callbacks, tests, and persistent storage.
- Keep `visual.realtime.enabled` default `false`; disabled mode consumes only `analysis` at the existing two-second worker cadence.
- Pin OpenVINO to `2025.4.1`; model files live only under ignored `runtime/models/openvino-2025.4.1/` and are never silently downloaded.
- Verify pinned model size and SHA-256 before loading. YuNet: 232589 bytes, `8f2383e4dd3cfbb4553ea8718107fc0423210dc964f9f4280604804ed2552fa4`; pose XML: 218215 bytes, `ebd70031f92e52b7f1d6ef3b1aead6eff0c9c52130e65ecf77a2447b90a32b84`; pose BIN: 8197354 bytes, `fd4604233dd9ca09fba51c098b662e5fe6b03bf5dac174b686c3d6d5977cf8d5`.
- Use only generated images and synthetic signal sequences in tests. Do not read or write real household media.
- Do not push, merge, create a PR, modify `main`, or modify the user’s i9 `runtime/` configuration in this task. Produce local commits only.

---

### Task 1: Strict realtime contracts and opt-in settings

**Files:**
- Modify: `packages/contracts/vision.py`
- Modify: `packages/contracts/settings.py`
- Modify: `packages/contracts/__init__.py`
- Modify: `config/settings.example.yaml`
- Modify: `config/settings.schema.json`
- Test: `tests/contracts/test_vision_review.py`
- Test: `tests/contracts/test_settings.py`

**Interfaces:**
- Produces `RealtimeObservation`, `RealtimeCandidateTransition`, `RealtimeCandidateKind`, `RealtimeCandidateTransitionKind`, `SceneQuality`, `BedSubjectTrack`, `AdultTrack`, and `HeadFaceState`.
- Produces `RealtimeVisualSettings(enabled: bool = False)` as `VisualSettings.realtime`.
- Candidate transitions use rule version literal `realtime-visual-v1` and monotonic seconds, not wall-clock timestamps.

- [ ] **Step 1: Write failing strict contract tests**

Add tests that instantiate a complete observation, reject `motion_ratio=1.1`, negative counts, negative `processing_ms`, unknown enum values, and extra fields. Add a transition test proving only `watch_opened|candidate_cleared` are accepted and `ALERT_OPENED` is not representable.

```python
observation = RealtimeObservation(
    motion_ratio=0.2,
    scene_quality=SceneQuality.USABLE,
    pose_count=1,
    face_count=1,
    bed_subject_track=BedSubjectTrack.INSIDE,
    adult_track=AdultTrack.ABSENT,
    head_face_state=HeadFaceState.VISIBLE,
    processing_ms=12.5,
)
assert observation.motion_ratio == 0.2
```

- [ ] **Step 2: Run tests and verify RED**

Run: `./.venv-alpha/bin/python -m pytest tests/contracts/test_vision_review.py tests/contracts/test_settings.py -q`

Expected: collection fails because the realtime contracts and settings do not exist.

- [ ] **Step 3: Implement the contracts and settings**

Use frozen, extra-forbidden Pydantic models. Counts are `int | None`: `None` is the only model-unavailable representation; it must not be converted to zero. `processing_ms` is finite and non-negative. Add `realtime: RealtimeVisualSettings = RealtimeVisualSettings()` under `VisualSettings`.

- [ ] **Step 4: Regenerate and validate the checked-in schema**

Run:

```bash
./.venv-alpha/bin/python - <<'PY'
import json
from pathlib import Path
from packages.contracts.settings import AppSettings
Path('config/settings.schema.json').write_text(
    json.dumps(AppSettings.model_json_schema(), indent=2, ensure_ascii=False) + '\n',
    encoding='utf-8',
)
PY
./.venv-alpha/bin/python -m json.tool config/settings.schema.json >/dev/null
```

- [ ] **Step 5: Run tests and verify GREEN**

Run: `./.venv-alpha/bin/python -m pytest tests/contracts/test_vision_review.py tests/contracts/test_settings.py -q`

Expected: all contract and settings tests pass.

- [ ] **Step 6: Commit**

```bash
git add packages/contracts config/settings.example.yaml config/settings.schema.json tests/contracts
git commit -m "feat: define realtime visual contracts"
```

### Task 2: Pinned model assets and redacted optional backend

**Files:**
- Modify: `pyproject.toml`
- Create: `services/vision/realtime_models.py`
- Create: `packages/monitoring/realtime_models.py`
- Create: `tools/realtime_models.py`
- Create: `tests/vision/test_realtime_models.py`
- Create: `tests/monitoring/test_realtime_models.py`

**Interfaces:**
- Produces `verify_realtime_model_assets(root: Path) -> ModelAssetStatus` with stable `ok|missing|size_mismatch|digest_mismatch` codes.
- Produces explicit CLI `check` and `install`; `install` downloads to temporary files, verifies size/digest, then atomically replaces the fixed destinations.
- Produces `RealtimeModelBackend.infer(bgr: numpy.ndarray) -> RealtimeModelSignals` and `build_realtime_model_backend(root: Path) -> RealtimeModelBackend | None`.
- `RealtimeModelSignals` carries face rectangles and pose centers/neck-hip angles only in process memory; it is never exposed by worker callbacks.

- [ ] **Step 1: Write failing asset verification tests**

Use small injected synthetic manifests to prove missing, wrong size, wrong digest, and valid files return stable codes without including paths or bytes in `repr(status)`.

- [ ] **Step 2: Run asset tests and verify RED**

Run: `./.venv-alpha/bin/python -m pytest tests/monitoring/test_realtime_models.py tests/vision/test_realtime_models.py -q`

Expected: collection fails because the model modules do not exist.

- [ ] **Step 3: Implement verification and explicit atomic installation**

Use three fixed HTTPS sources from OpenCV Zoo and Open Model Zoo 2023.0 FP16. Refuse redirects to a non-HTTPS destination, cap reads at expected size plus one byte, write under the destination parent, `fsync`, verify, then `os.replace`. Do not invoke installation from worker/bootstrap/startup.

- [ ] **Step 4: Implement the optional runtime backend**

Import `openvino` only inside the backend builder. Require `openvino.__version__` to begin with `2025.4`; otherwise return a redacted unavailable status. Build YuNet with `cv2.FaceDetectorYN_create`, compile pose IR to `CPU`, and reduce output to bounded face rectangles, pose centers, and torso angles. Convert every loading/inference exception to `RealtimeModelError('realtime_model_unavailable')` or `RealtimeModelError('realtime_inference_failed')`.

- [ ] **Step 5: Add Intel-macOS-only OpenVINO dependency and safe CLI tests**

Add `openvino==2025.4.1` with `sys_platform == 'darwin' and platform_machine == 'x86_64'`. Prove `tools/realtime_models.py --help` does not download and `check` against an empty temporary root returns a stable nonzero status without paths.

- [ ] **Step 6: Run tests and verify GREEN**

Run: `./.venv-alpha/bin/python -m pytest tests/monitoring/test_realtime_models.py tests/vision/test_realtime_models.py -q`

Expected: all model asset/backend boundary tests pass without OpenVINO installed on CI.

- [ ] **Step 7: Commit**

```bash
git add pyproject.toml packages/monitoring/realtime_models.py services/vision/realtime_models.py tools/realtime_models.py tests/monitoring/test_realtime_models.py tests/vision/test_realtime_models.py
git commit -m "feat: verify pinned realtime vision models"
```

### Task 3: Safe-frame realtime analyzer

**Files:**
- Create: `services/vision/realtime_analyzer.py`
- Create: `tests/vision/test_realtime_analyzer.py`
- Modify: `tests/vision/test_frame_policy.py`

**Interfaces:**
- Produces `RealtimeVisualAnalyzer.analyze(frame: PreparedAnalysisFrame, *, monotonic_now: float) -> RealtimeObservation`.
- Consumes an optional `RealtimeModelBackend`; absent or failed backend yields `pose_count=None`, `face_count=None`, and uncertain semantic tracks while preserving motion and scene quality.
- The analyzer accepts only `PreparedAnalysisFrame`; no `CapturedFrame` overload exists.

- [ ] **Step 1: Write failing generated-image analyzer tests**

Generate 960×540 JPEGs for static texture, center motion, edge-only motion, dark, flat, blurred, and global infrared-like luma shift. Prove the first frame has zero motion, center motion exceeds the adaptive floor, edge-only motion cannot create a semantic track, model absence remains `None`, and a three-second infrared grace produces `uncertain` instead of camera obstruction.

- [ ] **Step 2: Run analyzer tests and verify RED**

Run: `./.venv-alpha/bin/python -m pytest tests/vision/test_realtime_analyzer.py tests/vision/test_frame_policy.py -q`

Expected: collection fails because `RealtimeVisualAnalyzer` does not exist.

- [ ] **Step 3: Implement minimal OpenCV analysis**

Decode the prepared JPEG with `cv2.imdecode`, verify exact dimensions, calculate luma mean/stddev, Laplacian variance, edge density, and center-region absolute difference. Keep a bounded EMA of stable motion. A global luma shift larger than 35 with low local motion starts a three-second uncertain grace. Classify model tracks only when scene quality is usable and signals are finite and in bounds.

- [ ] **Step 4: Prove privacy ordering at the real boundary**

Use a recording model backend and a generated source JPEG whose privacy polygon covers a colored patch. Call `VisionFramePolicy.prepare()` before `analyze()` and assert the backend receives black pixels at that patch and never receives the original `CapturedFrame` payload.

- [ ] **Step 5: Run tests and verify GREEN**

Run: `./.venv-alpha/bin/python -m pytest tests/vision/test_realtime_analyzer.py tests/vision/test_frame_policy.py -q`

Expected: all analyzer and frame-policy tests pass.

- [ ] **Step 6: Commit**

```bash
git add services/vision/realtime_analyzer.py tests/vision/test_realtime_analyzer.py tests/vision/test_frame_policy.py
git commit -m "feat: analyze safe frames in realtime"
```

### Task 4: Deterministic candidate state machine

**Files:**
- Create: `services/vision/realtime_candidates.py`
- Create: `tests/vision/test_realtime_candidates.py`

**Interfaces:**
- Produces `RealtimeCandidateStateMachine.evaluate(observation: RealtimeObservation, *, monotonic_now: float) -> tuple[RealtimeCandidateTransition, ...]`.
- Each track uses `idle -> observing -> watch_open -> cooldown`; only transitions are externally visible.
- Semantic candidates require model counts not `None`, usable scene quality, and relevant prior history. Camera obstruction remains available when semantic models are absent.

- [ ] **Step 1: Write failing table-driven state tests**

Cover opening/clearing thresholds for significant motion (0.6/2s), rollover proxy (1/2s), face obstruction (1.5/2s), exit (1/2s), adult intervention (0.6/2s), and camera obstruction (2/2s). Add startup warmup, time rollback, no prior face/inside history, low quality, edge-only/no-subject motion, adult suppression of exit for 30 seconds, and no duplicate watch tests.

- [ ] **Step 2: Run tests and verify RED**

Run: `./.venv-alpha/bin/python -m pytest tests/vision/test_realtime_candidates.py -q`

Expected: collection fails because the candidate state machine does not exist.

- [ ] **Step 3: Implement the pure state machine**

Use monotonic floats only. Warm up semantic tracks for ten seconds while allowing camera obstruction. Use an adaptive motion threshold `max(0.01, noise_mean + 3 * noise_deviation)` bounded to `0.20`. Record face-visible and subject-inside history for ten seconds. A rollover proxy requires significant motion, one pose, and face transition from visible to temporarily missing; its name and docs remain `possible_rollover_or_prone`, never a confirmed posture.

- [ ] **Step 4: Prove it cannot mutate risk state**

Evaluate every candidate against a real `VisualRiskStateMachine`, assert its state remains `NORMAL`, and assert candidate transition kinds are disjoint from `RiskTransitionKind` values `alert_opened|recovered`.

- [ ] **Step 5: Run tests and verify GREEN**

Run: `./.venv-alpha/bin/python -m pytest tests/vision/test_realtime_candidates.py tests/vision/test_risk_state.py -q`

Expected: all candidate and risk-state tests pass.

- [ ] **Step 6: Commit**

```bash
git add services/vision/realtime_candidates.py tests/vision/test_realtime_candidates.py
git commit -m "feat: track realtime visual candidates"
```

### Task 5: 5/3/1 FPS load controller

**Files:**
- Create: `services/vision/realtime_load.py`
- Create: `tests/vision/test_realtime_load.py`

**Interfaces:**
- Produces `RealtimeLoadController.observe(processing_ms: float, *, monotonic_now: float) -> RealtimeLoadStatus`.
- `RealtimeLoadStatus` exposes `target_fps: Literal[1,3,5]`, `p95_ms`, and optional `degraded|recovered` transition code only; it never exposes samples or paths.

- [ ] **Step 1: Write failing load sequence tests**

Prove 5 FPS stays at 5 below 180ms, drops to 3 only after five continuous seconds above P95 180ms, drops to 1 only after ten continuous seconds above P95 300ms, and recovers one level only after 60 continuous seconds within the current budget. Reject NaN, infinity, negative duration, and decreasing time.

- [ ] **Step 2: Run tests and verify RED**

Run: `./.venv-alpha/bin/python -m pytest tests/vision/test_realtime_load.py -q`

Expected: collection fails because `RealtimeLoadController` does not exist.

- [ ] **Step 3: Implement bounded-window P95 and transitions**

Keep only the last ten seconds of samples in a deque. Compute nearest-rank P95 from the bounded sample list. Reset overload/recovery evidence whenever the relevant budget condition changes. Emit a transition only when the tier changes.

- [ ] **Step 4: Run tests and verify GREEN**

Run: `./.venv-alpha/bin/python -m pytest tests/vision/test_realtime_load.py -q`

Expected: all load-controller tests pass.

- [ ] **Step 5: Commit**

```bash
git add services/vision/realtime_load.py tests/vision/test_realtime_load.py
git commit -m "feat: degrade realtime visual load safely"
```

### Task 6: Worker dual cadence and urgent Qwen scheduling

**Files:**
- Modify: `services/stream/frame_source.py`
- Modify: `services/vision/worker.py`
- Modify: `services/vision/bootstrap.py`
- Modify: `tests/stream/test_frame_source.py`
- Modify: `tests/vision/test_worker.py`
- Modify: `tests/vision/test_bootstrap.py`

**Interfaces:**
- `Go2RtcAnalysisFrameSource(stream_name: Literal['analysis','analysis_realtime']='analysis')` fixes the requested local stream name at construction.
- `VisualWorker` receives optional analyzer, candidate machine, load controller, and `on_realtime_candidate`/`on_realtime_health` callbacks.
- Realtime mode prepares frames at the current load tier, adds at most one frame per two seconds to the Qwen ring, and keeps regular review at ten seconds.

- [ ] **Step 1: Write failing source and worker cadence tests**

At 5 FPS for ten seconds assert about 51 realtime analyzer calls, six ring frames at seconds 0/2/4/6/8/10, and one regular review at ten seconds. Disabled mode must retain six policy/ring calls. Assert a semantic watch with a warm ring submits `urgent=True` in the same `run_frame` call and callback latency is no more than 0.2 seconds in the injected monotonic clock.

- [ ] **Step 2: Run tests and verify RED**

Run: `./.venv-alpha/bin/python -m pytest tests/stream/test_frame_source.py tests/vision/test_worker.py tests/vision/test_bootstrap.py -q`

Expected: new realtime construction and cadence assertions fail.

- [ ] **Step 3: Implement independent light/ring/review gates**

Keep the existing two-second gate only for disabled mode. In realtime mode, run policy/analyzer at `1 / target_fps`, frame health on every accepted safe frame, ring add at most every two seconds, and regular submit every ten seconds. If a watch opens with fewer than four review frames set one `urgent_pending`; submit once frames are sufficient. Busy or rate-limited urgent submissions do not queue.

- [ ] **Step 4: Implement fail-closed degradation**

Analyzer/model exceptions update redacted realtime health and leave frame health, ring sampling, and regular reviews active. Candidate callback exceptions become `realtime_callback_failed` and cannot stop the worker. Candidate clears never call `VisualReviewRuntime`.

- [ ] **Step 5: Compose opt-in runtime**

Bootstrap chooses `analysis_realtime` only when settings enable it. It verifies model assets and attempts the optional backend; unavailable models create one `realtime_model_degraded` health update while analyzer motion/scene processing stays active. Extend `VisualRuntimeResources` ownership and idempotent close tests.

- [ ] **Step 6: Run tests and verify GREEN**

Run: `./.venv-alpha/bin/python -m pytest tests/stream/test_frame_source.py tests/vision/test_worker.py tests/vision/test_bootstrap.py tests/vision/test_review_scheduler.py tests/vision/test_review_runtime.py -q`

Expected: all worker, source, scheduler, runtime, and bootstrap tests pass.

- [ ] **Step 7: Commit**

```bash
git add services/stream/frame_source.py services/vision/worker.py services/vision/bootstrap.py tests/stream/test_frame_source.py tests/vision/test_worker.py tests/vision/test_bootstrap.py
git commit -m "feat: schedule realtime visual review"
```

### Task 7: go2rtc profile, explicit setup commands, documentation, and gates

**Files:**
- Modify: `config/go2rtc.alpha.yaml`
- Modify: `Makefile`
- Modify: `tools/install_alpha_macos.sh`
- Modify: `tests/deploy/test_alpha_commands.py`
- Modify: `tests/deploy/test_visual_worker_deploy.py`
- Modify: `docs/superpowers/specs/2026-08-06-realtime-visual-candidate-layer-design.md`
- Modify: `docs/STATUS.md`
- Modify: `docs/CHECKPOINT.md`
- Modify: `docs/NEXT.md`

**Interfaces:**
- Adds fixed template stream `analysis_realtime: ffmpeg:source#video=mjpeg#width=960#height=540#raw=-r 5` while preserving `analysis` at 1 FPS.
- Adds explicit `make alpha-realtime-models-check` and `make alpha-realtime-models-install`; neither runs during ordinary `alpha-start`.
- Existing runtime YAML remains preserved by install. The final report tells the user the current i9 runtime config still requires an explicit reviewed upgrade before enabling realtime mode.

- [ ] **Step 1: Write failing deployment behavior tests**

Parse the YAML and assert both analysis profiles are exact and video-only. Dry-run both Make targets and assert only the explicit install target contains network download behavior. Assert start scripts do not invoke model installation and installer still preserves existing runtime configuration.

- [ ] **Step 2: Run deployment tests and verify RED**

Run: `./.venv-alpha/bin/python -m pytest tests/deploy/test_alpha_commands.py tests/deploy/test_visual_worker_deploy.py -q`

Expected: realtime stream and Make target assertions fail.

- [ ] **Step 3: Implement the template and explicit commands**

Add the 5 FPS stream, Make help/targets, and Intel macOS dependency installation through the project package. Do not auto-edit existing `runtime/go2rtc.yaml` and do not auto-enable settings.

- [ ] **Step 4: Update approved status and honest delivery state**

Mark the spec approved. Record software/synthetic completion only after gates pass; record real i9 model installation, P50/P95, CPU, latency, and household accuracy as unverified follow-up. Do not claim real-time accuracy from CI.

- [ ] **Step 5: Run focused and complete verification**

Run:

```bash
./.venv-alpha/bin/python -m pytest tests/contracts tests/monitoring/test_realtime_models.py tests/vision tests/stream tests/deploy -q
./.venv-alpha/bin/python -m pytest -q
node --test tests/frontend/*.test.mjs
./.venv-alpha/bin/python -m compileall -q apps packages services tools
bash -n tools/*.sh
./.venv-alpha/bin/python -m json.tool config/settings.schema.json >/dev/null
git diff --check
```

Expected: zero failures; document the exact Python and Node test counts.

- [ ] **Step 6: Review scope and sensitive-data diff**

Run:

```bash
git status --short
git diff --stat 60c15cc..HEAD
git diff --check 60c15cc..HEAD
git grep -nEi 'github_pat_|password=|token=|cs2://|192\.168\.' -- ':!docs/superpowers/plans/*'
```

Expected: only planned files are changed and no credential, private URI, private address, or real household media appears.

- [ ] **Step 7: Commit final integration and evidence**

```bash
git add config/go2rtc.alpha.yaml Makefile tools/install_alpha_macos.sh tests/deploy docs/STATUS.md docs/CHECKPOINT.md docs/NEXT.md docs/superpowers/specs/2026-08-06-realtime-visual-candidate-layer-design.md docs/superpowers/plans/2026-08-06-realtime-visual-candidate-layer.md
git commit -m "docs: record realtime visual candidate gate"
```

## Plan self-review

- Spec coverage: candidate rules, two cadences, privacy-before-model, pinned assets, model degradation, 5/3/1 load control, urgent Qwen, disabled rollback, deployment templates, synthetic gates, and honest i9 follow-up each map to a task.
- Placeholder scan: no `TBD`, `TODO`, “implement later”, or unspecified error-handling step remains.
- Type consistency: Tasks 3–6 consume the exact contracts from Task 1; only Task 6 owns ring/review cadence; candidate transitions never share `RiskTransitionKind`.
- Known limitation retained from the approved design: the first implementation uses a conservative rollover proxy from motion + tracked pose + face disappearance. It remains a `watch` candidate and requires Qwen and later household validation; it is not described as confirmed prone posture.
