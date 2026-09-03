# Dashboard tabs, analytics and alerts pre-integration review

**Status: integrated and full-gate closed.** The Dashboard-focused gates, complete
frontend gate, compilation, diff/privacy/artifact scans and merge preview passed. The
pre-integration executor denied Unix-domain socket creation before the unrelated test
reached project code; that accepted exception remains documented below as historical
evidence. A post-integration run on exact merged head `2d0f2cc6` permitted the fixture
and returned a zero-exit full Python gate, so the plan assertion is now checked.

## Exact state

- Branch: `codex/dashboard-tabs-analytics-alerts`
- Feature base / merge base: `cabd4cf10e35a4aa9877a9b3c9a1e8692818948d`
- Exact committed implementation HEAD: `d8e7a09d4464c7f8ebd4d28c6d648c480673fd9f`
- Intended integration target: `origin/codex/visual-regression-corpus`
- Target before fetch: `fd7af06748c16cdba3f0ba06ccc7e0f7a096893a`
- Target after fetch: `fd7af06748c16cdba3f0ba06ccc7e0f7a096893a`
- Target advanced from the known `fd7af06748c16cdba3f0ba06ccc7e0f7a096893a`:
  `false`
- Unique commits from the merge base at the implementation preview: Dashboard `17`;
  target `18` (the Task 9 evidence commit is created after that read-only preview)
- Task 9 handoff commit: this record and its three cross-boundary test edits are committed
  together; the resulting full SHA is recorded in the ignored Task 9 execution report
  immediately after commit creation

## Task commits

- Task 1: `0e6cef415654df35fea6c7474bb3297a43d09d67`
- Task 2: `f4db33b39a1f390fd59314eff3fb109181219bbb`,
  `437c51e3c9a62d0f27681978bda87e0f9a8c1c15`
- Task 3: `bc1f242da2db166ce106c99f23eb6db623c639fd`,
  `d7980a4d6648f28d89793b95ed67c1caeb1be86f`
- Task 4: `d1a2c3cfb1795375554552527cac21bfa1cab97a`
- Task 5: `460330fd4265ee1f353aa7d52136c9bc18135ed8`,
  `98c237460ba2e117454cb4953e461ff56f240bb2`
- Task 6: `570c7c9a731e83a59b1e197cbb18605483563d04`,
  `5cf0ef83f8d98e19088030c496d7c9080b93db02`
- Task 7: `bdada2368b5d36a7cbdcb25a81ed25e0cb6d91a0`,
  `a49dce28919dbaf1110023956fc7ff492e907ee7`
- Task 8: `acb428138055efd8f08b372970e64b4bdb741427`,
  `3e08446502a615e314c6a7987f6636012b3a4695`,
  `d8e7a09d4464c7f8ebd4d28c6d648c480673fd9f`
- Task 9: accepted-exception evidence commit containing this review and the three named
  test changes; exact full SHA recorded after commit creation in the ignored execution
  report

The preceding design and plan commits are
`bc983f0807e177f8b2643333448e9455bdea891c` and
`3e35fd5825674f4cf527359c4a34a360f565abbe`.

## Verification evidence

### Focused closure gate

```bash
./.venv-alpha/bin/python -m pytest -q tests/dashboard tests/api/test_alpha_app.py tests/api/test_runtime.py
node --test tests/frontend/*.test.mjs
```

- Python: `143 passed`, `0 failed`, one pre-existing Starlette/AnyIO deprecation
  warning; the final pre-commit rerun completed in `2.33s`.
- Node: `130 passed`, `0 failed`, `0 skipped`.
- The new cross-boundary coverage proves all five Dashboard API paths authenticate
  before provider access and return `no-store`; all four new local assets authenticate
  before file reads and return `no-store`; the page has one live source, four Tabs, no
  raw status preformatted block, no external resource URL, no legacy auto-mount script,
  and the required local script order.
- The existing compatibility tests remain present and green for the legacy incident
  303 target, test notification, snapshot, HD tickets, disabled PTZ and gauge
  calibration. The strengthened legacy hash regression selects Alerts and highlights
  only `environment:incident-1`.
- The `320px` and `390px` static contracts find the `max-width: 720px` breakpoint,
  four equal Tab columns, `44px` controls, border-box sizing, a viewport-bounded shell,
  and no page-level fixed pixel width wider than either viewport.
- Provider-failure sentinels for database/path, exception class, stream list, token,
  topic, confidence, rule version and evidence key do not enter Dashboard responses.

### Full software gate

```bash
./.venv-alpha/bin/python -m compileall -q apps packages services tools
./.venv-alpha/bin/python -m pytest -q
node --test tests/frontend/*.test.mjs
git diff --check
```

- `compileall`: exit `0`.
- Full Python: **accepted owner-authorized executor-infrastructure exception**, exit `1`;
  `2412 passed`, `1 expected skip`, `1 failed`, one warning, in `52.21s`.
- Exact failure:
  `tests/tools/test_private_remote_access.py::test_policy_acknowledgement_rejects_unix_socket`.
  The test fails at `socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)` with
  `PermissionError: [Errno 1] Operation not permitted`, before project code runs.
- The exact failing test was rerun and failed identically. Direct Unix-domain socket
  construction also failed under both the project interpreter and system Python,
  confirming an executor-policy limitation. The test was not modified, skipped,
  deselected or weakened.
- The owner accepted this exact exception and authorized continuation to integration and
  remote publication. This acceptance does not convert the command to green and does not
  assert that the complete Python command returned zero.
- Node rerun: `130 passed`, `0 failed`, `0 skipped`.
- `git diff --check`: exit `0`.

### Branch delta and privacy/artifact checks

The prescribed pre-Task9 committed branch scan from the merge base listed `25` planned
Dashboard source/test/spec/plan paths. The evidence commit adds only this bounded review
path; the plan and three tests were already in that planned path set. The committed and
final pre-commit deltas passed `git diff --check` and the exact high-signal scan for
access tokens, private-key headers, local home-directory paths, inline notification
tokens and camera-secret assignments. Filename scans found no tracked or untracked
image, audio, video, SQLite/database, key, profile or generated
runtime/settings/calibration artifact.

No real camera, household image/audio/video, private overlay, notification service,
production database, event/evidence writer, Baby Care writer or device-control path ran.
Tests used fakes, monkeypatched transports and pytest temporary data only. Camera Reply
remained `false`; the real PTZ path remained disabled; no real notification and no
production/household write occurred.

## Read-only integration preview

```bash
git fetch origin
git for-each-ref --format='%(refname:short) %(objectname)' refs/remotes/origin/codex/ | sort
base=$(git merge-base HEAD origin/codex/visual-regression-corpus)
git log --left-right --cherry-pick --oneline "$base"...HEAD
git log --left-right --cherry-pick --oneline "$base"...origin/codex/visual-regression-corpus
git merge-tree "$base" HEAD origin/codex/visual-regression-corpus > /tmp/dashboard-merge-tree.txt
rg -n '^(<<<<<<<|=======|>>>>>>>)' /tmp/dashboard-merge-tree.txt || true
```

- Fetch: exit `0`; the exact target did not advance.
- Merge base: `cabd4cf10e35a4aa9877a9b3c9a1e8692818948d`.
- Left/right count: Dashboard `17`, target `18`.
- Merge-tree output: `4855` lines; conflict markers: `0`.
- Exact conflict paths: none.
- `apps/api/alpha.py`: no conflict; target has no post-base change to this path.
- `apps/api/runtime.py`: no conflict; target has no post-base change to this path.
- `SUMMARY.md`, `docs/STATUS.md`, `docs/CHECKPOINT.md`, `docs/NEXT.md`: no conflict;
  they changed only on the target side and were deliberately not edited by this task.
- No other Codex ref was treated as an integration target.

## Software proof and remaining gates

Software evidence covers the four-Tab structure, closed authenticated APIs, read-only
Dashboard queries, deterministic alert projections, bounded `24h`/`7d` analytics,
stale-data behavior, media-node lifecycle regressions, keyboard/ARIA behavior, local
assets, static responsive constraints and redacted failure responses.

It does not prove real MJSXJ17CM/CS2 compatibility, camera or Guardian accuracy,
household scene accuracy, real notification delivery, installed-i9 readiness, two-phone
delivery, 320px/390px rendering on a physical iPhone, iPhone network quality, sustained
performance, infant safety or safe unattended care. A real-device/iPhone visual smoke
gate remains required under separate authorization and continuous adult supervision.

## Pre-integration flags at evidence-commit time

```text
owner_exception_accepted=true
push_authorized=true
push_performed=false
pr=false
merge_performed=false
rebase=false
cherry_pick=false
main_changed=false
stable_changed=false
task9_evidence_commit=true
```

Next action: independently review this evidence commit, verify that the exact target ref
has not advanced, merge into `codex/visual-regression-corpus`, rerun the available gates
on the integrated tree, and push the owner-authorized target ref. A future run in an
executor that permits Unix-domain sockets should close the one deliberately unchecked
full-Python-zero plan assertion.

## Post-integration closure

The Dashboard line, including final review fix `5271449`, was merged with target
`fd7af067` as `2d0f2cc6d0b934ba4a81067133f7a823dfa6ec5e` and pushed by ordinary
fast-forward to `origin/codex/visual-regression-corpus`. A fresh exact-head run in a
macOS context that permits AF_UNIX fixtures closed the earlier infrastructure
exception: full Python passed `2497` tests with one expected
`visual_corpus_first_stage_incomplete` skip; frontend passed `132`; compilation and
`git diff --check` also passed. The worktree and remote were clean and equal. No PR,
protected-branch change or real-device access was performed by this closure.
