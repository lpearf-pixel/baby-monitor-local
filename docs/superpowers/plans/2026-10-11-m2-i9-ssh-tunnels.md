# M2-i9 SSH Tunnel Management Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Provide one M2-launched, launchd-supervised SSH session that forwards go2rtc 1984 to M2 and Ollama 11435 to i9, with safe lifecycle controls and separated health reporting.

**Architecture:** The M2 user LaunchAgent owns one SSH process targeting the i9 LAN address. Its `-L` endpoint is local to M2 and its loopback-only `-R` endpoint is remote on i9. Repository scripts render only local ignored configuration, manage one private label, and never stop or rewrite the existing i9-only Ollama tunnel.

**Tech Stack:** macOS launchd, OpenSSH, Bash 3.2-compatible scripts, bounded curl/lsof/ssh checks, shell/Python synthetic tests.

**Spec:** User-approved 2026-10-11 M2 ↔ i9 tunnel management requirements in the task request.

## Global Constraints

- No credentials, private keys, host-specific paths or runtime logs in Git.
- Camera Reply remains false; Guardian, go2rtc, Ollama and Baby Care are never restarted by tunnel code.
- Existing `com.babymonitor.ollama-tunnel` is inspected but never automatically disabled.
- Port conflicts and missing SSH configuration fail closed without killing unknown processes.
- Scripts are ASCII-only, LF, Bash 3.2 compatible, bounded and idempotent.
- Only the approved feature branch is changed; no main/stable merge or force push.

## Review Focus

- Existing i9-only tunnel owns 11435: install must report conflict and leave it untouched (Task 2 test).
- One forward succeeds while the other fails: status must expose each layer independently (Task 3 test).
- SSH exits or loses network: launchd may retry with throttle, but controls must not create a second process (Task 2/4 tests).
- Invalid identity/target or unsafe placeholder: render/install must reject before launchd writes (Task 1 test).
- API listener is alive but HTTP health fails: status must distinguish listener from go2rtc/Ollama reachability (Task 3 test).

### Task 1: Safe template and configuration renderer

**Files:**
- Create: `config/launchd/com.babymonitor.ssh-tunnels.plist.template`
- Create: `scripts/tunnels/render.sh`
- Test: `tests/tunnels/test_render.sh`

**Interfaces:**
- `render.sh --template PATH --output PATH --target USER@HOST --identity PATH --log-dir PATH`
- Output is a private candidate plist containing one SSH command with both `-L` and `-R` forwards.

- [x] Write RED tests for required placeholders, fixed SSH flags, loopback binds, no secret echo and rejection of unsafe/empty values.
- [x] Run the render tests and observe the expected failures.
- [x] Implement the renderer with shell-safe validation and atomic candidate output.
- [x] Run `bash -n`, ASCII/LF checks and render tests.
- [x] Commit `feat: add combined ssh tunnel launchd template`.

### Task 2: Install/uninstall/control lifecycle

**Files:**
- Create: `scripts/tunnels/install.sh`
- Create: `scripts/tunnels/uninstall.sh`
- Create: `scripts/tunnels/control.sh`
- Test: `tests/tunnels/test_control.sh`

**Interfaces:**
- `install.sh --target USER@HOST --identity PATH` installs only `com.babymonitor.ssh-tunnels` for the current user.
- `uninstall.sh` removes only that label and its generated plist.
- `control.sh start|stop|restart|status|check` operates only that label and uses bounded waits.

- [x] Write RED tests for launchctl command construction, existing-label ownership, port conflict fail-closed, and no unrelated label operations.
- [x] Implement install/uninstall with ownership markers and no automatic migration of the old Ollama label.
- [x] Implement bounded start/stop/restart; never call kill on unknown PIDs or other labels.
- [x] Run synthetic lifecycle tests with fake launchctl/lsof/curl and verify recovery/throttle behavior.
- [x] Commit `feat: add safe ssh tunnel lifecycle controls`.

### Task 3: Layered status and health checks

**Files:**
- Create: `scripts/tunnels/check.sh`
- Modify: `scripts/tunnels/control.sh`
- Test: `tests/tunnels/test_check.sh`

**Interfaces:**
- `check.sh --target USER@HOST --identity PATH` emits bounded key/value lines for `ssh_process`, `m2_port_1984`, `go2rtc_api`, `i9_port_11435`, `ollama_api`.
- Each value is independently `reachable`, `unreachable`, `conflict`, `unknown` or `not_installed`.

- [x] Write RED tests for every independent combination and no-reconnect behavior.
- [x] Implement local M2 checks and one bounded remote i9 probe without printing credentials, payloads or logs.
- [x] Verify M7 path through i9 `127.0.0.1:11435/api/tags` without changing the existing endpoint.
- [x] Run shell syntax, synthetic checks and `make -n` integration if a Make target is added.
- [x] Commit `feat: add layered ssh tunnel health checks`.

### Task 4: Operations documentation and review gate

**Files:**
- Create: `docs/operations/ssh-tunnels.md`
- Modify: `docs/STATUS.md`, `docs/NEXT.md`, `SUMMARY.md`, `AGENTS.md` only if a durable rule is genuinely missing.
- Test: `tests/tunnels/test_docs.sh`

- [ ] Document M2 installation, rollback, existing-service conflict migration, M7 Ollama check and separate M2/i9 status interpretation.
- [ ] Explicitly state that install is not run automatically and old services are not disabled.
- [ ] Run all tunnel tests, `bash -n`, ASCII/LF, `git diff --check` and privacy scans.
- [ ] Perform read-only review of all changed paths and preserve `Interactive`/`test.sh`.
- [ ] Commit `docs: document combined ssh tunnel operations`.

### Task 5: Delivery

- [ ] Confirm current branch is `codex/m7-local-llm-parenting-assistant` and no protected branch is involved.
- [ ] Run the focused tunnel suite and relevant existing deployment tests once.
- [ ] Commit only reviewed scripts, template, tests and documentation; do not stage user files.
- [ ] Push the feature branch normally and report local/remote SHA, test counts and hardware-install pending state.
