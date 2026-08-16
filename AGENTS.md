# Baby Monitor Local Project Rules

## Project Mission and Boundaries

- Build a local-first, privacy-preserving Baby Guardian for the confirmed Xiaomi
  MJSXJ17CM camera, Intel i9 Mac, M2 Mac, WS2021 dial gauge and two iPhones.
- The system may observe, summarize and raise candidate safety events. It is not a
  medical device, does not diagnose, and never replaces direct adult supervision.
- Keep live viewing independent of AI availability. A model, tunnel or analysis
  failure must not break the camera's microSD recording, Mi Home access, Dashboard,
  environment monitoring or other independent workers.
- Deliver Xiaomi-first. Add other cameras only through the existing frame-source
  boundary after the Xiaomi Alpha is accepted; do not mix compatibility work into
  the current guardian loop without an approved specification.
- Audio and cry detection remain deferred until the visual guardian loop is complete.
- Baby Guardian is the local perception/event layer. A future Baby Care integration
  may read normalized Guardian events, but Guardian must never write the Baby Care
  database directly.

## System Architecture and Ownership

- The Xiaomi camera and its microSD card own continuous capture and loop recording.
- The Intel i9 Mac owns camera ingest, go2rtc, Dashboard, environment reading,
  deterministic risk state, event/evidence storage, notification dispatch and
  launchd supervision.
- The M2 Mac owns local Ollama semantic review. The i9 may reach it only through the
  restricted loopback SSH-forwarding design; the tunnel and visual worker are
  independently supervised.
- Qwen or another semantic model produces bounded observations only. The deterministic
  i9 state machine owns alert confirmation, recovery, deduplication and audit state.
- The visual worker, gauge worker, environment watchdog, Dashboard, go2rtc and model
  tunnel must degrade independently. Do not introduce a supervisor action that
  restarts the full Alpha stack for one component failure.
- Normal analysis frames remain bounded in memory. Only privacy-processed event
  evidence may be written locally under the repository's evidence lifecycle rules.
- Environment monitoring is read-only. Do not add actuator or automatic device-control
  APIs for air conditioning, humidifiers, fans, plugs or camera movement.
- PTZ remains disabled until the real MJSXJ17CM motor protocol has public evidence,
  fixtures and a safe minimum movement/rollback gate. Mi Home remains the control path.

## Safety and Privacy Invariants

- Never commit, paste into issues, or expose in logs: household images or audio,
  baby footage, room layout, account credentials, device keys, notification topics or
  tokens, private addresses, local absolute deployment paths, SQLite databases,
  runtime state, calibration data or generated local settings.
- Runtime secrets must use local secret references or ignored runtime configuration.
  Never place a credential in source, Git history, a command argument, an example, a
  test fixture or `SUMMARY.md`. Revoke any credential exposed in chat or logs.
- Tests use generated, synthetic or explicitly public media only.
- Apply bed-zone cropping and privacy masking before model transmission, persistence
  or evidence export. Raw continuous camera video and audio remain local by default.
- Notifications are text-only unless a separately approved authenticated design says
  otherwise. Do not include media, paths, private addresses, model prose, credentials
  or unauthenticated links.
- Bind camera administration, go2rtc and model forwarding to loopback. Never use
  Tailscale Funnel or router port forwarding. Remote viewing must use authenticated
  private access; do not open camera, database or go2rtc ports to the public internet.
- Logs and health endpoints expose stable status codes and bounded metrics, not raw
  exceptions, payloads, frames, URLs or configuration values.
- Storage, logging, model, notification and evidence failures must fail closed and
  must not fabricate alerts, recoveries, completed evidence or healthy status.

## Repository and Git Governance

- Protect `main`. The stable Xiaomi release line is `stable/xiaomi-alpha`; feature
  work stays on the current explicitly approved feature branch.
- Before editing, inspect the real repository root, remote, branch, HEAD, dirty files,
  recent commits and relevant documentation. Repository state overrides stale prose.
- Preserve all user changes. Never reset, clean, overwrite, rebase, force-push, merge,
  delete branches, create a PR or modify a protected branch without explicit approval.
- Do not stage unrelated files. In particular, preserve an existing untracked
  `uv.lock` unless the user separately approves its ownership and inclusion.
- Use focused commits with clear intent. Report local and remote commit identities
  separately when a connector-generated squash commit differs from local history.
- Push only the approved branch and scope. A push does not imply approval to create a
  PR, merge, tag a release or modify `main`.
- Never store a personal access token in the repository. Use the user's configured
  GitHub CLI, credential manager, SSH identity or approved GitHub connector.

## Configuration and Runtime Rules

- Python requires version 3.11 or newer. The Intel x86_64 macOS realtime path pins
  OpenVINO to the version declared in `pyproject.toml`.
- Centralize runtime configuration. Do not scatter addresses, ports, credentials,
  thresholds, paths or model identifiers through scripts and services.
- Commit templates and examples only. Real settings, calibration, media, databases,
  models and launchd-generated state stay in ignored local locations.
- Preserve fixed loopback and model boundaries already enforced by contracts. Do not
  make endpoints, prompts, model labels or privacy limits user-replaceable as a shortcut.
- Prefer structured status files and stable diagnostic codes over large raw logs.
  Read only the relevant bounded diagnostic window when investigating failures.
- Keep SQLite event/outbox operations restart-safe and idempotent. Preserve causal
  notification order and distinguish pending, ready, failed and interrupted evidence.

## macOS and Shell Compatibility

- User-facing macOS commands must be short, copy-safe and ASCII-only.
- Put reusable or long procedures in repository scripts; do not require multiline
  heredocs or large terminal pastes.
- Repository shell scripts must be ASCII-only, UTF-8 with LF endings, compatible with
  macOS Bash 3.2 and BSD utilities, and pass `bash -n`.
- Avoid GNU-only flags, smart quotes, Chinese shell comments and emoji in scripts.
- Scripts must be idempotent where practical, use bounded waits, return reliable exit
  codes, redact underlying output and identify a fixed log category on failure.
- Do not assume Git executable bits are preserved; invoke repository scripts through
  the Makefile or `bash` according to existing project patterns.

## Verification Strategy

- Follow design approval before implementation for behavior or architecture changes.
  Maintain specifications in `docs/superpowers/specs/` and plans in
  `docs/superpowers/plans/`.
- Use focused tests for small slices. Run the full software gate for a major milestone,
  release, stable-branch integration or broad infrastructure change.
- Python focused checks use the relevant paths under `tests/`; the full software suite
  is `python -m pytest -q`. Dashboard tests use
  `node --test tests/frontend/*.test.mjs`.
- Validate changed Python with compilation, changed shell with `bash -n`, shell text
  with ASCII/LF checks, Make entries with `make -n`, and every change with
  `git diff --check`.
- Scan the final tracked diff for credentials, private keys, private network literals,
  runtime media, SQLite files and generated settings.
- `make alpha-guardian-test` is the installed i9 automatic acceptance entry. It must
  remain side-effect bounded: no real notification, synthetic risk event or production
  event/evidence write.
- Software tests never prove camera accuracy, household scene accuracy, two-phone
  delivery, installed launchd readiness, sustained performance or safe unattended care.
  Record each real-device gate separately with redacted evidence.
- Never weaken, delete or bypass a failing test to obtain a green result. Diagnose the
  first actionable failure, fix it and rerun the same command.

## Work Session Takeover

1. Read this file completely.
2. Read root `SUMMARY.md`, then `docs/STATUS.md`, `docs/CHECKPOINT.md` and
   `docs/NEXT.md` for detailed evidence and next work.
3. Run read-only Git checks for root, remotes, branch, HEAD, dirty state, upstream and
   recent commits. Reconcile any difference with the summary before editing.
4. Preserve unrelated changes and state a task contract: current state, goal, allowed
   scope, prohibited actions, completion criteria, exact verification and delivery
   boundary.
5. Continue the highest approved unfinished slice. Do not restart completed milestones
   or let deferred performance work block the guardian feature sequence.
6. For ordinary implementation problems, test failures and recoverable local errors,
   diagnose the first actionable cause, fix it within the approved slice and rerun the
   same gate. Do not stop merely because a planned step needs routine debugging.
7. After a slice passes its required gate, update the owning plan checkbox/status and
   the authoritative handoff documents before moving to the next slice.
8. Ask only for missing decisions that materially change behavior, privacy, safety,
   deployment or irreversible remote operations.

Stop and request direction when progress requires new permissions or credentials, an
irreversible external operation, access to private household data not already supplied
through an approved local workflow, or a material conflict with the approved architecture.

## Required Delivery Report

Every completed slice must report:

- observable functionality delivered;
- files and interfaces changed;
- fresh verification commands and pass/fail counts;
- what software evidence does and does not prove;
- remaining real-device, privacy, safety and performance gates;
- branch, local HEAD, remote state and whether anything was pushed, merged or committed;
- unrelated files deliberately preserved;
- the exact next product slice.

Update `SUMMARY.md` at meaningful checkpoints, release-line changes, remote publication
or changes to the ordered next priority. Keep durable rules here and transient state in
the summary.

## Authoritative Documentation

- `SUMMARY.md`: compact current handoff snapshot.
- `docs/STATUS.md`: detailed current capability and gate status.
- `docs/CHECKPOINT.md`: chronological verification evidence.
- `docs/NEXT.md`: ordered delivery queue.
- `README.md`: user-facing product and operating overview.
- `SECURITY.md`: public-repository security policy.
- `ROADMAP.md`: milestone direction.
- `docs/superpowers/specs/`: approved designs.
- `docs/superpowers/plans/`: implementation plans.

When these documents disagree, use fresh repository/runtime evidence, correct the stale
document in the same approved scope, and never silently choose the more optimistic claim.
