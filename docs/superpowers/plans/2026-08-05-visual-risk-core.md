# Automatic Care Visual Risk Core Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the pure deterministic core that validates Qwen visual observations and turns sustained face-occlusion, prone-posture, and out-of-bed candidates into deduplicated watch, alert, intervention, and recovery transitions.

**Architecture:** Keep model observations separate from deterministic decisions. `packages/contracts/vision.py` owns strict immutable schema-v1 observation and transition contracts; `services/vision/risk_state.py` owns three independent in-memory risk tracks and snapshot restoration without network, file, model, or notification I/O.

**Tech Stack:** Python 3.11, Pydantic 2, pytest.

## Global Constraints

- All visual outputs are auxiliary care candidates, never medical facts.
- A single model result never opens an alert.
- Candidate confidence below `0.70` can enter `watch` but cannot accumulate toward `alert`.
- Alerts require two valid candidate observations spanning at least 10 seconds.
- Recovery requires two explicit safe observations spanning at least 10 seconds.
- Adult presence records intervention but never recovers a risk by itself.
- Restart restores open alerts only; all pending candidate and recovery counters reset.
- Inputs must use timezone-aware, monotonically non-decreasing timestamps.
- Production modules in this stage perform no network, model, filesystem, database, media, or notification I/O.
- Tests use only programmatically constructed observations and contain no household media or identifiers.

---

### Task 1: Strict visual observation and decision contracts

**Files:**
- Create: `packages/contracts/vision.py`
- Modify: `packages/contracts/__init__.py`
- Test: `tests/contracts/test_vision_review.py`

**Interfaces:**
- Consumes: Pydantic v2 and the repository timezone-aware datetime convention.
- Produces: `VisualReview`, visual enum classes, `VisualRiskKind`, `VisualRiskState`, `RiskTransitionKind`, `RiskTransition`, and `RiskSnapshot`.

- [ ] **Step 1: Write failing strict-schema tests**

Create tests that construct a valid `VisualReview`, reject extra fields, reject duplicate or more-than-five reason codes, reject confidence outside `0.0..1.0`, and reject naive transition/snapshot datetimes. Include this representative strict parse:

```python
review = VisualReview.model_validate(
    {
        "schema_version": 1,
        "baby_visibility": "visible",
        "face_visibility": "not_visible",
        "posture": "supine",
        "bed_state": "inside",
        "adult_presence": "absent",
        "image_quality": "usable",
        "risk": "high",
        "reason_codes": ["face_not_visible"],
        "confidence": 0.82,
    }
)
assert review.face_visibility is FaceVisibility.NOT_VISIBLE
```

- [ ] **Step 2: Run the tests and verify RED**

Run: `.venv-alpha/bin/pytest tests/contracts/test_vision_review.py -q`  
Expected: FAIL during collection because `packages.contracts.vision` does not exist.

- [ ] **Step 3: Implement the immutable strict contracts**

Use `ConfigDict(extra="forbid", frozen=True)`, `Literal[1]`, `StrEnum`, `Field(ge=0, le=1)`, and timezone-aware validators. `reason_codes` must use `max_length=5` and an after-validator that rejects duplicates. Define transitions with these exact fields:

```python
class RiskTransition(VisionContract):
    transition_kind: RiskTransitionKind
    risk_kind: VisualRiskKind | None
    previous_state: VisualRiskState
    current_state: VisualRiskState
    observed_at: datetime
    confidence: float | None = Field(default=None, ge=0, le=1)
    rule_version: Literal["visual-risk-v1"] = "visual-risk-v1"
    notify: bool
```

`RiskSnapshot` contains `schema_version=1`, aware `snapshot_at`, and a frozenset of `open_risks`.

- [ ] **Step 4: Run the contract tests and verify GREEN**

Run: `.venv-alpha/bin/pytest tests/contracts/test_vision_review.py -q`  
Expected: all tests PASS with no warnings.

- [ ] **Step 5: Commit the contract slice**

```bash
git add packages/contracts/vision.py packages/contracts/__init__.py tests/contracts/test_vision_review.py
git commit -m "feat: define strict visual review contracts"
```

### Task 2: Deterministic candidate confirmation and recovery

**Files:**
- Create: `services/vision/__init__.py`
- Create: `services/vision/risk_state.py`
- Test: `tests/vision/__init__.py`
- Test: `tests/vision/test_risk_state.py`

**Interfaces:**
- Consumes: `VisualReview`, `VisualRiskKind`, `VisualRiskState`, `RiskTransition`, `RiskTransitionKind`, and `RiskSnapshot` from Task 1.
- Produces: `VisualRiskStateMachine.evaluate(review: VisualReview, observed_at: datetime) -> tuple[RiskTransition, ...]`, `snapshot(snapshot_at: datetime) -> RiskSnapshot`, and `from_snapshot(snapshot: RiskSnapshot) -> VisualRiskStateMachine`.

- [ ] **Step 1: Write failing behavior tests**

Cover each behavior independently with fixed aware timestamps:

```python
machine = VisualRiskStateMachine()
first = machine.evaluate(face_hidden(confidence=0.82), NOW)
second = machine.evaluate(face_hidden(confidence=0.85), NOW + timedelta(seconds=10))
assert [item.transition_kind for item in first] == [RiskTransitionKind.WATCH_STARTED]
assert [item.transition_kind for item in second] == [RiskTransitionKind.ALERT_OPENED]
```

Add separate tests for prone and outside candidates, two observations less than 10 seconds apart, low-confidence candidates never alerting, two explicit safe observations recovering, repeated alert candidates producing no duplicate transition, adult intervention occurring once without recovery, three risks tracking independently, and timestamp rollback rejection.

- [ ] **Step 2: Run the state tests and verify RED**

Run: `.venv-alpha/bin/pytest tests/vision/test_risk_state.py -q`  
Expected: FAIL during collection because `services.vision.risk_state` does not exist.

- [ ] **Step 3: Implement the minimal pure state machine**

Use one private `_RiskTrack` per `VisualRiskKind`. Candidate evidence rules are exact:

```python
face_candidate = review.face_visibility is FaceVisibility.NOT_VISIBLE and review.risk is ModelRisk.HIGH
prone_candidate = review.posture is Posture.PRONE_CANDIDATE and review.risk is ModelRisk.HIGH
outside_candidate = review.bed_state is BedState.OUTSIDE_CANDIDATE
valid_candidate = candidate and review.confidence >= 0.70
```

Safe evidence is exact: face `clear`; posture one of `supine/side/upright`; bed `inside`. `uncertain`, poor image, partial visibility, low confidence, and adult presence are never safe evidence. Emit transitions only when externally visible state changes. Preserve alert state on adult intervention.

- [ ] **Step 4: Run state and contract tests and verify GREEN**

Run: `.venv-alpha/bin/pytest tests/vision/test_risk_state.py tests/contracts/test_vision_review.py -q`  
Expected: all tests PASS.

- [ ] **Step 5: Commit the deterministic state slice**

```bash
git add services/vision tests/vision
git commit -m "feat: add deterministic visual risk state machine"
```

### Task 3: Restart snapshot boundary and stage documentation

**Files:**
- Modify: `services/vision/risk_state.py`
- Modify: `tests/vision/test_risk_state.py`
- Modify: `docs/STATUS.md`
- Modify: `docs/CHECKPOINT.md`
- Modify: `docs/NEXT.md`

**Interfaces:**
- Consumes: `RiskSnapshot` from Task 1 and open risk tracks from Task 2.
- Produces: restart-safe restoration that keeps open alerts but discards pre-restart pending candidate/recovery evidence.

- [ ] **Step 1: Write failing restart tests**

Open a face alert, start one recovery observation, snapshot, restore, and prove one post-restart safe observation cannot recover it. Then provide a second post-restart safe observation 10 seconds later and prove it recovers. Separately snapshot a `watch` state and prove it restores as normal with no pending evidence.

- [ ] **Step 2: Run the restart tests and verify RED**

Run: `.venv-alpha/bin/pytest tests/vision/test_risk_state.py -q`  
Expected: the new restart assertions FAIL because snapshot restoration is not implemented yet.

- [ ] **Step 3: Implement snapshot creation and restoration**

`snapshot()` serializes only tracks currently in `alert`. `from_snapshot()` constructs fresh tracks, marks listed tracks alert, and leaves candidate/recovery counters and adult-presence memory empty. Reject snapshot times earlier than any subsequent evaluated observation through the same monotonic-time guard.

- [ ] **Step 4: Run stage verification**

Run:

```bash
.venv-alpha/bin/pytest tests/contracts/test_vision_review.py tests/vision/test_risk_state.py -q
.venv-alpha/bin/pytest -q
node --test tests/frontend/*.test.mjs
git diff --check
```

Expected: all Python and frontend tests PASS; `git diff --check` exits 0.

- [ ] **Step 5: Record honest status and commit**

Document R1 as implemented and automatically tested, while keeping M2/Ollama, frame privacy, event media, ntfy, Dashboard feedback, and household validation explicitly pending.

```bash
git add services/vision/risk_state.py tests/vision/test_risk_state.py docs/STATUS.md docs/CHECKPOINT.md docs/NEXT.md
git commit -m "docs: record visual risk core checkpoint"
```

## Plan self-review

- The plan covers every R1 requirement in the phase design and intentionally excludes all R2–R5 I/O.
- All types and method names are defined before later tasks consume them.
- No placeholder implementation steps or household media are present.
- Each production behavior has an explicit RED and GREEN command.

