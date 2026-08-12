# Visual Launchd Update Recovery Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the visual worker launchd update tolerate delayed service removal, retry bounded registration, and report the exact safe failure stage without leaving the old worker offline.

**Architecture:** Keep the existing atomic plist and EXIT-trap transaction. Add small Bash helpers for bounded unregistration, bounded registration, and verified activation; exercise them through the real update script with a stateful fake launchctl that models macOS transition timing.

**Tech Stack:** macOS launchd, Bash 3.2, BSD utilities, plist XML, Python 3.11, pytest, Make.

## Global Constraints

- Work only on `codex/xiaomi-alpha-visual-risk-core` from `e4c92648144c5a73c5ab54fde90097e061a86010`.
- Do not change the analyzer, models, load-controller policy, FPS/latency thresholds, other launchd services, `main`, or the running i9 worker.
- Preserve the exact pre-update plist and never overwrite the existing `.r3-background.bak`.
- Shell remains ASCII-only, UTF-8 LF, macOS Bash 3.2/BSD compatible, and free of GNU-only flags.
- Output only fixed allow-listed fields; never print launchctl stderr, paths, configuration, credentials, private addresses, or household data.
- Use focused tests; do not run the full repository gate for this small deployment fix.
- Commit locally only. Do not fetch, push, create a PR, merge, or modify `main`.

---

### Task 1: Reproduce launchd transition timing

**Files:**
- Modify: `tests/deploy/test_visual_launchd_update.py`
- Test: `tests/deploy/test_visual_launchd_update.py`

**Interfaces:**
- Consumes: `tools/update_visual_launchd.sh` and a fake `launchctl` state file.
- Produces: observable tests for delayed unregistration and transient bootstrap failure.

- [ ] **Step 1: Extend the launchd fixture**

Represent `loaded`, `removing:N`, and `unloaded` states. Make `print` decrement
`removing:N` while still returning success, make `bootstrap` fail until the
state is `unloaded`, and provide a fake `sleep` that records calls without
waiting.

- [ ] **Step 2: Write the delayed-unregistration test**

Run the real updater with two removal observations. Assert exit 0, the
Interactive plist, one loaded service, two recorded sleeps before the first
bootstrap, and the stable PASS output.

- [ ] **Step 3: Write the transient-bootstrap test**

Configure candidate bootstrap to fail twice after unregistration. Assert the
third bootstrap succeeds, the job is loaded once, and the update exits 0.

- [ ] **Step 4: Verify RED**

Run:

```bash
./.venv-alpha/bin/python -m pytest -q \
  tests/deploy/test_visual_launchd_update.py \
  -k 'delayed_unregistration or retries_transient_candidate_bootstrap'
```

Expected: both tests fail against `e4c9264`; the first exposes immediate
bootstrap/rollback failure and the second exposes the single-attempt candidate
activation.

### Task 2: Add bounded lifecycle helpers

**Files:**
- Modify: `tools/update_visual_launchd.sh`
- Test: `tests/deploy/test_visual_launchd_update.py`

**Interfaces:**
- Consumes: service identifier, domain, installed plist, `launchctl`, and
  `sleep`.
- Produces: `wait_until_unregistered`, `bootstrap_with_retry`, and
  `activate_installed_job` Bash functions returning status without emitting
  unredacted output.

- [ ] **Step 1: Implement the minimal unregistration wait**

Poll `launchctl print "$SERVICE"` once per second for at most 30 observations.
Return success on the first absent result and failure after the bound.

- [ ] **Step 2: Implement bounded bootstrap retry**

Attempt `launchctl bootstrap "$DOMAIN" "$PLIST"` at most 30 times. Accept
either a successful command or a registered job observed by `launchctl print`;
otherwise sleep one second between attempts and return failure at the bound.

- [ ] **Step 3: Implement verified activation**

After registration, require `launchctl kickstart -k "$SERVICE"` and a final
successful `launchctl print "$SERVICE"`. Return distinct function statuses so
the caller can select `*_bootstrap_timeout`, `*_kickstart_failed`, or
`*_verify_failed`.

- [ ] **Step 4: Use helpers for candidate activation and rollback**

After successful `bootout`, require bounded unregistration before installing
the candidate. Use the shared activation helper in the main path and EXIT
rollback, while preserving exit 2 for a successfully rolled-back candidate
failure and exit 3 for a rollback-stage failure.

- [ ] **Step 5: Verify GREEN for Task 1**

Run the Task 1 command. Expected: both regression tests pass with no stderr.

### Task 3: Prove recovery and error separation

**Files:**
- Modify: `tests/deploy/test_visual_launchd_update.py`
- Modify: `docs/superpowers/specs/2026-08-08-realtime-visual-production-sampler-design.md`

**Interfaces:**
- Consumes: candidate/rollback plist content and separate fake-bootstrap
  failure counters.
- Produces: recovery behavior and stable `rollback_bootstrap_timeout` failure.

- [ ] **Step 1: Write a rollback-retry test**

Make every Interactive bootstrap fail, then make the restored Background job
fail twice before succeeding. Assert exit 2, exact restoration of the original
plist, preserved persistent backup, one loaded job, and
`reason=activation_bootstrap_timeout`.

- [ ] **Step 2: Verify RED**

Run only the rollback-retry test. Expected: failure because the existing EXIT
trap performs one immediate rollback bootstrap.

- [ ] **Step 3: Write the rollback-timeout test**

Make Interactive and Background bootstraps fail through the retry bound.
Assert exit 3, restored plist bytes, absent service, empty stderr, and
`reason=rollback_bootstrap_timeout`.

- [ ] **Step 4: Verify RED**

Run only the rollback-timeout test. Expected: failure because the current
script reports `rollback_failed`.

- [ ] **Step 5: Verify GREEN**

Run all `tests/deploy/test_visual_launchd_update.py` tests. Expected: all pass.

- [ ] **Step 6: Correct the performance evidence**

Record that the unchanged Background job briefly reached 5 FPS after restart,
then the same PID selected 3 FPS after P95 `256.935ms` and maximum
`325.313ms`; identify `realtime_fps` as the controller target and keep
Interactive as an unaccepted same-host experiment.

### Task 4: Focused delivery verification and local implementation commit

**Files:**
- Modify: `docs/superpowers/plans/2026-08-11-visual-launchd-update-recovery.md`

**Interfaces:**
- Consumes: all planned changes.
- Produces: fresh verification evidence and one local implementation commit
  after the separately committed design and plan.

- [ ] **Step 1: Run focused tests**

```bash
./.venv-alpha/bin/python -m pytest -q \
  tests/deploy/test_visual_launchd_update.py \
  tests/deploy/test_realtime_visual_diagnostic_deploy.py \
  tests/tools/test_realtime_visual_performance.py \
  tests/tools/test_realtime_visual_status.py \
  tests/vision/test_realtime_load.py
```

- [ ] **Step 2: Run static checks**

```bash
./.venv-alpha/bin/python -m py_compile tests/deploy/test_visual_launchd_update.py
bash -n tools/update_visual_launchd.sh
make -n alpha-visual-launchd-update
git diff --check
```

Also lint `deploy/launchd/com.babymonitor.visual.plist.example` with `plutil`
when available, verify the changed shell file is ASCII with LF endings, and
scan the exact changed/tracked-new file set for secrets, private keys, private
addresses, runtime media, and database artifacts.

- [ ] **Step 3: Review scope and acceptance**

Compare the staged diff with this plan and the design. Confirm there are no
unrelated files, no weakened/deleted tests, no remote operations, and no claim
that software tests prove i9 performance.

- [ ] **Step 4: Commit locally**

```bash
git add \
  tools/update_visual_launchd.sh \
  tests/deploy/test_visual_launchd_update.py \
  docs/superpowers/specs/2026-08-08-realtime-visual-production-sampler-design.md
git commit -m "fix: harden visual launchd update recovery"
```

Do not push. Report the local commit, fresh focused evidence, remaining i9
validation, and the exact next command only after explicit push approval.
