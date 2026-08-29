# Offline Guardian Scenario Expansion Design

**Date:** 2026-08-29

**Status:** Approved design; implementation paused by the owner. This document does
not authorize implementation while paused, camera or household-media access, model or
threshold changes, Camera Reply, PTZ, notification delivery, Baby Care writes, baseline
promotion, PR creation, merge or protected-branch changes.

## 1. Goal

Extend the accepted four-scenario offline flow to the existing suite limit of eight
scenarios. The extension adds repeatable evidence for `prone_candidate` Guardian
behavior, `outside_candidate` Guardian behavior and the already closed low-risk diaper
and burping Voice actions. It must preserve the separation between actual visual
observations and synthetic deterministic Guardian expectations.

The extension is a regression and integration test. It does not prove that the current
model recognizes real rollover, prone sleep, face covering, absence from bed or adult
intervention accurately.

## 2. Approaches and decision

The approved approach expands the current fixed scenario suite without changing any
production model, threshold or Guardian rule. Existing public/public-derived visual
fixtures exercise the real file replay and visual worker; separately declared semantic
timelines exercise deterministic Guardian behavior; generated PCM exercises the closed
Voice controller.

Two alternatives remain rejected:

- Using manifest labels as visual PASS ground truth would silently create a baseline
  while the public corpus remains `PARTIAL`.
- Tuning the model or thresholds before a fixed regression exists would overfit a small
  and incomplete corpus and could weaken fail-closed behavior.

## 3. Exact eight-scenario suite

The existing four scenarios remain unchanged in purpose:

- `SAFE-SLEEP-01`;
- `FACE-OCCLUSION-01`;
- `ADULT-INTERVENTION-01`;
- `VOICE-FEEDING-01`.

The expansion adds exactly four scenarios:

### 3.1 PRONE-CANDIDATE-01

- Visual observation uses admitted public clip `DAY-03` with
  `provenance=PUBLIC_VIDEO` and `analysis_realtime`.
- Its actual observation/candidate counts remain observational. The visual lane passes
  only pipeline, model-state, frame-accounting and privacy/isolation gates.
- A separate `SYNTHETIC_SEMANTIC_ORACLE` supplies two qualifying
  `prone_candidate` reviews ten seconds apart, one duplicate qualifying review and two
  explicit safe reviews ten seconds apart.
- Expected Guardian behavior is one watch, one alert, no duplicate event and one
  recovery for `prone_candidate`; final Dashboard state has one recovered event and no
  open event.
- The report must not describe `DAY-03` as a real rollover or prone-sleep example.

### 3.2 OUTSIDE-CANDIDATE-01

- Visual observation uses public-derived synthetic clip `OCC-03` with
  `provenance=GENERATED_VISUAL` and `analysis_realtime`.
- A separate oracle supplies two qualifying `outside_candidate` reviews, one duplicate
  review and two explicit inside/visible safe reviews.
- Expected Guardian behavior is one watch, one alert, no duplicate event and one
  recovery for `outside_candidate`; final Dashboard state has one recovered event and
  no open event.
- `OCC-03` is not a real household absence example and cannot validate bed-exit
  accuracy.

### 3.3 VOICE-DIAPER-01

- Generated mono PCM covers exact wake, exact `diaper_change_start`, a fresh exact
  wake, exact `diaper_change_complete` and all three negative classes in section 5.
- Expected output includes two wake-ready codes, acknowledgements for both target
  actions, correct classification of the legal cross-action control, and silence for
  ambiguous multi-action and no-wake controls.
- No transcript or PCM enters the result. No signer, outbox or Baby Care client exists.

### 3.4 VOICE-BURPING-01

- Generated mono PCM covers exact wake, exact `burping_start`, a fresh exact wake,
  exact `burping_complete` and all three negative classes in section 5.
- Expected output includes two wake-ready codes, acknowledgements for both target
  actions, correct classification of the legal cross-action control, and silence for
  ambiguous multi-action and no-wake controls.
- This proves only generated-fixture controller behavior, not Xiaomi microphone recall
  or real adult speech recognition.

## 4. Visual provenance correction

`OCC-02` is a tracked `SYNTHETIC` derivative of admitted public clip `DAY-02`; its
scenario provenance must be corrected from `PUBLIC_VIDEO` to `GENERATED_VISUAL`.

Scenario-to-manifest validation must enforce a one-level provenance rule:

- `PUBLIC_DATASET` clip -> `PUBLIC_VIDEO`;
- `SYNTHETIC` clip -> `GENERATED_VISUAL`, with exactly one non-null
  `parent_clip_id` whose parent is a direct `PUBLIC_DATASET` clip;
- that public parent must not itself have a parent;
- recursive ancestry, a synthetic parent, missing/duplicate parent, private-local,
  unsupported or provenance-mismatched clip -> fail before download, preparation,
  model construction or runtime-root creation.

The fixed CLI selects exactly five unique visual clips:

```text
DAY-01, OCC-02, NEG-03, DAY-03, OCC-03
```

Their three unique public source downloads total 25,964,039 declared bytes, below the
existing 128 MiB first-stage aggregate cap. The cap must not be raised.

At the fixed 5 FPS replay profile, the exact frame contract is:

```text
DAY-01  = 65
OCC-02  = 50
NEG-03  = 50
DAY-03  = 100
OCC-03  = 65
total   = 330
```

Every clip must report `frames.total == frames.processed` at its exact value and
`frames.skipped == frames.dropped == errors.decode == errors.worker == 0`. Any mismatch
fails the visual lane; these transport/accounting assertions do not make visual labels
ground truth.

## 5. Voice result contract

The existing generated Voice lane must add two optional closed expectations to every
step:

```text
expected_action_code: ActionCode | null
expected_match_kind: exact | corrected | high_risk_candidate | null
```

The lane must compare both values for every step, including wake and negative steps;
absence is represented only by `null`. A reason/response match with the wrong action or
match kind is `scenario_voice_mismatch`.

The result also adds bounded action-code counters so an acknowledgement cannot hide
cross-action classification:

```text
action.feeding_command
action.diaper_change_start
action.diaper_change_complete
action.burping_start
action.burping_complete
```

Only exact low-risk action matches may increment these counters. Corrected Feeding and
high-risk medication candidates retain their existing closed behavior; medication is
excluded from this expansion. Result contracts remain bounded and contain no text,
audio, paths, URLs, identifiers or model prose.

The three mandatory negative classes are:

1. **Legal cross-action control:** an exact low-risk command from the other tested
   action domain in one exact wake-with-command step. It is negative only for the
   scenario's target action. It must be acknowledged under its own
   `expected_action_code` with
   `expected_match_kind=exact`, and must not increment either target-action counter.
2. **Ambiguous multi-action control:** one wake-prefixed utterance containing two or
   more action domains. It must return `listen_only_ignored`, with no response, action
   code or match kind and no action counter increment.
3. **No-wake control:** one otherwise exact target action while the controller is idle,
   without a wake phrase. It must return `listen_only_ignored`, with no response,
   action code or match kind and no action counter increment.

The cross-action control for the diaper scenario is a burping action; the control for
the burping scenario is a diaper action. Questions, medication and unsupported commands
remain additional closed controls but cannot replace these three mandatory classes.
Each new Voice scenario therefore has exactly seven steps: standalone wake, target
start, standalone wake, target complete, legal cross-action wake-with-command,
ambiguous multi-action wake-with-command and no-wake target action. Its exact expected
response count is five: two ready codes, two target acknowledgements and one legal
cross-action acknowledgement.

## 6. Isolation and execution

The visual lane and Guardian lane have the explicit relationship `INDEPENDENT`.
Neither consumes, gates, rewrites or derives expectations from the other's result.
Scenario ID is their only join key, and aggregate status merely combines their separate
PASS/FAIL/SKIP states. A Guardian oracle PASS can never fill in a missing visual
candidate, and a visual observation can never create a Guardian event in this flow.

The extension reuses the accepted runner, whole-command 180-second deadline, fresh
Voice component factories, owner-private runtime and prepared-media validation, atomic
JSON/HTML report publication and six false isolation proofs.

It must not initialize or contact:

- Xiaomi authentication, CS2 or go2rtc;
- a camera microphone, browser microphone or speaker;
- Camera Reply, PTZ, Ollama or notification dispatch;
- production SQLite, evidence storage, Baby Care, signer or outbox.

The report remains ignored, media-free and mode `0600` below a mode-`0700` run root.
No baseline is generated, compared or promoted.

## 7. PASS and non-proof semantics

- Visual PASS means the fixed clip decoded and traversed the current visual pipeline
  within its software bounds. It is not an accuracy result.
- Guardian PASS means declared synthetic reviews produced the exact current rule,
  event, deduplication, recovery and Dashboard projection.
- Voice PASS means generated PCM and fixed ASR fixtures produced exact closed action
  outcomes, correctly self-classified the legal cross-action control and kept the
  ambiguous/no-wake controls silent.
- Aggregate PASS requires every required lane to pass.

The report and handoff must list actual visual candidate counts, including zero. A
missing rollover, obstruction or absence candidate is a model-capability observation;
it cannot be replaced by the Guardian oracle or converted into a success claim.

## 8. Failure handling

- Unknown scenario, wrong provenance, missing clip or unsafe public ancestry fails
  before media preparation.
- Wrong action code, match kind, response count, ambiguous/no-wake acceptance or legal
  cross-action misclassification fails the Voice lane.
- Guardian transition/event/Dashboard mismatch fails the Guardian lane without
  changing thresholds or expected results after observation.
- Timeout, interruption, component close failure or report failure retains the first
  stable failure and never fabricates PASS.
- Raw exception, transcript, PCM, path, URL, host and model prose remain absent from
  normal output and reports.

## 9. Verification matrix

Implementation requires RED -> GREEN coverage for:

- exactly eight unique scenarios and the four new IDs;
- provenance correction for `OCC-02` and manifest-bound provenance rejection;
- one-level public-parent validation, recursive/synthetic-parent rejection and the
  exact five-clip selection;
- exact 65/50/50/100/65 frame accounting, 330 total and zero skipped/dropped/decode/
  worker counts;
- explicit `INDEPENDENT` visual/oracle contract coverage;
- prone watch/open/dedup/recovery and final recovered Dashboard state;
- outside watch/open/dedup/recovery and final recovered Dashboard state;
- diaper start/complete exact action counters plus all three negative classes;
- burping start/complete exact action counters plus all three negative classes;
- per-step action-code/match-kind mismatch rejection;
- legal cross-action self-classification, ambiguous multi-action silence and no-wake
  silence, with question/unsupported/medication inputs remaining closed;
- report privacy, action-count bounds and explicit visual non-proof language;
- the actual bounded eight-scenario run through all required lanes;
- focused, full Python, frontend, compile, shell, Make, diff, media and privacy gates.

## 10. Delivery boundary and later work

Implementation remains paused until the owner resumes it. When resumed, the work stays
on `codex/visual-regression-corpus`, uses focused commits and receives independent
review before factual STATUS/CHECKPOINT/NEXT updates.

The following remain later and separate:

- model training, threshold changes or a promoted public baseline;
- private household capture or `LOCAL_READY` admission;
- real-baby rollover/face-covering/bed-exit accuracy acceptance;
- real far-field diaper/burping Voice recall;
- Camera Reply, Baby Care writes, notification delivery and remote access.
