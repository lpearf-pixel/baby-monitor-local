# Guardian Evidence Retention Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Automatically expire privacy-processed Guardian evidence after 30 days and enforce the configured 30 GiB quota without deleting events, active captures or notification-pending evidence.

**Architecture:** Add a closed retention projection and guarded delete to the existing SQLite store, extend the evidence filesystem boundary with safe usage/deletion operations, and compose them in an independent daily retention worker. The visual runtime supplies the existing centralized retention settings and treats every cleanup failure as isolated, redacted and retryable.

**Tech Stack:** Python 3.11+, SQLite, Pydantic, pathlib/os, pytest, existing visual-worker threading and JSON-line diagnostics.

## Global Constraints

- Use `retention.event_retention_days` and `retention.event_quota_gb`; add no second configuration surface.
- Retain risk events, interventions and notification rows; delete only eligible evidence media and evidence rows.
- Never delete an open event, collecting evidence, an event with a pending notification,
  or a recovered event whose recovery notification is missing/non-terminal.
- Do not expose evidence media, paths, stored keys, digests, event IDs or exception text in retention logs.
- Guardian must not write Baby Care data or introduce Dad/Mom identity.
- Do not modify `main`, `stable/xiaomi-alpha`, the published Dashboard branch, or create a PR.

---

### Task 1: Closed SQLite retention projection

**Files:**
- Modify: `services/storage/visual_risk.py`
- Modify: `tests/storage/test_visual_risk_store.py`

**Interfaces:**
- Produces: frozen `StoredEvidenceRetentionEntry(event_id, state, retention_at, deletable)`.
- Produces: `VisualRiskEventStore.list_evidence_retention_entries() -> tuple[StoredEvidenceRetentionEntry, ...]`.
- Produces: `VisualRiskEventStore.delete_evidence_if_eligible(event_id: str) -> bool`.

- [ ] **Step 1: Write failing storage tests**

Add tests that create recovered/open events with ready/failed/interrupted/collecting evidence and missing/pending/terminal recovery notifications. Assert deterministic oldest-first entries, `retention_at == max(event.updated_at, evidence.updated_at)`, and `deletable` only for recovered terminal evidence with a terminal recovery notification and no pending notifications. Assert the guarded delete rechecks the exact selection under a SQLite writer lock and removes only the evidence row while retaining its event, interventions and terminal notification.

- [ ] **Step 2: Run storage tests and verify RED**

Run:

```bash
/tmp/baby-monitor-retention-venv/bin/python -m pytest -q tests/storage/test_visual_risk_store.py
```

Expected: FAIL because the retention model and methods do not exist.

- [ ] **Step 3: Implement the minimal storage projection and guarded delete**

Use one joined query over `visual_risk_evidence`, `visual_risk_events` and notification state. Convert timestamps with `datetime.fromisoformat`. In `delete_evidence_if_eligible`, start `BEGIN IMMEDIATE`, repeat the exact-record, recovered, terminal-recovery and no-pending checks, execute the bounded file callback under that writer lock, then delete the evidence row before commit.

- [ ] **Step 4: Run storage tests and verify GREEN**

Run the command from Step 2. Expected: all storage tests pass and `PRAGMA integrity_check` remains `ok`.

- [ ] **Step 5: Commit the storage slice**

```bash
git add services/storage/visual_risk.py tests/storage/test_visual_risk_store.py
git commit -m "feat: add guarded evidence retention queries"
```

### Task 2: Safe filesystem accounting and deletion

**Files:**
- Modify: `services/vision/evidence_files.py`
- Modify: `tests/vision/test_evidence_files.py`

**Interfaces:**
- Produces: `GuardianEvidenceFiles.total_bytes() -> int`.
- Produces: `GuardianEvidenceFiles.event_bytes(event_id: str) -> int`.
- Produces: `GuardianEvidenceFiles.delete_event(event_id: str) -> int` returning reclaimed bytes.

- [ ] **Step 1: Write failing filesystem tests**

Add generated-file tests proving total usage includes regular files in the evidence root, per-event usage derives the digest from `event_id`, known snapshot/clip deletion is idempotent, unrelated event directories remain, and any symbolic link at the root, `visual-risk` ancestor or selected event directory fails closed without following or deleting its target.

- [ ] **Step 2: Run filesystem tests and verify RED**

Run:

```bash
/tmp/baby-monitor-retention-venv/bin/python -m pytest -q tests/vision/test_evidence_files.py
```

Expected: FAIL because usage and deletion methods are missing.

- [ ] **Step 3: Implement strict traversal and controlled deletion**

Traverse and mutate through directory descriptors using `os.scandir`, `dir_fd`, `O_DIRECTORY` and `O_NOFOLLOW`; reject symbolic links and non-regular/non-directory entries, and never use database keys as paths. For a selected digest directory allow only `snapshot.jpg`, `clip.webp`, and writer-owned dot-prefixed temporary files; calculate reclaimed bytes before unlinking, fsync the parent after deletion, and remove empty directories only.

- [ ] **Step 4: Run filesystem tests and verify GREEN**

Run the command from Step 2. Expected: all evidence-file tests pass.

- [ ] **Step 5: Commit the filesystem slice**

```bash
git add services/vision/evidence_files.py tests/vision/test_evidence_files.py
git commit -m "feat: add safe evidence file cleanup"
```

### Task 3: Age and quota retention service

**Files:**
- Create: `services/vision/evidence_retention.py`
- Create: `tests/vision/test_evidence_retention.py`

**Interfaces:**
- Consumes: `list_evidence_retention_entries`, `delete_evidence_if_eligible`, `total_bytes`, `event_bytes`, and `delete_event`.
- Produces: frozen `EvidenceRetentionReport(result, deleted_count, reclaimed_bytes, usage_bytes, quota_bytes)`.
- Produces: `GuardianEvidenceRetention.cleanup(now: datetime) -> EvidenceRetentionReport`.

- [ ] **Step 1: Write failing age-policy tests**

Create synthetic entries/files and assert evidence at the cutoff is deleted, evidence one microsecond newer remains, the later event/evidence terminal timestamp controls age, and protected records never reach the file deleter.

- [ ] **Step 2: Run retention tests and verify RED**

Run:

```bash
/tmp/baby-monitor-retention-venv/bin/python -m pytest -q tests/vision/test_evidence_retention.py
```

Expected: FAIL because `services.vision.evidence_retention` does not exist.

- [ ] **Step 3: Implement minimal age cleanup**

Validate timezone-aware `now`, positive days and quota. Delete age-expired eligible entries oldest-first, files before the guarded database row, then return exact aggregate counts and remaining root usage.

- [ ] **Step 4: Run age-policy tests and verify GREEN**

Run the command from Step 2. Expected: age-policy tests pass.

- [ ] **Step 5: Write failing quota and failure tests**

Assert the oldest eligible evidence is removed until usage is within quota, protected/unmanaged usage can produce `quota_unmet`, a filesystem failure leaves the database row, a guarded database-delete failure remains retryable, and no result contains paths, keys, event IDs or exceptions.

- [ ] **Step 6: Run quota tests and verify RED**

Run the command from Step 2. Expected: new quota/failure cases fail for missing behavior.

- [ ] **Step 7: Implement quota cleanup and exact reports**

After age cleanup, recompute total usage and delete remaining eligible entries oldest-first while usage exceeds quota. Return `within_quota`, `deleted`, or `quota_unmet`; let unexpected dependencies raise to the scheduler boundary rather than claiming success.

- [ ] **Step 8: Run retention tests and verify GREEN**

Run the command from Step 2. Expected: all retention service tests pass.

- [ ] **Step 9: Commit the service slice**

```bash
git add services/vision/evidence_retention.py tests/vision/test_evidence_retention.py
git commit -m "feat: enforce guardian evidence retention"
```

### Task 4: Daily scheduler and production wiring

**Files:**
- Modify: `services/vision/evidence_retention.py`
- Modify: `tests/vision/test_evidence_retention.py`
- Modify: `tools/run_visual_worker.py`
- Modify: `tests/tools/test_run_visual_worker.py`

**Interfaces:**
- Produces: `GuardianEvidenceRetentionWorker.run(stop_event) -> None` with an immediate run and 86,400-second repeat interval.
- Production converts `event_quota_gb * 1024 ** 3`, shares one `GuardianEvidenceFiles`, starts one daemon thread, and joins it with a bounded timeout.

- [ ] **Step 1: Write failing worker tests**

Use a fake stop event to prove immediate cleanup, exact daily wait, clean stop, aggregate completed diagnostics, and redacted `retention_unavailable` diagnostics when cleanup raises a path/credential-bearing exception.

- [ ] **Step 2: Run worker tests and verify RED**

Run:

```bash
/tmp/baby-monitor-retention-venv/bin/python -m pytest -q tests/vision/test_evidence_retention.py
```

Expected: FAIL because the worker is missing.

- [ ] **Step 3: Implement worker and allowlisted logger**

The worker catches cleanup and logging failures, emits only the specified aggregate JSON fields, waits through `stop_event.wait(86400)`, and performs no filesystem or database work after the stop event is observed.

- [ ] **Step 4: Write failing production-wiring tests**

Patch the retention worker in `tests/tools/test_run_visual_worker.py`. Assert centralized settings are converted to days/bytes, retention starts independently, cleanup failure does not prevent the visual worker from running, and shutdown sets the shared stop event and joins the retention thread without exposing private exceptions.

- [ ] **Step 5: Run production-wiring tests and verify RED**

Run:

```bash
/tmp/baby-monitor-retention-venv/bin/python -m pytest -q tests/tools/test_run_visual_worker.py
```

Expected: FAIL because production does not construct or start retention.

- [ ] **Step 6: Implement production wiring**

Construct one `GuardianEvidenceFiles(data_dir / "guardian-evidence")`, pass it to both recorder and retention service, start the retention thread after signal setup, and preserve visual startup/runtime independence when the retention thread cannot start or exits.

- [ ] **Step 7: Run focused Guardian tests and verify GREEN**

Run:

```bash
/tmp/baby-monitor-retention-venv/bin/python -m pytest -q \
  tests/storage/test_visual_risk_store.py \
  tests/vision/test_evidence_files.py \
  tests/vision/test_evidence_recorder.py \
  tests/vision/test_evidence_retention.py \
  tests/events/test_guardian_query.py \
  tests/tools/test_run_visual_worker.py
```

Expected: all selected tests pass.

- [ ] **Step 8: Commit the runtime slice**

```bash
git add services/vision/evidence_retention.py tests/vision/test_evidence_retention.py tools/run_visual_worker.py tests/tools/test_run_visual_worker.py
git commit -m "feat: schedule guardian evidence cleanup"
```

### Task 5: Documentation, full gate and publication

**Files:**
- Modify: `SUMMARY.md`
- Modify: `docs/STATUS.md`
- Modify: `docs/CHECKPOINT.md`
- Modify: `docs/NEXT.md`
- Modify only if behavior changed: `README.md`

**Interfaces:**
- Produces: a durable handoff that records the cross-project acknowledgement boundary, retention behavior, exact verification counts and next non-conflicting slice.

- [ ] **Step 1: Correct status and ordered priorities**

Record `codex/guardian-evidence-retention` as the active branch, mark 30-day/30-GiB cleanup complete only after focused verification, remove two-parent acknowledgement from Guardian's immediate implementation queue, and keep it for a future Baby Care integration contract.

- [ ] **Step 2: Run the fresh full software gate**

Run:

```bash
/tmp/baby-monitor-retention-venv/bin/python -m pytest -q
node --test tests/frontend/*.test.mjs
/tmp/baby-monitor-retention-venv/bin/python -m compileall -q apps packages services tools tests
```

Run `bash -n` for every tracked shell file, `make -n alpha-guardian-start`,
`make -n alpha-guardian-test`, `git diff --check`, tracked runtime/media/SQLite scans,
and secret/private-key/private-network literal scans.

- [ ] **Step 3: Review scope and commit final evidence**

Confirm no Baby Care identity, acknowledgement, audio, media route, SQLite/media file,
credential or protected-branch change entered the diff. Commit only the intended docs:

```bash
git add SUMMARY.md docs/STATUS.md docs/CHECKPOINT.md docs/NEXT.md README.md
git commit -m "docs: record guardian evidence retention gate"
```

- [ ] **Step 4: Publish and verify the new branch**

Publish `codex/guardian-evidence-retention` without a PR or merge. Verify the remote
branch SHA, fetch it independently, and prove the remote tree equals the exact local
HEAD tree. Report local and remote commit identities separately if connector publication
creates a squash commit.

## Plan self-review

- Tasks 1-4 cover every design requirement: eligibility, age, quota, file safety,
  failure isolation, scheduler, diagnostics and production configuration.
- Task 5 covers the required project-state correction, full verification and exact-tree
  publication evidence.
- No task introduces a second configuration surface, parent identity, Baby Care write,
  media route, audio, PTZ, public exposure or protected-branch change.
