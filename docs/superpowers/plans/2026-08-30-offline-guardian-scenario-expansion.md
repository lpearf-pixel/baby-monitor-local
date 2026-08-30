# Offline Guardian Scenario Expansion Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Extend the fixed offline Guardian scenario command from four scenarios and seven lanes to eight scenarios and thirteen lanes while preserving visual/oracle independence, exact public-media frame accounting and privacy-safe generated Voice behavior.

**Architecture:** Keep the existing `OfflineGuardianScenarioRunner` and its three isolated lane adapters. Extend the closed schema and fixture first, then enforce exact visual provenance/frame contracts, add deterministic prone/outside Guardian timelines, bind every generated Voice step to its expected action/match result, and finally run the same fixed public-media CLI to publish one bounded ignored report. Actual visual observations remain independent from synthetic Guardian oracles and are never treated as ground truth.

**Tech Stack:** Python 3.11+, Pydantic 2, pytest, existing `VisualCorpusReplay`, existing `GuardianReplayProjector`, existing `ListenOnlyController`, SQLite through existing isolated services, ffmpeg through the existing corpus preparation path.

**Spec:** `docs/superpowers/specs/2026-08-29-offline-guardian-scenario-expansion-design.md`

## Global Constraints

- Work only on `codex/visual-regression-corpus`; do not modify `main` or `stable/xiaomi-alpha`.
- Do not access Xiaomi authentication, camera, CS2, go2rtc, microphone, speaker, Camera Reply, PTZ, Ollama, notification, Baby Care or production SQLite.
- Use only admitted `PUBLIC_DATASET` clips, their one-level `SYNTHETIC` derivatives and generated in-memory PCM.
- Keep public readiness `PARTIAL`; do not generate, compare or promote a baseline.
- Visual observations and Guardian semantic oracles have relationship `INDEPENDENT`; neither may consume or satisfy the other.
- Select exactly `DAY-01`, `OCC-02`, `NEG-03`, `DAY-03`, `OCC-03` at `analysis_realtime` 5 FPS.
- Require exact frame counts 65/50/50/100/65, total 330, and zero skipped/dropped/decode/worker frames.
- Permit exactly one reviewed direct `PUBLIC_DATASET` parent for `SYNTHETIC` clips; reject deeper, synthetic-parent, cyclic, missing, duplicate, private or source-mismatched ancestry before media preparation.
- Outputs remain bounded, media-free and locator-free below ignored owner-private runtime; report files are `0600` below `0700` directories.
- Every task uses RED -> GREEN, focused verification and a focused commit. Do not push, create a PR or merge without separate approval.

---

## File and interface map

- Modify `packages/contracts/offline_guardian_scenario.py`: add exact visual frames, explicit visual/oracle relationship, Voice action/match expectations and result bounds.
- Modify `tests/fixtures/offline_guardian_scenarios/scenarios.v1.json`: define the fixed eight scenarios and thirteen lanes without locators or transcript text.
- Modify `services/offline_guardian_scenario.py`: enforce exact visual accounting and per-step Voice action/match classification plus bounded action counters.
- Modify `tools/offline_guardian_scenario.py`: select five fixed clips, validate one-level public derivation, and generate opaque PCM/ASR fixtures for Feeding, diaper and burping scenarios.
- Modify `services/offline_guardian_report.py` only if the existing bounded result renderer needs an explicit visual/oracle relationship field; do not widen its privacy surface.
- Modify `tests/contracts/test_offline_guardian_scenario.py`, `tests/integration/test_offline_guardian_scenario.py` and `tests/tools/test_offline_guardian_scenario.py` for RED/GREEN coverage.
- Modify `SUMMARY.md`, `docs/STATUS.md`, `docs/CHECKPOINT.md`, `docs/NEXT.md` and this plan only after the exact fixed run and all verification gates finish.

## Task 1: Close the expanded scenario contract and fixture

**Files:**
- Modify: `packages/contracts/offline_guardian_scenario.py`
- Modify: `tests/contracts/test_offline_guardian_scenario.py`
- Modify: `tests/fixtures/offline_guardian_scenarios/scenarios.v1.json`

**Interfaces:**
- `VisualScenarioV1.expected_frames_processed: int` replaces the one-frame minimum with an exact value.
- `OfflineGuardianScenarioV1.visual_oracle_relationship: Literal["INDEPENDENT"] | None` is required exactly when both visual and Guardian lanes are configured.
- `VoiceScenarioStepV1.expected_action_code: ActionCode | None` and `expected_match_kind: Literal["exact", "corrected", "high_risk_candidate"] | None` bind each step outcome.
- The fixture contains exactly eight unique scenario IDs and thirteen required lanes.

- [x] **Step 1: Write contract RED tests**

Add tests that require exact IDs, lane totals, relationship coherence, expected frame values and Voice action/match pairs:

```python
def test_expanded_suite_has_exact_ids_lanes_and_frames() -> None:
    suite = load_offline_scenario_suite(FIXTURE)
    assert tuple(item.scenario_id for item in suite.scenarios) == (
        "SAFE-SLEEP-01", "FACE-OCCLUSION-01", "ADULT-INTERVENTION-01",
        "VOICE-FEEDING-01", "PRONE-CANDIDATE-01", "OUTSIDE-CANDIDATE-01",
        "VOICE-DIAPER-01", "VOICE-BURPING-01",
    )
    assert sum(len(item.required_lanes) for item in suite.scenarios) == 13
    assert [item.visual.expected_frames_processed for item in suite.scenarios if item.visual] == [65, 50, 50, 100, 65]


def test_visual_guardian_pair_requires_independent_relationship() -> None:
    payload = scenario_payload()
    payload["visual_oracle_relationship"] = None
    with pytest.raises(ValidationError):
        OfflineGuardianScenarioV1.model_validate(payload)


def test_voice_step_rejects_half_bound_action_identity() -> None:
    payload = {
        "step_id": "burping_start",
        "speech_expected": True,
        "from_replay": False,
        "expected_reason": "listen_only_acknowledged",
        "expected_response_code": "listen_only_received",
        "expected_action_code": "burping_start",
        "expected_match_kind": None,
    }
    with pytest.raises(ValidationError):
        contracts().VoiceScenarioStepV1.model_validate(payload)
```

- [x] **Step 2: Run RED**

Run:

```bash
../../.venv-alpha/bin/python -m pytest -q tests/contracts/test_offline_guardian_scenario.py
```

Expected: FAIL because the new fields and eight-scenario fixture do not exist.

- [x] **Step 3: Implement the minimum contract changes**

Keep the contracts package independent from service modules. Define a closed local
`ScenarioActionCode` literal with the same seven current care-action values and use it
for expectations:

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


class VisualScenarioV1(OfflineScenarioContract):
    clip_id: str
    profile: Literal["analysis_realtime", "analysis_slow"]
    expected_frames_processed: int = Field(ge=1, le=18_000)
    provenance: Literal["PUBLIC_VIDEO", "GENERATED_VISUAL"]


class VoiceScenarioStepV1(OfflineScenarioContract):
    # existing fields remain
    expected_action_code: ScenarioActionCode | None = None
    expected_match_kind: Literal["exact", "corrected", "high_risk_candidate"] | None = None

    @model_validator(mode="after")
    def require_action_identity_pair(self) -> "VoiceScenarioStepV1":
        if (self.expected_action_code is None) != (self.expected_match_kind is None):
            raise ValueError("offline_scenario_voice_invalid")
        return self
```

Require `visual_oracle_relationship="INDEPENDENT"` for scenarios containing both visual and Guardian lanes and `None` otherwise. Update the fixture to the exact eight IDs. Set `OCC-02` and `OCC-03` provenance to `GENERATED_VISUAL`; the other three visual clips remain `PUBLIC_VIDEO`.

- [x] **Step 4: Run GREEN and static checks**

```bash
../../.venv-alpha/bin/python -m pytest -q tests/contracts/test_offline_guardian_scenario.py tests/contracts/test_visual_corpus.py
../../.venv-alpha/bin/python -m compileall -q packages/contracts/offline_guardian_scenario.py
git diff --check
```

- [x] **Step 5: Commit**

```bash
git add packages/contracts/offline_guardian_scenario.py tests/contracts/test_offline_guardian_scenario.py tests/fixtures/offline_guardian_scenarios/scenarios.v1.json docs/superpowers/plans/2026-08-30-offline-guardian-scenario-expansion.md
git commit -m "feat: define expanded offline scenarios"
```

## Task 2: Enforce exact visual selection, ancestry and frame accounting

**Files:**
- Modify: `services/offline_guardian_scenario.py`
- Modify: `tools/offline_guardian_scenario.py`
- Modify: `tests/integration/test_offline_guardian_scenario.py`
- Modify: `tests/tools/test_offline_guardian_scenario.py`

**Interfaces:**
- `VISUAL_CLIP_IDS = ("DAY-01", "OCC-02", "NEG-03", "DAY-03", "OCC-03")`.
- `_is_public_or_public_derived` accepts public clips or one direct reviewed public parent with identical `source_id` and no parent of its own.
- `run_visual_lane` passes only when total and processed equal `expected_frames_processed` and skipped/dropped/decode/worker are all zero.

- [x] **Step 1: Write visual RED tests**

Add tests for the exact five-clip order, `OCC-02` provenance correction, `OCC-03` direct parent, synthetic-parent/deeper/source-mismatch rejection before downloader/preparer calls, and exact frame accounting:

```python
def test_visual_lane_rejects_non_exact_frame_accounting(tmp_path: Path) -> None:
    media = tmp_path / "public-fixture.mkv"
    generated_video(media, duration_seconds=13)
    value = scenario("SAFE-SLEEP-01")
    changed = value.model_copy(update={
        "visual": value.visual.model_copy(update={"expected_frames_processed": 64}),
    })
    result = run_visual_lane(
        changed,
        load_manifest(VISUAL_MANIFEST),
        lambda _clip, _profile: media,
        tmp_path,
        AvailableVisualBackend(),
    )
    assert (result.status, result.reason) == ("FAIL", "offline_scenario_visual_accounting_mismatch")
```

- [x] **Step 2: Run RED**

```bash
../../.venv-alpha/bin/python -m pytest -q tests/integration/test_offline_guardian_scenario.py -k visual tests/tools/test_offline_guardian_scenario.py -k 'selected or provenance or frame'
```

Expected: FAIL because selection has three IDs and the visual lane accepts a minimum.

- [x] **Step 3: Implement exact visual gates**

After building the bounded count map, require:

```python
accounting_ok = (
    aggregate.frames_total == visual.expected_frames_processed
    and aggregate.frames_processed == visual.expected_frames_processed
    and aggregate.frames_skipped == 0
    and aggregate.dropped_frames == 0
    and aggregate.decode_errors == 0
    and aggregate.worker_errors == 0
)
```

If the replay itself passes but `accounting_ok` is false, return `FAIL` with `offline_scenario_visual_accounting_mismatch`. Keep all observation/candidate counts factual, including zeros; never compare them with scenario labels or Guardian oracle expectations.

- [x] **Step 4: Run GREEN**

```bash
../../.venv-alpha/bin/python -m pytest -q tests/integration/test_offline_guardian_scenario.py -k visual tests/tools/test_offline_guardian_scenario.py
../../.venv-alpha/bin/python -m compileall -q services/offline_guardian_scenario.py tools/offline_guardian_scenario.py
git diff --check
```

- [x] **Step 5: Commit**

```bash
git add services/offline_guardian_scenario.py tools/offline_guardian_scenario.py tests/integration/test_offline_guardian_scenario.py tests/tools/test_offline_guardian_scenario.py docs/superpowers/plans/2026-08-30-offline-guardian-scenario-expansion.md
git commit -m "test: require exact offline visual replay"
```

## Task 3: Add independent prone and outside Guardian oracles

**Files:**
- Modify: `tests/fixtures/offline_guardian_scenarios/scenarios.v1.json`
- Modify: `tests/contracts/test_offline_guardian_scenario.py`
- Modify: `tests/integration/test_offline_guardian_scenario.py`

**Interfaces:**
- `PRONE-CANDIDATE-01`: visual `DAY-03`; separate synthetic `prone_candidate` watch/open/dedup/recovery timeline.
- `OUTSIDE-CANDIDATE-01`: visual `OCC-03`; separate synthetic `outside_candidate` watch/open/dedup/recovery timeline.
- Each final Dashboard projection contains one recovered event and zero open events.

- [x] **Step 1: Write Guardian RED tests**

```python
@pytest.mark.parametrize(("scenario_id", "risk"), [
    ("PRONE-CANDIDATE-01", "prone_candidate"),
    ("OUTSIDE-CANDIDATE-01", "outside_candidate"),
])
def test_new_guardian_oracle_opens_deduplicates_and_recovers(
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

Also assert the visual lane result is neither read by nor passed into `run_guardian_lane`, and a visual failure does not rewrite the oracle result.

- [x] **Step 2: Run RED**

```bash
../../.venv-alpha/bin/python -m pytest -q tests/contracts/test_offline_guardian_scenario.py tests/integration/test_offline_guardian_scenario.py -k 'prone or outside or independent'
```

Expected: FAIL until both exact timelines and counts exist.

- [x] **Step 3: Add the fixed timelines**

For each risk, use two qualifying reviews ten seconds apart, one duplicate qualifying review ten seconds later, then two explicit safe reviews ten seconds apart. Use only current `VisualReview` enum values and stable risk/reason codes. Expected counts are exactly one watch, one open, one recovery, no duplicate event, one recovered event and zero open Dashboard events.

- [x] **Step 4: Run GREEN**

```bash
../../.venv-alpha/bin/python -m pytest -q tests/contracts/test_offline_guardian_scenario.py tests/integration/test_offline_guardian_scenario.py -k 'guardian or prone or outside or independent' tests/vision/test_corpus_guardian_projection.py tests/vision/test_risk_state.py
git diff --check
```

- [x] **Step 5: Commit**

```bash
git add tests/fixtures/offline_guardian_scenarios/scenarios.v1.json tests/contracts/test_offline_guardian_scenario.py tests/integration/test_offline_guardian_scenario.py docs/superpowers/plans/2026-08-30-offline-guardian-scenario-expansion.md
git commit -m "test: cover independent Guardian candidates"
```

## Task 4: Bind generated Voice steps to exact action identity

**Files:**
- Modify: `services/offline_guardian_scenario.py`
- Modify: `tools/offline_guardian_scenario.py`
- Modify: `tests/fixtures/offline_guardian_scenarios/scenarios.v1.json`
- Modify: `tests/integration/test_offline_guardian_scenario.py`
- Modify: `tests/tools/test_offline_guardian_scenario.py`

**Interfaces:**
- Each step compares `reason`, `response_code`, `action_code` and `match_kind`.
- Lane counts include only bounded keys `action.<ActionCode>` for non-null exact action outcomes.
- `VOICE-DIAPER-01` and `VOICE-BURPING-01` each contain exactly seven steps and five responses: two ready, two target acknowledgements and one legal cross-action acknowledgement.

- [ ] **Step 1: Write Voice RED tests**

Cover diaper/burping start and complete, legal cross-action self-classification, ambiguous multi-action silence, no-wake silence, wrong action/match rejection and bounded counters:

```python
def expanded_voice_fixtures() -> tuple[dict[str, bytes], ScenarioAsr]:
    text_by_step = {
        "diaper_wake_start": "小小",
        "diaper_start": "开始换尿布",
        "diaper_wake_complete": "小小",
        "diaper_complete": "换好尿布了",
        "diaper_cross_burping": "小小开始拍嗝",
        "diaper_ambiguous": "小小开始换尿布然后开始拍嗝",
        "diaper_no_wake": "开始换尿布",
        "burping_wake_start": "小小",
        "burping_start": "开始拍嗝",
        "burping_wake_complete": "小小",
        "burping_complete": "拍嗝结束",
        "burping_cross_diaper": "小小开始换尿布",
        "burping_ambiguous": "小小开始拍嗝然后开始换尿布",
        "burping_no_wake": "开始拍嗝",
    }
    pcm = {
        step_id: generated_pcm(8_000 + index)
        for index, step_id in enumerate(text_by_step)
    }
    return pcm, ScenarioAsr({pcm[key]: value for key, value in text_by_step.items()})


def test_voice_lane_rejects_right_reply_with_wrong_action() -> None:
    value = scenario("VOICE-FEEDING-01")
    steps = list(value.voice.steps)
    steps[1] = steps[1].model_copy(update={"expected_action_code": "burping_start"})
    changed = value.model_copy(update={
        "voice": value.voice.model_copy(update={"steps": tuple(steps)}),
    })
    fixtures, asr = voice_fixtures()
    result = run_voice_lane(
        changed, fixtures.__getitem__, speech_vad(), asr, RecordingScenarioSynth()
    )
    assert (result.status, result.reason) == ("FAIL", "scenario_voice_mismatch")


def test_diaper_voice_counts_target_and_cross_action_exactly() -> None:
    fixtures, asr = expanded_voice_fixtures()
    result = run_voice_lane(
        scenario("VOICE-DIAPER-01"),
        fixtures.__getitem__,
        speech_vad(),
        asr,
        RecordingScenarioSynth(),
    )
    assert result.counts["action.diaper_change_start"] == 1
    assert result.counts["action.diaper_change_complete"] == 1
    assert result.counts["action.burping_start"] == 1
    assert result.counts["responses.total"] == 5
```

- [ ] **Step 2: Run RED**

```bash
../../.venv-alpha/bin/python -m pytest -q tests/integration/test_offline_guardian_scenario.py -k voice tests/tools/test_offline_guardian_scenario.py -k voice
```

Expected: FAIL because outcomes are not compared by action/match and the two fixtures do not exist.

- [ ] **Step 3: Implement per-step matching and generated fixtures**

Extend the mismatch predicate:

```python
if (
    outcome.reason != step.expected_reason
    or outcome.response_code != step.expected_response_code
    or outcome.action_code != step.expected_action_code
    or outcome.match_kind != step.expected_match_kind
):
    return _voice_failure("scenario_voice_mismatch")
```

Increment `action.<code>` only when both action code and match kind are non-null. Generate unique PCM byte strings for every opaque step ID and map them to exact in-memory ASR text. Do not serialize ASR text or PCM. Ambiguous multi-action and no-wake steps expect null action/match and no response.

- [ ] **Step 4: Run GREEN and adjacent Voice gates**

```bash
../../.venv-alpha/bin/python -m pytest -q tests/integration/test_offline_guardian_scenario.py -k voice tests/tools/test_offline_guardian_scenario.py tests/voice/test_listen_only.py tests/voice/test_care_action.py
../../.venv-alpha/bin/python -m compileall -q services/offline_guardian_scenario.py tools/offline_guardian_scenario.py
git diff --check
```

- [ ] **Step 5: Commit**

```bash
git add services/offline_guardian_scenario.py tools/offline_guardian_scenario.py tests/fixtures/offline_guardian_scenarios/scenarios.v1.json tests/integration/test_offline_guardian_scenario.py tests/tools/test_offline_guardian_scenario.py docs/superpowers/plans/2026-08-30-offline-guardian-scenario-expansion.md
git commit -m "feat: verify generated care actions"
```

## Task 5: Close eight-scenario orchestration and report contracts

**Files:**
- Modify: `tests/integration/test_offline_guardian_scenario.py`
- Modify: `tests/tools/test_offline_guardian_scenario.py`
- Modify: `services/offline_guardian_report.py` only if required by a failing relationship-report test.

**Interfaces:**
- Validation reports `scenario_count=8`, `visual_clip_count=5`.
- Execution reports exactly 8 results and 13 lanes in fixture order.
- `OfflineScenarioResultV1.visual_oracle_relationship` copies the declared value and
  exposes `INDEPENDENT` for paired scenarios without adding media, transcript, paths,
  URLs or raw errors.

- [ ] **Step 1: Write orchestration/report RED tests**

```python
def test_expanded_runner_has_eight_scenarios_and_thirteen_lanes(tmp_path: Path) -> None:
    media = tmp_path / "public-fixture.mkv"
    generated_video(media, duration_seconds=20)
    run = build_runner(tmp_path, media).run(load_offline_scenario_suite(FIXTURE))
    assert len(run.results) == 8
    assert sum(len(result.lanes) for result in run.results) == 13


def test_report_keeps_visual_and_oracle_relationship_explicit(tmp_path: Path) -> None:
    base = report_run()
    paired = base.results[0].model_copy(
        update={"visual_oracle_relationship": "INDEPENDENT"}
    )
    run = base.model_copy(update={"results": (paired,)})
    json_path, _html_path = publish_offline_scenario_report(
        run, report_destination(tmp_path)
    )
    payload = json.loads(json_path.read_text("ascii"))
    paired_results = [
        item for item in payload["results"] if len(item["lanes"]) == 2
    ]
    assert all(
        item["visual_oracle_relationship"] == "INDEPENDENT"
        for item in paired_results
    )
```

If the existing canonical result already contains the relationship in a privacy-safe location, test and reuse it. Otherwise add the smallest closed result field; do not infer it from lane outputs during rendering.

- [ ] **Step 2: Run RED**

```bash
../../.venv-alpha/bin/python -m pytest -q tests/integration/test_offline_guardian_scenario.py tests/tools/test_offline_guardian_scenario.py
```

Expected: FAIL on four-scenario/seven-lane assumptions or missing explicit relationship.

- [ ] **Step 3: Implement the minimum orchestration/report closure**

Retain current order, deadlines, fresh Voice factories, filesystem checks, first-failure behavior and atomic report publication. Change no Guardian rule, model threshold, worker logic or report size cap.

- [ ] **Step 4: Run GREEN and privacy checks**

```bash
../../.venv-alpha/bin/python -m pytest -q tests/contracts/test_offline_guardian_scenario.py tests/integration/test_offline_guardian_scenario.py tests/tools/test_offline_guardian_scenario.py
../../.venv-alpha/bin/python -m compileall -q packages/contracts/offline_guardian_scenario.py services/offline_guardian_scenario.py services/offline_guardian_report.py tools/offline_guardian_scenario.py
make -n alpha-offline-scenario-validate
make -n alpha-offline-scenario-run
git diff --check
```

- [ ] **Step 5: Commit**

```bash
git add packages/contracts/offline_guardian_scenario.py services/offline_guardian_scenario.py services/offline_guardian_report.py tools/offline_guardian_scenario.py tests/contracts/test_offline_guardian_scenario.py tests/integration/test_offline_guardian_scenario.py tests/tools/test_offline_guardian_scenario.py docs/superpowers/plans/2026-08-30-offline-guardian-scenario-expansion.md
git commit -m "feat: run expanded offline Guardian flow"
```

## Task 6: Execute the fixed public-media flow and close the milestone

**Files:**
- Modify: `SUMMARY.md`
- Modify: `docs/STATUS.md`
- Modify: `docs/CHECKPOINT.md`
- Modify: `docs/NEXT.md`
- Modify: `docs/superpowers/plans/2026-08-30-offline-guardian-scenario-expansion.md`

**Interfaces:**
- Records actual eight-scenario/thirteen-lane output, 330-frame accounting, candidate observations and performance aggregates.
- Records separately what software/public media proves and what remains real-baby, Xiaomi, Voice recall, private corpus and baseline gated.

- [ ] **Step 1: Run the fixed validation and bounded replay**

```bash
../../.venv-alpha/bin/python tools/offline_guardian_scenario.py validate
../../.venv-alpha/bin/python tools/offline_guardian_scenario.py run
```

Require `scenario_count=8`, `visual_clip_count=5`, `pass_count=8`, `fail_count=0`, `skip_count=0`, `lane_count=13`. Inspect only bounded aggregate JSON; require total visual frames 330 and every skipped/dropped/decode/worker count zero. Record factual model observations even when candidate counts are zero.

- [ ] **Step 2: Run complete verification**

```bash
../../.venv-alpha/bin/python -m pytest -q tests/contracts/test_offline_guardian_scenario.py tests/integration/test_offline_guardian_scenario.py tests/tools/test_offline_guardian_scenario.py tests/vision/test_corpus_replay.py tests/vision/test_corpus_guardian_projection.py tests/vision/test_risk_state.py tests/voice/test_listen_only.py tests/voice/test_care_action.py tests/api/test_alpha_app.py
../../.venv-alpha/bin/python -m pytest -q
node --test tests/frontend/*.test.mjs
../../.venv-alpha/bin/python -m compileall -q packages services tools
bash -n tools/*.sh
make -n alpha-offline-scenario-validate
make -n alpha-offline-scenario-run
git diff --check
```

Also parse tracked JSON, scan tracked files for media, scan added lines for credentials/private addresses/paths and confirm no camera/go2rtc/Ollama/notification/Baby Care process was initialized by the fixed flow.

- [ ] **Step 3: Perform read-only final review**

Review schema closure, one-level provenance, exact frames, visual/oracle independence, Voice action identity, cancellation/settlement, filesystem publication, report privacy and prohibited client initialization. Resolve every Critical or Important finding with a new RED/GREEN cycle.

- [ ] **Step 4: Update factual handoff documents**

Record the exact run ID, counts, performance and verification results. Do not claim model accuracy, public corpus READY, baseline approval, Xiaomi compatibility, real Voice recall or unattended safety.

- [ ] **Step 5: Commit the closure**

```bash
git add SUMMARY.md docs/STATUS.md docs/CHECKPOINT.md docs/NEXT.md docs/superpowers/plans/2026-08-30-offline-guardian-scenario-expansion.md
git commit -m "docs: record expanded offline Guardian flow"
```

Do not push, create a PR or merge without separate approval.
