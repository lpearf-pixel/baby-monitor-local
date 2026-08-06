# Visual Capture, Health, and Single-Flight Scheduler Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Complete visual stage R2b by maintaining one private low-rate go2rtc analysis stream, converting it into privacy-safe in-memory frames, detecting conservative camera disconnect/freeze conditions, and scheduling at most one future model review without a disk queue.

**Architecture:** Add an on-demand `analysis` stream derived from the existing Xiaomi `source`, then consume it through one loopback-only MJPEG connection. `VisualFrameHealthMonitor` owns deterministic disconnect/freeze evidence, `VisualReviewScheduler` owns the single-flight boundary, and `VisualWorker` composes capture, privacy policy, the existing 40-second ring, health, and an injected future reviewer. R2b has no Ollama client, SSH tunnel, notifications, event media, database writes, Dashboard routes, or launchd service; those enter in R3/R4 only when a real backend exists.

**Tech Stack:** Python 3.11, Pydantic 2, Pillow 11+, NumPy 2, go2rtc 1.9.14, pytest.

## Global Constraints

- Xiaomi credentials and the runtime `source` expression remain local and are never printed, logged, or copied into tests.
- go2rtc API access remains loopback-only; no caller-controlled URL, stream name, FFmpeg argument, proxy, or filesystem path enters the frame source.
- The analysis profile is exactly `ffmpeg:source#video=mjpeg#width=960#height=540#raw=-r 1`; the worker samples accepted frames every 2 seconds.
- One visual worker owns one long-lived `analysis` MJPEG consumer and reconnects with bounded backoff after EOF or transport failure.
- Bed crop and privacy masks are applied before a frame enters the review ring or reviewer.
- The ring remains in memory only, retains at most 40 seconds and 21 prepared frames, and creates no normal-frame files.
- A static baby or dark room is not sufficient evidence of a frozen camera. Freeze escalation requires 60 seconds of identical usable fingerprints and an identical frame after reconnect.
- Camera disconnect escalation requires 60 seconds of continuous source failure. Recovery requires 20 seconds of valid changing frames.
- At most one review future exists. A busy reviewer causes the due review to be skipped, never queued.
- Regular reviews are at least 10 seconds apart; an explicitly requested urgent review is at least 5 seconds after the previous submission.
- Model output remains observation evidence only. R2b does not open care alerts or send notifications.
- All timestamps are timezone-aware and all scheduling decisions use monotonic time.
- All production exceptions exposed across module boundaries use stable non-sensitive codes.
- Tests use generated JPEGs and fake streams only; no household images, recordings, addresses, IDs, or credentials enter Git.

---

### Task 1: Safe analysis-stream profile and runtime migration primitive

**Files:**
- Modify: `packages/monitoring/alpha_quality.py`
- Modify: `config/go2rtc.alpha.yaml`
- Modify: `tests/monitoring/test_alpha_quality.py`

**Interfaces:**
- Consumes: an already configured runtime mapping containing the private `streams.source` entry.
- Produces: `ANALYSIS_STREAM`, `with_visual_analysis_stream(config: dict[str, Any]) -> dict[str, Any]`, and HD/subtype transformations that preserve or install the exact analysis profile without exposing `source`.

- [ ] **Step 1: Write failing profile tests**

Import `ANALYSIS_STREAM` and `with_visual_analysis_stream`. Prove the transformation rejects a missing/non-Xiaomi `source`, preserves unknown Xiaomi query parameters and unrelated streams, installs the exact fixed analysis expression, does not mutate its input, and is idempotent:

```python
original = {
    "streams": {
        "source": "xiaomi://device:cn@192.0.2.10?did=example&vendor_hint=keep",
        "recording": "keep",
    }
}
updated = with_visual_analysis_stream(original)
assert updated["streams"]["analysis"] == ANALYSIS_STREAM
assert updated["streams"]["recording"] == "keep"
assert original["streams"].get("analysis") is None
assert with_visual_analysis_stream(updated) == updated
```

Also assert `upgrade_to_hd()` and `with_source_subtype()` include `ANALYSIS_STREAM`, so every existing safe quality migration converges on the same profile.

- [ ] **Step 2: Run the tests and verify RED**

Run: `.venv-alpha/bin/pytest tests/monitoring/test_alpha_quality.py -q`

Expected: collection fails because `ANALYSIS_STREAM` and `with_visual_analysis_stream` do not exist.

- [ ] **Step 3: Implement the immutable profile transformation**

Add:

```python
ANALYSIS_STREAM = "ffmpeg:source#video=mjpeg#width=960#height=540#raw=-r 1"

def with_visual_analysis_stream(config: dict[str, Any]) -> dict[str, Any]:
    result = deepcopy(config)
    streams = _streams(result)
    source = streams.get("source")
    if not isinstance(source, str) or not source.startswith("xiaomi://"):
        raise QualityConfigError("SOURCE_NOT_CONFIGURED")
    streams["analysis"] = ANALYSIS_STREAM
    return result
```

Have `upgrade_to_hd()` and `with_source_subtype()` set the same constant while already operating on their copied mappings. Add the same entry to `config/go2rtc.alpha.yaml`. Do not add a second camera URI or an always-on process; go2rtc starts FFmpeg only when the worker consumes `analysis`.

- [ ] **Step 4: Verify GREEN**

Run: `.venv-alpha/bin/pytest tests/monitoring/test_alpha_quality.py tests/monitoring/test_subtype_probe.py -q`

Expected: all profile and subtype tests pass.

- [ ] **Step 5: Commit the analysis profile slice**

```bash
git add packages/monitoring/alpha_quality.py config/go2rtc.alpha.yaml tests/monitoring/test_alpha_quality.py
git commit -m "feat: define private visual analysis stream"
```

### Task 2: One continuous loopback MJPEG consumer

**Files:**
- Modify: `services/stream/frame_source.py`
- Modify: `tests/stream/test_frame_source.py`

**Interfaces:**
- Consumes: fixed loopback go2rtc origin and fixed `analysis` stream.
- Produces: `Go2RtcAnalysisFrameSource.iter_frames(timeout_seconds: float = 8) -> Iterator[CapturedFrame]`; one iterator holds one HTTP response until EOF, close, or transport failure.

- [ ] **Step 1: Write failing continuous-source tests**

Use the existing generated `FakeResponse` and `mjpeg_payload`. Prove five yielded frames use exactly one request to `http://127.0.0.1:1984/api/stream.mjpeg?src=analysis`, preserve chronological aware capture times, and close the response when the iterator closes. Add tests for non-loopback base URLs, malformed boundary/length/JPEG, EOF, naive `now()`, and transport errors. Assert raised messages are only `malformed_mjpeg`, `frame_invalid`, or `frame_source_unavailable`, never the underlying exception text.

```python
source = Go2RtcAnalysisFrameSource(opener=opener, now=lambda: next(times))
iterator = source.iter_frames(timeout_seconds=8)
frames = [next(iterator) for _ in range(5)]
iterator.close()
assert len(opener.requests) == 1
assert opener.requests[0][0].endswith("/api/stream.mjpeg?src=analysis")
assert [frame.captured_at for frame in frames] == times_seen
```

- [ ] **Step 2: Run the tests and verify RED**

Run: `.venv-alpha/bin/pytest tests/stream/test_frame_source.py -q`

Expected: import fails because `Go2RtcAnalysisFrameSource` does not exist.

- [ ] **Step 3: Implement the continuous iterator**

Reuse `_validate_base_url`, `_boundary_from_headers`, `_read_part`, and `_validate_jpeg` through private module helpers instead of duplicating parsing rules. Build requests with `urllib.request.Request`, `urlencode({"src": "analysis"})`, `Accept: multipart/x-mixed-replace`, and the existing `ProxyHandler({})` opener. The generator opens once inside `with`, reads parts until response EOF/error, validates each JPEG and aware timestamp, and wraps all non-contract failures as `FrameSourceUnavailable("frame_source_unavailable")`.

Do not add caller-controlled `src`, raw URLs, headers, or reconnect loops to this class; worker composition owns reconnect policy.

- [ ] **Step 4: Verify GREEN**

Run: `.venv-alpha/bin/pytest tests/stream/test_frame_source.py tests/vision/test_frame_policy.py -q`

Expected: all tests pass and existing WS2021 burst behavior is unchanged.

- [ ] **Step 5: Commit the continuous source slice**

```bash
git add services/stream/frame_source.py tests/stream/test_frame_source.py
git commit -m "feat: add continuous visual frame source"
```

### Task 3: Conservative disconnect and freeze evidence

**Files:**
- Create: `services/vision/frame_health.py`
- Create: `tests/vision/test_frame_health.py`

**Interfaces:**
- Consumes: `PreparedAnalysisFrame`, aware wall time, monotonic seconds, and explicit reconnect results.
- Produces: `FrameHealthState`, `FrameHealthCode`, `FrameHealthTransition`, `VisualFrameHealthMonitor.observe(frame, monotonic_now)`, `source_failed(monotonic_now)`, and `confirm_reconnect(frame, monotonic_now)`.

- [ ] **Step 1: Write failing health tests**

Generate 960×540 JPEGs in memory and cover:

- one or many ordinary static-looking frames do not alert before 60 seconds;
- 60 seconds of byte-identical usable frames emits one `reconnect_required` transition;
- an identical valid frame after reconnect emits one `frame_frozen` transition;
- a changed frame after reconnect clears the candidate without a false alert;
- all-black, near-black, or low-contrast frames never become freeze evidence by themselves;
- source failures emit `source_offline` only after 60 seconds and never duplicate it;
- a single valid frame does not recover an offline/frozen state;
- valid changing frames spanning 20 seconds emit one recovery;
- naive/decreasing times are rejected before state mutation.

Representative assertion:

```python
monitor.observe(frame("red", seconds=0), monotonic_now=0.0)
candidate = monitor.observe(frame("red", seconds=60), monotonic_now=60.0)
assert candidate.code is FrameHealthCode.RECONNECT_REQUIRED
frozen = monitor.confirm_reconnect(
    frame("red", seconds=61), monotonic_now=61.0
)
assert frozen.code is FrameHealthCode.FRAME_FROZEN
```

- [ ] **Step 2: Run the tests and verify RED**

Run: `.venv-alpha/bin/pytest tests/vision/test_frame_health.py -q`

Expected: collection fails because `services.vision.frame_health` does not exist.

- [ ] **Step 3: Implement deterministic fingerprints and transitions**

Decode only the already privacy-masked prepared JPEG. Compute an immutable fingerprint containing SHA-256, 8×8 difference hash, rounded mean luminance, rounded luminance standard deviation, width, and height. A frame is usable freeze evidence only when mean luminance is at least `3.0` and standard deviation at least `1.0`.

Keep private monotonic markers for identical-frame start, first source failure, reconnect requirement, open failure state, and recovery start. Exact fingerprint equality for 60 seconds requests one reconnect. `confirm_reconnect()` can open `frame_frozen` only when the post-reconnect fingerprint equals the candidate fingerprint. `source_failed()` opens `source_offline` after 60 seconds. Recovery requires valid fingerprints that change at least once and span 20 seconds. Every public transition contains only enum codes and monotonic duration, never image bytes or paths.

- [ ] **Step 4: Verify GREEN**

Run: `.venv-alpha/bin/pytest tests/vision/test_frame_health.py tests/vision/test_frame_policy.py -q`

Expected: all tests pass.

- [ ] **Step 5: Commit the health slice**

```bash
git add services/vision/frame_health.py tests/vision/test_frame_health.py
git commit -m "feat: detect visual source degradation"
```

### Task 4: Single-flight review scheduler

**Files:**
- Create: `services/vision/review_scheduler.py`
- Create: `tests/vision/test_review_scheduler.py`

**Interfaces:**
- Consumes: four `PreparedAnalysisFrame` objects, injected `Executor`, and injected `review(frames) -> VisualReview` callable.
- Produces: `VisualReviewScheduler.try_submit(frames, monotonic_now, urgent=False) -> ReviewScheduleDecision`, `poll() -> ReviewCompletion | None`, and `close()`.

- [ ] **Step 1: Write failing scheduler tests**

Use a deterministic fake executor/future. Prove the first valid four-frame batch submits, fewer than four frames does not, a second due batch while busy is skipped without calling `submit`, regular submissions are at least 10 seconds apart, urgent submissions are at least 5 seconds apart, completion returns one strict `VisualReview`, exceptions become `ReviewCompletion(code="review_failed")` without exception text, and `close()` cancels a pending future without creating a new one.

```python
first = scheduler.try_submit(frames, monotonic_now=10.0)
busy = scheduler.try_submit(frames, monotonic_now=20.0)
assert first is ReviewScheduleDecision.SUBMITTED
assert busy is ReviewScheduleDecision.SKIPPED_BUSY
assert executor.submit_count == 1
```

- [ ] **Step 2: Run the tests and verify RED**

Run: `.venv-alpha/bin/pytest tests/vision/test_review_scheduler.py -q`

Expected: collection fails because `services.vision.review_scheduler` does not exist.

- [ ] **Step 3: Implement the scheduler**

Define enum decisions `submitted`, `skipped_busy`, `skipped_not_due`, and `skipped_insufficient_frames`. Store at most one `Future[VisualReview]`. `try_submit()` validates four chronological aware frames and uses the injected executor only when due. `poll()` returns `None` while pending, returns exactly one success/failure completion when done, then clears the future. Failure completions expose only `review_failed`. `close()` marks the scheduler closed and cancels a pending future; later submission raises `RuntimeError("review scheduler is closed")`.

- [ ] **Step 4: Verify GREEN**

Run: `.venv-alpha/bin/pytest tests/vision/test_review_scheduler.py tests/contracts/test_vision_review.py -q`

Expected: all tests pass.

- [ ] **Step 5: Commit the scheduler slice**

```bash
git add services/vision/review_scheduler.py tests/vision/test_review_scheduler.py
git commit -m "feat: add single-flight visual review scheduler"
```

### Task 5: Compose the R2b visual worker without production model I/O

**Files:**
- Create: `services/vision/worker.py`
- Create: `tests/vision/test_worker.py`
- Modify: `services/vision/__init__.py`

**Interfaces:**
- Consumes: a factory returning `Iterator[CapturedFrame]`, `VisionFramePolicy`, `AnalysisFrameRing`, `VisualFrameHealthMonitor`, `VisualReviewScheduler`, and a stop event.
- Produces: `VisualWorker.run(stop_event)`, `run_frame(frame, monotonic_now)`, immutable `VisualWorkerHealth`, and callbacks for review completion and frame-health transitions.

- [ ] **Step 1: Write failing worker tests**

Use fake clocks, generated JPEGs, a stream factory, and callbacks. Prove:

- the worker accepts at most one prepared frame every 2 seconds even if input is faster;
- privacy-safe prepared frames, never original camera JPEGs, enter the ring and scheduler;
- four approximately two-second-spaced frames are selected for a review due at 10 seconds;
- a pending review does not block capture and no review backlog forms;
- source EOF/failure closes the iterator, reports health evidence, waits a bounded 1/2/4/8-second backoff, and reconnects;
- `reconnect_required` closes the current iterator and the first new frame goes through `confirm_reconnect()`;
- policy failure degrades worker health without leaking exception text or killing the loop;
- stopping closes the iterator and scheduler;
- no filesystem, SQLite, notification, environment-worker, or API objects are imported or called.

Representative cadence check:

```python
for second in range(9):
    worker.run_frame(captured(second), monotonic_now=float(second))
assert len(ring) == 5  # accepted at 0, 2, 4, 6, 8
assert scheduler.submitted_batches == 0
worker.run_frame(captured(10), monotonic_now=10.0)
assert scheduler.submitted_batches == 1
```

- [ ] **Step 2: Run the tests and verify RED**

Run: `.venv-alpha/bin/pytest tests/vision/test_worker.py -q`

Expected: collection fails because `services.vision.worker` does not exist.

- [ ] **Step 3: Implement the worker composition**

`run_frame()` enforces the 2-second monotonic sampling deadline, prepares the frame, observes health, adds it to the ring, polls the scheduler, selects `ring.select_review_frames(count=4, spacing_seconds=2)`, and tries a regular submission on the 10-second cadence. It forwards only immutable transitions/completions to callbacks.

`run()` owns the stream iterator and reconnect loop. Backoff is the fixed bounded sequence `1, 2, 4, 8, 8...` seconds and resets after the first valid frame. It never sleeps through `stop_event.wait(delay)`. A reconnect requested by the health monitor closes the iterator immediately and marks the next prepared frame for `confirm_reconnect()`.

Do not add `tools/run_visual_worker.py`, launchd, real threads, Ollama, SSH, persistence, or notifications in this task. R3 will compose a real executor/reviewer and only then deploy the independent process.

- [ ] **Step 4: Verify GREEN**

Run:

```bash
.venv-alpha/bin/pytest tests/vision/test_worker.py tests/vision/test_frame_health.py tests/vision/test_review_scheduler.py -q
.venv-alpha/bin/pytest tests/vision tests/stream/test_frame_source.py tests/contracts/test_vision_review.py -q
```

Expected: all R1/R2 tests pass.

- [ ] **Step 5: Commit the worker core**

```bash
git add services/vision/worker.py services/vision/__init__.py tests/vision/test_worker.py
git commit -m "feat: compose visual capture worker core"
```

### Task 6: Record the R2b checkpoint and run the repository gate

**Files:**
- Modify: `docs/STATUS.md`
- Modify: `docs/CHECKPOINT.md`
- Modify: `docs/NEXT.md`
- Modify: `docs/superpowers/plans/2026-08-05-visual-capture-health-scheduler.md`

**Interfaces:**
- Consumes: passing R2b modules and tests.
- Produces: an honest checkpoint that separates software evidence from real i9/M2 accuracy and advances only to R3.

- [ ] **Step 1: Mark completed plan steps and update status**

Record the exact test counts from the final run. State that continuous loopback capture, privacy-safe sampling, conservative health evidence, bounded reconnect, and single-flight scheduling are implemented in software. Keep real M2/Ollama calls, SSH tunnel, launchd, alert persistence, screenshots/video, ntfy, Dashboard feedback, household accuracy, 24-hour environment acceptance, and 72-hour release validation explicitly pending.

- [ ] **Step 2: Run focused and full verification**

```bash
.venv-alpha/bin/pytest tests/vision tests/stream/test_frame_source.py tests/monitoring/test_alpha_quality.py tests/contracts/test_vision_review.py -q
.venv-alpha/bin/pytest -q
node --test tests/frontend/*.test.mjs
.venv-alpha/bin/python -m compileall -q apps packages services tools
bash -n tools/*.sh
git diff --check
git status --short
```

Expected: all Python and frontend tests pass; compilation, shell syntax, diff check, and worktree inspection succeed.

- [ ] **Step 3: Run public-repository boundary checks**

Confirm no tracked path starts with `runtime/`, no tracked media/database/environment file was added, and no GitHub token/private-key marker occurs in the diff. Print only candidate counts, never candidate values.

- [ ] **Step 4: Commit the R2b checkpoint**

```bash
git add docs/STATUS.md docs/CHECKPOINT.md docs/NEXT.md docs/superpowers/plans/2026-08-05-visual-capture-health-scheduler.md
git commit -m "docs: record visual capture scheduler checkpoint"
```

## Plan self-review

- The plan covers the remaining R2 safe-frame stage: dedicated stream, continuous capture, disconnect/freeze evidence, bounded reconnect, memory-only ring, and single-flight scheduling.
- It does not deploy a fake visual service before R3 provides a real local reviewer; launchd and M2 tunnel lifecycle remain explicit R3 work.
- Every new public type and method is defined before a later task consumes it.
- Every production behavior has a mutation-catching RED test, a minimal GREEN implementation, an exact command, and a bounded failure code.
- Facts (captured frames and source failures), hypotheses (freeze candidate), decisions (reconnect/offline/frozen transitions), and later outcomes (parent review) remain separate.
- No placeholder, household-media fixture, network credential, arbitrary URL, shell subprocess, disk frame queue, or automatic actuator appears in the plan.
