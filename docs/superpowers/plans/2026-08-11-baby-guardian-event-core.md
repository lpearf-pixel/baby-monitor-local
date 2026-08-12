# Baby Guardian Event Core Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Persist deterministic Baby guardian risk lifecycles and adult interventions with restart restoration and privacy-safe structured logs.

**Architecture:** A focused SQLite store owns visual-risk lifecycle records in the existing `events.sqlite3` database. A pipeline maps existing `RiskTransition` values into idempotent store operations and allowlisted JSON-line logs; production bootstrap injects the restored risk snapshot and transition callback without changing model or threshold behavior.

**Tech Stack:** Python 3.11+, Pydantic 2, sqlite3, standard-library JSON/hash/UUID APIs, pytest.

## Global Constraints

- Do not change model selection, confidence threshold `0.70`, confirmation span `10 seconds`, recovery span `10 seconds`, or realtime FPS behavior.
- Do not write image, video, model prose, reason codes, credentials, URLs, private addresses, camera identifiers, filesystem paths, or exception messages to logs.
- Runtime data stays beneath configured `app.data_dir` and is never committed.
- Persistence and logging failures must not stop the visual worker.
- This slice adds no media, ntfy risk delivery, Dashboard UI, parent feedback, audio, i9 service mutation, remote push, PR, merge, or `main` change.

---

### Task 1: Strict visual risk lifecycle store

**Files:**
- Create: `services/storage/visual_risk.py`
- Create: `tests/storage/test_visual_risk_store.py`

**Interfaces:**
- Consumes: `VisualRiskKind`, aware `RiskTransition` timestamps, local `events.sqlite3` path.
- Produces: `StoredVisualRiskEvent`, `StoredVisualIntervention`, and `VisualRiskEventStore` methods `migrate()`, `integrity_check()`, `open_event()`, `recover_event()`, `record_intervention()`, `load_open()`, `list_events()`.

- [ ] **Step 1: Write failing contract and migration tests**

Test aware-time validation, incoherent recovery rejection, repeatable migration, foreign keys, one-open-event-per-risk, and database integrity.

- [ ] **Step 2: Run tests and verify RED**

Run: `python -m pytest -q tests/storage/test_visual_risk_store.py`

Expected: FAIL during collection because `services.storage.visual_risk` does not exist.

- [ ] **Step 3: Implement strict models and schema**

Use frozen Pydantic models. Create `visual_risk_events`, `visual_interventions`, and `visual_risk_interventions`; add a partial unique index on `risk_kind WHERE state='open'` and indexes ordered by `updated_at`.

- [ ] **Step 4: Add lifecycle behavior tests and verify RED**

Prove `open_event()` is idempotent for an already-open risk, `recover_event()` closes only the matching risk, interventions remain when no risk is open, and an intervention links to every currently open event.

- [ ] **Step 5: Implement transaction-scoped lifecycle operations and verify GREEN**

Use `BEGIN IMMEDIATE` semantics through one sqlite connection per operation. Never expose sqlite rows directly; validate every read through strict models.

Run: `python -m pytest -q tests/storage/test_visual_risk_store.py`

Expected: all tests PASS.

### Task 2: Risk transition pipeline and JSON-line diagnostics

**Files:**
- Create: `services/vision/risk_event_pipeline.py`
- Create: `tests/vision/test_risk_event_pipeline.py`

**Interfaces:**
- Consumes: `RiskTransition`, `VisualRiskEventStore`, a text stream, and optional UUID factory.
- Produces: `VisualRiskEventPipeline.restore_snapshot(snapshot_at) -> RiskSnapshot` and `handle(transition) -> None`.

- [ ] **Step 1: Write failing transition mapping tests**

Assert alert open/recovery persistence, watch-only logging, adult intervention persistence, duplicate callback idempotency, and recovery-without-open ignored behavior.

- [ ] **Step 2: Run tests and verify RED**

Run: `python -m pytest -q tests/vision/test_risk_event_pipeline.py`

Expected: FAIL because `VisualRiskEventPipeline` does not exist.

- [ ] **Step 3: Implement minimal mapping and allowlisted logs**

Serialize one compact sorted JSON object per line. Build objects only from fixed scalar fields and enum values. Hash `adult_intervention|rule_version|observed_at.isoformat()` for deterministic intervention IDs.

- [ ] **Step 4: Write failure-isolation and secrecy tests, then verify RED**

Use a store that raises with a sensitive exception string and a broken text stream. Assert `handle()` never raises, stderr output contains only `guardian.persistence_failed`, and forbidden strings are absent.

- [ ] **Step 5: Implement isolation and verify GREEN**

Catch store failures at the pipeline boundary and emit only a stable code. Catch all stream failures inside the logger.

Run: `python -m pytest -q tests/vision/test_risk_event_pipeline.py tests/storage/test_visual_risk_store.py`

Expected: all tests PASS.

### Task 3: Runtime restoration and production wiring

**Files:**
- Modify: `services/vision/bootstrap.py`
- Modify: `tools/run_visual_worker.py`
- Modify: `tests/vision/test_bootstrap.py`
- Modify: `tests/tools/test_run_visual_worker.py`

**Interfaces:**
- Consumes: `initial_risk_snapshot: RiskSnapshot | None`, `on_risk_transition: Callable[[RiskTransition], None] | None`, resolved `app.data_dir`.
- Produces: worker startup that migrates `events.sqlite3`, restores open risk states, and persists every subsequent deterministic transition.

- [ ] **Step 1: Write failing bootstrap injection tests**

Open a stored face risk, start the worker with recording resources, and assert `build_visual_runtime` receives the snapshot and risk callback. Assert a clean database supplies an empty snapshot.

- [ ] **Step 2: Run tests and verify RED**

Run: `python -m pytest -q tests/vision/test_bootstrap.py tests/tools/test_run_visual_worker.py`

Expected: FAIL because bootstrap lacks the new parameters and production setup lacks the event pipeline.

- [ ] **Step 3: Implement snapshot-aware runtime construction**

Build `VisualRiskStateMachine.from_snapshot(initial_risk_snapshot)` when supplied, otherwise construct a fresh machine. Pass `on_risk_transition` into `VisualReviewRuntime`.

- [ ] **Step 4: Wire the production store and pipeline**

Resolve `data_dir` exactly once, migrate `events.sqlite3`, construct `VisualRiskEventPipeline(stream=sys.stderr)`, restore a snapshot using an aware wall-clock time, and inject both callback and snapshot.

- [ ] **Step 5: Verify focused integration**

Run: `python -m pytest -q tests/storage/test_visual_risk_store.py tests/vision/test_risk_event_pipeline.py tests/vision/test_risk_state.py tests/vision/test_review_runtime.py tests/vision/test_bootstrap.py tests/tools/test_run_visual_worker.py`

Expected: all tests PASS with no unredacted runtime paths or exception strings.

### Task 4: Document and commit the first guardian slice

**Files:**
- Modify: `docs/CHECKPOINT.md`
- Modify: `docs/NEXT.md`
- Modify: `docs/STATUS.md`

**Interfaces:**
- Consumes: verified implementation evidence.
- Produces: an honest checkpoint naming event persistence/logging complete and media, notification, feedback, unified acceptance script, household accuracy, and performance gates pending.

- [ ] **Step 1: Run fresh focused and static gates**

Run:

```bash
python -m pytest -q tests/storage/test_visual_risk_store.py tests/vision/test_risk_event_pipeline.py tests/vision/test_risk_state.py tests/vision/test_review_runtime.py tests/vision/test_bootstrap.py tests/tools/test_run_visual_worker.py
python -m compileall -q apps packages services tools tests
git diff --check
```

Expected: all tests PASS; compile and diff checks exit 0.

- [ ] **Step 2: Review privacy and artifact boundaries**

Inspect changed files for credential markers, private addresses, media/database extensions, runtime paths, free-form exception logging, and changes to thresholds, models, realtime load control, or `main`.

- [ ] **Step 3: Record checkpoint and commit only planned files**

Create one local implementation commit after the design/plan commit. Do not add the pre-existing untracked `uv.lock`; do not push.

## Plan self-review

- Every requirement in the event-core design maps to Tasks 1-4.
- Store, pipeline, and production wiring interfaces use matching names and types.
- Media, ntfy, Dashboard feedback, unified local acceptance, performance, and audio remain explicit later slices rather than placeholders inside this implementation.
