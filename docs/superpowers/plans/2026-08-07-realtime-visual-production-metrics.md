# Realtime Visual Production Metrics Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Expose the realtime visual worker's current load tier and bounded processing-time distribution through a local, redacted, fail-closed status command.

**Architecture:** Extend `RealtimeLoadStatus` with nearest-rank P50/P95/max and bounded sample count, then let `VisualWorker` publish an immutable redacted snapshot after each successful analysis. A single-purpose writer atomically replaces a mode-`0600` JSON file, while a strict reader/CLI reports only an allowlisted aggregate contract and rejects missing, stale, or malformed state without exposing paths or exceptions.

**Tech Stack:** Python 3.11+, standard-library dataclasses/JSON/filesystem APIs, pytest, GNU Make/macOS launchd integration.

## Global Constraints

- The state schema is exactly version `1`; no extra JSON fields are accepted.
- `realtime_fps` is one of `1`, `3`, or `5`; `sample_count` is `1..51`.
- Processing values are finite, non-negative, rounded to three decimals, and satisfy P50 <= P95 <= max.
- The state file is `runtime/status/realtime-visual.json`, published atomically with mode `0600`.
- Files older than 15 seconds are stale; missing, stale, and invalid states fail closed with stable redacted output.
- Never persist frames, tensors, detection counts, candidate data, room/device/network details, paths, exceptions, credentials, or logs.
- Do not change realtime model thresholds, candidate/risk rules, Qwen scheduling, alerts, dependencies, or network listeners.
- Do not push, merge, or modify `main`; deliver local commits on `codex/xiaomi-alpha-visual-risk-core`.

---

### Task 1: Bounded load distribution contract

**Files:**
- Modify: `services/vision/realtime_load.py`
- Test: `tests/vision/test_realtime_load.py`

**Interfaces:**
- Consumes: `RealtimeLoadController.observe(processing_ms: float, *, monotonic_now: float)`.
- Produces: `RealtimeLoadStatus(target_fps, sample_count, p50_ms, p95_ms, max_ms, transition_code)` with a 51-sample/10-second bounded window.

- [x] **Step 1: Write failing hand-calculated distribution tests**

Add tests that feed `10.001`, `20.002`, `30.003`, and `40.004` milliseconds and assert literal values `sample_count == 4`, `p50_ms == 20.002`, `p95_ms == 40.004`, and `max_ms == 40.004`. Add a boundary test proving samples older than 10 seconds are evicted and no more than 51 samples remain.

- [x] **Step 2: Run the focused test and verify RED**

Run: `.venv-alpha/bin/python -m pytest tests/vision/test_realtime_load.py -q`

Expected: FAIL because `RealtimeLoadStatus` lacks `sample_count`, `p50_ms`, and `max_ms`.

- [x] **Step 3: Implement the minimal bounded statistics**

Use `deque(maxlen=51)`, compute nearest-rank percentiles from the current 10-second window, and return all aggregate fields before resetting overload/recovery evidence. Keep existing transition timing unchanged.

- [x] **Step 4: Run focused tests and verify GREEN**

Run: `.venv-alpha/bin/python -m pytest tests/vision/test_realtime_load.py tests/vision/test_worker.py -q`

Expected: all load and worker tests pass after updating the existing fixed load test double to construct the expanded status.

### Task 2: Worker redacted snapshot and callback isolation

**Files:**
- Create: `services/vision/realtime_status.py`
- Modify: `services/vision/worker.py`
- Modify: `services/vision/bootstrap.py`
- Test: `tests/vision/test_worker.py`
- Test: `tests/vision/test_bootstrap.py`

**Interfaces:**
- Consumes: the expanded `LoadStatusLike` fields and analyzer `model_state`.
- Produces: frozen `RealtimeVisualMetricsSnapshot(realtime_fps, sample_count, processing_p50_ms, processing_p95_ms, processing_max_ms, realtime_model_state)` and optional `on_realtime_status(snapshot)` callback.

- [x] **Step 1: Write failing snapshot publication tests**

Assert that one successful analysis publishes exactly one immutable snapshot containing only the six aggregate fields and literal hand-supplied values. Add a test whose callback raises an exception and prove candidate evaluation continues while `on_realtime_health` receives only `realtime_status_write_failed`.

- [x] **Step 2: Run worker tests and verify RED**

Run: `.venv-alpha/bin/python -m pytest tests/vision/test_worker.py -q`

Expected: FAIL because the snapshot class and callback do not exist.

- [x] **Step 3: Implement snapshot publication after successful analysis**

Define the frozen snapshot in `realtime_status.py`, add the callback to `VisualWorker`, and invoke it in its own `try/except` after load/model health is updated. Publish the stable health code on callback failure without entering `realtime_analysis_failed` and without interrupting candidate evaluation.

- [x] **Step 4: Thread the callback through bootstrap and verify GREEN**

Add `on_realtime_status` as an optional keyword to `build_visual_runtime`, pass it to `VisualWorker`, and test the real bootstrap boundary. Run: `.venv-alpha/bin/python -m pytest tests/vision/test_worker.py tests/vision/test_bootstrap.py -q`.

Expected: all worker and bootstrap tests pass.

### Task 3: Atomic writer and strict redacted reader

**Files:**
- Modify: `services/vision/realtime_status.py`
- Create: `tools/realtime_visual_status.py`
- Create: `tests/vision/test_realtime_status.py`
- Create: `tests/tools/test_realtime_visual_status.py`

**Interfaces:**
- Consumes: `RealtimeVisualMetricsSnapshot` plus injected wall-clock time.
- Produces: `RealtimeVisualStatusWriter(path, wall_clock=time.time)` and CLI `main(argv=None, *, wall_clock=time.time) -> int`.

- [x] **Step 1: Write failing writer contract tests**

Use a temporary directory to prove the writer creates strict schema-v1 JSON, rounds values to three decimals, leaves the target at mode `0600`, replaces an existing target, and rejects NaN, out-of-range counts/FPS, invalid model states, and inverted percentile order before filesystem mutation.

- [x] **Step 2: Run writer tests and verify RED**

Run: `.venv-alpha/bin/python -m pytest tests/vision/test_realtime_status.py -q`

Expected: FAIL because the writer is not implemented.

- [x] **Step 3: Implement validation and atomic publication**

Validate before filesystem mutation; create the parent directory, create a same-directory temporary file, set file descriptor mode `0600`, write fixed-key JSON, flush and `fsync`, then `os.replace`. Remove only the writer-owned temporary file after a failed publication.

- [x] **Step 4: Write failing CLI state tests**

Call the real CLI main function against controlled files and assert exact fixed-order output for available state. Assert only `realtime_metrics=unavailable`, `realtime_metrics=stale`, or `realtime_metrics=invalid` for each failing branch, a non-zero exit code, empty stderr, and no path or exception text.

- [x] **Step 5: Run CLI tests and verify RED**

Run: `.venv-alpha/bin/python -m pytest tests/tools/test_realtime_visual_status.py -q`

Expected: FAIL because the CLI does not exist.

- [x] **Step 6: Implement strict reader and CLI**

Accept exactly the eight schema fields, reject booleans masquerading as numbers, reject non-finite/range/order violations, classify age greater than 15 seconds as stale, and print available aggregate keys in the approved order. Keep the optional `--path` argument for controlled testing while defaulting to `runtime/status/realtime-visual.json`.

- [x] **Step 7: Verify writer and CLI GREEN**

Run: `.venv-alpha/bin/python -m pytest tests/vision/test_realtime_status.py tests/tools/test_realtime_visual_status.py -q`

Expected: all status tests pass with no emitted path or exception detail.

### Task 4: Production wiring and deployment command

**Files:**
- Modify: `tools/run_visual_worker.py`
- Modify: `Makefile`
- Test: `tests/tools/test_run_visual_worker.py`
- Test: `tests/tools/test_realtime_visual_status.py`

**Interfaces:**
- Consumes: `RealtimeVisualStatusWriter(ROOT / "runtime/status/realtime-visual.json")`.
- Produces: worker callback wiring and `make alpha-visual-status` invocation only when the worker is running.

- [x] **Step 1: Write failing production wiring tests**

Verify the entrypoint supplies the writer callback to `build_visual_runtime`. Exercise a Make dry-run and/or controlled Make invocation to prove the reader command is guarded by the same launchd/PID liveness decision and that no HTTP listener is added.

- [x] **Step 2: Run focused integration tests and verify RED**

Run: `.venv-alpha/bin/python -m pytest tests/tools/test_run_visual_worker.py tests/tools/test_realtime_visual_status.py -q`

Expected: FAIL because the writer is not wired and Make does not invoke the status reader.

- [x] **Step 3: Wire production entrypoint and Make target**

Construct the writer before bootstrap and inject it as `on_realtime_status`. Extend `alpha-visual-status` with a guarded CLI call; preserve existing worker, Ollama tunnel, and bridge output.

- [x] **Step 4: Run focused tests and verify GREEN**

Run: `.venv-alpha/bin/python -m pytest tests/vision/test_realtime_load.py tests/vision/test_realtime_status.py tests/vision/test_worker.py tests/vision/test_bootstrap.py tests/tools/test_run_visual_worker.py tests/tools/test_realtime_visual_status.py -q`

Expected: all production metrics tests pass.

### Task 5: Full verification, privacy review, and local delivery

**Files:**
- Modify: `docs/CHECKPOINT.md`
- Modify: this plan to mark completed steps

**Interfaces:**
- Consumes: all prior tasks.
- Produces: fresh software-gate evidence and one local commit; no remote mutation.

- [x] **Step 1: Run the complete automated gates**

Run:

```bash
.venv-alpha/bin/python -m pytest -q
node --test tests/frontend/*.test.mjs
.venv-alpha/bin/python -m compileall -q apps packages services tools
.venv-alpha/bin/python -m json.tool config/settings.schema.json >/dev/null
bash -n tools/*.sh
make -n alpha-visual-status >/dev/null
git diff --check
```

Expected: Python and browser suites pass, compilation/schema/Shell/Make/diff checks exit zero, and only the pre-existing Starlette/httpx warning remains.

- [x] **Step 2: Run tracked-artifact and secret boundaries**

Inspect `git status --short`, reject tracked files under `runtime/`, reject image/audio/video/database extensions, scan changed files for GitHub token/private-key markers and private network literals, and confirm the state schema names only the eight approved fields.

- [x] **Step 3: Review the diff against every approved requirement**

Confirm strict schema, atomic same-filesystem replacement, mode `0600`, stale/invalid/unavailable fail-closed behavior, callback isolation, no new port, no model/risk/candidate change, and no raw household data path.

- [x] **Step 4: Record honest checkpoint evidence and commit locally**

Update `docs/CHECKPOINT.md` with software-only evidence and the still-pending i9 10-minute gate. Commit the focused implementation on `codex/xiaomi-alpha-visual-risk-core`; do not push.
