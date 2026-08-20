# go2rtc Health-Aware Start Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Recover automatically when the recorded go2rtc PID is alive but its loopback API is unhealthy, without killing an unrelated process.

**Architecture:** Add a go2rtc-specific startup guard around the existing generic PID helper. The guard accepts a bounded loopback API probe only when its PID file names a live process whose full BSD `ps -ww` command exactly matches the repository executable and configuration arguments and that same PID owns the API listener. It validates any live unhealthy PID by command identity before replacement, reuses the existing bounded stop pattern only for a verified match, and then starts one replacement through `start_if_stopped`.

**Tech Stack:** macOS Bash 3.2, BSD `ps`, `curl`, pytest subprocess integration tests.

## Global Constraints

- Change only `tools/start_alpha.sh` and `tests/deploy/test_alpha_commands.py`.
- Keep go2rtc administration and probing on loopback.
- Shell output must be fixed ASCII and must not expose PIDs, paths, commands, URLs, configuration, or private addresses.
- Do not alter Dashboard or independent-worker startup behavior.
- Preserve untracked `.local/`, `Interactive`, and `test.sh`.
- Deliver one focused local implementation commit; do not push, merge, create a PR, or modify a protected branch.

---

### Task 1: Replace a verified live-but-unhealthy go2rtc process

**Files:**
- Modify: `tests/deploy/test_alpha_commands.py`
- Modify: `tools/start_alpha.sh`

**Interfaces:**
- Consumes: `GO2RTC_PID`, `$ROOT/.local/bin/go2rtc`, `$ROOT/runtime/go2rtc.yaml`, and loopback `http://127.0.0.1:1984/api`.
- Produces: shell function `ensure_go2rtc_started`; fixed failure text `go2rtc pid identity mismatch`.

- [ ] **Step 1: Add a subprocess fixture for go2rtc startup states**

  Add a focused helper beside `_write_executable` that constructs the minimum
  temporary Alpha tree, starts a real disposable `sleep` process for the live
  PID case, installs fake `curl`, `ps`, `uname`, `id`, `route`, and `launchctl`
  commands, and records whether the replacement go2rtc executable runs. The
  fake `curl` returns unhealthy until the replacement marker exists and healthy
  afterward. Register cleanup that terminates only the disposable sleep child.

- [ ] **Step 2: Write the live-but-unhealthy failing regression test**

  Add a test with this behavioral contract:

  ```python
  def test_alpha_start_replaces_verified_live_but_unhealthy_go2rtc(tmp_path: Path) -> None:
      fixture = _go2rtc_start_fixture(tmp_path, ps_identity="expected")
      result = fixture.run_start()

      assert result.returncode == 0, result.stderr
      assert fixture.replacement_marker.exists()
      assert not fixture.original_pid_is_alive()
  ```

- [ ] **Step 3: Run the regression test and verify RED**

  Run:

  ```bash
  .venv-alpha/bin/python -m pytest -q tests/deploy/test_alpha_commands.py::test_alpha_start_replaces_verified_live_but_unhealthy_go2rtc
  ```

  Expected: FAIL because the current `start_if_stopped` accepts the live PID,
  skips the replacement, and the API readiness check times out.

- [ ] **Step 4: Add the unrelated-live-PID fail-closed test**

  Add a second test using the same fixture with `ps_identity="unrelated"`:

  ```python
  def test_alpha_start_does_not_stop_unrelated_live_pid(tmp_path: Path) -> None:
      fixture = _go2rtc_start_fixture(tmp_path, ps_identity="unrelated")
      result = fixture.run_start()

      assert result.returncode != 0
      assert result.stderr.strip() == "go2rtc pid identity mismatch"
      assert fixture.original_pid_is_alive()
      assert not fixture.replacement_marker.exists()
  ```

  Run it and verify that it fails for the expected missing identity check, not
  because of fixture setup.

- [ ] **Step 5: Implement the minimum health-aware startup guard**

  In `tools/start_alpha.sh`, add small helpers with these responsibilities:

  ```bash
  go2rtc_api_ready() {
    curl -fsS --max-time 2 http://127.0.0.1:1984/api >/dev/null 2>&1
  }

  go2rtc_pid_matches() {
    local pid="$1"
    local command
    command="$(ps -ww -p "$pid" -o command= 2>/dev/null || true)"
    [[ "$command" == "$ROOT/.local/bin/go2rtc -config $ROOT/runtime/go2rtc.yaml" ]]
  }
  ```

  Add `ensure_go2rtc_started` so it:

  - returns immediately when `go2rtc_api_ready` succeeds only after a PID file,
    live PID, exact full-command identity, and `lsof` confirmation that the same
    PID owns the API listener verify; otherwise it emits the fixed identity
    error without stopping anything;
  - removes a dead stale PID through existing `start_if_stopped` behavior;
  - reports `go2rtc pid identity mismatch` and returns nonzero when a live PID
    does not match;
  - uses the existing 20-observation, 0.25-second graceful stop and final
    forced-stop behavior for a matching unhealthy PID;
  - removes that PID file and calls `start_if_stopped` once for the replacement.

  Replace the direct go2rtc `start_if_stopped` call with
  `ensure_go2rtc_started`. Reuse `go2rtc_api_ready` in the existing bounded
  readiness loop and final check.

- [ ] **Step 6: Verify GREEN for focused startup behavior**

  Run:

  ```bash
  .venv-alpha/bin/python -m pytest -q tests/deploy/test_alpha_commands.py
  ```

  Expected: all tests pass, including replacement of the verified unhealthy
  PID, preservation of the unrelated live PID, rejection of a healthy
  unrelated endpoint, an API listener not owned by the verified PID, and a
  long-command BSD `ps -ww` identity case.

- [ ] **Step 7: Run shell and repository verification**

  Run:

  ```bash
  bash -n tools/start_alpha.sh
  make -n alpha-start
  .venv-alpha/bin/python -m pytest -q tests/deploy/test_guardian_commands.py tests/deploy/test_alpha_commands.py
  git diff --check
  ```

  Verify the changed shell file is ASCII-only with LF endings, then scan the
  tracked diff for credentials, private keys, private network literals,
  runtime media, SQLite files, generated settings, and absolute deployment
  paths. Software evidence proves startup state handling only; it does not
  prove camera availability, household-scene accuracy, notifications, or safe
  unattended care.

- [ ] **Step 8: Commit only the implementation slice**

  ```bash
  git add tools/start_alpha.sh tests/deploy/test_alpha_commands.py
  git commit -m "fix: recover unhealthy go2rtc startup"
  ```

Report branch, local HEAD, upstream divergence, verification counts, no
push/merge/PR, preserved unrelated files, remaining real-device source gate,
and the next product slice.

---

### 2026-08-20 follow-up: macOS single launchd owner

- [x] Reproduce bootstrap failure followed by a second direct go2rtc process.
- [x] Add RED tests for no direct fallback, kickstart-only recovery and no
  port/PID-selected stop.
- [x] Add and install a project-owned user launchd definition.
- [x] Preserve the exact process/listener identity check without weakening the
  non-macOS PID path.
- [x] Verify one stable process across restart and a second idempotent start.
- [x] Add and verify `make alpha-go2rtc-restart` without restarting sibling services.
- [ ] After restarting the camera itself, require `make alpha-source-check` PASS and
  record codec, dimensions and positive bytes without private source details.
