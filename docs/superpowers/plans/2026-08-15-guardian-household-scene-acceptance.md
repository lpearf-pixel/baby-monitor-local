# Guardian Household Scene Acceptance Implementation Plan

Date: 2026-08-15  
Design: `docs/superpowers/specs/2026-08-15-guardian-household-scene-acceptance-design.md`

## Goal

Deliver `make alpha-guardian-scene-test`, a supervised Intel i9 workflow that records
fixed aggregate outcomes for seven safe household synthetic scenes without persisting
media, model prose, private configuration or production Guardian events.

## Acceptance Thresholds

- Ten completed trials are required for every scene.
- Empty bed, doll/prop, adult in frame, infrared/night view, mosquito-net movement and
  safe normal-turning substitute require zero risk-level false positives.
- Safely simulated camera obstruction requires at least nine `correct` trials out of
  ten and no `unavailable` trial.
- Any production event/evidence write, ntfy send, invalid state, storage failure,
  duplicate trial or unavailable observation fails closed.

These thresholds are an initial household acceptance gate, not a medical accuracy
claim. Changing them requires a later approved specification.

## Task 1 — Closed Result Contract and Store

Create a small module under `services/vision/` with:

- fixed scene and outcome enums;
- strict schema-v1 run/trial records;
- a controlled runtime result path;
- mode-`0600`, same-directory atomic replacement;
- symlink rejection, duplicate prevention and monotonic trial ordinals;
- explicit `incomplete`, `passed` and `failed` states;
- deterministic resume of an incomplete run.

Write tests first under `tests/vision/` for schema rejection, thresholds, atomic write,
permissions, resume, interruption and fail-closed filesystem behavior.

Commit after focused verification:

```text
feat: add guardian scene acceptance store
```

## Task 2 — Interactive Runner

Add `tools/test_guardian_scenes.py` or a thin shell/Python pair that:

- requires a controlling terminal in production;
- confirms no real infant and adult supervision before observation;
- walks the fixed scene order and ten trials per scene;
- accepts only `correct`, `false_positive`, `missed` or `unavailable`;
- reads only an allow-listed redacted observation adapter;
- never initializes notification, event or evidence writers;
- resumes an incomplete run and prints fixed ASCII status lines;
- ends with `guardian_scene_test=PASS|FAIL|INCOMPLETE|SIMULATED`.

Hook-only test mode must use temporary state and can emit only `SIMULATED`. Add focused
tests under `tests/tools/` for safety rejection, TTY rejection, all outcomes, resume,
redaction, no-side-effect boundaries and output order.

Commit after focused verification:

```text
feat: add supervised guardian scene acceptance
```

## Task 3 — Make and Operations Wiring

Add the thin `alpha-guardian-scene-test` Make target, help text and `.PHONY` entry.
Update the automatic command wiring tests and the runbook with short ASCII-only command
instructions. Do not call the scene command from `alpha-guardian-test`; the automatic
gate remains noninteractive and side-effect bounded.

Commit after focused verification:

```text
docs: add guardian scene acceptance workflow
```

## Task 4 — Software Gate

Run:

```bash
python -m pytest -q <focused scene paths>
node --test tests/frontend/*.test.mjs
bash -n <changed shell files>
make -n alpha-guardian-scene-test
git diff --check
```

Then run the full Python suite. Scan the tracked diff for credentials, private network
literals, media, SQLite files, generated settings and private paths. Do not weaken or
skip a failing test.

## Task 5 — Installed Intel i9 Gate

With no real infant present and an adult supervising:

1. verify Guardian readiness and redacted visual metrics;
2. run `make alpha-guardian-scene-test`;
3. complete exactly ten safe trials for each fixed scene;
4. confirm the command neither sends ntfy nor writes production event/evidence data;
5. record only aggregate fixed outcomes and the final marker in `docs/CHECKPOINT.md`.

The physical checkpoint is a separate documentation commit. It must keep household
media, paths, coordinates, addresses, credentials and model prose out of Git and chat.
