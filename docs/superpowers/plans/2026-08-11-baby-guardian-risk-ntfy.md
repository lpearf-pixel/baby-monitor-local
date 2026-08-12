# Baby Guardian Risk ntfy Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Deliver idempotent, text-only Baby Guardian risk notifications through the existing private ntfy channel without blocking the visual worker.

**Architecture:** Persist notification intents in a SQLite outbox beside risk events. A background dispatcher converts allowlisted stored data into a redacted ntfy payload and records terminal or bounded retry results.

**Tech Stack:** Python 3.11, SQLite, Pydantic v2, urllib, pytest.

## Global Constraints

- Reuse the existing ntfy topic, token environment variable, base URL validation, timeout, and HTTP retry adapter boundaries.
- Never send or log media, paths, private addresses, camera URIs, model output, credentials, payload bodies, response bodies, or exception text.
- Do not block the visual analysis callback on network I/O.
- Do not modify model behavior, risk thresholds, FPS, Dashboard, i9 services, `main`, or remote branches.
- Preserve and exclude the pre-existing untracked `uv.lock`.

---

### Task 1: Persist notification outbox

**Files:**
- Modify: `services/storage/visual_risk.py`
- Modify: `tests/storage/test_visual_risk_store.py`

**Interfaces:**
- Consumes: `StoredVisualRiskEvent`, `StoredVisualRiskEvidence`, and the existing `events.sqlite3` migration.
- Produces: `StoredVisualRiskNotification`, `queue_notification(...)`, `next_pending_notification(...)`, `record_notification_result(...)`.

- [ ] **Step 1: Write failing storage tests** for unique event-stage intents, linked intervention identities, pending order, retry scheduling, terminal immutability, and timezone validation.
- [ ] **Step 2: Run** `/tmp/baby-guardian-venv/bin/pytest -q tests/storage/test_visual_risk_store.py` and confirm failures name missing notification APIs.
- [ ] **Step 3: Implement** the strict Pydantic contract, migration, atomic queue/read/result methods, and SQLite constraints.
- [ ] **Step 4: Run the same test** and confirm all storage tests pass.
- [ ] **Step 5: Commit** only the storage implementation and tests with `feat: persist guardian notification outbox`.

### Task 2: Build redacted risk ntfy adapter

**Files:**
- Create: `services/notifications/guardian_ntfy.py`
- Create: `tests/notifications/test_guardian_ntfy.py`

**Interfaces:**
- Consumes: a stored notification plus allowlisted event and evidence data.
- Produces: `NtfyGuardianNotifier.notify(notification, event, evidence_state) -> NotificationResult`.

- [ ] **Step 1: Write failing adapter tests** for all stages and risk labels, evidence fallback, HTTPS/DNS validation, bounded HTTP retry, permanent 4xx rejection, and malicious stored values.
- [ ] **Step 2: Run** `/tmp/baby-guardian-venv/bin/pytest -q tests/notifications/test_guardian_ntfy.py` and confirm the module is missing.
- [ ] **Step 3: Implement** an allowlist-only payload and reuse `NotificationResult`, `NtfyOpener`, URL validation, and the existing retry timings.
- [ ] **Step 4: Run adapter plus existing ntfy tests** and confirm all pass.
- [ ] **Step 5: Commit** with `feat: add redacted guardian ntfy payloads`.

### Task 3: Queue intents from the risk pipeline

**Files:**
- Modify: `services/vision/risk_event_pipeline.py`
- Modify: `tests/vision/test_risk_event_pipeline.py`

**Interfaces:**
- Consumes: successfully persisted open, recovery, and adult intervention transitions.
- Produces: persisted notification intents and safe queue log codes; performs no HTTP calls.

- [ ] **Step 1: Write failing pipeline tests** for new-event open, duplicate open, recovery, linked intervention, unlinked intervention, and queue failure isolation.
- [ ] **Step 2: Run** `/tmp/baby-guardian-venv/bin/pytest -q tests/vision/test_risk_event_pipeline.py` and confirm expected failures.
- [ ] **Step 3: Implement** queue calls after event persistence and emit only fixed safe queue results.
- [ ] **Step 4: Run pipeline and storage tests** and confirm all pass.
- [ ] **Step 5: Commit** with `feat: queue guardian risk notifications`.

### Task 4: Dispatch pending notifications off-thread

**Files:**
- Create: `services/notifications/guardian_dispatcher.py`
- Create: `tests/notifications/test_guardian_dispatcher.py`

**Interfaces:**
- Consumes: `VisualRiskEventStore`, `NtfyGuardianNotifier`, wall clock, stop event.
- Produces: `GuardianNotificationDispatcher.run(stop_event)` and safe structured dispatch logs.

- [ ] **Step 1: Write failing dispatcher tests** for delivered, rejected, unavailable retry schedule, exhaustion, empty queue, notifier exception, and log redaction.
- [ ] **Step 2: Run** `/tmp/baby-guardian-venv/bin/pytest -q tests/notifications/test_guardian_dispatcher.py` and confirm the module is missing.
- [ ] **Step 3: Implement** single-row polling, bounded retry state changes, interruptible waits, and fixed-field JSON logs.
- [ ] **Step 4: Run notification and storage tests** and confirm all pass.
- [ ] **Step 5: Commit** with `feat: dispatch guardian notifications safely`.

### Task 5: Wire production configuration and lifecycle

**Files:**
- Modify: `services/vision/notification_config.py`
- Modify: `tools/run_visual_worker.py`
- Modify: `tests/vision/test_notification_config.py`
- Modify: `tests/tools/test_run_visual_worker.py`

**Interfaces:**
- Consumes: existing `AppSettings.notifications` and local environment values.
- Produces: notifier construction plus a dispatcher thread that starts after runtime setup and joins during cleanup.

- [ ] **Step 1: Write failing production tests** for shared configuration, dispatcher startup, invalid configuration disablement, clean stop, and dispatcher failure isolation.
- [ ] **Step 2: Run the focused production tests** and confirm the new behavior is absent.
- [ ] **Step 3: Implement** construction and lifecycle wiring without changing source-health notification behavior.
- [ ] **Step 4: Run all risk, notification, worker, and source-health focused tests** and confirm all pass.
- [ ] **Step 5: Commit** with `feat: wire guardian risk ntfy delivery`.

### Task 6: Record and verify the checkpoint

**Files:**
- Modify: `docs/CHECKPOINT.md`
- Modify: `docs/NEXT.md`

**Interfaces:**
- Consumes: fresh verification evidence.
- Produces: an honest checkpoint that keeps physical Android receipt, Dashboard feedback, unified acceptance, performance, and audio pending.

- [ ] **Step 1: Update status documents** with only verified behavior and remaining physical acceptance.
- [ ] **Step 2: Run the full focused set**, Python compile, `git diff --check`, tracked runtime/media scan, and changed-file secret/private-data scan.
- [ ] **Step 3: Review the complete diff** against this specification and ensure no model, threshold, FPS, Dashboard, or remote changes entered the slice.
- [ ] **Step 4: Commit** only planned status files with `docs: record guardian risk ntfy checkpoint`.
