# Baby Monitor Ordered Delivery Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans for
> the current software-only stage. Do not dispatch overlapping work across the scenario,
> Voice, Camera Reply or private-capture boundaries. Steps use checkbox (`- [ ]`) syntax
> for tracking.

**Goal:** Finish the remaining Baby Monitor Local work in dependency order without
reopening completed milestones, weakening safety gates or treating software evidence as
real-device acceptance.

**Architecture:** Use the latest published feature history as one read-only evidence
base, but execute each remaining subsystem through its own approved specification and
plan. Software-only expansion comes first; adult-supervised Voice, Camera Reply,
household capture and the final release gate remain separate transitions with explicit
stop lines.

**Tech Stack:** Python 3.11+, Pydantic 2, pytest, Node test runner, ffmpeg/ffprobe,
OpenVINO 2025.4.1, go2rtc Xiaomi MISS/CS2, macOS launchd and Git.

**Specs:**

- `docs/superpowers/specs/2026-08-29-offline-guardian-scenario-expansion-design.md`
- `docs/superpowers/specs/2026-08-27-voice-care-multi-intent-asr-optimization-design.md`
- `docs/superpowers/specs/2026-08-26-xiaomi-camera-reply-lifecycle-design.md`
- `docs/superpowers/specs/2026-08-29-private-local-visual-corpus-overlay-design.md`
- `docs/superpowers/specs/2026-08-04-baby-monitor-local-design.md`

## Global Constraints

- Start from `origin/codex/visual-regression-corpus` at or after exact reviewed base
  `7cf8d023f706f3a77d0835916854dfd4db450a64`; preserve a newer remote head and stop on
  divergence instead of resetting, rebasing or force-pushing.
- Protect `main` and `stable/xiaomi-alpha`. Do not create or merge a PR, tag a release,
  force-push, delete a branch or rewrite history without separate authority.
- Keep one external Xiaomi producer and `transport=auto`. Never force UDP/TCP, create a
  second camera connection, call PTZ or restart the whole Alpha stack for one component.
- Keep `camera_reply_enabled=false` except inside a separately approved, adult-supervised
  Camera Reply matrix with an immediate rollback path.
- Never persist household frames, audio, transcripts, local paths, addresses, tokens,
  device keys or model prose. Generated/public fixtures are the only inputs for
  software-only stages.
- Baby Monitor may classify closed care actions but must not construct a Baby Care
  writer, signer or outbox in this plan. No action recognition is a care-record write.
- Medication remains outside the low-risk acceptance path. Do not acknowledge, correct,
  infer or write medication start/completion without a separate high-risk design.
- Every implementation slice uses RED -> GREEN, a focused commit and factual checkpoint.
  A later stage never converts an earlier failed gate into PASS.

---

## Current evidence checkpoint

The ordered plan begins from these verified repository facts:

| Area | Evidence already present | State carried forward |
|---|---|---|
| Visual public corpus | 13 reviewed clips; 825/825 replayed frames | `PARTIAL`; `WIDE-02` and `NEG-01` missing; no baseline |
| Private visual overlay | Software Tasks 1-7 through `f37ae57` | No household capture; no real descriptor; no `LOCAL_READY` |
| Offline scenario flow | Four scenarios, seven lanes, 165/165 frames through `b174f94` | Software-complete; eight-scenario expansion next |
| Multi-action Voice | Tasks 1-7 through `df7b762`; low-risk generated 18/18 and negatives 48/48 | Feeding/diaper/burping remain Listen-only; medication blocked |
| Camera Reply lifecycle | Software through Task 16; clean isolated reply evidence followed by failed V3E Task 17 | Production flag false; full matrix not accepted |
| Stable release | `stable/xiaomi-alpha@0df20aed` | Feature work is not merged or released |

Repository documentation has one historical branch mismatch: the Camera Reply branch
tip predates later device evidence already contained in the visual branch history. The
latest descendant base is authoritative for continuation; do not rerun a completed
device step merely because an older branch copy of `docs/NEXT.md` still says it is
waiting.

## Stage 0: Establish one exact continuation baseline

**Files:**

- Read: `AGENTS.md`
- Read: `SUMMARY.md`
- Read: `docs/STATUS.md`
- Read: `docs/CHECKPOINT.md`
- Read: `docs/NEXT.md`
- Read: this plan and the detailed Stage 1 plan

**Interfaces:**

- Consumes the remote feature ref and existing worktree state.
- Produces one clean isolated implementation worktree with no silent merge, reset or
  protected-branch mutation.

- [x] **Step 1: Fetch and prove the exact remote base**

```bash
git fetch --prune --no-tags origin
git ls-remote origin refs/heads/codex/visual-regression-corpus
git rev-parse origin/codex/visual-regression-corpus
git merge-base --is-ancestor 0d2588733fc5ab947aaf85df11725c1ba652928a origin/codex/visual-regression-corpus
```

Expected: the branch exists, the first two SHA values match, and the Camera Reply/
multi-action checkpoint is an ancestor. If the remote is newer than the plan's reviewed
base, inspect the new commits before continuing.

- [x] **Step 2: Protect existing worktrees**

```bash
git status --short --branch
git worktree list --porcelain
```

Expected: the selected implementation worktree is clean. Any tracked or untracked user
change is a stop condition; do not clean, reset, checkout over or move it.

- [x] **Step 3: Run the software-only baseline**

```bash
../../.venv-alpha/bin/python -m pytest -q \
  tests/contracts/test_offline_guardian_scenario.py \
  tests/integration/test_offline_guardian_scenario.py \
  tests/tools/test_offline_guardian_scenario.py \
  tests/voice/test_care_action.py \
  tests/voice/test_listen_only.py
git diff --check
```

Expected: zero failures and no diff errors. A missing local environment is reported as
`NOT_RUN` and resolved before implementation; an old recorded test count is not a
substitute.

**Stage exit:** exact base known, clean isolated worktree, focused baseline green.

## Stage 1: Implement the eight-scenario offline expansion

**Files:**

- Execute: `docs/superpowers/plans/2026-08-30-offline-guardian-scenario-expansion.md`
- Governed by:
  `docs/superpowers/specs/2026-08-29-offline-guardian-scenario-expansion-design.md`

**Interfaces:**

- Consumes only tracked public/generated fixtures and existing scenario/Voice/Guardian
  boundaries.
- Produces exactly eight scenarios, thirteen independent lanes, five visual clips and
  exact 330-frame accounting plus a private media-free report.

- [x] **Step 1: Execute detailed Tasks 1-6 with focused commits**

Use the detailed plan exactly. Do not change visual models, thresholds, Guardian rules,
Voice recognition thresholds or the public corpus manifest to obtain a pass.

- [x] **Step 2: Run the actual bounded public/generated flow**

```bash
../../.venv-alpha/bin/python tools/offline_guardian_scenario.py validate
../../.venv-alpha/bin/python tools/offline_guardian_scenario.py run
```

Expected: validation reports eight scenarios, thirteen lanes, five clips and 330
expected frames. The run must account for 330/330 frames with zero skipped, dropped,
decode-error or worker-error frames. Actual visual candidate counts remain observational.

- [x] **Step 3: Complete review and factual closure**

Run the detailed final gate, review the exact diff and update status documents only
with fresh evidence. Push only when the owner explicitly requests it.

**Stage exit:** software-only expansion passes or fails closed with a bounded reason;
no camera, speaker, notification, production database, household media or Baby Care
client was touched.

## Stage 2: Close the low-risk multi-action Voice decision

**Files:**

- Follow:
  `docs/superpowers/plans/2026-08-27-voice-care-multi-intent-asr-optimization.md`
- Update only after a fresh supervised decision:
  `docs/reviews/2026-08-27-voice-care-multi-intent-asr-optimization-resolution.md`
  and the four handoff documents.

**Interfaces:**

- Consumes the current Paraformer, closed action registry and aggregate-only counters.
- Produces a bounded decision for Feeding, diaper change and burping only; it does not
  write care data or authorize Camera Reply.

- [ ] **Step 1: Reconcile existing Task 8 evidence before any new run**

Carry forward the failed original recall matrix, the bounded combined-command fix and
its 4/4 installed recheck. Do not rerun the rejected ContextualParaformer/hotword A/B,
load invalid Whisper artifacts or enlarge edit-distance/tail-buffer policy.

- [ ] **Step 2: Stop for explicit adult-supervised authority**

No household microphone test runs unattended. Require the logged-in i9 owner, Camera
Reply false, Voice healthy/idle, one Xiaomi producer and fresh fixed counters.

- [ ] **Step 3: Execute only the remaining low-risk acceptance specified by Task 8**

Use the accepted combined single-sentence forms. Record fixed counts and failure codes
only. Any false accept, cross-action increment, duplicate response, source replacement
or unexpected output failure stops the gate.

- [ ] **Step 4: Publish a low-risk-only decision**

Mark Feeding, diaper and burping independently. Keep medication explicitly blocked and
keep Baby Care writes absent. A low-risk PASS does not resume Camera Reply automatically.

**Stage exit:** low-risk actions have an evidence-backed keep/rollback decision; high-risk
medication remains deferred.

## Stage 3: Diagnose and re-gate Camera Reply

**Files:**

- Follow:
  `docs/superpowers/plans/2026-08-26-xiaomi-camera-reply-lifecycle.md`
- Continue Task 17 only after its next behavior has a separately approved design.

**Interfaces:**

- Consumes the repaired generation-owned speaker lifecycle, finite-file drain and
  aggregate Voice transition counters.
- Produces either one clean V3E matrix or a stable failed-closed diagnosis; production
  remains on the i9 speaker until the full matrix passes.

- [ ] **Step 1: Keep Camera Reply disabled while designing the next correction**

The current evidence classifies four of five failed follow-ups as near-start text, not
reply echo and not far text. The next design may consider only a bounded affirmative
start-shaped armed follow-up after fixed particle removal, with explicit negation,
stop, cancel, question and adversarial rejection. Do not implement generic edit distance.

- [ ] **Step 2: RED/GREEN the approved correction in software**

Run the affected Voice, Camera Reply and pinned lifecycle tests plus compile, shell/Make,
diff and privacy gates. No camera speaker runs in this step.

- [ ] **Step 3: Stop for a new adult-supervised activation authority**

Before activation require one producer, `transport=auto`, healthy camera microphone,
zero pending/residual speaker state, a current marker and immediate flag rollback.

- [ ] **Step 4: Repeat the complete V3E matrix from zero counters**

Require five standalone wakes, three complete two-stage dialogues, three silent
timeouts and five non-wake controls. Any miss, movement, truncation, duplicate, timeout
outside the silent case, producer replacement or residual state fails the whole run.

**Stage exit:** only a clean matrix may support a later production-output decision.
Regardless of outcome, restore `camera_reply_enabled=false` before reporting.

## Stage 4: Resolve visual corpus readiness without lowering admission

**Files:**

- Public route:
  `docs/superpowers/plans/2026-08-29-visual-regression-corpus-ready-baseline.md`
- Private route:
  `docs/superpowers/plans/2026-08-29-private-local-visual-corpus-overlay.md`

**Interfaces:**

- Public route consumes a license-clear checksum-pinned real empty wide clip.
- Private route consumes fresh owner-supervised capture authority and keeps all media in
  ignored mode-`0700`/`0600` runtime.

- [ ] **Step 1: Prefer a qualifying public source when available**

Keep the bounded search/download limits and all recorded source rejects. One admitted
clip may carry both `WIDE-02` and `NEG-01`; do not duplicate it to satisfy counts.

- [ ] **Step 2: Stop for authority before any private capture**

Task 8 may capture at most two 20-30 second video-only candidates from the existing
shared producer and admit at most one. No PTZ, speaker, second producer or audio track.

- [ ] **Step 3: Keep public and private readiness separate**

Private `LOCAL_READY` never changes public `PARTIAL`. No baseline command runs until
the applicable route is reviewed and the exact baseline digest receives a separate
owner decision.

**Stage exit:** one route reaches its own honest readiness state without changing the
other or weakening the ten-second real-wide gate.

## Stage 5: Complete remaining device and release gates

**Files:**

- Follow the authoritative P0-P5 sections in `docs/NEXT.md` and the existing subsystem
  plans; do not create a replacement all-in-one runtime.

**Interfaces:**

- Consumes closed subsystem evidence.
- Produces final local-release evidence only after every required real-device gate.

- [ ] **Step 1: Finish deferred environment and Guardian observations**

Complete WS2021 darkness/infrared, glare, occlusion and movement fail-closed checks and
the supervised real-Baby normal-care observation when a Baby is available. Do not infer
real-scene accuracy from synthetic/public fixtures.

- [ ] **Step 2: Keep remote-access installation optional**

P4 software may remain complete without installing or exposing it. Never use Funnel or
router forwarding.

- [ ] **Step 3: Run the final 72-hour release gate**

Only after all local release prerequisites pass, run the fixed 72-hour gate across i9,
camera, M2, network, storage and approved phone checks. Earlier 10-minute/24-hour runs
do not substitute.

- [ ] **Step 4: Stop before integration**

Request explicit authority for PR, stable merge, tag or release publication. A passed
feature branch is not automatically a stable release.

## Required review checkpoints

| Checkpoint | Trigger | Required decision |
|---|---|---|
| R0 | Exact remote base changes | Inspect new commits or stop |
| R1 | Eight-scenario software gate ends | Keep/fix/rollback implementation without tuning models |
| R2 | Low-risk Voice device gate ends | Per-action keep/rollback; medication remains separate |
| R3 | Camera Reply software correction ends | Whether a supervised matrix is safe to authorize |
| R4 | Camera Reply V3E ends | Keep flag false or request a distinct production switch |
| R5 | Public/private visual readiness changes | Approve exact digest and route; never merge readiness states |
| R6 | 72-hour gate ends | Decide integration, tag and release separately |

## Current execution handoff

This publication resumes **Stage 1 software implementation only**. A local Codex should
read `AGENTS.md`, the five handoff documents, the approved expansion spec, this ordered
plan and `docs/superpowers/plans/2026-08-30-offline-guardian-scenario-expansion.md`, then
execute the detailed plan task-by-task. It must stop after the Stage 1 closure report.

Stages 2-5 remain queued. They are not implicit authority for household capture,
speaker activation, PTZ, Baby Care writes, installation, PR, merge, stable changes or
release publication.
