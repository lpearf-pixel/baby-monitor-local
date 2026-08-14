# Guardian Live Acceptance Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a supervised `make alpha-guardian-test-live` command that sends one clearly marked harmless ntfy acceptance message and records fixed, redacted confirmation for two phones and the authenticated Dashboard.

**Architecture:** Keep the Make target thin. A Bash 3.2 orchestration script owns terminal confirmations, readiness ordering, hook-only simulation, and fixed reporting; a small Python helper builds only the existing Alpha notification gateway from centralized environment configuration and invokes its test-notification operation without putting secrets in argv or initializing Dashboard databases. Production and simulated modes have disjoint final markers so software tests cannot fabricate physical acceptance.

**Tech Stack:** Python 3.11+, pytest, macOS Bash 3.2, BSD utilities, GNU Make, existing Alpha runtime and ntfy gateway.

## Global Constraints

- Work only on `codex/guardian-evidence-retention`; do not modify `main` or `stable/xiaomi-alpha`.
- Do not push, merge, create a PR, tag, or rewrite remote history in this plan.
- `make alpha-guardian-test` remains noninteractive and notification-free.
- The live command sends at most one clearly labeled text-only acceptance notification per invocation.
- No Baby risk simulation, production event/evidence/outbox write, media persistence, camera control, or Baby Care integration.
- Production confirmation reads exact literal `YES` from the controlling terminal; piped input cannot authorize a real send.
- Test mode never reads production runtime configuration or performs network/device I/O and ends in `guardian_live_test=SIMULATED`, never PASS.
- Shell is ASCII-only UTF-8/LF, macOS Bash 3.2 compatible, bounded, redacted, and free of GNU-only flags.
- No topic, token, credential, address, path, payload, phone identity, raw command output, or exception text may enter acceptance output or Git.
- Preserve all unrelated user files and the existing independent service boundaries.

---

### Task 1: Safe live-notification helper

**Files:**
- Create: `tools/send_guardian_live_notification.py`
- Create: `tests/tools/test_send_guardian_live_notification.py`
- Modify: `apps/api/runtime.py`
- Modify: `tests/api/test_runtime.py`

**Interfaces:**
- Consumes: `apps.api.runtime.notification_gateway_from_env()` and `AlphaGateway.send_test_notification()`.
- Produces: `send_live_notification(gateway_factory: Callable[[], AlphaGateway] = notification_gateway_from_env) -> bool` and `main() -> int`.
- The CLI writes no stdout or stderr; exit `0` means the existing gateway accepted the test notification, exit `1` means a redacted failure.

- [x] **Step 1: Write RED tests for the acceptance copy and helper isolation**

Add a recording `urlopen` context to `tests/api/test_runtime.py`, invoke
`Go2RTCAlphaGateway.send_test_notification()`, and assert that the body contains
both `验收测试` and `不是宝宝风险告警`, the title contains `验收测试`, no URL or
credential is in the body, and the authorization token exists only in the HTTP
header.

Create `tests/tools/test_send_guardian_live_notification.py` with real fake runtime
objects:

```python
class RecordingGateway:
    def __init__(self, error: Exception | None = None) -> None:
        self.calls = 0
        self.error = error

    def send_test_notification(self) -> None:
        self.calls += 1
        if self.error is not None:
            raise self.error


def test_send_live_notification_calls_gateway_once() -> None:
    gateway = RecordingGateway()
    assert send_live_notification(lambda: gateway) is True
    assert gateway.calls == 1


def test_send_live_notification_redacts_factory_failure(capsys) -> None:
    def broken_gateway():
        raise RuntimeError("secret topic at private path")
    assert send_live_notification(broken_gateway) is False
    assert capsys.readouterr() == ("", "")
```

Also test gateway failure, `main()` returning `0/1`, and no helper output.

- [x] **Step 2: Run the new tests and verify RED**

Run:

```text
./.venv-alpha/bin/python -m pytest -q \
  tests/api/test_runtime.py \
  tests/tools/test_send_guardian_live_notification.py
```

Expected: FAIL because the helper module does not exist and the existing Alpha
message is not explicitly labeled as a non-risk acceptance test.

- [x] **Step 3: Implement the minimum helper and safe copy**

Add `notification_gateway_from_env()` and make `runtime_from_env()` reuse it so
the live helper can construct only the notification gateway. Update
`Go2RTCAlphaGateway.send_test_notification()` to retain the current centralized
URL/topic/token/timeout behavior while using:

```python
data="Guardian 通知通道验收测试：这不是宝宝风险告警。".encode("utf-8")
headers={
    "Title": "Baby Monitor Local Acceptance Test",
    "Priority": "high",
    "Tags": "test_tube,white_check_mark",
    # Existing optional Authorization header remains unchanged.
}
```

Implement the helper without logging raw failures:

```python
from collections.abc import Callable

from apps.api.alpha import AlphaGateway
from apps.api.runtime import notification_gateway_from_env


def send_live_notification(
    gateway_factory: Callable[[], AlphaGateway] = notification_gateway_from_env,
) -> bool:
    try:
        gateway_factory().send_test_notification()
    except Exception:
        return False
    return True


def main() -> int:
    return 0 if send_live_notification() else 1


if __name__ == "__main__":
    raise SystemExit(main())
```

- [x] **Step 4: Run the focused tests and verify GREEN**

Run the Step 2 command. Expected: all selected tests PASS with no new warning or
captured secret output.

- [x] **Step 5: Commit Task 1**

```text
git add apps/api/runtime.py tools/send_guardian_live_notification.py \
  tests/api/test_runtime.py tests/tools/test_send_guardian_live_notification.py
git commit -m "feat: add safe guardian live notification probe"
```

---

### Task 2: Supervised live acceptance command

**Files:**
- Create: `tools/test_guardian_live.sh`
- Modify: `Makefile`
- Modify: `tests/deploy/test_guardian_commands.py`
- Modify: `tools/test_guardian.sh`

**Interfaces:**
- Consumes: `tools/guardian_readiness.sh`, `.venv-alpha/bin/python`, `runtime/alpha.env`, and `tools/send_guardian_live_notification.py`.
- Produces: `make alpha-guardian-test-live` and final markers `guardian_live_test=PASS|FAIL|SIMULATED`.
- Test-only hooks: `BABY_MONITOR_GUARDIAN_LIVE_TEST_MODE=1` and executable `readiness` / `notification` files under `BABY_MONITOR_GUARDIAN_LIVE_HOOK_DIR`.

- [x] **Step 1: Write RED shell-orchestration tests**

Extend `tests/deploy/test_guardian_commands.py` with `_live_hooks()` and
`_run_live()` helpers. `_run_live()` supplies confirmation lines through stdin
only while live test mode is enabled. Cover these contracts:

```python
def test_guardian_live_success_is_simulated_and_not_physical_pass(tmp_path):
    result, hooks = _run_live(tmp_path, answers=["YES"] * 6)
    assert result.returncode == 0
    assert result.stdout.splitlines() == [
        "SIMULATED live safety",
        "SIMULATED live readiness",
        "SIMULATED live notification",
        "SIMULATED live phone_a",
        "SIMULATED live phone_b",
        "SIMULATED live live_view",
        "SIMULATED live event_list",
        "guardian_live_test=SIMULATED",
    ]
    assert (hooks / "notification.calls").read_text(encoding="ascii") == "1\n"
    assert "guardian_live_test=PASS" not in result.stdout
```

Add separate tests proving:

- missing test hooks fail before a simulated PASS marker;
- the first or second safety rejection prevents readiness and notification;
- readiness failure prevents notification;
- notification failure is redacted and called once;
- each of `phone_a`, `phone_b`, `live_view`, and `event_list` fails at its own
  stage and prevents later prompts;
- lowercase, whitespace-padded, empty, and EOF answers are rejected;
- all stdout lines match the closed ASCII grammar and stderr contains no hook
  output;
- production mode without an interactive terminal fails with
  `interactive_required` before reading runtime config or sending;
- `make -n alpha-guardian-test-live` prints only the new script invocation;
- the existing automatic test still never invokes a live notification hook.

- [x] **Step 2: Run the live command tests and verify RED**

Run:

```text
./.venv-alpha/bin/python -m pytest -q tests/deploy/test_guardian_commands.py
```

Expected: FAIL because the Make target and live orchestration script do not exist.

- [x] **Step 3: Implement `tools/test_guardian_live.sh`**

Implement these small shell functions:

```text
emit_success(stage)       # SIMULATED in test mode, PASS in production
fail(stage, stable_code)  # fixed FAIL line, final FAIL marker, exit 1
confirm(stage, prompt)    # stdin only in test mode; exact YES via /dev/tty in production
run_readiness()           # hook in test mode; guardian_readiness.sh otherwise
send_notification()       # hook in test mode; source alpha.env and run Python helper otherwise
```

Production checks `[[ -t 0 ]]` and read/write access to `/dev/tty` before the
first confirmation. Every hook and real subprocess redirects stdout/stderr to
`/dev/null`. Test mode requires both executable hooks; missing hooks fail closed.
After two safety confirmations, perform readiness and one notification call,
then confirm `phone_a`, `phone_b`, `live_view`, and `event_list` in order. Emit
the exact fixed output from the approved specification.

- [x] **Step 4: Wire Make and automatic regression coverage**

Add `alpha-guardian-test-live` to `.PHONY`, help, and a thin target:

```make
alpha-guardian-test-live:
	@$(BASH) tools/test_guardian_live.sh
```

Update `check_make_wiring()` in `tools/test_guardian.sh` so `make -n` validates
all three Guardian targets. Add the new helper and deploy tests to the existing
focused software test list, but do not invoke the live command itself.

- [x] **Step 5: Run focused tests and static shell checks**

Run:

```text
./.venv-alpha/bin/python -m pytest -q \
  tests/deploy/test_guardian_commands.py \
  tests/api/test_runtime.py \
  tests/tools/test_send_guardian_live_notification.py
bash -n tools/test_guardian_live.sh tools/test_guardian.sh
LC_ALL=C grep -n '[^\t -~]' tools/test_guardian_live.sh tools/test_guardian.sh
if LC_ALL=C grep -n $'\r' tools/test_guardian_live.sh tools/test_guardian.sh; then exit 1; fi
make -n alpha-guardian-start alpha-guardian-test alpha-guardian-test-live
git diff --check
```

Expected: pytest PASS; `bash -n`, Make dry-run, and diff check exit zero; both
grep checks print nothing.

- [x] **Step 6: Commit Task 2**

```text
git add Makefile tools/test_guardian_live.sh tools/test_guardian.sh \
  tests/deploy/test_guardian_commands.py
git commit -m "feat: add supervised guardian live acceptance"
```

---

### Task 3: Full software gate and project status

**Files:**
- Modify: `SUMMARY.md`
- Modify: `docs/STATUS.md`
- Modify: `docs/CHECKPOINT.md`
- Modify: `docs/NEXT.md`
- Modify: `docs/superpowers/plans/2026-08-14-guardian-live-acceptance.md`

**Interfaces:**
- Consumes: verified Task 1 and Task 2 commits plus the approved design.
- Produces: a durable handoff that distinguishes software-complete from pending physical i9/two-phone acceptance.

- [x] **Step 1: Run the complete fresh software gate**

Run:

```text
./.venv-alpha/bin/python -m pytest -q
node --test tests/frontend/*.test.mjs
./.venv-alpha/bin/python -m compileall -q apps packages services tools
bash -n $(git ls-files '*.sh')
make -n alpha-guardian-start alpha-guardian-test alpha-guardian-test-live
git diff --check
```

Also scan tracked files for runtime/media/SQLite artifacts and scan changed
production files for credential prefixes, private-key markers, and private-network
literals using the existing `tools/test_guardian.sh` policy. Expected: all software
checks PASS; only the already documented Starlette/httpx warning may remain.

- [x] **Step 2: Review the exact diff against the specification**

Confirm line by line that:

- production PASS requires a terminal plus all six exact confirmations;
- readiness and safety failures occur before notification;
- one invocation sends at most one notification;
- test mode cannot source runtime config or emit physical PASS;
- automatic Guardian acceptance stays side-effect free;
- no event/evidence/outbox/media/Baby Care write path was added;
- no secrets, private addresses, paths, payloads, or raw exceptions are exposed.

- [x] **Step 3: Update durable status documents and plan checkboxes**

Record the exact fresh Python and Node counts, static checks, branch and commits.
Mark the command software-complete while keeping a real installed-i9 run with two
phones pending. Move the next priority to installed-i9 Guardian/live acceptance,
household synthetic-scene validation, and the deferred launchd performance gate.
Do not claim model accuracy or physical delivery from synthetic tests.

- [x] **Step 4: Commit Task 3 documentation**

```text
git add SUMMARY.md docs/STATUS.md docs/CHECKPOINT.md docs/NEXT.md \
  docs/superpowers/plans/2026-08-14-guardian-live-acceptance.md
git commit -m "docs: record guardian live acceptance gate"
```

- [x] **Step 5: Re-run final integrity checks on exact HEAD**

Run `git status --short --branch`, `git log -5 --oneline --decorate`, focused
tests for changed behavior, `git diff --check HEAD^`, and a final sensitive/artifact
scan. Report local and remote identities separately. Do not push or integrate the
diverged upstream history without a separately approved remote action.
