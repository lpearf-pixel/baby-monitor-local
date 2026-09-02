# Visual Cross-Risk Correction Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use
> superpowers:subagent-driven-development (recommended) or superpowers:executing-plans
> to implement this plan one task at a time with review checkpoints. Do not execute
> independent tasks concurrently because they change the same Guardian contracts and
> state machine.

**Goal:** Stop empty-bed and adult-only observations from creating face-cover
watch/alert/event/notification output while preserving the real baby-present face
lifecycle and independently valid outside/adult evidence.

**Architecture:** Preserve each immutable raw `VisualReview`, derive one canonical
closed evidence object, and make the existing `VisualRiskStateMachine` consume that
object for all three risks. A confirmed no-baby/outside sequence resolves an existing
face lifecycle with `resolution_cause=subject_outside` and `notify=false`; an explicit
face-clear recovery retains its notification. The event pipeline persists both kinds
of recovery but queues a recovery notification only when the transition requests it.

**Tech Stack:** Python 3.11+, Pydantic 2, dataclasses, SQLite-backed
`VisualRiskEventStore`, pytest.

**Spec:**
`docs/superpowers/specs/2026-09-02-offline-application-rehearsal-design.md`, especially
Sections 5, 6.1 and 10.

## Global Constraints

- Start from the current remote descendant of `a58253a91b527b89641743bf557b04049d6e0b8a`.
  Fetch and inspect any newer commits; never reset, rebase or force-push over them.
- Keep `camera_reply_enabled=false`. Do not initialize camera, microphone, speaker,
  PTZ, Xiaomi, go2rtc, notification dispatch or Baby Care adapters.
- Do not reject a structurally valid raw review merely because its semantics conflict.
  Canonicalize it so valid outside/adult evidence survives while invalid face evidence
  is removed.
- Do not weaken the 0.70 confidence threshold or ten-second/two-observation
  confirmation rule. Do not tune prompts, models or thresholds in this plan.
- Do not change the accepted `offline-guardian-v1` fixture, its eight scenarios,
  thirteen lanes, five clips or 330-frame contract.
- Keep recovery causes closed and machine-readable. No prose, media, transcript,
  private path, model response or device identifier may enter a contract or log.
- Use RED -> GREEN for every behavior change. After each task run its focused tests,
  inspect the diff, and create the named focused commit.
- Stop on a regression, unexpected production-adapter import, remote divergence or
  missing test dependency. Do not enter the application-rehearsal plan until this
  entire plan is green.

---

## Task Brief

| Field | Contract |
|---|---|
| Current state | The reviewed state machine accepts `baby=not_visible`, `face=not_visible`, `bed=outside_candidate`, `risk=high` as simultaneous face and outside evidence. The event pipeline also queues every `RECOVERED` transition regardless of `notify`. |
| Allowed scope | `packages/contracts/vision.py`, a new pure evidence module, the visual risk state machine/event pipeline, focused tests, and factual status/checkpoint updates after verification. |
| Prohibited scope | Model/prompt tuning, UI-only suppression, DB schema migration, production notification delivery, real devices/media, Camera Reply, Baby Care, medication, baseline promotion, PR/merge, `main` or `stable/xiaomi-alpha`. |
| Done means | The required truth table passes through direct state-machine and actual store/query paths; positive face control still opens/recovers; `subject_outside` is non-notifying; old eight-scenario regression remains unchanged and green. |
| Delivery | Focused commits on `codex/visual-regression-corpus`; stop after software evidence and independent review. |

## Required interfaces and invariants

Add these closed types to `packages/contracts/vision.py`:

```python
class RiskResolutionCause(StrEnum):
    EXPLICIT_SAFE = "explicit_safe"
    SUBJECT_OUTSIDE = "subject_outside"


class VisualSemanticConflict(StrEnum):
    FACE_WITHOUT_SUBJECT = "face_without_subject"
```

Extend `RiskTransition` with:

```python
resolution_cause: RiskResolutionCause | None = None
```

Its model validator must enforce exactly:

- only `WATCH_CLEARED` and `RECOVERED` may carry a cause;
- `subject_outside` is valid only for `risk_kind=face_not_visible` and
  `notify=false`;
- `explicit_safe` is valid only for a risk-specific `WATCH_CLEARED` or `RECOVERED`;
- every lifecycle resolution has one cause; all non-resolution transitions have null.

Create `services/vision/risk_evidence.py` with this public shape:

```python
@dataclass(frozen=True)
class RiskEvidence:
    candidate: bool
    safe: bool
    resolution_cause: RiskResolutionCause | None = None


@dataclass(frozen=True)
class CanonicalVisualEvidence:
    face: RiskEvidence
    prone: RiskEvidence
    outside: RiskEvidence
    semantic_conflicts: tuple[VisualSemanticConflict, ...]

    def for_risk(self, risk_kind: VisualRiskKind) -> RiskEvidence:
        return {
            VisualRiskKind.FACE_NOT_VISIBLE: self.face,
            VisualRiskKind.PRONE_CANDIDATE: self.prone,
            VisualRiskKind.OUTSIDE_CANDIDATE: self.outside,
        }[risk_kind]


def canonicalize_visual_review(
    review: VisualReview,
) -> CanonicalVisualEvidence:
    subject_attributable = (
        review.baby_visibility
        in {BabyVisibility.VISIBLE, BabyVisibility.PARTIAL}
        and review.bed_state is BedState.INSIDE
    )
    usable_confident = (
        review.image_quality is ImageQuality.USABLE
        and review.confidence >= MINIMUM_CONFIDENCE
    )
    face_candidate = (
        subject_attributable
        and usable_confident
        and review.face_visibility is FaceVisibility.NOT_VISIBLE
        and review.risk is ModelRisk.HIGH
    )
    face_explicit_safe = (
        subject_attributable
        and usable_confident
        and review.face_visibility is FaceVisibility.CLEAR
        and review.adult_presence is AdultPresence.ABSENT
    )
    subject_outside = (
        usable_confident
        and review.baby_visibility is BabyVisibility.NOT_VISIBLE
        and review.bed_state is BedState.OUTSIDE_CANDIDATE
    )
    conflicts = (
        (VisualSemanticConflict.FACE_WITHOUT_SUBJECT,)
        if review.face_visibility is FaceVisibility.NOT_VISIBLE
        and not subject_attributable
        else ()
    )
    generic_safe = (
        usable_confident
        and review.adult_presence is AdultPresence.ABSENT
    )
    return CanonicalVisualEvidence(
        face=RiskEvidence(
            candidate=face_candidate,
            safe=face_explicit_safe or subject_outside,
            resolution_cause=(
                RiskResolutionCause.SUBJECT_OUTSIDE
                if subject_outside
                else RiskResolutionCause.EXPLICIT_SAFE
                if face_explicit_safe
                else None
            ),
        ),
        prone=RiskEvidence(
            candidate=(
                review.posture is Posture.PRONE_CANDIDATE
                and review.risk is ModelRisk.HIGH
            ),
            safe=(
                generic_safe
                and review.posture
                in {Posture.SUPINE, Posture.SIDE, Posture.UPRIGHT}
            ),
            resolution_cause=(
                RiskResolutionCause.EXPLICIT_SAFE
                if generic_safe
                and review.posture
                in {Posture.SUPINE, Posture.SIDE, Posture.UPRIGHT}
                else None
            ),
        ),
        outside=RiskEvidence(
            candidate=review.bed_state is BedState.OUTSIDE_CANDIDATE,
            safe=generic_safe and review.bed_state is BedState.INSIDE,
            resolution_cause=(
                RiskResolutionCause.EXPLICIT_SAFE
                if generic_safe and review.bed_state is BedState.INSIDE
                else None
            ),
        ),
        semantic_conflicts=conflicts,
    )
```

The mapper is pure: it receives the frozen raw review, performs no I/O, and returns no
free text. It must implement this exact face logic:

```python
subject_attributable = (
    review.baby_visibility in {BabyVisibility.VISIBLE, BabyVisibility.PARTIAL}
    and review.bed_state is BedState.INSIDE
)
usable_confident = (
    review.image_quality is ImageQuality.USABLE
    and review.confidence >= MINIMUM_CONFIDENCE
)
face_candidate = (
    subject_attributable
    and usable_confident
    and review.face_visibility is FaceVisibility.NOT_VISIBLE
    and review.risk is ModelRisk.HIGH
)
face_explicit_safe = (
    subject_attributable
    and usable_confident
    and review.face_visibility is FaceVisibility.CLEAR
    and review.adult_presence is AdultPresence.ABSENT
)
subject_outside = (
    usable_confident
    and review.baby_visibility is BabyVisibility.NOT_VISIBLE
    and review.bed_state is BedState.OUTSIDE_CANDIDATE
)
```

`subject_outside` supplies safe/inapplicable evidence only to the face track and uses
the `subject_outside` cause. It must not be blocked by adult presence. The conflict
`face_without_subject` is present when raw `face_visibility=not_visible` but
`subject_attributable` is false. Preserve existing prone and outside candidate/safe
semantics unless a test proves a change is required for the approved truth table.

## Task 1: Add closed transition causes and canonical evidence

**Files:**

- Modify: `packages/contracts/vision.py`
- Create: `services/vision/risk_evidence.py`
- Create: `tests/vision/test_risk_evidence.py`
- Modify: `tests/contracts/test_vision_review.py`

**Interfaces:** The exact enums, transition validator and pure mapper above.

- [x] **Step 1: Write failing contract tests**

Add parametrized tests proving valid `explicit_safe` and `subject_outside` resolution
transitions parse, and that each of these fails with `ValidationError`:

- `ALERT_OPENED` with either cause;
- `RECOVERED` without a cause;
- `subject_outside` on `outside_candidate`;
- `subject_outside` with `notify=true`;
- `ADULT_INTERVENTION` with a cause.

Run:

```bash
../../.venv-alpha/bin/python -m pytest tests/contracts/test_vision_review.py -q
```

Expected RED: imports/field assertions fail because the closed cause contract does not
exist.

- [x] **Step 2: Write failing canonical-evidence truth-table tests**

In `tests/vision/test_risk_evidence.py`, use frozen `VisualReview` builders and assert:

| Review | Face | Outside | Conflict |
|---|---|---|---|
| baby visible, inside, face not visible, usable/high/0.90 | candidate true | candidate false | none |
| baby not visible, outside, face not visible, usable/high/0.90 | candidate false; safe true; `subject_outside` | candidate true | `face_without_subject` |
| same with adult present | same face result | candidate true | same conflict |
| baby uncertain or bed uncertain, face not visible | candidate false; safe false | independently derived only | `face_without_subject` |
| baby visible, inside, face clear, adult absent | safe true; `explicit_safe` | safe false | none |
| baby visible, inside, face not visible, confidence 0.69 | candidate false | unchanged independent result | none |
| no baby, outside, unusable or confidence 0.69 | no face candidate or outside-based recovery | existing low-confidence outside behavior only | conflict if raw face is not visible |

Also assert `for_risk()` maps all three `VisualRiskKind` members and no review object is
mutated.

Run:

```bash
../../.venv-alpha/bin/python -m pytest tests/vision/test_risk_evidence.py -q
```

Expected RED: the module does not exist.

- [x] **Step 3: Implement the minimum contracts and pure mapper**

Add the two enums and validator to `packages/contracts/vision.py`. Implement the mapper
without importing the state machine to avoid a cycle; define the shared confidence
constant in `risk_evidence.py` and re-export/import it from `risk_state.py` in Task 2.
Deduplicate conflicts by construction so the tuple contains each closed conflict at
most once per review.

- [x] **Step 4: Run focused GREEN and compile**

```bash
../../.venv-alpha/bin/python -m pytest \
  tests/contracts/test_vision_review.py \
  tests/vision/test_risk_evidence.py -q
../../.venv-alpha/bin/python -m compileall -q \
  packages/contracts/vision.py services/vision/risk_evidence.py
git diff --check
```

Expected: all selected tests pass; compile and diff checks are silent.

- [x] **Step 5: Commit**

```bash
git add packages/contracts/vision.py services/vision/risk_evidence.py \
  tests/contracts/test_vision_review.py tests/vision/test_risk_evidence.py
git commit -m "fix: canonicalize visual risk evidence"
```

## Task 2: Enforce the truth table in the state machine

**Files:**

- Modify: `services/vision/risk_state.py`
- Modify: `tests/vision/test_risk_state.py`

**Interfaces:** `VisualRiskStateMachine.evaluate()` remains source-compatible and
continues returning `tuple[RiskTransition, ...]`. Internally it consumes one
`CanonicalVisualEvidence` per review and passes the evidence cause into track advance.

- [x] **Step 1: Replace the impossible combined-risk expectation with RED regressions**

Revise the existing combined-risk test that currently expects face + prone + outside
from an absent baby. Keep valid independently attributable risks as separate positive
controls. Add exact tests:

1. two no-baby/outside/face-not-visible reviews at `t0` and `t+10s` produce only
   outside `WATCH_STARTED`, then outside `ALERT_OPENED`; face stays `NORMAL`;
2. adult present on the first review adds one `ADULT_INTERVENTION`, but still no face
   output;
3. two baby-present/inside/face-not-visible reviews open the face alert;
4. confidence 0.69 creates no new face watch (not a low-confidence WATCH);
5. uncertain baby/bed creates no face candidate and no outside-based recovery.

Run:

```bash
../../.venv-alpha/bin/python -m pytest tests/vision/test_risk_state.py -q
```

Expected RED: current implementation opens face WATCH/ALERT for absent-baby input and
still emits a low-confidence face WATCH.

- [x] **Step 2: Add RED lifecycle tests for an existing face state**

Build a face alert at `t0/t+10s`, then assert:

- one no-baby/outside review does not close it;
- the second qualifying review ten seconds later emits face `RECOVERED`, cause
  `subject_outside`, `notify=false`, while outside emits `ALERT_OPENED`;
- a face WATCH follows the same confirmed two-review rule and emits `WATCH_CLEARED`
  with `subject_outside` and `notify=false`;
- two baby-present face-clear reviews still emit `RECOVERED`, cause `explicit_safe`,
  `notify=true`;
- an intervening uncertain/unusable review resets outside-based recovery evidence and
  cannot claim a cause.

- [x] **Step 3: Route state evaluation through canonical evidence**

Call `canonicalize_visual_review(review)` once in `evaluate()`. Replace
`_evidence_for()` with `evidence.for_risk(risk_kind)`. Change `_advance_track()` and
`_transition()` to accept and propagate `resolution_cause`. Set face-recovery
notification behavior with this exact rule:

```python
notify = resolution_cause is RiskResolutionCause.EXPLICIT_SAFE
```

for `RECOVERED`; `WATCH_CLEARED` remains non-notifying. Face candidate evidence that
fails the confidence/quality predicate must not move `NORMAL` to `WATCH`. Preserve the
existing prone/outside low-confidence state behavior unless the approved truth-table
tests prove a necessary compatibility fix.

- [x] **Step 4: Run focused GREEN and the review-runtime compatibility tests**

```bash
../../.venv-alpha/bin/python -m pytest \
  tests/vision/test_risk_evidence.py \
  tests/vision/test_risk_state.py \
  tests/vision/test_review_runtime.py -q
../../.venv-alpha/bin/python -m compileall -q services/vision/risk_state.py
git diff --check
```

Expected: exact truth-table and lifecycle tests pass without changing public runtime
signatures.

- [x] **Step 5: Commit**

```bash
git add services/vision/risk_state.py tests/vision/test_risk_state.py
git commit -m "fix: gate face risk on attributable baby"
```

## Task 3: Persist recovery but suppress false recovery notification

**Files:**

- Modify: `services/vision/risk_event_pipeline.py`
- Modify: `tests/vision/test_risk_event_pipeline.py`

**Interfaces:** Recovery persistence is unchanged. `_GuardianJsonLog.emit()` adds only
the closed `resolution_cause` value when present. Notification queueing follows the
transition's `notify` boolean.

- [x] **Step 1: Write RED pipeline tests**

Using an actual temporary `VisualRiskEventStore`, open a face event and handle a
`RECOVERED` transition with `subject_outside`/`notify=false`. Assert:

- the event state becomes recovered;
- zero `risk_recovered` notification rows are queued;
- the JSON log contains `"resolution_cause":"subject_outside"`;
- event and notification IDs remain bounded and no exception prose is logged.

Keep/add the explicit-safe control asserting it persists recovery and queues exactly one
`risk_recovered` notification. Add a contract-defense test showing a non-notifying
transition cannot accidentally queue through `_persist()`.

Run:

```bash
../../.venv-alpha/bin/python -m pytest tests/vision/test_risk_event_pipeline.py -q
```

Expected RED: current pipeline queues a recovery notification unconditionally and the
log omits the cause.

- [x] **Step 2: Implement the minimum pipeline change**

Include `resolution_cause` in the structured payload only when non-null. Always call
`recover_event()` for a valid `RECOVERED` transition. Guard only the notification call:

```python
if transition.notify:
    self._queue_notification(
        event=event,
        stage="risk_recovered",
        queued_at=transition.observed_at,
        transition=transition,
    )
```

Do not add a DB column or reinterpret a non-notifying recovery as an ignored
transition.

- [x] **Step 3: Run focused GREEN**

```bash
../../.venv-alpha/bin/python -m pytest \
  tests/vision/test_risk_event_pipeline.py \
  tests/storage/test_visual_risk_store.py \
  tests/events/test_guardian_query.py -q
../../.venv-alpha/bin/python -m compileall -q services/vision/risk_event_pipeline.py
git diff --check
```

- [x] **Step 4: Commit**

```bash
git add services/vision/risk_event_pipeline.py \
  tests/vision/test_risk_event_pipeline.py
git commit -m "fix: suppress subject-outside recovery notice"
```

## Task 4: Prove the actual Guardian store/query path

**Files:**

- Create: `tests/integration/test_visual_cross_risk.py`
- Modify only if required by a failing compatibility test:
  `services/vision/corpus_replay.py`

**Interfaces:** Exercise `VisualRiskStateMachine` -> `VisualRiskEventPipeline` ->
`VisualRiskEventStore` -> `GuardianEventQueryService`; do not replace any of these with
a recording fake. A wrapper may record calls to `queue_notification` while delegating
to the actual store.

- [x] **Step 1: Add six exact end-to-end scenarios**

Create fresh temporary databases and fixed clocks for:

| Scenario | Exact end state |
|---|---|
| safe baby | no event, no notification |
| positive face occlusion + explicit clear | one recovered face event, open + recovery notification |
| empty bed | one open outside event; zero face event/notification |
| adult-only outside | one adult intervention, one open outside event; zero face event/notification |
| legacy inconsistent review | one unique semantic conflict, one open outside event; zero face output |
| face then outside | recovered face event with non-notifying `subject_outside`; one open outside event; no face recovery notification |

Assert both stored rows and media-free dashboard projection. Explicitly assert that one
raw semantic conflict does not discard the outside event.

- [x] **Step 2: Run RED, then add only required integration plumbing**

```bash
../../.venv-alpha/bin/python -m pytest \
  tests/integration/test_visual_cross_risk.py -q
```

If Tasks 1-3 are complete, these tests should normally pass without business-code
changes. A RED here indicates a real boundary mismatch: fix the smallest production
boundary, add a focused test beside it, and record why in the commit.

- [x] **Step 3: Run Guardian and old offline compatibility gates**

```bash
../../.venv-alpha/bin/python -m pytest \
  tests/integration/test_visual_cross_risk.py \
  tests/vision/test_corpus_guardian_projection.py \
  tests/contracts/test_offline_guardian_scenario.py \
  tests/integration/test_offline_guardian_scenario.py \
  tests/tools/test_offline_guardian_scenario.py -q
```

Then execute the existing fixed flow once:

```bash
make PYTHON=../../.venv-alpha/bin/python alpha-offline-scenario-validate
make PYTHON=../../.venv-alpha/bin/python alpha-offline-scenario-run
```

Expected: validation PASS; run PASS with exactly 8 scenarios, 13 lanes, 5 visual clips,
330 frames, and zero skipped/dropped/decode/worker errors. If public downloads are
unavailable, stop and report that environmental blocker; do not convert a SKIP into
PASS or edit the fixture.

- [x] **Step 4: Commit**

```bash
git add tests/integration/test_visual_cross_risk.py \
  services/vision/corpus_replay.py
git diff --cached --quiet || git commit -m "test: cover visual cross-risk flow"
```

Do not stage `services/vision/corpus_replay.py` if it did not change.

## Task 5: Full gate, independent review and factual checkpoint

**Files:**

- Modify after fresh verification only: `SUMMARY.md`
- Modify after fresh verification only: `docs/STATUS.md`
- Append after fresh verification only: `docs/CHECKPOINT.md`
- Modify after fresh verification only: `docs/NEXT.md`

- [x] **Step 1: Run the complete verification from the exact candidate head**

```bash
git status --short --branch
../../.venv-alpha/bin/python -m pytest -q
npm test
git diff --check
git grep -nE '(/Users/|/home/|token|password|BEGIN (RSA|OPENSSH|EC) PRIVATE KEY)' -- \
  packages services tests docs SUMMARY.md ':!docs/CHECKPOINT.md'
git status --short --branch
```

Interpret the privacy grep manually: ordinary documentation words such as "token" are
not failures; private literal values and absolute user paths are. Record exact fresh
test counts and the candidate SHA. Never copy older counts into this checkpoint.

- [x] **Step 2: Review the complete diff against the approved truth table**

Use `superpowers:requesting-code-review`. Required review questions:

1. Can any no-baby/outside or adult-only input start/extend a face watch?
2. Can one missing frame close a face alert?
3. Does confirmed `subject_outside` persist recovery without a recovery notification?
4. Does explicit face clear still notify?
5. Is independently valid outside/adult evidence retained on semantic conflict?
6. Did any DB schema, production adapter, prompt/model/threshold or old fixture change?

Fix every Critical/Important finding with RED/GREEN and rerun the full gate. Minor
findings must be fixed or explicitly recorded before handoff.

- [x] **Step 3: Update factual docs and commit**

Record only results observed in Steps 1-2. State that this is deterministic application
semantics, not real-baby/model accuracy. Keep Camera Reply false and Stage 2 device
decisions `NOT_PROVEN`.

```bash
git add SUMMARY.md docs/STATUS.md docs/CHECKPOINT.md docs/NEXT.md
git commit -m "docs: record visual cross-risk correction gate"
```

- [x] **Step 4: Stop line**

Fetch and confirm the remote branch has not diverged. Push only a fast-forward after
explicit delivery authority. Do not run a device, enable Camera Reply, enter the
panoramic gate, merge a PR or modify `main/stable`. Proceed to
`2026-09-02-offline-application-rehearsal.md` only from a clean descendant whose full
Task 5 gate is green.
