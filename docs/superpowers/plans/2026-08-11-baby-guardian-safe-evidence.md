# Baby Guardian Safe Evidence Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Attach a privacy-processed screenshot and bounded animated WebP clip to each newly opened Baby guardian risk event.

**Architecture:** Extend the existing safe-frame ring with a read-only time-window snapshot. A focused evidence store and file writer persist one evidence lifecycle per event, while an in-memory recorder captures the pre-10/post-30-second window and is fed only `PreparedAnalysisFrame` values by the worker.

**Tech Stack:** Python 3.11+, sqlite3, Pillow, hashlib, pathlib, pytest.

## Global Constraints

- Only `PreparedAnalysisFrame` may enter evidence code; never accept `CapturedFrame` or an original stream URL.
- Preserve the existing 2-second ring cadence, 40-second retention, 21-frame limit, model settings, risk thresholds, and realtime load behavior.
- Store media only below configured `data_dir/guardian-evidence`; use digest directories, atomic replacement, mode `0700` directories and `0600` files.
- Logs must not contain paths, evidence keys, digests, images, model prose, credentials, URLs, private addresses, camera identifiers, or exception text.
- Media, database, and log failures must not stop risk persistence or the visual worker.
- This slice adds no ntfy risk delivery, Dashboard UI, parent feedback, audio, i9 service mutation, remote push, PR, merge, or `main` change.

---

### Task 1: Safe frame window snapshot

**Files:**
- Modify: `services/vision/frame_ring.py`
- Modify: `tests/vision/test_frame_ring.py`

**Interfaces:**
- Consumes: aware `start_at` and `end_at` datetimes.
- Produces: `AnalysisFrameRing.snapshot_window(*, start_at, end_at) -> tuple[PreparedAnalysisFrame, ...]`.

- [ ] Write tests proving inclusive chronological selection, empty windows, aware-time validation, and no mutation.
- [ ] Run `python -m pytest -q tests/vision/test_frame_ring.py` and verify failure because `snapshot_window` is absent.
- [ ] Implement the minimal read-only selector over the bounded deque.
- [ ] Re-run the test file and commit the green task.

### Task 2: Evidence database lifecycle

**Files:**
- Modify: `services/storage/visual_risk.py`
- Modify: `tests/storage/test_visual_risk_store.py`

**Interfaces:**
- Produces: frozen `StoredVisualRiskEvidence` and store methods `begin_evidence()`, `complete_evidence()`, `fail_evidence()`, `interrupt_collecting_evidence()`, `get_evidence()`.

- [ ] Write tests for repeatable migration, event foreign key, idempotent begin, ready completion, fixed failure codes, 21-frame bound, and restart interruption.
- [ ] Run `python -m pytest -q tests/storage/test_visual_risk_store.py` and verify RED on missing evidence interfaces.
- [ ] Add `visual_risk_evidence` with strict checks and transaction-scoped methods that validate every row.
- [ ] Re-run storage tests and commit the green task.

### Task 3: Atomic private media writer

**Files:**
- Create: `services/vision/evidence_files.py`
- Create: `tests/vision/test_evidence_files.py`

**Interfaces:**
- Produces: `GuardianEvidenceFiles.write_snapshot(event_id, frame) -> str` and `write_clip(event_id, frames) -> str`, returning strict relative keys.

- [ ] Write generated-image tests proving digest-only directories, JPEG/WebP readability, animation frame count, and `0700`/`0600` modes.
- [ ] Run `python -m pytest -q tests/vision/test_evidence_files.py` and verify RED because the module is absent.
- [ ] Implement Pillow encoding and same-directory atomic writes with `fsync`; reject empty clips and invalid image payloads.
- [ ] Re-run the file tests and commit the green task.

### Task 4: Bounded evidence recorder and redacted logs

**Files:**
- Create: `services/vision/evidence_recorder.py`
- Create: `tests/vision/test_evidence_recorder.py`

**Interfaces:**
- Consumes: `GuardianEvidenceStore`, `GuardianEvidenceFiles`, a frame-window provider, and a text stream.
- Produces: `start(event, transition)`, `observe(frame)`, `recover_interrupted(at)`, and `close(at)`.

- [ ] Write tests showing immediate screenshot, pre-10-second selection, post-30-second completion, duplicate start idempotency, 21-frame cap, continued capture after risk recovery, restart interruption, and sensitive failure redaction.
- [ ] Run the recorder tests and verify RED because the module is absent.
- [ ] Implement one bounded active capture per event; finalize to WebP only when a frame reaches the deadline; use fixed allowlisted JSON log payloads and isolate every dependency failure.
- [ ] Re-run recorder, file, ring, and storage tests and commit the green task.

### Task 5: Runtime and production wiring

**Files:**
- Modify: `services/vision/worker.py`
- Modify: `services/vision/bootstrap.py`
- Modify: `services/vision/risk_event_pipeline.py`
- Modify: `tools/run_visual_worker.py`
- Modify: `tests/vision/test_worker.py`
- Modify: `tests/vision/test_bootstrap.py`
- Modify: `tests/vision/test_risk_event_pipeline.py`
- Modify: `tests/tools/test_run_visual_worker.py`

**Interfaces:**
- `VisualWorker(..., on_safe_frame: Callable[[PreparedAnalysisFrame], None] | None)` emits only after the frame enters the safe ring.
- `VisualRiskEventPipeline(..., on_event_opened: Callable[[StoredVisualRiskEvent, RiskTransition], None] | None)` emits only for a newly created event.
- `build_visual_runtime(..., on_safe_frame=...)` wires the worker callback.

- [ ] Write tests proving safe-frame callback timing, created-only evidence start, callback failure isolation, startup interruption recovery, and resource-close interruption.
- [ ] Run the four affected test files and verify RED on the missing callback contracts.
- [ ] Add the minimal callback interfaces and construct the evidence store/files/recorder beneath resolved `data_dir` in `run_visual_worker.py`.
- [ ] Re-run focused integration and commit the green task.

### Task 6: Checkpoint and focused verification

**Files:**
- Modify: `docs/CHECKPOINT.md`
- Modify: `docs/NEXT.md`
- Modify: `docs/STATUS.md`

- [ ] Run fresh focused tests for visual risk store, frame ring, evidence files/recorder, event pipeline, worker, bootstrap, and worker entrypoint.
- [ ] Run `python -m compileall -q apps packages services tools tests` and `git diff --check`.
- [ ] Scan planned files for credentials, private addresses, media/database artifacts, runtime paths, exception logging, and changes to thresholds/models/load control.
- [ ] Record only verified evidence; keep ntfy, Dashboard feedback, unified acceptance, household accuracy, performance, and audio pending. Commit planned files only and exclude the pre-existing `uv.lock`.

## Plan self-review

- Tasks 1-5 cover every component and failure boundary in the approved safe-evidence design.
- The frame, event, evidence, and callback types match across tasks.
- No task requires FFmpeg, original video, an unbounded queue, or a production i9 action.
- Risk ntfy and Dashboard work remain separate testable slices rather than hidden placeholders.
