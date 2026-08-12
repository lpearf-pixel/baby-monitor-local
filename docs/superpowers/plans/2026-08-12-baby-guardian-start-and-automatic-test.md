# Baby Guardian Start and Automatic Test Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add safe one-command startup and complete automatic acceptance commands for the installed Baby Guardian Alpha chain.

**Architecture:** Keep the Makefile targets thin. A startup wrapper delegates process creation to the existing idempotent Alpha start script, then a dedicated readiness script verifies every required guardian dependency with bounded, redacted probes. A separate automatic-test orchestrator runs repository, regression, installation, readiness, live-media, and isolated guardian checks while suppressing raw command output and aggregating fixed PASS/FAIL lines.

**Tech Stack:** macOS Bash 3.2, BSD command-line tools, Make, launchd, curl, Python 3.11, pytest.

## Global Constraints

- Protect `main`; stay on `codex/baby-guardian-event-loop` and do not push, merge, or modify remote state.
- Preserve the existing untracked `uv.lock` and all runtime/user data.
- Shell scripts must be ASCII-only UTF-8 with LF endings, parse under macOS Bash 3.2, and avoid GNU-only options.
- `alpha-guardian-start` may only perform the service and pid-file mutations already authorized through `tools/start_alpha.sh`.
- `alpha-guardian-test` must not send ntfy traffic, synthesize a live risk, or write the production event/evidence databases.
- Output must contain only fixed check identifiers, fixed failure codes, counts, and the final status; never print configuration values, URLs, private addresses, paths, payloads, exceptions, or logs.
- Every readiness poll is bounded; all required i9 installation, service, and media failures return nonzero.
- Keep existing Alpha targets and their behavior unchanged.

---

### Task 1: Bounded Guardian Startup Readiness

**Files:**
- Create: `tools/guardian_readiness.sh`
- Create: `tools/start_guardian.sh`
- Create: `tests/deploy/test_guardian_commands.py`

**Interfaces:**
- Consumes: `tools/start_alpha.sh`, `.venv-alpha/bin/python`, `tools/realtime_models.py check`, `tools/realtime_visual_status.py`, launchd labels or portable pid files.
- Produces: `bash tools/start_guardian.sh` with fixed `PASS start <check>` / `FAIL start <check> <reason>` lines and final `guardian_start=PASS|FAIL`.

- [x] **Step 1: Write failing startup behavior tests**

```python
def test_guardian_start_delegates_once_then_reports_all_readiness_checks(tmp_path):
    project, hooks = guardian_project(tmp_path, all_checks_pass=True)
    result = run_guardian(project, "tools/start_guardian.sh", hooks)
    assert result.returncode == 0
    assert result.stdout.splitlines()[-1] == "guardian_start=PASS"
    assert (hooks / "alpha_start.calls").read_text(encoding="ascii") == "1\n"


def test_guardian_start_aggregates_fixed_failures_without_leaking_raw_output(tmp_path):
    project, hooks = guardian_project(tmp_path, failing={"visual_worker", "metrics"})
    result = run_guardian(project, "tools/start_guardian.sh", hooks)
    assert result.returncode != 0
    assert "FAIL start visual_worker unavailable" in result.stdout
    assert "FAIL start visual_metrics unavailable" in result.stdout
    assert "guardian_start=FAIL" in result.stdout
    assert "synthetic-secret" not in result.stdout + result.stderr
```

- [x] **Step 2: Run the startup tests and verify RED**

Run: `/tmp/baby-guardian-venv/bin/pytest -q tests/deploy/test_guardian_commands.py -k guardian_start`

Expected: FAIL because `tools/start_guardian.sh` and `tools/guardian_readiness.sh` do not exist.

- [x] **Step 3: Implement the minimum bounded readiness and wrapper scripts**

```bash
#!/usr/bin/env bash
set -u

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
if ! bash "$ROOT/tools/start_alpha.sh" >/dev/null 2>&1; then
  echo "FAIL start alpha_start start_failed"
  echo "guardian_start=FAIL"
  exit 1
fi
echo "PASS start alpha_start"
if bash "$ROOT/tools/guardian_readiness.sh"; then
  echo "guardian_start=PASS"
  exit 0
fi
echo "guardian_start=FAIL"
exit 1
```

`guardian_readiness.sh` must execute fixed, output-suppressed probes for go2rtc, Dashboard, visual worker, environment watchdog, gauge worker, pinned realtime models, current visual metrics, and the Ollama bridge only when semantic review is enabled. It must continue after a failed probe, count failures, and return one only after all safe checks have run. `BABY_MONITOR_GUARDIAN_HOOK_DIR` is accepted only when `BABY_MONITOR_GUARDIAN_TEST_MODE=1`, giving tests a deterministic executable per check without exposing an acceptance bypass during normal use.

- [x] **Step 4: Run startup and adjacent deployment tests and verify GREEN**

Run: `/tmp/baby-guardian-venv/bin/pytest -q tests/deploy/test_guardian_commands.py tests/deploy/test_alpha_commands.py tests/deploy/test_gauge_worker_deploy.py tests/deploy/test_visual_worker_deploy.py`

Expected: all selected tests pass.

- [x] **Step 5: Verify shell policy and commit Task 1**

Run: `bash -n tools/guardian_readiness.sh tools/start_guardian.sh && LC_ALL=C grep -n '[^ -~\t]' tools/guardian_readiness.sh tools/start_guardian.sh; test $? -eq 1`

Commit: `feat: add bounded guardian startup readiness`

### Task 2: Complete Side-Effect-Free Automatic Acceptance

**Files:**
- Create: `tools/test_guardian.sh`
- Modify: `tests/deploy/test_guardian_commands.py`

**Interfaces:**
- Consumes: `.venv-alpha/bin/python`, git tracked-file metadata, `tools/guardian_readiness.sh`, `make alpha-source-check`, and focused pytest test paths.
- Produces: `bash tools/test_guardian.sh` with ordered repository/software/installation/service/media/isolation checks, final counts, `guardian_test=PASS|FAIL`, and zero only when every required check passes.

- [x] **Step 1: Write failing automatic acceptance tests**

```python
def test_guardian_test_runs_every_phase_and_reports_pass(tmp_path):
    project, hooks = guardian_project(tmp_path, all_checks_pass=True)
    result = run_guardian(project, "tools/test_guardian.sh", hooks)
    assert result.returncode == 0
    assert result.stdout.splitlines()[-1] == "guardian_test=PASS"
    assert_phase_order(result.stdout, ["repository", "software", "installation", "service", "media", "isolation"])


def test_guardian_test_collects_later_safe_results_after_failure(tmp_path):
    project, hooks = guardian_project(tmp_path, failing={"python_regression", "source_check"})
    result = run_guardian(project, "tools/test_guardian.sh", hooks)
    assert result.returncode != 0
    assert "FAIL software python_regression check_failed" in result.stdout
    assert "FAIL media source_check check_failed" in result.stdout
    assert "PASS isolation guardian_focused" in result.stdout
    assert "synthetic-secret" not in result.stdout + result.stderr
```

Also cover: test hooks ignored unless explicit test mode is set, malformed hook directories fail closed, output has only the accepted line grammar, no notification command is invoked, and no event/evidence path is written.

- [x] **Step 2: Run automatic acceptance tests and verify RED**

Run: `/tmp/baby-guardian-venv/bin/pytest -q tests/deploy/test_guardian_commands.py -k guardian_test`

Expected: FAIL because `tools/test_guardian.sh` does not exist.

- [x] **Step 3: Implement the minimum ordered aggregator**

```bash
run_check() {
  local phase="$1"
  local check="$2"
  shift 2
  if run_probe "$check" "$@"; then
    echo "PASS $phase $check"
    PASS_COUNT=$((PASS_COUNT + 1))
  else
    echo "FAIL $phase $check check_failed"
    FAIL_COUNT=$((FAIL_COUNT + 1))
  fi
}
```

The concrete checks are: repository `shell_policy`, `make_wiring`, `tracked_runtime`, `sensitive_literals`; software `python_regression`; installation `required_binaries`, `runtime_config`, `launchd_definitions`, `realtime_models`; service readiness delegated as individually reported checks; media `source_check`; isolation `guardian_focused`. Commands run with stdout/stderr suppressed. The Python regression and guardian-focused lists are explicit and do not call ntfy endpoints or production CLIs that write event data.

- [x] **Step 4: Run automatic acceptance and adjacent guardian tests and verify GREEN**

Run: `/tmp/baby-guardian-venv/bin/pytest -q tests/deploy/test_guardian_commands.py tests/notifications/test_guardian_dispatcher.py tests/notifications/test_guardian_ntfy.py tests/storage/test_visual_risk_store.py tests/vision/test_evidence_files.py tests/vision/test_evidence_recorder.py tests/vision/test_risk_event_pipeline.py tests/tools/test_run_visual_worker.py`

Expected: all selected tests pass.

- [x] **Step 5: Verify shell policy and commit Task 2**

Run: `bash -n tools/test_guardian.sh && LC_ALL=C grep -n '[^ -~\t]' tools/test_guardian.sh; test $? -eq 1`

Commit: `feat: add guardian automatic acceptance script`

### Task 3: Stable Make Entrypoints and Delivery Verification

**Files:**
- Modify: `Makefile`
- Modify: `tests/deploy/test_guardian_commands.py`
- Modify: `docs/CHECKPOINT.md`
- Modify: `docs/NEXT.md`
- Modify: `docs/STATUS.md`
- Modify: `docs/superpowers/plans/2026-08-12-baby-guardian-start-and-automatic-test.md`

**Interfaces:**
- Consumes: `tools/start_guardian.sh` and `tools/test_guardian.sh`.
- Produces: `make alpha-guardian-start` and `make alpha-guardian-test` plus current status documentation.

- [x] **Step 1: Write failing Make target tests**

```python
def test_makefile_exposes_guardian_commands_without_side_effects():
    start = subprocess.run(["make", "-n", "alpha-guardian-start"], cwd=ROOT, capture_output=True, text=True)
    test = subprocess.run(["make", "-n", "alpha-guardian-test"], cwd=ROOT, capture_output=True, text=True)
    assert start.returncode == 0
    assert "bash tools/start_guardian.sh" in start.stdout
    assert test.returncode == 0
    assert "bash tools/test_guardian.sh" in test.stdout
```

- [x] **Step 2: Run Make target tests and verify RED**

Run: `/tmp/baby-guardian-venv/bin/pytest -q tests/deploy/test_guardian_commands.py -k makefile`

Expected: FAIL because the targets do not exist.

- [x] **Step 3: Add thin targets and help text**

```make
alpha-guardian-start:
	@$(BASH) tools/start_guardian.sh

alpha-guardian-test:
	@$(BASH) tools/test_guardian.sh
```

Add both targets to `.PHONY` and the existing help output. Do not alter existing targets.

- [x] **Step 4: Run the fresh focused completion gate**

Run:

```text
/tmp/baby-guardian-venv/bin/pytest -q tests/deploy/test_guardian_commands.py tests/deploy/test_alpha_commands.py tests/deploy/test_gauge_worker_deploy.py tests/deploy/test_visual_worker_deploy.py tests/notifications/test_guardian_dispatcher.py tests/notifications/test_guardian_ntfy.py tests/notifications/test_ntfy.py tests/notifications/test_visual_ntfy.py tests/storage/test_visual_risk_store.py tests/vision/test_evidence_files.py tests/vision/test_evidence_recorder.py tests/vision/test_frame_ring.py tests/vision/test_notification_config.py tests/vision/test_risk_event_pipeline.py tests/vision/test_worker.py tests/tools/test_realtime_visual_status.py tests/tools/test_run_visual_worker.py
node --test tests/frontend/*.test.mjs
bash -n tools/start_guardian.sh tools/guardian_readiness.sh tools/test_guardian.sh
git diff --check
```

Additionally verify every changed shell file is ASCII/LF, no runtime/media/database file is tracked, and changed production files contain no credential/private-key/private-address literal.

- [x] **Step 5: Update status documents and mark plan checkboxes**

Record that option A is software-complete, list both commands, preserve real Android delivery and live risk rehearsal as deferred, and retain the i9 run as the remaining environment acceptance.

- [x] **Step 6: Commit verified wiring and documentation**

Commit implementation wiring with `feat: expose guardian start and automatic test`, then commit status-only changes with `docs: record guardian automatic test checkpoint`.
