# Visual Regression Corpus READY and Baseline Closure Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use
> `superpowers:subagent-driven-development` (recommended) or
> `superpowers:executing-plans` to implement this plan task-by-task. Steps use checkbox
> (`- [ ]`) syntax for tracking.

**Goal:** Admit one reproducible, licensed real empty crib/room-wide source segment that
honestly covers both `WIDE-02` and `NEG-01`, move the fixed visual corpus from
`PARTIAL` to `READY`, replay the complete corpus, and explicitly promote its first
reviewed observational baseline.

**Architecture:** Preserve the 13-clip corpus and all existing replay boundaries.
Separate source admission from code and manifest changes: a candidate must first pass
license, direct-download, checksum, duration and frame-review gates. Once admitted, one
`WIDE-02` clip may carry both scenario IDs; replay results expose scenario groups so
baseline promotion measures complete scenario coverage without duplicating the same
media as a second clip.

**Tech Stack:** Python 3.11+, Pydantic 2, pytest, JSON, urllib, hashlib,
ffmpeg/ffprobe, existing `VisualCorpusReplay`, existing isolated go2rtc codec gate,
Make.

**Spec:** `docs/superpowers/specs/2026-08-28-visual-regression-corpus-design.md`

**Predecessor plan:**
`docs/superpowers/plans/2026-08-28-visual-regression-corpus.md`

**Published starting point:**
`codex/visual-regression-corpus@4c511203e568e428460fc69dc47ebe86e80ed168`

**Status:** Continuation plan recorded; execution has not started. The current authority
is docs-only. Source acquisition, code/manifest changes, baseline promotion, commits and
remote operations each require the authority stated by the executing user turn.

## Global Constraints

- Keep `main` and `stable/xiaomi-alpha` unchanged. Never merge, rebase, force-push,
  create a PR, tag or publish unless the current user turn explicitly permits it.
- Do not modify Voice, Camera Reply, Xiaomi producer lifecycle, PTZ, audio, WS2021,
  Baby Care, notifications, Guardian thresholds, prompts or model selection.
- Tests use generated, synthetic or explicitly public media only. Household video,
  room layout, camera frames and private recordings are prohibited.
- Downloaded media, thumbnails, contact sheets, prepared artifacts, results and
  temporary databases remain under ignored owner-private runtime with directories
  mode `0700` and files mode `0600`.
- Never put media, credentials, cookies, account tokens, private paths or runtime state
  in Git, command arguments, ordinary logs, chat or status documents.
- Do not bypass YouTube/Vimeo verification, reuse browser cookies, automate an account,
  record a screen, capture a protected stream or use an undocumented media endpoint.
- A thumbnail, still image, slide, title card, repeated frame, looped 9.6-second clip,
  interpolation, synthetic scale or composited background cannot satisfy the real-wide
  gate.
- The qualifying source must have an explicit primary license, commercial and research
  use allowed, a stable non-interactive HTTPS file, exact byte length not exceeding
  128 MiB, SHA-256, and a total first-stage source budget not exceeding 256 MiB.
- The admitted interval must contain at least ten continuous source seconds after title
  and transition removal, with real `crib_wide` or `room_wide` framing, no baby,
  no adult, `wide_content_role=empty_or_object_only`, and an honestly empty crib/room
  for `NEG-01`.
- One reviewed source segment may carry `scenario_ids=["WIDE-02","NEG-01"]`.
  Do not duplicate the same frames under two clip IDs to inflate diversity.
- `safe`, `needs_review` and `risk_candidate` remain observational model output,
  never objective ground truth or a reason to rewrite labels.
- The manifest stays `PARTIAL` and no baseline command runs unless every admission
  condition passes. An unavailable source is a valid closed outcome.
- Camera access, installed go2rtc, launchd, production SQLite and household inference
  are outside this plan. The codec gate uses only a temporary loopback process and a
  prepared public file.
- This remains the public READY plan. The proposed private overlay at
  `docs/superpowers/plans/2026-08-29-private-local-visual-corpus-overlay.md` has a
  separate `LOCAL_READY` state and cannot unlock this plan's G1–G6 public gates.

---

## Current evidence and decision model

### Observations

- The published corpus contains 13 clips and 26 prepared artifacts.
- `OCC-03` and `NEG-02` are covered.
- Only `WIDE-02` and `NEG-01` remain missing.
- Thirteen-clip replay passed 825/825 frames; the isolated 2560x1440 HEVC gate passed.
- The 30-minute result belongs to the earlier 11-clip corpus and cannot be relabelled as
  13-clip or future READY evidence.
- The current baseline promotion contract requires every scenario name as a separate
  clip ID even though the approved spec allows one clip to cover multiple scenarios.

### Hypothesis

One real licensed empty crib/room-wide segment can close both remaining scenarios.
Scenario-group propagation can then reconcile baseline promotion with the existing
multi-scenario manifest contract without creating duplicate media entries.

### Decision

Search only bounded new source candidates. If none passes, append one rejection
checkpoint and stop with `PARTIAL`. If one passes, first prove the multi-scenario
promotion behavior with RED tests, then make the smallest contract/replay change, admit
one `WIDE-02` clip, and proceed through READY, replay and explicit promotion gates.

### Outcome boundary

A promoted baseline proves repeatable behavior for the fixed public corpus. It does not
prove model accuracy, native Xiaomi CS2, physical IR equivalence, household transfer,
real-baby safety or unattended care.

## Known-source stop ledger

Do not retry an entry unless the stated re-open condition becomes externally observable.
Record that changed fact before downloading anything.

| Source | Current decision | Re-open only when |
|---|---|---|
| Pexels `7509178`, `7508454`, `7509174`, `7509180` | Adult/baby present in usable wide interval | A different source revision or a newly published exact time range is available |
| Pexels/Pixabay `854376` | Crib/toy close-up, not wide | A different full media revision changes framing |
| Pexels `3676819` | 3.88 seconds and not room-wide | A distinct source file is at least ten continuous seconds and real-wide |
| NICHD `O2cHch-uKZQ` | Interview/baby-close footage | A distinct official source file contains a qualifying empty-wide interval |
| NICHD `29sLucYtvpA` | Adult clears crib and immediately places baby | A distinct official edit exposes ten continuous empty-wide seconds |
| Coverr empty nursery candidate | 9.6 seconds; current media endpoint returned 404 | A stable licensed full file is at least ten continuous seconds |
| Mixkit childcare-bed candidate | Personal-use-only license | The primary license explicitly permits project research and commercial use |
| CPSC `VNekf5P9_Yg`, `UGFvlRQFY30` | Interactive YouTube verification; thumbnails only | CPSC or an authorized mirror exposes a stable, non-interactive full file with clear reuse rights |
| Safe Sleep NC Vimeo `17528273` | Public connection reset before metadata/media | A stable authorized full-file endpoint and license evidence are available |
| CDC SIDS Safe Sleep, SHA-256 `38f0061f4aee91bf3dd883fcc40c396fbeb936a090c9e60bfe8d5e8cb8a228aa` | Already reviewed; presenters/demonstration, no qualifying interval | A different checksum-pinned official revision contains a qualifying interval |
| CDC Beyond the Data / Zika candidates | Studio/general footage, not empty crib-wide | A distinct official source file meets every content gate |

## File and interface map

- `docs/CHECKPOINT.md`: append bounded source decisions and actual gate evidence.
- `tests/fixtures/visual_corpus/manifest.json`: declare the admitted source and one
  reviewed `WIDE-02` clip with both remaining scenario IDs.
- `tests/fixtures/visual_corpus/source/licenses.json`: record primary license evidence.
- `tests/fixtures/visual_corpus/source/checksums.json`: record exact file identity.
- `tests/fixtures/visual_corpus/README.md`: document READY coverage without media.
- `services/vision/corpus_replay.py`: project controlled scenario IDs into comparison
  groups.
- `services/vision/corpus_baseline.py`: require complete scenario groups instead of
  requiring duplicate clip IDs.
- `tools/visual_corpus.py`: add the admitted clip to the fixed replay selection.
- `tests/contracts/test_visual_corpus.py`: protect source/manifest admission.
- `tests/vision/test_first_stage_visual_corpus.py`: prove READY and real-wide coverage.
- `tests/vision/test_corpus_replay.py`: prove deterministic scenario groups.
- `tests/vision/test_corpus_baseline.py`: prove multi-scenario promotion and closed
  incomplete candidates.
- `tests/tools/test_visual_corpus.py`: keep fixed CLI selection identical to manifest.
- `tests/fixtures/visual_corpus/baselines/visual-baseline.v1.json`: first explicitly
  reviewed observational baseline, created only at Task 5.
- `SUMMARY.md`, `docs/STATUS.md`, `docs/CHECKPOINT.md`, `docs/NEXT.md`: factual
  handoff after each stopping point.

## Stage gates

| Gate | Entry | Exit | Stop condition |
|---|---|---|---|
| G0 source review | Published clean `4c511203` | One PASS admission record | No candidate satisfies all source/content rules |
| G1 contract RED/GREEN | G0 PASS | Multi-scenario replay/promotion tests pass | A change would weaken source or promotion rules |
| G2 corpus READY | G1 PASS | Manifest READY, 14 clips, zero missing scenarios | Download, checksum, probe or label mismatch |
| G3 short replay | G2 PASS | 14/14 complete candidate and codec PASS | Any decode, worker, model, drop or backlog failure |
| G4 sustained replay | G3 PASS | Fresh 30-minute READY aggregate PASS | RSS growth above 256 MiB, error, duplicate or backlog |
| G5 baseline review | G3 and G4 PASS | Owner approves exact candidate digest | Missing review or any ambiguous aggregate |
| G6 promotion/closure | G5 approved | Baseline promoted, compare/full gates PASS | Digest mismatch, existing baseline or incomplete groups |

### Task 1: Bounded real empty-wide source admission

**Files:**
- Modify only on REJECT: `docs/CHECKPOINT.md`
- No tracked manifest, code or test change before PASS.

**Interfaces:**
- Consumes: the fixed admission policy and known-source stop ledger above.
- Produces: one immutable PASS record with `source_id`, primary page, direct HTTPS
  file URL, license, reuse decisions, exact bytes, SHA-256, reviewed start/end
  milliseconds, objective labels and review confidence; or one bounded REJECT record.

- [ ] **Step 1: Reconfirm exact starting state**

Run:

```bash
git branch --show-current
git rev-parse HEAD
git status --porcelain=v1
git ls-remote --heads origin refs/heads/codex/visual-regression-corpus
```

Expected: branch `codex/visual-regression-corpus`, local and remote at
`4c511203e568e428460fc69dc47ebe86e80ed168`, and no tracked changes before the task.

- [ ] **Step 2: Review one bounded candidate batch**

Review at most eight new primary source pages and download at most three full files.
Exclude every stop-ledger entry unless its exact re-open condition is documented first.
Reject account/login/cookie/verification paths without attempting a bypass.

For each complete file, record only public metadata and aggregate frame-review facts.
Keep the file and contact sheet under `runtime/test-corpus/visual/research/` with owner-
private permissions; never write media or local paths to tracked documents.

- [ ] **Step 3: Apply the source and content gate**

A PASS candidate must satisfy all Global Constraints and must remain empty-wide for one
half-open interval of at least 10,000 ms. Review that interval at no coarser than
500 ms sampling and check its beginning and end frames separately. Reject title cards,
cuts, fades, temporary adult hands, baby entry, close framing and fake scale.

- [ ] **Step 4: Stop honestly when no candidate passes**

If the batch has no PASS candidate, append one aggregate checkpoint listing public IDs,
fixed rejection reasons and whether any stop-ledger fact changed. Run:

```bash
../../.venv-alpha/bin/python -m pytest -q tests/contracts/test_visual_corpus.py tests/tools/test_visual_corpus.py tests/vision/test_corpus_baseline.py
make PYTHON=../../.venv-alpha/bin/python alpha-visual-corpus-validate
git diff --check
```

Expected: focused tests pass, readiness remains `PARTIAL`, clip count remains 13,
missing scenarios remain 2, and no replay/baseline command runs. Stop this plan here.

- [ ] **Step 5: Freeze the PASS admission record**

Before editing the manifest, record the exact public facts and the reviewed interval.
The record must prove `framing=crib_wide|room_wide`,
`baby_visibility=not_visible`, `adult_visibility=absent`,
`object_state=empty`, and `wide_content_role=empty_or_object_only`.

### Task 2: Reconcile multi-scenario clips with baseline promotion

**Files:**
- Modify: `services/vision/corpus_replay.py`
- Modify: `services/vision/corpus_baseline.py`
- Modify: `tests/vision/test_corpus_replay.py`
- Modify: `tests/vision/test_corpus_baseline.py`

**Interfaces:**
- Consumes: `VisualCorpusClip.scenario_ids`.
- Produces: deterministic `scenario:<ScenarioId>` comparison groups and a promotion
  gate requiring all 15 scenario groups across 10 to 20 unique replay results.

- [ ] **Step 1: Write replay-group RED**

Add a replay test whose one clip has
`scenario_ids=("WIDE-02", "NEG-01")`. Assert its groups include both
`scenario:WIDE-02` and `scenario:NEG-01` exactly once and in sorted order.

- [ ] **Step 2: Write promotion RED**

Add a baseline test with 14 unique replay results where the `WIDE-02` result contains
both missing scenario groups. Assert promotion succeeds only when all 15
`scenario:*` groups and all three mandatory wide-role groups exist. Keep separate
negative assertions for a missing scenario group, fewer than 10 results, more than 20
results and a missing empty-wide group.

- [ ] **Step 3: Run RED**

Run:

```bash
../../.venv-alpha/bin/python -m pytest -q tests/vision/test_corpus_replay.py tests/vision/test_corpus_baseline.py
```

Expected: the new scenario-group and 14-result promotion assertions fail against the
clip-ID-only implementation.

- [ ] **Step 4: Implement deterministic scenario groups**

In `_comparison_groups(clip)`, append
`scenario:<value>` for `clip.scenario_ids` sorted by enum value. Preserve every
existing framing, scale, lighting, visibility, wide-role and intersection group.

In `corpus_baseline.py`, replace the mandatory clip-ID set with the 15 mandatory
`scenario:*` groups, require `10 <= len(candidate.results) <= 20`, and preserve the
three mandatory wide-role groups, all-PASS requirement, expected digest, atomic write
and no-overwrite behavior.

- [ ] **Step 5: Run GREEN and adjacent gates**

Run:

```bash
../../.venv-alpha/bin/python -m pytest -q tests/vision/test_corpus_replay.py tests/vision/test_corpus_baseline.py tests/tools/test_visual_corpus.py
../../.venv-alpha/bin/python -m compileall -q services/vision tools
git diff --check
```

Expected: all affected tests pass and no existing comparison group disappears.

- [ ] **Step 6: Commit only when locally authorized**

Suggested commit:

```text
fix: align visual baseline with scenario coverage
```

Do not commit under docs-only authority and never push from this step.

### Task 3: Admit the one real-wide clip and move the manifest to READY

**Files:**
- Modify: `tests/fixtures/visual_corpus/manifest.json`
- Modify: `tests/fixtures/visual_corpus/source/licenses.json`
- Modify: `tests/fixtures/visual_corpus/source/checksums.json`
- Modify: `tests/fixtures/visual_corpus/README.md`
- Modify: `tools/visual_corpus.py`
- Modify: `tests/contracts/test_visual_corpus.py`
- Modify: `tests/vision/test_first_stage_visual_corpus.py`
- Modify: `tests/tools/test_visual_corpus.py`

**Interfaces:**
- Consumes: Task 1's immutable PASS record and Task 2's scenario-group contract.
- Produces: one reviewed `WIDE-02` source segment carrying
  `["WIDE-02","NEG-01"]`, a 14-clip `READY` manifest and fixed replay selection.

- [ ] **Step 1: Write manifest/selection RED**

Update first-stage tests to require `readiness=READY`, 14 unique clip IDs, every
`ScenarioId`, at least three real wide clips and all three wide roles. Require the
`WIDE-02` record to carry both remaining scenarios and the exact empty-wide labels
from Task 1. Keep the tracked-media prohibition unchanged.

Run:

```bash
../../.venv-alpha/bin/python -m pytest -q tests/contracts/test_visual_corpus.py tests/vision/test_first_stage_visual_corpus.py tests/tools/test_visual_corpus.py
```

Expected: RED because the tracked manifest is still `PARTIAL` with 13 clips.

- [ ] **Step 2: Add exact source identity**

Copy Task 1's PASS facts into the manifest source record and the two source ledgers.
Use `download_method=DIRECT_HTTPS`, exact bytes and lowercase SHA-256. Keep
`github_allowed=false` and `local_only=true` even if redistribution is legally
allowed.

- [ ] **Step 3: Add the reviewed clip**

Create exactly one `clip_id=WIDE-02` source segment with both scenario IDs, exact
reviewed start/end milliseconds, `source_type=PUBLIC_DATASET`,
`recipe.kind=SOURCE_SEGMENT`, `label_provenance=frame_review`,
`review_state=reviewed`, and the objective labels frozen in Task 1. Set manifest
`readiness=READY`.

- [ ] **Step 4: Extend fixed replay selection**

Insert `WIDE-02` into `FIRST_STAGE_CLIP_IDS` in manifest order. Do not add a
duplicated `NEG-01` clip. Preserve the test that the tuple exactly equals the tracked
manifest clip order.

- [ ] **Step 5: Run GREEN and deterministic preparation**

Run:

```bash
../../.venv-alpha/bin/python -m pytest -q tests/contracts/test_visual_corpus.py tests/vision/test_first_stage_visual_corpus.py tests/tools/test_visual_corpus.py tests/vision/test_corpus_prepare.py
make PYTHON=../../.venv-alpha/bin/python alpha-visual-corpus-validate
make PYTHON=../../.venv-alpha/bin/python alpha-visual-corpus-prepare
```

Expected: validation reports `readiness=READY`, `clip_count=14`,
`missing_scenarios=0`; preparation verifies the new full source and publishes/reuses
28 private artifacts without tracking media.

- [ ] **Step 6: Commit only when locally authorized**

Suggested commit:

```text
test: admit real empty-wide visual corpus clip
```

Do not commit under docs-only authority and never push from this step.

### Task 4: Complete short replay, codec and sustained gates

**Files:**
- Runtime only: `runtime/test-corpus/visual/results/`
- No baseline file in this task.

**Interfaces:**
- Consumes: the READY 14-clip manifest and prepared artifacts.
- Produces: a private candidate result, exact candidate digest, fresh codec result and
  fresh 30-minute aggregate.

- [ ] **Step 1: Run complete short replay**

Run:

```bash
make PYTHON=../../.venv-alpha/bin/python alpha-visual-regression
```

Expected: 14/14 clips PASS with zero decode, worker, dropped-frame and queue-backlog
errors. Record the exact candidate SHA-256 and bounded aggregate metrics.

- [ ] **Step 2: Run isolated HEVC gate**

Run:

```bash
make PYTHON=../../.venv-alpha/bin/python alpha-visual-corpus-codec-gate
```

Expected: local prepared 2560x1440 HEVC decode PASS,
`camera_accessed=false`, `production_service_touched=false`; an unavailable local
encoder/binary is an explicit SKIP, not a camera test.

- [ ] **Step 3: Run fresh READY 30-minute gate**

Run:

```bash
make PYTHON=../../.venv-alpha/bin/python alpha-visual-regression-long
```

Expected: at least 1,800 media seconds, zero decode/worker/backlog/duplicate errors and
RSS growth no greater than 256 MiB. Do not reuse the earlier 11-clip result.

- [ ] **Step 4: Record evidence without promoting**

Append exact clip/frame/run counts, p50/p95/max, candidate digest, codec outcome, RSS,
error counts and what the evidence does not prove to `docs/CHECKPOINT.md`. Keep the
candidate private. Stop on any FAIL or ambiguous result.

### Task 5: Review and explicitly promote the first baseline

**Files:**
- Create: `tests/fixtures/visual_corpus/baselines/visual-baseline.v1.json`
- Runtime input: `runtime/test-corpus/visual/results/visual-candidate.json`

**Interfaces:**
- Consumes: Task 4's exact private candidate digest and reviewed aggregate.
- Produces: one immutable canonical tracked baseline and a PASS self-comparison.

- [ ] **Step 1: Review candidate completeness**

Verify all 14 results are PASS; the result set contains all 15 `scenario:*` groups,
all three mandatory wide roles, matching manifest/recipe/profile/model identities, and
zero operational failures. Review the `WIDE-02` objective labels against Task 1's
record. Do not use Guardian inference as ground truth.

- [ ] **Step 2: Obtain explicit digest approval**

Report the exact 64-character candidate SHA-256 and bounded metrics to the user. Stop
until the user explicitly approves promotion of that digest. Approval to execute prior
tasks is not baseline-promotion approval.

- [ ] **Step 3: Promote exactly the approved digest**

Run:

```bash
test "${#BASELINE_SHA256}" -eq 64
make PYTHON=../../.venv-alpha/bin/python BASELINE_SHA256="$BASELINE_SHA256" alpha-visual-regression-promote
```

Before running, set `BASELINE_SHA256` in the operator shell to the exact digest
approved in Step 2; do not substitute a newer candidate. Expected: one canonical
baseline file and matching
`baseline_sha256`. Digest mismatch, incomplete scenarios, missing wide group or an
existing destination fails closed.

- [ ] **Step 4: Compare against the promoted baseline**

Run:

```bash
make PYTHON=../../.venv-alpha/bin/python alpha-visual-regression-compare
```

Expected: `PASS`, zero regression count and 14 compared clips.

- [ ] **Step 5: Commit only when locally authorized**

Suggested commit:

```text
test: promote first visual regression baseline
```

Do not commit or push without the current user's explicit authority.

### Task 6: Full verification, handoff and retrospective

**Files:**
- Modify: `SUMMARY.md`
- Modify: `docs/STATUS.md`
- Modify: `docs/CHECKPOINT.md`
- Modify: `docs/NEXT.md`
- Modify: this plan to mark only actually completed checkboxes.

**Interfaces:**
- Consumes: exact software/runtime evidence from Tasks 1-5.
- Produces: a factual READY/baseline checkpoint and the next one-change optimization
  entry, without changing model behavior.

- [ ] **Step 1: Run focused and full software gates**

Run:

```bash
../../.venv-alpha/bin/python -m pytest -q tests/contracts/test_visual_corpus.py tests/vision/test_corpus_storage.py tests/vision/test_corpus_download.py tests/vision/test_corpus_prepare.py tests/vision/test_first_stage_visual_corpus.py tests/stream/test_file_frame_source.py tests/vision/test_corpus_replay.py tests/vision/test_corpus_guardian_projection.py tests/vision/test_corpus_baseline.py tests/tools/test_visual_corpus.py tests/tools/test_visual_corpus_codec_gate.py
../../.venv-alpha/bin/python -m pytest -q
node --test tests/frontend/*.test.mjs
../../.venv-alpha/bin/python -m compileall -q packages services tools
make -n alpha-visual-corpus-validate alpha-visual-corpus-prepare alpha-visual-regression alpha-visual-regression-compare alpha-visual-regression-promote alpha-visual-regression-long alpha-visual-corpus-codec-gate
../../.venv-alpha/bin/python -m json.tool tests/fixtures/visual_corpus/manifest.json >/dev/null
git diff --check
```

Expected: focused/full/frontend/compile/JSON/Make/diff gates pass and
`visual_corpus_first_stage_incomplete` is absent. Record actual counts; never copy
counts from this plan.

- [ ] **Step 2: Run privacy and tracked-artifact review**

Review the complete branch diff and prove that Git contains no downloaded/generated
media, runtime result, SQLite database, model, private address, credential, token,
cookie, key or generated settings. Confirm ignored research artifacts are not staged.

- [ ] **Step 3: Update factual handoff documents**

Record exact branch/head, source/license decision, READY clip/scenario count, replay,
codec, sustained, baseline digest, compare result, test counts, privacy result, remote
state and unverified real-device risks. Separate observations, hypotheses, decisions
and outcomes.

- [ ] **Step 4: Define the next optimization entry**

The next visual optimization must change one approved component only and compare the
same READY corpus/profile against `visual-baseline.v1.json`. It requires a separate
design/authorization and must preserve deterministic Guardian ownership. Do not begin
that optimization in this plan.

- [ ] **Step 5: Final delivery review**

Run:

```bash
git status --short --branch
git diff --stat 4c511203e568e428460fc69dc47ebe86e80ed168
git log --oneline --decorate -12
```

Report local/remote identities separately. Push only the approved feature branch if a
later user turn explicitly authorizes it; never create a PR or merge implicitly.

## Current exact next action

Wait for explicit source-search execution authority. Then execute Task 1 only. A
bounded REJECT is a complete valid result and leaves the corpus at `PARTIAL`; a PASS
unlocks Task 2. Do not pre-implement the scenario-group change or touch the manifest
before a source passes.

The private-overlay proposal is a separate review queue. Reviewing or later
implementing it does not count as a public Task 1 PASS and does not authorize capture,
manifest edits, replay or baseline operations under this plan.
