# Offline Guardian Scenario Expansion Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use
> superpowers:subagent-driven-development (recommended) or superpowers:executing-plans
> to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Expand the fixed offline Guardian flow from four scenarios/seven lanes to
exactly eight scenarios/thirteen lanes with exact 330-frame accounting, independent
prone/outside Guardian oracles and closed diaper/burping Voice outcomes.

**Architecture:** Extend the existing strict Pydantic suite and injected runner instead
of adding another orchestration path. Public/generated visual clips remain observational;
synthetic Guardian timelines and generated Voice fixtures remain independent lanes joined
only by scenario ID. Validate provenance and exact identities before preparation or model
construction, then retain only bounded aggregate counts in the private report.

**Tech Stack:** Python 3.11+, Pydantic 2, pytest, existing
`VisualCorpusReplay`/`GuardianReplayProjector`/`ListenOnlyController`, ffmpeg through the
existing corpus pipeline, Node test runner and Make.

**Spec:**
`docs/superpowers/specs/2026-08-29-offline-guardian-scenario-expansion-design.md`

**Execution status (2026-08-30):** Tasks 1-6 and Task 7 Steps 1-3/5-6 were completed
through business head `0688d38` and docs checkpoint `277da3e`. The fixed run passed
8/8 scenarios, 13/13 lanes and 330/330 frames; full software gates are recorded in
`docs/CHECKPOINT.md`. Task 7 Step 4 remains open because no independent reviewer has
yet reviewed the merged exact head. Do not advance to the next ordered product stage
until that review is clean or its findings are resolved.

## Global Constraints

- Implement on `codex/visual-regression-corpus` from the latest clean remote descendant
  of reviewed base `7cf8d023f706f3a77d0835916854dfd4db450a64`.
- Use only existing tracked public/generated corpus metadata and generated Voice PCM.
  Do not access a camera, microphone, speaker, Xiaomi authentication, CS2, go2rtc,
  Ollama, notification service, production SQLite or Baby Care.
- Keep `visual_oracle_relationship=INDEPENDENT`; visual observations never satisfy,
  alter or gate a Guardian oracle.
- Select exactly `DAY-01`, `OCC-02`, `NEG-03`, `DAY-03`, `OCC-03`. Their three public
  sources declare 25,964,039 bytes; do not raise the 128 MiB first-stage cap.
- Require exact per-clip frames `65, 50, 50, 100, 65`, total 330, with zero skipped,
  dropped, decode-error or worker-error frames.
- Keep Feeding, diaper change and burping as internal Listen-only behavior. Medication,
  care writes, signer/outbox construction and external intent expansion are prohibited.
- Keep reports ignored/private (`0700` root, `0600` files), media-free and free of
  transcript, PCM, paths, URLs, hosts, model prose and raw exceptions.
- Do not change the realtime model, threshold, Guardian state machine, public corpus
  readiness or baseline state to make the suite pass.
- Each task is RED -> GREEN and ends in one focused commit. Do not push, create a PR,
  merge or change `main/stable` without separate authority.

---

## File and interface map

- Modify `packages/contracts/offline_guardian_scenario.py`: exact-frame,
  visual/oracle-relationship and per-step Voice action expectations.
- Modify `tests/fixtures/offline_guardian_scenarios/scenarios.v1.json`: exact eight
  scenarios, thirteen lanes and all closed expectations.
- Modify `services/offline_guardian_scenario.py`: binding validation, exact visual
  accounting, Voice action comparison/counters and relationship propagation.
- Modify `services/offline_guardian_report.py`: fixed independence/non-proof rendering.
- Modify `tools/offline_guardian_scenario.py`: exact five-clip selection, generated
  fixture mapping and bounded validation/run output.
- Modify `tests/contracts/test_offline_guardian_scenario.py`: contract/fixture RED tests.
- Modify `tests/integration/test_offline_guardian_scenario.py`: Guardian, visual, Voice,
  runner and report RED tests.
- Modify `tests/tools/test_offline_guardian_scenario.py`: fixed CLI and provenance RED
  tests.
- Modify `SUMMARY.md`, `docs/STATUS.md`, `docs/CHECKPOINT.md`, `docs/NEXT.md` and this
  plan only after the actual bounded flow and final gates finish.

## Task 1: Bind exact scenario and Voice expectation contracts

**Files:**

- Modify: `packages/contracts/offline_guardian_scenario.py`
- Modify: `tests/contracts/test_offline_guardian_scenario.py`
- Modify: `tests/fixtures/offline_guardian_scenarios/scenarios.v1.json`

**Interfaces:**

- Produces `ScenarioActionCode`, `ScenarioMatchKind` and
  `VisualOracleRelationship` closed literals.
- Replaces `VisualScenarioV1.minimum_frames_processed` with
  `VisualScenarioV1.expected_frames_processed`.
- Adds required nullable `expected_action_code` and `expected_match_kind` to every
  `VoiceScenarioStepV1`.
- Adds nullable `visual_oracle_relationship` to scenario and result contracts, requiring
  `INDEPENDENT` exactly when visual and Guardian lanes coexist.

- [x] **Step 1: Write contract RED tests**

Add strict tests that exercise the new fields directly:

```python
def test_visual_guardian_scenario_requires_independent_relationship() -> None:
    payload = scenario_payload()
    payload["visual_oracle_relationship"] = None
    with pytest.raises(ValidationError):
        contracts().OfflineGuardianScenarioV1.model_validate(payload)


def test_voice_step_requires_explicit_nullable_action_expectations() -> None:
    step = {
        "step_id": "wake",
        "speech_expected": True,
        "from_replay": False,
        "expected_reason": "listen_only_armed",
        "expected_response_code": "listen_only_ready",
        "expected_action_code": None,
        "expected_match_kind": None,
    }
    contracts().VoiceScenarioStepV1.model_validate(step)
    del step["expected_action_code"]
    with pytest.raises(ValidationError):
        contracts().VoiceScenarioStepV1.model_validate(step)
```

Also test these invalid pairs:

```text
action=null, match=exact
action=diaper_change_start, match=null
action=diaper_change_start, match=high_risk_candidate
action=medication_start_candidate, match=exact
visual+guardian relationship=null
voice-only relationship=INDEPENDENT
expected_frames_processed=0
```

Also assert that `medication_start_candidate/high_risk_candidate` remains a valid closed
pair even though no medication step is admitted to this suite.

- [x] **Step 2: Run RED**

```bash
../../.venv-alpha/bin/python -m pytest -q \
  tests/contracts/test_offline_guardian_scenario.py
```

Expected: failures show the missing relationship, exact-frame and per-step action
fields; do not weaken fixture assertions.

- [x] **Step 3: Implement the minimum closed types**

Add these exact aliases and fields:

```python
ScenarioActionCode = Literal[
    "feeding_command",
    "diaper_change_start",
    "diaper_change_complete",
    "burping_start",
    "burping_complete",
    "medication_start_candidate",
    "medication_complete_candidate",
]
ScenarioMatchKind = Literal["exact", "corrected", "high_risk_candidate"]
VisualOracleRelationship = Literal["INDEPENDENT"]


class VisualScenarioV1(OfflineScenarioContract):
    clip_id: str = Field(pattern=r"^[A-Z][A-Z0-9-]{1,63}$")
    profile: Literal["analysis_realtime", "analysis_slow"]
    expected_frames_processed: int = Field(ge=1, le=18_000)
    provenance: Literal["PUBLIC_VIDEO", "GENERATED_VISUAL"]


class VoiceScenarioStepV1(OfflineScenarioContract):
    step_id: str = Field(pattern=r"^[a-z0-9][a-z0-9_-]{0,63}$")
    speech_expected: bool
    from_replay: bool = False
    expected_reason: str = Field(pattern=r"^[a-z0-9_]+$")
    expected_response_code: str | None = Field(
        default=None,
        pattern=r"^[a-z0-9_]+$",
    )
    expected_action_code: ScenarioActionCode | None
    expected_match_kind: ScenarioMatchKind | None

    @model_validator(mode="after")
    def require_action_pair(self) -> "VoiceScenarioStepV1":
        if (self.expected_action_code is None) != (self.expected_match_kind is None):
            raise ValueError("offline_scenario_voice_invalid")
        if self.expected_match_kind == "high_risk_candidate" and not (
            self.expected_action_code is not None
            and self.expected_action_code.startswith("medication_")
        ):
            raise ValueError("offline_scenario_voice_invalid")
        if self.expected_match_kind == "corrected" and self.expected_action_code != "feeding_command":
            raise ValueError("offline_scenario_voice_invalid")
        if self.expected_match_kind == "exact" and (
            self.expected_action_code is not None
            and self.expected_action_code.startswith("medication_")
        ):
            raise ValueError("offline_scenario_voice_invalid")
        return self
```

The closed schema retains medication candidate codes so future negative controls can
assert the existing silent high-risk outcome, but this eight-scenario fixture contains
no medication step and the five low-risk counters exclude both codes. Add
`visual_oracle_relationship` to `OfflineGuardianScenarioV1` and
`OfflineScenarioResultV1`. Extend `require_coherent_lanes()` so visual+guardian requires
`INDEPENDENT`, while every other lane combination requires `None`.

- [x] **Step 4: Keep the existing four-scenario fixture valid**

Before adding new scenarios, update the existing entries exactly:

| Scenario | Contract change |
|---|---|
| `SAFE-SLEEP-01` | `expected_frames_processed=65`, relationship `INDEPENDENT` |
| `FACE-OCCLUSION-01` | `expected_frames_processed=50`, provenance `GENERATED_VISUAL`, relationship `INDEPENDENT` |
| `ADULT-INTERVENTION-01` | `expected_frames_processed=50`, relationship `INDEPENDENT` |
| `VOICE-FEEDING-01` | every step declares action/match; Feeding is `feeding_command/exact`; other steps are null/null |

Voice-only `VOICE-FEEDING-01` declares `visual_oracle_relationship=null` and keeps two
responses.

- [x] **Step 5: Run GREEN and static checks**

```bash
../../.venv-alpha/bin/python -m pytest -q \
  tests/contracts/test_offline_guardian_scenario.py \
  tests/contracts/test_visual_corpus.py
../../.venv-alpha/bin/python -m compileall -q \
  packages/contracts/offline_guardian_scenario.py
git diff --check
```

Expected: zero failures; the tracked fixture loads; canonical bytes remain ASCII and
stable.

- [x] **Step 6: Commit**

```bash
git add packages/contracts/offline_guardian_scenario.py \
  tests/contracts/test_offline_guardian_scenario.py \
  tests/fixtures/offline_guardian_scenarios/scenarios.v1.json
git commit -m "feat: bind offline scenario expectations"
```

## Task 2: Add the four new scenarios and deterministic Guardian oracles

**Files:**

- Modify: `tests/fixtures/offline_guardian_scenarios/scenarios.v1.json`
- Modify: `tests/contracts/test_offline_guardian_scenario.py`
- Modify: `tests/integration/test_offline_guardian_scenario.py`

**Interfaces:**

- Extends `offline-guardian-v1` to these exact ordered IDs:
  `SAFE-SLEEP-01`, `FACE-OCCLUSION-01`, `ADULT-INTERVENTION-01`,
  `VOICE-FEEDING-01`, `PRONE-CANDIDATE-01`, `OUTSIDE-CANDIDATE-01`,
  `VOICE-DIAPER-01`, `VOICE-BURPING-01`.
- Adds two `SYNTHETIC_SEMANTIC_ORACLE` timelines with exact watch/open/dedup/recovery
  and final Dashboard state.
- Adds two seven-step generated Voice declarations; runtime wiring follows in Task 3.

- [x] **Step 1: Write exact-suite RED tests**

Replace the four-ID assertion with the exact eight-ID tuple and add:

```python
def test_tracked_suite_has_exact_lane_and_frame_budget() -> None:
    suite = contracts().load_offline_scenario_suite(FIXTURE)
    lanes = sum(len(item.required_lanes) for item in suite.scenarios)
    frames = sum(
        item.visual.expected_frames_processed
        for item in suite.scenarios
        if item.visual is not None
    )
    assert lanes == 13
    assert frames == 330
```

Assert five exact visual bindings and the corrected `OCC-02` provenance.

- [x] **Step 2: Run RED**

```bash
../../.venv-alpha/bin/python -m pytest -q \
  tests/contracts/test_offline_guardian_scenario.py
```

Expected: the exact eight-ID/lane/frame assertions fail against the four-scenario
fixture.

- [x] **Step 3: Add the prone and outside scenarios**

Use `DAY-03/100/PUBLIC_VIDEO` for `PRONE-CANDIDATE-01` and
`OCC-03/65/GENERATED_VISUAL` for `OUTSIDE-CANDIDATE-01`. Both declare
`visual_oracle_relationship="INDEPENDENT"` and required lanes
`["visual_observation", "guardian_deterministic"]`.

Each timeline has five entries at `00, 10, 20, 30, 40` seconds:

```text
entry 1: qualifying candidate -> watch
entry 2: qualifying candidate -> alert
entry 3: same qualifying candidate -> no duplicate
entry 4: explicit safe review -> no recovery yet
entry 5: explicit safe review -> recovery
```

For prone, set `posture=prone_candidate`, `risk=high`,
`reason_codes=[prone_candidate]`; safe entries use the existing all-safe review. For
outside, set `baby_visibility=not_visible`, `face_visibility=not_visible`,
`bed_state=outside_candidate`, `risk=watch`, `reason_codes=[outside_candidate]`; safe
entries return visible/clear/inside.

Declare these two exact expectation objects:

```json
{
  "transition_counts": {
    "alert_opened.prone_candidate": 1,
    "recovered.prone_candidate": 1,
    "watch_started.prone_candidate": 1
  },
  "event_counts": {"prone_candidate.recovered": 1},
  "dashboard_event_count": 1,
  "dashboard_open_event_count": 0
}
```

```json
{
  "transition_counts": {
    "alert_opened.outside_candidate": 1,
    "recovered.outside_candidate": 1,
    "watch_started.outside_candidate": 1
  },
  "event_counts": {"outside_candidate.recovered": 1},
  "dashboard_event_count": 1,
  "dashboard_open_event_count": 0
}
```

- [x] **Step 4: Add the exact diaper and burping declarations**

Each scenario is Voice-only, relationship null, provenance `GENERATED_AUDIO`, seven
speech-positive steps and five expected responses.

| Scenario | Steps in order |
|---|---|
| `VOICE-DIAPER-01` | `diaper_wake`, `diaper_start`, `diaper_wake_complete`, `diaper_complete`, `diaper_cross_burping`, `diaper_ambiguous`, `diaper_no_wake` |
| `VOICE-BURPING-01` | `burping_wake`, `burping_start`, `burping_wake_complete`, `burping_complete`, `burping_cross_diaper`, `burping_ambiguous`, `burping_no_wake` |

Standalone wakes expect `listen_only_armed/listen_only_ready/null/null`. Target actions
use these exact result tuples:

| Step | reason / response / action / match |
|---|---|
| `diaper_start` | `listen_only_acknowledged / listen_only_received / diaper_change_start / exact` |
| `diaper_complete` | `listen_only_acknowledged / listen_only_received / diaper_change_complete / exact` |
| `burping_start` | `listen_only_acknowledged / listen_only_received / burping_start / exact` |
| `burping_complete` | `listen_only_acknowledged / listen_only_received / burping_complete / exact` |

Cross-action wake-with-command expects the other action's own code with `exact`.
Ambiguous and no-wake steps expect `listen_only_ignored`, no response and null/null.

- [x] **Step 5: Write and run Guardian GREEN tests**

Parameterize the existing real projector test:

```python
@pytest.mark.parametrize(
    ("scenario_id", "risk"),
    [
        ("PRONE-CANDIDATE-01", "prone_candidate"),
        ("OUTSIDE-CANDIDATE-01", "outside_candidate"),
    ],
)
def test_new_guardian_oracles_watch_open_deduplicate_and_recover(
    tmp_path: Path,
    scenario_id: str,
    risk: str,
) -> None:
    result = run_guardian_lane(scenario(scenario_id), private_root(tmp_path))
    assert result.status == "PASS"
    assert result.counts[f"transition.watch_started.{risk}"] == 1
    assert result.counts[f"transition.alert_opened.{risk}"] == 1
    assert result.counts[f"transition.recovered.{risk}"] == 1
    assert result.counts[f"event.{risk}.recovered"] == 1
    assert result.counts["dashboard.open"] == 0
```

Run:

```bash
../../.venv-alpha/bin/python -m pytest -q \
  tests/contracts/test_offline_guardian_scenario.py \
  tests/integration/test_offline_guardian_scenario.py -k 'guardian or tracked_suite'
git diff --check
```

Expected: zero failures and no production event store access.

- [x] **Step 6: Commit**

```bash
git add tests/fixtures/offline_guardian_scenarios/scenarios.v1.json \
  tests/contracts/test_offline_guardian_scenario.py \
  tests/integration/test_offline_guardian_scenario.py
git commit -m "test: expand offline guardian scenario suite"
```

## Task 3: Enforce per-step Voice identity and bounded action counters

**Files:**

- Modify: `services/offline_guardian_scenario.py`
- Modify: `tools/offline_guardian_scenario.py`
- Modify: `tests/integration/test_offline_guardian_scenario.py`

**Interfaces:**

- `run_voice_lane` compares reason, response, action code and match kind for every
  speech-positive step.
- Produces five fixed `action.<code>` counters initialized to zero; only exact low-risk
  outcomes increment them.
- `_generated_voice_fixture()` maps opaque IDs to generated PCM and fixed ASR strings;
  no text enters a result or report.

- [x] **Step 1: Write Voice identity RED tests**

Extend fixture PCM/ASR mappings with these exact generated strings:

```python
texts = {
    "diaper_wake": "小小",
    "diaper_start": "开始换尿布",
    "diaper_wake_complete": "小小",
    "diaper_complete": "换好尿布了",
    "diaper_cross_burping": "嘿小小开始拍嗝",
    "diaper_ambiguous": "嘿小小开始换尿布然后开始拍嗝",
    "diaper_no_wake": "开始换尿布",
    "burping_wake": "小小",
    "burping_start": "开始拍嗝",
    "burping_wake_complete": "小小",
    "burping_complete": "拍嗝结束",
    "burping_cross_diaper": "嘿小小开始换尿布",
    "burping_ambiguous": "嘿小小开始拍嗝然后开始换尿布",
    "burping_no_wake": "开始拍嗝",
}
```

Use a unique nonzero amplitude per opaque ID. Assert each new scenario passes, produces
five responses, increments its two target counters once, increments the legal
cross-action counter once and leaves the other two action counters zero.

Add mismatch tests that change only expected action code or only expected match kind;
both must return `scenario_voice_mismatch`. Add explicit assertions that ambiguous and
no-wake steps produce no action counter increment.

Construct separate test-only Voice scenarios for an armed question, unsupported
command and exact medication candidate. Question/unsupported outcomes remain
`listen_only_ignored/null/null`; medication remains
`listen_only_high_risk_candidate/medication_start_candidate/high_risk_candidate` with
no response and no increment to any of the five low-risk action counters. These
additional controls do not enter the tracked seven-step diaper or burping scenarios.

- [x] **Step 2: Run RED**

```bash
../../.venv-alpha/bin/python -m pytest -q \
  tests/integration/test_offline_guardian_scenario.py -k voice
```

Expected: new scenarios fail because the fixture provider lacks their opaque IDs and
the lane does not compare action identity.

- [x] **Step 3: Implement exact per-step comparison**

Define the one ordered action set in `services/offline_guardian_scenario.py`:

```python
SCENARIO_ACTION_CODES = (
    "feeding_command",
    "diaper_change_start",
    "diaper_change_complete",
    "burping_start",
    "burping_complete",
)
```

Initialize all five counters to zero. After the existing `controller.handle` call,
compare:

```python
if (
    outcome.reason != step.expected_reason
    or outcome.response_code != step.expected_response_code
    or outcome.action_code != step.expected_action_code
    or outcome.match_kind != step.expected_match_kind
):
    return _voice_failure("scenario_voice_mismatch")
```

Increment only when `outcome.match_kind == "exact"` and the action code belongs to the
five-code tuple. Corrected Feeding remains represented by its outcome but cannot
increment an exact-action counter. A high-risk candidate cannot occur in this suite.

- [x] **Step 4: Extend the generated fixture provider**

Add all opaque step IDs from Task 2 to `_generated_voice_fixture()` using generated
memory-only PCM and the fixed strings above. Repeated semantic text may use distinct PCM
values because the lookup is by complete bytes. Retain no generated byte sequence after
the run.

- [x] **Step 5: Run GREEN and adjacent Voice gates**

```bash
../../.venv-alpha/bin/python -m pytest -q \
  tests/integration/test_offline_guardian_scenario.py -k voice \
  tests/voice/test_care_action.py \
  tests/voice/test_listen_only.py \
  tests/tools/test_voice_action_benchmark.py
../../.venv-alpha/bin/python -m compileall -q \
  services/offline_guardian_scenario.py tools/offline_guardian_scenario.py
git diff --check
```

Expected: zero false accepts in existing tests, no Camera Reply regression and no
external care intent or Baby Care import.

- [x] **Step 6: Commit**

```bash
git add services/offline_guardian_scenario.py \
  tools/offline_guardian_scenario.py \
  tests/integration/test_offline_guardian_scenario.py
git commit -m "feat: bind offline voice action outcomes"
```

## Task 4: Validate provenance before I/O and require exact visual accounting

**Files:**

- Modify: `services/offline_guardian_scenario.py`
- Modify: `tools/offline_guardian_scenario.py`
- Modify: `tests/integration/test_offline_guardian_scenario.py`
- Modify: `tests/tools/test_offline_guardian_scenario.py`

**Interfaces:**

- Produces `validate_visual_scenario_bindings(suite, manifest) -> tuple[VisualCorpusClip, ...]`.
- Accepts `PUBLIC_DATASET -> PUBLIC_VIDEO` and one direct
  `SYNTHETIC -> reviewed PUBLIC_DATASET same source_id -> GENERATED_VISUAL` derivation.
- `run_visual_lane(...)` requires exact total/processed frames and zero skip/drop/error.

- [x] **Step 1: Write provenance RED tests**

Cover these failures before calling downloader, preparer or model builder:

```text
unknown selected clip
duplicate selected clip identity
PUBLIC_DATASET declared GENERATED_VISUAL
SYNTHETIC declared PUBLIC_VIDEO
synthetic clip with missing parent
synthetic clip with another synthetic parent
synthetic clip with mismatched source_id
synthetic ancestry cycle
private-local or unsupported source type
sixth unexpected visual clip in the fixed selection
```

Use an explicit mutation such as
`model_copy(update={"parent_clip_id": "OCC-02"})` only to construct deliberately
impossible ancestry for the pure binding validator; do not weaken
`VisualCorpusManifest` production validation.
Patch downloader/model constructors and assert their call counts remain zero on failure.

- [x] **Step 2: Write exact-frame RED tests**

Update the existing generated-video test to assert:

```python
assert result.counts["frames.total"] == 65
assert result.counts["frames.processed"] == 65
assert result.counts["frames.skipped"] == 0
assert result.counts["frames.dropped"] == 0
assert result.counts["errors.decode"] == 0
assert result.counts["errors.worker"] == 0
```

Add parameterized failing aggregates for total mismatch, processed mismatch, one skip,
one drop, one decode error and one worker error. Every case returns FAIL with
`offline_scenario_visual_frame_mismatch` unless the underlying replay already returned a
more specific safe failure.

- [x] **Step 3: Run RED**

```bash
../../.venv-alpha/bin/python -m pytest -q \
  tests/integration/test_offline_guardian_scenario.py -k visual \
  tests/tools/test_offline_guardian_scenario.py -k 'selection or provenance or validate'
```

Expected: current minimum-frame logic accepts at least one deliberately mismatched case.

- [x] **Step 4: Implement the pure binding validator**

Build a unique clip map without silently overwriting duplicates. For each configured
visual lane, require one manifest clip, exact declared provenance and at most one direct
parent. For a synthetic clip, require:

```python
parent is not None
parent.source_type is SourceType.PUBLIC_DATASET
parent.source_id == clip.source_id
parent.parent_clip_id is None
```

Return clips in scenario order. Raise only
`offline_scenario_visual_provenance_invalid`. Call the validator in CLI validation and
before `_create_runtime_root()` in the runner. The CLI must call it before
`_prepare_selected_visuals()` and `_build_model_backend_quietly()`. Add this fixed
reason to the CLI `SAFE_REASONS` allowlist so normal output remains bounded and useful;
never return the offending clip, source or ancestry.

- [x] **Step 5: Implement exact frame settlement**

After mapping bounded counts, accept visual PASS only when:

```python
exact = (
    aggregate.frames_total == visual.expected_frames_processed
    and aggregate.frames_processed == visual.expected_frames_processed
    and aggregate.frames_skipped == 0
    and aggregate.dropped_frames == 0
    and aggregate.decode_errors == 0
    and aggregate.worker_errors == 0
)
```

Preserve an existing non-PASS replay reason. Use
`offline_scenario_visual_frame_mismatch` only when the replay claimed PASS but `exact`
is false.

- [x] **Step 6: Run GREEN and adjacent corpus gates**

```bash
../../.venv-alpha/bin/python -m pytest -q \
  tests/integration/test_offline_guardian_scenario.py -k visual \
  tests/tools/test_offline_guardian_scenario.py \
  tests/contracts/test_visual_corpus.py \
  tests/vision/test_corpus_replay.py
git diff --check
```

Expected: all malformed ancestry fails before I/O and all accepted visual lanes have
exact accounting.

- [x] **Step 7: Commit**

```bash
git add services/offline_guardian_scenario.py \
  tools/offline_guardian_scenario.py \
  tests/integration/test_offline_guardian_scenario.py \
  tests/tools/test_offline_guardian_scenario.py
git commit -m "fix: enforce offline visual provenance"
```

## Task 5: Expose independence and explicit observational counts safely

**Files:**

- Modify: `services/offline_guardian_scenario.py`
- Modify: `services/offline_guardian_report.py`
- Modify: `tests/integration/test_offline_guardian_scenario.py`

**Interfaces:**

- Runner copies `visual_oracle_relationship` from scenario declaration to result.
- Visual results include an explicit zero/nonzero count for every fixed realtime
  candidate transition key.
- JSON/HTML report names the relationship and states fixed non-proof semantics without
  clip-content claims.

- [x] **Step 1: Write result/report RED tests**

Assert both new Guardian scenarios report `INDEPENDENT`, Voice-only results report null,
and the JSON round-trip preserves the value. Add one visual result with no emitted
candidates and require explicit zero keys.

Construct the fixed key set from current enums:

```python
expected_candidate_keys = {
    f"candidate.{transition.value}.{candidate.value}"
    for transition in RealtimeCandidateTransitionKind
    for candidate in RealtimeCandidateKind
}
assert expected_candidate_keys <= set(result.counts)
assert all(result.counts[key] == 0 for key in expected_candidate_keys)
```

HTML assertions require `INDEPENDENT` and the fixed statement that visual counts are
observational and Guardian counts come from synthetic semantic oracles. Assert the
report does not call `DAY-03` a rollover/prone example or `OCC-03` an actual bed exit.

- [x] **Step 2: Run RED**

```bash
../../.venv-alpha/bin/python -m pytest -q \
  tests/integration/test_offline_guardian_scenario.py -k 'report or candidate or relationship'
```

Expected: relationship and zero candidate keys are absent.

- [x] **Step 3: Populate the fixed bounded candidate key set**

Import current candidate enums and create the Cartesian key set in stable enum order.
Fail closed with `offline_scenario_visual_aggregate_invalid` if the replay returns a
candidate key outside that set; do not silently drop it. Use
`aggregate.candidate_counts.get(key, 0)` for every allowed key. Reject overflow through
the existing 64-count contract; do not include raw observations or prose.

- [x] **Step 4: Propagate and render independence**

When building `OfflineScenarioResultV1`, copy
`scenario.visual_oracle_relationship`. Add a fixed report column or bounded field for
the relationship. Keep HTML escaped, script-free and without external resources.

- [x] **Step 5: Run GREEN and privacy checks**

```bash
../../.venv-alpha/bin/python -m pytest -q \
  tests/integration/test_offline_guardian_scenario.py
../../.venv-alpha/bin/python -m compileall -q \
  services/offline_guardian_scenario.py services/offline_guardian_report.py
git diff --check
```

Expected: canonical JSON and HTML pass, explicit zeros are bounded and no media/text
payload appears.

- [x] **Step 6: Commit**

```bash
git add services/offline_guardian_scenario.py \
  services/offline_guardian_report.py \
  tests/integration/test_offline_guardian_scenario.py
git commit -m "feat: report independent scenario evidence"
```

## Task 6: Lock the fixed CLI and run the complete bounded suite

**Files:**

- Modify: `tools/offline_guardian_scenario.py`
- Modify: `tests/tools/test_offline_guardian_scenario.py`
- Modify: `Makefile` only if the existing fixed target commands no longer match

**Interfaces:**

- `VISUAL_CLIP_IDS = ("DAY-01", "OCC-02", "NEG-03", "DAY-03", "OCC-03")`.
- Fixed validation reports eight scenarios, thirteen lanes, five visual clips and 330
  expected frames.
- Fixed run reports eight scenario results, thirteen lanes and 330 processed frames.

- [x] **Step 1: Write fixed CLI RED tests**

Update validation output exactly:

```text
result=PASS
suite_id=offline-guardian-v1
scenario_count=8
lane_count=13
visual_clip_count=5
expected_frame_count=330
```

Update the selection test to require source types
`PUBLIC_DATASET,SYNTHETIC,PUBLIC_DATASET,PUBLIC_DATASET,SYNTHETIC` in exact clip order.
Assert three unique public source IDs and declared bytes `25_964_039`, still below
`MAX_FIRST_STAGE_BYTES`.

Extend the patched run-output test with `frame_count=330`. Retain rejection of caller
URL/path/model/port and the source-code scan for Xiaomi, go2rtc, Camera Reply, Ollama,
notifications and Baby Care clients.

- [x] **Step 2: Run RED**

```bash
../../.venv-alpha/bin/python -m pytest -q \
  tests/tools/test_offline_guardian_scenario.py
```

Expected: old constants report four scenarios, seven lanes and three clips.

- [x] **Step 3: Implement the exact constants and aggregate output**

Add fixed constants:

```python
VISUAL_CLIP_IDS = ("DAY-01", "OCC-02", "NEG-03", "DAY-03", "OCC-03")
EXPECTED_SCENARIO_COUNT = 8
EXPECTED_LANE_COUNT = 13
EXPECTED_FRAME_COUNT = 330
```

Validation compares computed values to all constants and fails with the existing
redacted command reason on mismatch. Run output computes processed frames only from
visual lane `frames.processed`; it does not trust the constant as observed output.

- [x] **Step 4: Run CLI GREEN and dry-runs**

```bash
../../.venv-alpha/bin/python -m pytest -q \
  tests/contracts/test_offline_guardian_scenario.py \
  tests/integration/test_offline_guardian_scenario.py \
  tests/tools/test_offline_guardian_scenario.py
../../.venv-alpha/bin/python tools/offline_guardian_scenario.py validate
make -n alpha-offline-scenario-validate
make -n alpha-offline-scenario-run
git diff --check
```

Expected: fixed validation PASS with 8/13/5/330 and no device access.

- [x] **Step 5: Run the actual bounded public/generated suite**

```bash
../../.venv-alpha/bin/python tools/offline_guardian_scenario.py run
```

Require all of the following before calling the run PASS:

```text
scenario_count=8
pass_count=8
skip_count=0
fail_count=0
lane_count=13
frame_count=330
```

Inspect the ignored canonical report for 330 total/processed visual frames, zero
skipped/dropped/decode/worker errors, both `INDEPENDENT` relationships and exact Voice
action counters. Do not change expected results after observing output. A model
capability count of zero remains an observation, not a defect to hide.

- [x] **Step 6: Commit**

```bash
git add tools/offline_guardian_scenario.py \
  tests/tools/test_offline_guardian_scenario.py Makefile
git commit -m "feat: run expanded offline guardian scenarios"
```

If `Makefile` did not change, omit it from `git add` rather than staging it needlessly.

## Task 7: Run full verification, review and factual handoff

**Files:**

- Modify: `SUMMARY.md`
- Modify: `docs/STATUS.md`
- Modify: `docs/CHECKPOINT.md`
- Modify: `docs/NEXT.md`
- Modify: `docs/superpowers/plans/2026-08-30-offline-guardian-scenario-expansion.md`

**Interfaces:**

- Records exact software/public/generated evidence and actual test counts.
- Leaves real-baby accuracy, public/private readiness, Camera Reply, medication and Baby
  Care writes separately gated.

- [x] **Step 1: Run the fresh focused gate**

```bash
../../.venv-alpha/bin/python -m pytest -q \
  tests/contracts/test_offline_guardian_scenario.py \
  tests/integration/test_offline_guardian_scenario.py \
  tests/tools/test_offline_guardian_scenario.py \
  tests/contracts/test_visual_corpus.py \
  tests/vision/test_corpus_replay.py \
  tests/vision/test_corpus_guardian_projection.py \
  tests/vision/test_risk_state.py \
  tests/voice/test_care_action.py \
  tests/voice/test_listen_only.py \
  tests/tools/test_voice_action_benchmark.py
```

Expected: exit 0 with no unexpected skip or false accept.

- [x] **Step 2: Run complete software/static gates**

```bash
../../.venv-alpha/bin/python -m pytest -q
node --test tests/frontend/*.test.mjs
../../.venv-alpha/bin/python -m compileall -q packages services tools
bash -n tools/*.sh
make -n alpha-offline-scenario-validate
make -n alpha-offline-scenario-run
git diff --check
```

Expected: all commands exit 0. Record the actual counts; retain only the existing
documented public-corpus expected skip if it still occurs.

- [x] **Step 3: Run bounded repository/privacy checks**

```bash
git status --short
git diff --name-only HEAD~6..HEAD
git ls-files | rg -i '\.(mp4|mov|mkv|webm|wav|pcm|sqlite|sqlite3)$' || true
git diff --unified=0 HEAD~6..HEAD | rg -n -i \
  'V1:|password|token|secret|private[_ -]?key|/Users/|/workspace/|192\.168\.|10\.[0-9]+\.' || true
```

Expected: only planned source/test/fixture/docs files changed; no tracked runtime media,
database, credential, private path or network literal. Review every match rather than
assuming empty output.

- [ ] **Step 4: Perform independent review**

Review exact contract closure, direct-parent provenance, validation-before-I/O ordering,
330-frame settlement, visual/oracle independence, Guardian dedup/recovery, Voice
cross-action identity, ambiguous/no-wake silence, cleanup, report privacy and prohibited
client absence. Resolve each Critical or Important finding with a new RED/GREEN commit.

- [x] **Step 5: Update factual handoff documents**

Record exact head, scenario/lane/frame results, test counts, changed files and what the
run does not prove. Set the next ordered stage to low-risk Voice decision reconciliation;
do not authorize a household run in prose.

- [x] **Step 6: Commit the closure**

```bash
git add SUMMARY.md docs/STATUS.md docs/CHECKPOINT.md docs/NEXT.md \
  docs/superpowers/plans/2026-08-30-offline-guardian-scenario-expansion.md
git commit -m "docs: record offline scenario expansion gate"
```

Do not push, create a PR, merge or change `main/stable` without a new explicit request.

## Execution handoff

Execute Tasks 1-7 in order. Stop after each task if its focused GREEN is not clean.
After Task 7, report local/remote heads separately, all commits, exact test output,
actual 8/13/330 result, privacy findings, non-proof boundaries and the next gated stage.
