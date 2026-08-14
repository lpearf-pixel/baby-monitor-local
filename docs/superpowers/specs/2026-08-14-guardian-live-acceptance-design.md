# Guardian Live Acceptance Design

Date: 2026-08-14
Status: approved design, pending implementation

## 1. Goal

Add one explicit `make alpha-guardian-test-live` command for a supervised Intel
i9 acceptance session. The command verifies that the installed Guardian chain is
ready, sends exactly one harmless text-only ntfy acceptance message, and records
manual confirmation that both household Android phones received it and that the
authenticated Dashboard remains usable.

This command is intentionally separate from `make alpha-guardian-test` because
the existing automatic command must remain safe to run without network side
effects, synthetic risks, production event writes, or operator interaction.

## 2. Scope

The live command covers:

- installed Guardian readiness on the i9;
- one real ntfy test-message dispatch through the centralized production
  notification configuration;
- independent manual receipt confirmation for fixed labels `phone_a` and
  `phone_b`;
- manual confirmation that live viewing and the media-free Guardian event list
  are available through the authenticated Dashboard;
- fixed, ASCII-only, redacted PASS/FAIL output that the operator may redirect to
  a private local evidence file.

The live command does not:

- create or simulate a Baby risk;
- write risk events, evidence rows, evidence media, notification outbox rows, or
  other production database state;
- save camera frames, screenshots, clips, room details, phone identities, ntfy
  topics, credentials, private addresses, paths, payloads, or exception text;
- test model accuracy, Baby posture, face obstruction, bed exit, medical state,
  unattended care, notification priority variants, offline delivery recovery, or
  the 72-hour release gate;
- add per-parent acknowledgement or false-positive feedback to Guardian;
- integrate with Baby Care or write the Baby Care database.

## 3. Command boundary

The Makefile exposes a thin target:

```text
alpha-guardian-test-live
    -> tools/test_guardian_live.sh
```

`tools/test_guardian_live.sh` owns orchestration and fixed reporting. A focused
Python helper owns the one notification operation and reuses the existing
centralized Alpha notification configuration through a narrow gateway factory.
The helper invokes the existing safe test-notification behavior in-process so
credentials never appear in command-line arguments or output, and it does not
construct the full Dashboard runtime or initialize any SQLite database.

No new notification address, topic, token, timeout, or secret-loading system is
introduced. The command reads the same ignored local runtime configuration used
by the installed Alpha Dashboard.

## 4. Supervised flow

The production command follows this exact order:

```text
require interactive terminal
  -> confirm no real infant is in the rehearsal scene
  -> confirm an adult is present and supervising
  -> run the existing bounded Guardian readiness checks
  -> send one harmless acceptance notification
  -> confirm receipt on phone_a
  -> confirm receipt on phone_b
  -> confirm authenticated live view is visible
  -> confirm Guardian event list is visible
  -> emit final PASS only when every step passed
```

The ASCII notification title must identify an `Acceptance Test`, while the body
must clearly state that it is an acceptance test and not a real Baby risk. It
remains text-only and contains no media, evidence
link, private address, event ID, camera identifier, model output, environmental
reading, path, credential, or household detail.

The command sends at most one notification per invocation. A readiness or safety
confirmation failure occurs before network delivery. A failed phone or Dashboard
confirmation after delivery produces a final FAIL and does not send a replacement.

## 5. Confirmation and fail-closed behavior

Production confirmations are read from the controlling terminal rather than a
pipe or environment variable. Each question accepts only the exact literal `YES`.
End-of-file, an unavailable terminal, an empty answer, lowercase or padded input,
or any other response fails the command. Prompts use `/dev/tty`; stdout therefore
remains safe to redirect as acceptance evidence without converting piped input
into authorization.

The following failures are redacted to stable codes:

- `interactive_required`;
- `safety_not_confirmed`;
- `readiness_failed`;
- `notification_failed`;
- `phone_a_unconfirmed`;
- `phone_b_unconfirmed`;
- `live_view_unconfirmed`;
- `event_list_unconfirmed`.

The script never prints the failed command, subprocess output, HTTP status, URL,
topic, credential, configuration value, prompt response, or raw exception.

Final production output ends with exactly one of:

```text
guardian_live_test=PASS
guardian_live_test=FAIL
```

Exit status is zero only for production PASS.

Successful production output uses these fixed lines in order:

```text
PASS live safety
PASS live readiness
PASS live notification
PASS live phone_a
PASS live phone_b
PASS live live_view
PASS live event_list
guardian_live_test=PASS
```

A failure prints only `FAIL live <stage> <stable_code>` followed by
`guardian_live_test=FAIL`. Completed earlier stages may already have emitted their
fixed PASS lines; later stages are not attempted.

## 6. Automated test isolation

Automated tests use `BABY_MONITOR_GUARDIAN_LIVE_TEST_MODE=1`, temporary hook
commands under `BABY_MONITOR_GUARDIAN_LIVE_HOOK_DIR`, and scripted confirmation
input supplied only to the test subprocess. Test mode must never source production runtime
configuration, open a camera stream, call the Dashboard, send ntfy traffic, or
write repository/runtime data.

Even when every injected hook succeeds, test mode ends with:

```text
guardian_live_test=SIMULATED
```

This prevents synthetic orchestration evidence from being mistaken for physical
i9/two-phone acceptance. Test mode returns zero only to allow deterministic
software contract tests; it can never produce `guardian_live_test=PASS`. Successful
test-mode stage lines begin with `SIMULATED live`, not `PASS live`. A failed test
fixture ends with `guardian_live_test=FAIL` and returns nonzero.

Missing or malformed test hooks fail closed. Tests also prove that the existing
`make alpha-guardian-test` does not call the live command or notification helper.

## 7. Compatibility and security

- Shell remains compatible with macOS system Bash 3.2 and BSD utilities.
- All tracked shell text is ASCII-only UTF-8 with LF endings.
- The command uses bounded checks and no GNU-only flags.
- Runtime secrets remain in ignored local secret references or environment
  configuration and never enter Git, argv, stdout, stderr, or a report file.
- The command does not expose go2rtc, the camera, SQLite, or the Dashboard to the
  public internet and does not add a Tailscale Funnel or router port mapping.
- Live viewing remains independent of semantic-model and notification success.
- A notification failure cannot restart or mutate the Guardian services.

## 8. Verification

Implementation uses RED to GREEN tests for:

- Make/help wiring without executing the live command;
- confirmation ordering and failure before notification;
- readiness failure preventing notification;
- exactly one notification call on the successful path;
- separate phone A and phone B confirmation failures;
- Dashboard live-view and event-list confirmation failures;
- fixed redacted output and exit status;
- test mode producing `SIMULATED`, never production `PASS`;
- missing test hooks failing closed;
- the existing automatic Guardian test remaining notification-free;
- the Python notification helper using a generated test double and rejecting
  unsafe or failed results without leaking exceptions.

Fresh completion evidence includes focused Python tests, the complete Python and
Dashboard Node suites, Python compilation, changed-shell `bash -n`, ASCII/LF
checks, Make dry-runs, `git diff --check`, tracked runtime/media/database scans,
and changed-file credential/private-literal scans.

Software verification proves only orchestration, redaction, and isolation against
synthetic fixtures. A real `guardian_live_test=PASS` can be produced only by the
installed i9 command with both phones and a supervised, infant-free rehearsal.

## 9. Cross-project boundary

This slice remains entirely inside `baby-monitor-local`. Fixed labels `phone_a`
and `phone_b` are acceptance labels, not user identities. Per-parent event
acknowledgement, actor-bound feedback, and family authorization remain future Baby
Care responsibilities through a separately approved read-only Guardian integration.
