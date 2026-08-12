# Visual Launchd Interactive Scheduling Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Deploy the visual worker as a launchd `Interactive` process through a repository-owned, rollback-safe update command so the i9 production worker can retain the verified 5 FPS scheduling behavior.

**Architecture:** Keep the analyzer, load controller, performance thresholds, and every non-visual service unchanged. Change only the visual launchd template and add one Bash 3.2 lifecycle script that renders and validates the new plist, preserves the original background plist backup, replaces the registered job without duplication, verifies it, and restores the exact pre-update plist and registration state on failure.

**Tech Stack:** macOS launchd, plist XML, Bash 3.2, BSD utilities, Make, Python 3.11, pytest.

## Global Constraints

- Work only on `codex/xiaomi-alpha-visual-risk-core` from `f4845ad152344b0b4f5320af44d4e42e50550a68`.
- Do not change `main`, push, create or merge a PR, or alter performance thresholds.
- Do not touch gauge, environment watchdog, Ollama tunnel, Dashboard, model, candidate, or risk-state behavior.
- Do not read, write, print, or commit household media, bed zones, candidates, network configuration, credentials, or runtime settings.
- Shell remains ASCII-only, UTF-8/LF, macOS Bash 3.2 and BSD-tool compatible.
- Use focused tests for this slice and deliver one local commit only.

---

### Task 1: Lock the interactive scheduling and lifecycle contract

**Files:**
- Modify: `tests/deploy/test_visual_worker_deploy.py`
- Create: `tests/deploy/test_visual_launchd_update.py`

**Interfaces:**
- Consumes: the visual plist template and a fake macOS `launchctl`/`plutil` environment.
- Produces: observable contracts for `ProcessType=Interactive`, successful single-job replacement, persistent background backup preservation, rollback after activation failure, and the Make entrypoint.

- [x] **Step 1: Change the launchd template expectation**

Change the existing visual-agent test to require the literal plist value `Interactive`; leave the Ollama tunnel expectation as `Background`.

- [x] **Step 2: Add subprocess lifecycle tests**

Run a copied project fixture with fake `uname`, `plutil`, and stateful `launchctl`. Assert success calls `print`, `bootout`, `bootstrap`, `kickstart -k`, and final `print`; assert the installed/runtime plist is interactive and `.r3-background.bak` preserves the original bytes. In a second test, make the first `bootstrap` fail and assert the script restores the original installed plist, re-registers it, leaves exactly one loaded service, and returns a stable redacted failure.

- [x] **Step 3: Add the Make boundary test**

Invoke `alpha-visual-launchd-update` with an injected Bash executable and assert it calls only `tools/update_visual_launchd.sh`.

- [x] **Step 4: Verify RED**

Run:

```bash
./.venv-alpha/bin/python -m pytest -q \
  tests/deploy/test_visual_worker_deploy.py \
  tests/deploy/test_visual_launchd_update.py
```

Expected: fail because the template is still `Background`, the lifecycle script is absent, and the Make target is absent.

### Task 2: Implement the minimal rollback-safe update

**Files:**
- Modify: `deploy/launchd/com.babymonitor.visual.plist.example`
- Create: `tools/update_visual_launchd.sh`
- Modify: `Makefile`

**Interfaces:**
- Consumes: `deploy/launchd/com.babymonitor.visual.plist.example`, the installed user LaunchAgent, and launchd service `gui/$(id -u)/com.babymonitor.visual`.
- Produces: `make alpha-visual-launchd-update`; stable success `visual_launchd_update=PASS process_type=Interactive`; stable failure codes; persistent non-overwritten `com.babymonitor.visual.plist.r3-background.bak`.

- [x] **Step 1: Set only the visual plist to Interactive**

Replace the visual template's `ProcessType` value with `Interactive`; do not change any other job template.

- [x] **Step 2: Add the update script**

Implement preflight for Intel macOS, the template, installed plist, `plutil`, and a registered visual service. Render into a temporary file, lint it, snapshot the current installed plist, create the persistent background backup only when absent, boot out the old job, atomically install the candidate, bootstrap and kickstart it, verify registration, and then synchronize `runtime/launchd/com.babymonitor.visual.plist`. An EXIT trap must restore the snapshot and old registration after any post-bootout failure. All output is fixed and redacted.

- [x] **Step 3: Expose the Make target**

Add the phony/help entry and execute the repository script through `$(BASH)`.

- [x] **Step 4: Verify GREEN**

Run the Task 1 pytest command and expect all tests to pass, then run `bash -n tools/update_visual_launchd.sh` and `make -n alpha-visual-launchd-update`.

### Task 3: Record the evidence and acceptance boundary

**Files:**
- Modify: `docs/superpowers/specs/2026-08-08-realtime-visual-production-sampler-design.md`
- Modify: `docs/CHECKPOINT.md`
- Modify: `docs/STATUS.md`
- Modify: `docs/NEXT.md`

**Interfaces:**
- Consumes: the observed foreground 5 FPS/P95-at-or-below-180 ms result versus background 1 FPS/P50-around-400 ms.
- Produces: a durable root-cause record, deployment command, rollback boundary, and still-pending post-deployment 3-minute observation plus 10-minute performance gate.

- [x] **Step 1: Document the controlled comparison**

Record that the foreground single-variable experiment met the 5 FPS budget while the registered `Background` job reproducibly fell to 1 FPS, identifying launchd scheduling as the production bottleneck without changing thresholds or analyzer behavior.

- [x] **Step 2: Document deployment and remaining acceptance**

Record `make alpha-visual-launchd-update`, its persistent backup/automatic rollback behavior, and that software verification does not itself prove the installed i9 job. Keep the 3-minute post-update observation and full 10-minute sampler pending.

- [x] **Step 3: Run the focused delivery gate**

Run the deployment and performance tests, Python compilation for changed Python tests, `bash -n` for the new script, `plutil -lint` when available, Make dry-runs, ASCII/LF checks, `git diff --check`, and a tracked-file scan for credentials, private keys, private addresses, runtime media, or database artifacts.

- [x] **Step 4: Review and commit locally**

Confirm only the planned files changed, re-read this plan against the diff, and create one local commit on `codex/xiaomi-alpha-visual-risk-core`. Do not push.
