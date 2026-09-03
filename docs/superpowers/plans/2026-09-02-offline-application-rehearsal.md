# Offline Application Rehearsal Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use
> superpowers:subagent-driven-development (recommended) or superpowers:executing-plans
> to implement this plan one task at a time with review checkpoints. Do not dispatch
> tasks that share contracts, fixtures, runner or report state in parallel.

**Goal:** Rehearse the complete low-risk Voice + Guardian + event/projection +
output-decision flow with historical aggregate evidence, public/generated fixtures,
recording sinks, fixed failures and repeat quotas before requesting one panoramic
real-device test.

**Architecture:** Add a separate `offline-application-rehearsal-v1` contract and runner
above existing production-safe boundaries. The runner imports the accepted
`offline-guardian-v1` result once, executes twelve deterministic functional scenarios
from fresh roots, runs a fixed failure pack, and repeats the application and cross-risk
gates. Historical evidence is a read-only ledger and never contributes to fresh PASS.
Real outputs are replaced by bounded recording sinks; the private atomic report stores
only closed IDs, counts, digests and evidence classes.

**Tech Stack:** Python 3.11+, Pydantic 2, pytest, existing `ListenOnlyController`,
`VisualRiskStateMachine`, `VisualRiskEventPipeline`, `VisualRiskEventStore`,
`GuardianEventQueryService`, SHA-256 canonical JSON, Make.

**Spec:**
`docs/superpowers/specs/2026-09-02-offline-application-rehearsal-design.md`.

## Global Constraints

- This plan depends on every gate in
  `docs/superpowers/plans/2026-09-02-visual-cross-risk-correction.md`. Verify that
  `services/vision/risk_evidence.py` exists and its full gate is green before Task 1.
- Start from a clean current descendant of the published visual branch. Fetch and
  inspect a newer remote head; never reset, rebase or force-push over it.
- `camera_reply_enabled=false` is a literal report invariant. Do not import or
  instantiate `CameraReplyOutput`, Xiaomi/go2rtc clients, PTZ, real notification
  dispatch, Baby Care clients/signers/outboxes, or private media readers.
- Use only generated mono PCM, fixed ASR objects, deterministic `VisualReview` values
  and the already approved public/generated offline visual suite.
- Do not persist raw PCM, speech text, transcripts, model prose, exception text,
  household frames, URLs, host/device identifiers or absolute private paths.
- Historical evidence is displayed only under `HISTORICAL`, always has
  `fresh_for_this_run=false`, and is excluded from fresh scenario/fault/repetition
  totals and PASS calculation.
- Visual observation and application oracle evidence remain `INDEPENDENT`. Never use a
  public clip label or model candidate as deterministic Guardian truth.
- One fault must not stop an independent sibling result. Keep the first stable closed
  reason, run bounded cleanup, and never fabricate PASS after an exception.
- Each task follows RED -> GREEN, focused verification and the named focused commit.
  Stop if any task requires a production adapter or weakens an existing gate.

---

## Task Brief

| Field | Contract |
|---|---|
| Current state | The original eight-scenario flow passes as a component test, low-risk Voice actions are software-reachable, live per-action decisions remain `NOT_PROVEN`, and repeated on-site tests are paused. |
| Goal state | One command proves the imported 8/13/330 component result, twelve application scenarios, fixed fault behavior, ten fresh full runs, fifty cross-risk instances, stable normalized digests, zero forbidden side effects and private atomic reporting. |
| Allowed scope | New rehearsal contracts/fixtures/runner/recording sinks/report/tool, a public wrapper around the old fixed-flow executor, Make targets, focused tests and factual status/checkpoint updates. |
| Prohibited scope | Real devices/private media, Camera Reply, notifications, Baby Care, medication action output, live PASS publication, model tuning, corpus/baseline promotion, PR/merge, protected branches. |
| Delivery | Focused commits on `codex/visual-regression-corpus`; software PASS authorizes only a later request for one panoramic session. |

## Exact versioned contract

Create `packages/contracts/offline_application_rehearsal.py` with frozen,
`extra="forbid"` Pydantic models and these closed aliases/enums:

```python
EvidenceClass = Literal["HISTORICAL", "SOFTWARE_REHEARSAL", "PANORAMIC_DEVICE"]
EvidenceResult = Literal["PASS", "FAIL", "PARTIAL", "NOT_PROVEN"]
ApplicationLane = Literal[
    "application_oracle", "voice_application", "joined_application"
]
RunStatus = Literal["PASS", "FAIL"]
ReplyBehavior = Literal["success", "timeout", "failure"]
```

Required public models and functions:

```python
class OfflineApplicationContract(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class HistoricalEvidenceV1(OfflineApplicationContract):
    evidence_class: Literal["HISTORICAL"] = "HISTORICAL"
    evidence_id: str
    source_commit: str                 # exactly 40 lowercase hex
    observed_at: datetime              # timezone-aware
    scope: Literal[
        "low_risk_voice_reachability",
        "empty_room_zero_event_sample",
        "camera_reply_v3e",
    ]
    result: EvidenceResult
    fresh_for_this_run: Literal[False] = False


class ApplicationStepV1(OfflineApplicationContract):
    step_id: str
    offset_ms: int
    visual_review: VisualReview | None = None
    voice_fixture_id: str | None = None
    expected_action_code: ScenarioActionCode | None = None
    expected_match_kind: ScenarioMatchKind | None = None
    reply_behavior: ReplyBehavior | None = None
    # validator: exactly one visual or voice input; voice identity pair is coherent


class RehearsalScenarioV1(OfflineApplicationContract):
    scenario_id: str
    lane: ApplicationLane
    steps: tuple[ApplicationStepV1, ...]
    expected_counts: dict[str, int]


class RehearsalSuiteV1(OfflineApplicationContract):
    schema_version: Literal[1] = 1
    suite_id: Literal["offline-application-rehearsal-v1"]
    scenarios: tuple[RehearsalScenarioV1, ...]  # exactly 12 fixed IDs


class ApplicationScenarioResultV1(OfflineApplicationContract):
    evidence_class: Literal["SOFTWARE_REHEARSAL"] = "SOFTWARE_REHEARSAL"
    scenario_id: str
    lane: ApplicationLane
    status: RunStatus
    reason: str
    counts: dict[str, int]
    event_ids: tuple[str, ...] = ()
    reply_ids: tuple[str, ...] = ()


class FaultResultV1(OfflineApplicationContract):
    fault_id: str
    outcome: Literal["CLOSED", "UNEXPECTED"]
    reason: str
    cleanup_count: int


class RepetitionIterationV1(OfflineApplicationContract):
    iteration: int
    status: RunStatus
    stable_digest: str
    counts: dict[str, int]


class RepetitionResultV1(OfflineApplicationContract):
    status: RunStatus
    reason: str
    iterations: tuple[RepetitionIterationV1, ...]  # exactly 10
    cross_risk_instances: Literal[50]
    cross_risk_pass: int


class SideEffectCountsV1(OfflineApplicationContract):
    camera_access: Literal[False] = False
    camera_reply_enabled: Literal[False] = False
    ptz_commands: Literal[False] = False
    real_notifications: Literal[False] = False
    baby_care_writes: Literal[False] = False
    private_media_reads: Literal[False] = False
    raw_audio_persisted: Literal[False] = False


class OfflineApplicationRunV1(OfflineApplicationContract):
    schema_version: Literal[1] = 1
    suite_id: Literal["offline-application-rehearsal-v1"]
    run_id: str
    generated_at: datetime
    status: RunStatus
    reason: str
    evidence_class: Literal["SOFTWARE_REHEARSAL"]
    historical: tuple[HistoricalEvidenceV1, ...]  # exactly 3
    results: tuple[ApplicationScenarioResultV1, ...]  # exactly 12
    faults: tuple[FaultResultV1, ...]  # exactly 10
    repetition: RepetitionResultV1
    imported_status: Literal["PASS"]
    imported_scenarios: Literal[8]
    imported_lanes: Literal[13]
    imported_visual_clips: Literal[5]
    imported_frames: Literal[330]
    imported_skipped_frames: Literal[0]
    imported_dropped_frames: Literal[0]
    imported_decode_errors: Literal[0]
    imported_worker_errors: Literal[0]
    imported_visual_oracle_relationship: Literal["INDEPENDENT"]
    side_effects: SideEffectCountsV1
    counts: dict[str, int]
```

The module also exports strict
`load_rehearsal_suite(path: Path) -> RehearsalSuiteV1`,
`load_historical_ledger(path: Path) -> tuple[HistoricalEvidenceV1, ...]`,
`canonical_application_run_bytes(run: OfflineApplicationRunV1) -> bytes`, and
`stable_application_digest(run: OfflineApplicationRunV1) -> str` functions.

All identifier/count dictionaries are bounded by the same lowercase safe-key pattern
used by `offline_guardian_scenario.py`. Input files are at most 256 KiB. Steps are
strictly increasing by `offset_ms`, IDs are unique, and the suite validator requires
the exact scenario set and lane cardinality 6/3/3. The top-level result has literal
false side-effect fields:

```text
camera_access
camera_reply_enabled
ptz_commands
real_notifications
baby_care_writes
private_media_reads
raw_audio_persisted
```

It also has exact zero counters for no-baby face watch/alert/event/notification and
residual reply sessions. `stable_application_digest()` normalizes only declared run
ID, generated event/reply IDs and timestamps. It must not normalize status, reason,
scenario/fault IDs, evidence classes, counts or side-effect fields.

## Exact functional pack

The fixture must contain only these twelve IDs:

| Lane | Scenario ID | Exact fresh behavior |
|---|---|---|
| application | `APP-SAFE-SLEEP-01` | zero risk/adult/notification output |
| application | `APP-FACE-OCCLUSION-01` | face watch 1, open 1, explicit-safe recovery 1; one face event; open + recovered notifications |
| application | `APP-EMPTY-BED-01` | outside watch/open 1 each; one outside event/notification; every face counter 0 |
| application | `APP-ADULT-ONLY-01` | adult intervention 1; outside watch/open 1 each; one outside notification; every face counter 0 |
| application | `APP-CROSS-RISK-LEGACY-01` | unique `face_without_subject` conflict 1; outside only; every face output 0 |
| application | `APP-FACE-TO-OUTSIDE-01` | face opens, then confirmed `subject_outside` recovery without recovery notice; outside opens and owns continuing alert |
| voice | `APP-VOICE-FEEDING-01` | `feeding_command/exact` once plus legal-cross-action, ambiguous and no-wake controls with exact silence/output |
| voice | `APP-VOICE-DIAPER-01` | `diaper_change_start/exact` and `diaper_change_complete/exact` once each plus controls |
| voice | `APP-VOICE-BURPING-01` | `burping_start/exact` and `burping_complete/exact` once each plus controls |
| joined | `APP-JOINED-FEEDING-SAFE-01` | safe visual steps interleaved with exact Feeding reply lifecycle |
| joined | `APP-JOINED-DIAPER-ADULT-ONLY-01` | adult/outside-only visual semantics interleaved with both diaper actions; face output 0 |
| joined | `APP-JOINED-BURPING-FACE-TO-OUTSIDE-01` | both burping actions interleaved with face-to-outside lifecycle; no face recovery notice |

Use four visual offsets separated by ten seconds where an open + recovery lifecycle is
required. Use two offsets separated by ten seconds for a simple confirmed alert.
Joined scenarios execute one ordered list and prove ID/state isolation; they do not
claim real concurrency.

## Task 1: Define strict contracts and exact fixtures

**Files:**

- Create: `packages/contracts/offline_application_rehearsal.py`
- Create: `tests/fixtures/offline_application_rehearsal/scenarios.v1.json`
- Create: `tests/fixtures/offline_application_rehearsal/history.v1.json`
- Create: `tests/contracts/test_offline_application_rehearsal.py`

- [x] **Step 1: Write RED contract tests**

Tests must reject: unknown keys; more/fewer than twelve scenarios; any changed/missing
ID; wrong 6/3/3 lane split; duplicate/out-of-order steps; a step with zero or two input
kinds; incoherent action/match pair; medication code; prose reason; negative/unbounded
count; naive time; non-40-hex commit; historical `fresh=true`; report side-effect true;
oversize input; digest normalization of a semantic field.

Tests must accept the exact tracked fixtures and assert all declared cardinalities,
zero side effects and deterministic canonical bytes.

Run:

```bash
../../.venv-alpha/bin/python -m pytest \
  tests/contracts/test_offline_application_rehearsal.py -q
```

Expected RED: import/module and fixture loading fail.

- [x] **Step 2: Add the exact fixture contents**

Use generated fixture IDs only; never embed a speech transcript. The three history
entries are exactly:

| evidence ID | scope | result |
|---|---|---|
| `HIST-VOICE-REACHABILITY-20260902` | `low_risk_voice_reachability` | `PARTIAL` |
| `HIST-EMPTY-ROOM-50S` | `empty_room_zero_event_sample` | `PARTIAL` |
| `HIST-CAMERA-REPLY-V3E` | `camera_reply_v3e` | `FAIL` |

Use source commit `c75d9296d9dc920198075578ffc3429ea3400b21` and the already documented UTC
observation date; the ledger must contain no denominator reconstruction or live PASS.

- [x] **Step 3: Implement minimum strict models/loaders/digest**

Use `Path.lstat()`, `O_NOFOLLOW` where available, maximum-byte checks before parsing,
strict Pydantic validation and canonical ASCII JSON. The stable digest must operate on a
documented normalized model dump rather than string replacement.

- [x] **Step 4: Run focused GREEN and commit**

```bash
../../.venv-alpha/bin/python -m pytest \
  tests/contracts/test_offline_application_rehearsal.py -q
../../.venv-alpha/bin/python -m compileall -q \
  packages/contracts/offline_application_rehearsal.py
../../.venv-alpha/bin/python -m json.tool \
  tests/fixtures/offline_application_rehearsal/scenarios.v1.json >/dev/null
../../.venv-alpha/bin/python -m json.tool \
  tests/fixtures/offline_application_rehearsal/history.v1.json >/dev/null
git diff --check
git add packages/contracts/offline_application_rehearsal.py \
  tests/contracts/test_offline_application_rehearsal.py \
  tests/fixtures/offline_application_rehearsal
git commit -m "feat: define offline application rehearsal contract"
```

## Task 2: Load historical evidence without promoting it

**Files:**

- Create: `services/offline_application_history.py`
- Create: `tests/integration/test_offline_application_history.py`

**Interfaces:**

```python
@dataclass(frozen=True)
class HistoricalEvidenceSummary:
    items: tuple[HistoricalEvidenceV1, ...]
    counts: Mapping[EvidenceResult, int]


def summarize_historical_evidence(
    items: tuple[HistoricalEvidenceV1, ...],
) -> HistoricalEvidenceSummary:
    counts = Counter(item.result for item in items)
    return HistoricalEvidenceSummary(items=items, counts=MappingProxyType(counts))
```

- [x] **Step 1: Write RED separation tests**

Assert ledger counts remain in the historical section, the summary cannot produce a
fresh scenario result, all items retain `fresh_for_this_run=false`, and a historical
FAIL/PARTIAL does not make a deterministic software scenario pass or fail. Assert no
transcript/path/prose field exists on the models.

- [x] **Step 2: Implement the pure summary and run GREEN**

```bash
../../.venv-alpha/bin/python -m pytest \
  tests/integration/test_offline_application_history.py -q
../../.venv-alpha/bin/python -m compileall -q \
  services/offline_application_history.py
git diff --check
git add services/offline_application_history.py \
  tests/integration/test_offline_application_history.py
git commit -m "feat: classify historical rehearsal evidence"
```

## Task 3: Build recording event/notification and reply sinks

**Files:**

- Create: `services/offline_application_sinks.py`
- Create: `tests/integration/test_offline_application_sinks.py`

**Interfaces:**

```python
@dataclass(frozen=True)
class RecordedNotification:
    notification_id: str
    event_id: str
    stage: Literal["risk_opened", "risk_recovered", "adult_intervention"]
    intervention_id: str | None


@dataclass(frozen=True)
class RecordedReply:
    reply_id: str
    response_code: str
    generated_byte_count: int
    started_count: Literal[1]
    terminal_count: Literal[1]
    terminal_state: Literal["succeeded", "timed_out", "failed", "cancelled"]


class RecordingNotificationStore:
    # wraps/delegates an actual VisualRiskEventStore
    queued: tuple[RecordedNotification, ...]


class RecordingReplySink:
    def speak_code(self, code: str, cancelled: StopEvent) -> bool:
        """Record one closed reply lifecycle and return its terminal success flag."""

    def close(self) -> None:
        """Close any active lifecycle without retaining audio or transcript data."""

    @property
    def residual_sessions(self) -> int:
        """Return zero after every bounded success or failure cleanup."""
```

The reply sink records only generated reply ID, closed response code, bounded generated
byte count, lifecycle counters and final state. It never stores audio bytes. `success`
returns true once; `timeout` and `failure` return false with distinct stable result
codes; every mode ends with zero residual sessions after `close()`. It must reject
duplicate completion and use a caller-provided ID factory so repeat tests can prove
global uniqueness.

- [x] **Step 1: Write RED lifecycle and adapter-isolation tests**

Assert success/timeout/failure/close/duplicate-call behavior, exact IDs, cleanup after an
exception, notification decision recording, and delegation to a real temporary event
store. Use a source scan to assert this module does not import `camera_reply`, Xiaomi,
go2rtc, notification dispatch or Baby Care.

- [x] **Step 2: Implement and run GREEN**

```bash
../../.venv-alpha/bin/python -m pytest \
  tests/integration/test_offline_application_sinks.py -q
../../.venv-alpha/bin/python -m compileall -q \
  services/offline_application_sinks.py
git diff --check
git add services/offline_application_sinks.py \
  tests/integration/test_offline_application_sinks.py
git commit -m "feat: add recording application sinks"
```

## Task 4: Execute the six deterministic Guardian application scenarios

**Files:**

- Create: `services/offline_application_rehearsal.py`
- Create: `tests/integration/test_offline_application_rehearsal.py`

**Interfaces:**

```python
class OfflineApplicationRehearsalRunner:
    def run_functional_pack(
        self, suite: RehearsalSuiteV1
    ) -> tuple[ApplicationScenarioResultV1, ...]:
        """Run the exact twelve scenarios in fixture order from fresh roots."""

def run_application_oracle_scenario(
    scenario: RehearsalScenarioV1,
    scenario_root: Path,
    *,
    event_id_factory: Callable[[], str],
    notification_id_factory: Callable[[], str],
) -> ApplicationScenarioResultV1:
    """Run one deterministic Guardian scenario through the actual local store."""
```

- [x] **Step 1: Write RED for the exact application truth table**

Run only the six `application_oracle` fixture entries. Assert every transition kind,
risk kind, resolution cause, event state, dashboard count, notification stage,
semantic-conflict count and final open risk against the table above. In particular:

- all empty/adult/legacy face counters are exactly zero;
- the adult transition occurs once and is non-notifying;
- the positive face control has both `risk_opened` and `risk_recovered`;
- face-to-outside has face recovery cause `subject_outside`, no face recovery
  notification, and an open outside event.

- [x] **Step 2: Implement through actual production-safe boundaries**

For each scenario create a fresh 0700 root and SQLite store. Instantiate the real state
machine, event pipeline and query service, plus the recording notification wrapper.
Count a semantic conflict once per closed conflict kind per scenario, not once per
repeated review. Compare actual counters to the exact fixture dictionary and fail with
the first closed reason `application_oracle_mismatch`.

- [x] **Step 3: Run GREEN and commit**

```bash
../../.venv-alpha/bin/python -m pytest \
  tests/integration/test_offline_application_rehearsal.py \
  tests/integration/test_visual_cross_risk.py -q
../../.venv-alpha/bin/python -m compileall -q \
  services/offline_application_rehearsal.py
git diff --check
git add services/offline_application_rehearsal.py \
  tests/integration/test_offline_application_rehearsal.py
git commit -m "feat: rehearse guardian application scenarios"
```

## Task 5: Execute generated Voice and joined scenarios

**Files:**

- Modify: `services/offline_application_rehearsal.py`
- Modify: `tests/integration/test_offline_application_rehearsal.py`

**Interfaces:** Add:

```python
def run_voice_application_scenario(
    scenario: RehearsalScenarioV1,
    scenario_root: Path,
    *,
    voice_fixture_provider: Callable[[str], bytes],
    asr_factory: Callable[[], Asr],
    reply_sink_factory: Callable[[ReplyBehavior], RecordingReplySink],
) -> ApplicationScenarioResultV1:
    """Run one generated Voice scenario with exact identity assertions."""


def run_joined_application_scenario(
    scenario: RehearsalScenarioV1,
    scenario_root: Path,
    *,
    voice_fixture_provider: Callable[[str], bytes],
    asr_factory: Callable[[], Asr],
    reply_sink_factory: Callable[[ReplyBehavior], RecordingReplySink],
    event_id_factory: Callable[[], str],
    notification_id_factory: Callable[[], str],
) -> ApplicationScenarioResultV1:
    """Run one ordered interleaved visual/Voice application episode."""
```

Use the current `ListenOnlyController` directly with fixed ASR result objects and
generated non-household PCM. Every voice step compares exact `reason`, response code,
action code, match kind, controller phase and recording reply lifecycle.

- [x] **Step 1: Write RED for three Voice scenarios**

Feeding must produce exactly one `feeding_command/exact`. Diaper and burping must each
produce exact start and complete codes once. Across declared controls assert:

- another legal exact action is classified as its own code;
- ambiguous multi-action input produces no action/reply;
- an exact action without wake produces no action/reply;
- ASR no-match and synthetic source failure fail closed;
- reply success/timeout/failure each has one terminal lifecycle and cleanup;
- medication action/output counts remain zero.

- [x] **Step 2: Write RED for three joined scenarios**

Execute the ordered step offsets, not two unrelated post-hoc results. Assert visual
progress counters continue across Voice steps, IDs are unique across visual/reply
domains, one domain failure cannot alter the other domain's state, and final reply
sessions are zero. Repeat the adult-only and face-to-outside zero/notification
assertions inside joined lanes.

- [x] **Step 3: Implement minimum Voice/joined routing and run GREEN**

```bash
../../.venv-alpha/bin/python -m pytest \
  tests/integration/test_offline_application_rehearsal.py \
  tests/voice/test_listen_only.py -q
../../.venv-alpha/bin/python -m compileall -q \
  services/offline_application_rehearsal.py
git diff --check
git add services/offline_application_rehearsal.py \
  tests/integration/test_offline_application_rehearsal.py
git commit -m "feat: join voice and guardian rehearsal lanes"
```

## Task 6: Add the fixed fault-injection pack

**Files:**

- Modify: `services/offline_application_rehearsal.py`
- Create: `tests/integration/test_offline_application_faults.py`

**Interfaces:**

```python
def run_fault_pack(
    runner_factory: Callable[[], OfflineApplicationRehearsalRunner],
) -> tuple[FaultResultV1, ...]:
    """Run the exact ten injected boundary faults in declared order."""
```

Use exactly ten runner-level cases; report publication failure is tested separately in
Task 8:

| Fault ID | Injection boundary | Stable expected reason |
|---|---|---|
| `FAULT-VISUAL-COMPONENT-01` | visual component double | `visual_component_failed` |
| `FAULT-SEMANTIC-INVALID-01` | strict contract input | `semantic_review_invalid` |
| `FAULT-SEMANTIC-CONFLICT-01` | canonical mapper | `semantic_conflict_closed` |
| `FAULT-DUPLICATE-REVIEW-01` | delivery guard | `duplicate_review_rejected` |
| `FAULT-NONMONOTONIC-REVIEW-01` | state clock | `nonmonotonic_review_rejected` |
| `FAULT-VOICE-NOMATCH-01` | fixed ASR | `voice_no_match` |
| `FAULT-REPLY-TIMEOUT-01` | recording reply | `reply_timeout` |
| `FAULT-REPLY-FAILURE-01` | recording reply | `reply_failed` |
| `FAULT-EVENT-STORE-01` | store wrapper | `event_store_failed` |
| `FAULT-PROJECTION-01` | query wrapper | `projection_failed` |

The design's no-wake and ambiguous-input cases are exact functional Voice controls in
Task 5, not duplicated as fault IDs. Reply cleanup failure is injected in the sink tests
and again as the leaked-session negative in Task 7. Report publication failure is the
atomic rollback case in Task 8. Together those tests cover every design fault boundary
without inflating the fixed ten-case runner summary.

- [x] **Step 1: Write RED exact-fault tests**

Assert all ten results are returned in fixture order, expected fail-closed cases never
report functional PASS, the first reason remains stable, all cleanup counters are zero,
and failure of one case does not prevent later independent cases from running.
`FAULT-SEMANTIC-CONFLICT-01` is an expected closed conflict result and must still retain
independent outside evidence; it does not become an unhandled exception.

- [x] **Step 2: Implement explicit injected doubles only**

Do not monkeypatch production globals. Pass boundary doubles/factories into the runner.
Catch only at the scenario/fault boundary, map known outcomes to closed reasons, discard
exception strings, and run cleanup in `finally`.

- [x] **Step 3: Run GREEN and commit**

```bash
../../.venv-alpha/bin/python -m pytest \
  tests/integration/test_offline_application_faults.py \
  tests/integration/test_offline_application_rehearsal.py -q
../../.venv-alpha/bin/python -m compileall -q \
  services/offline_application_rehearsal.py
git diff --check
git add services/offline_application_rehearsal.py \
  tests/integration/test_offline_application_faults.py
git commit -m "test: inject offline application failures"
```

## Task 7: Enforce 10-run and 50-instance stability quotas

**Files:**

- Modify: `services/offline_application_rehearsal.py`
- Create: `tests/integration/test_offline_application_repetition.py`

**Interfaces:**

```python
def run_repetition_gate(
    runner_factory: Callable[[int], OfflineApplicationRehearsalRunner],
    suite: RehearsalSuiteV1,
    *,
    full_run_count: Literal[10] = 10,
    cross_risk_count: Literal[50] = 50,
) -> RepetitionResultV1:
    """Run fresh application packs and cross-risk instances to fixed quotas."""
```

- [x] **Step 1: Write RED freshness/uniqueness/digest tests**

Assert exactly ten complete packs run from ten new roots and fifty state machines run
from fifty new instances. Collect every event and reply ID across all iterations and
assert global uniqueness. Assert all successful normalized digests match while raw run
IDs/timestamps/IDs differ. Inject one leaked reply session, duplicate ID and no-baby
face output separately; each must fail the repetition result with its exact closed
reason.

- [x] **Step 2: Implement bounded summaries**

Store one representative set of twelve functional results plus ten compact iteration
summaries (`iteration`, `status`, stable digest, bounded counters). Do not retain 120
duplicated result trees. The fifty-instance result stores aggregate exact counts only.

- [x] **Step 3: Run GREEN and commit**

```bash
../../.venv-alpha/bin/python -m pytest \
  tests/integration/test_offline_application_repetition.py -q
../../.venv-alpha/bin/python -m compileall -q \
  services/offline_application_rehearsal.py
git diff --check
git add services/offline_application_rehearsal.py \
  tests/integration/test_offline_application_repetition.py
git commit -m "feat: repeat offline application rehearsal"
```

## Task 8: Publish one private atomic aggregate report

**Files:**

- Create: `services/offline_application_report.py`
- Create: `tests/integration/test_offline_application_report.py`

**Interfaces:**

```python
def publish_offline_application_report(
    run: OfflineApplicationRunV1,
    destination: Path,
) -> tuple[Path, Path]:
    """Atomically publish bounded JSON and HTML into an empty private root."""
```

Use the established no-replace, fsync and same-inode cleanup design from
`services/offline_guardian_report.py`, with distinct filenames
`application-result.v1.json` and `application-report.html` and bounded sizes 512 KiB /
1 MiB.

- [x] **Step 1: Write RED privacy/atomicity/report tests**

Assert 0700 root, 0600 final files, canonical JSON, ASCII HTML, no overwrite, symlink
rejection, partial-publication rollback, fsync/cleanup failure behavior and exact report
sections for historical/software/panoramic evidence. `PANORAMIC_DEVICE` must be marked
not executed. Scan both outputs to reject transcript, exception text, URL, host/address,
private absolute path, token and media fields.

Assert a forced report-publication failure returns/raises only
`offline_application_report_failed` and cannot leave a final PASS file or temp file.

- [x] **Step 2: Implement by adapting, not mutating, the old publisher**

Do not relax the old report's behavior. Render the mandatory zero fields and explicit
disclaimer: software PASS is control-flow evidence only and does not publish live Voice,
visual accuracy or Camera Reply PASS.

- [x] **Step 3: Run GREEN and commit**

```bash
../../.venv-alpha/bin/python -m pytest \
  tests/integration/test_offline_application_report.py -q
../../.venv-alpha/bin/python -m compileall -q \
  services/offline_application_report.py
git diff --check
git add services/offline_application_report.py \
  tests/integration/test_offline_application_report.py
git commit -m "feat: publish offline application report"
```

## Task 9: Add validate/run commands and import the old suite once

**Files:**

- Modify: `tools/offline_guardian_scenario.py`
- Create: `tools/offline_application_rehearsal.py`
- Create: `tests/tools/test_offline_application_rehearsal.py`
- Modify: `Makefile`

**Interfaces:** Rename/expose only a compatibility wrapper in the old tool:

```python
def execute_fixed_flow():
    return _execute_fixed_flow()
```

New commands:

```text
python tools/offline_application_rehearsal.py validate
python tools/offline_application_rehearsal.py run
make alpha-offline-application-validate
make alpha-offline-application-run
```

- [x] **Step 1: Write RED CLI/source-boundary tests**

Assert validate is I/O-bounded to tracked JSON and returns exact scenario/history
counts. Assert run invokes the old fixed flow exactly once and refuses application PASS
unless it returns PASS with 8 scenarios, 13 lanes, 5 visual clips and 330 frames. Assert
the new tool has no imports/references for Camera Reply, Xiaomi, go2rtc, PTZ, real
notification dispatch, Baby Care or private visual overlay.

Assert the final emitted closed JSON summary contains: 12/12 functional scenarios,
10/10 full iterations, 50/50 cross-risk instances, ten fault results, imported
8/13/330 component counts, zero forbidden side effects, report basename only, and no
absolute path.

- [x] **Step 2: Implement strict commands and Make targets**

Use a private ignored run root below the existing runtime boundary, fixed 180-second
whole-run timeout, first stable failure reason and exit codes 0 PASS / 2 FAIL. The old
suite is a prerequisite executed once before the ten application iterations; do not
re-download/re-run its 330 frames ten times.

- [x] **Step 3: Run tool GREEN, source scans and dry runs**

```bash
../../.venv-alpha/bin/python -m pytest \
  tests/tools/test_offline_application_rehearsal.py \
  tests/tools/test_offline_guardian_scenario.py -q
../../.venv-alpha/bin/python -m compileall -q \
  tools/offline_application_rehearsal.py tools/offline_guardian_scenario.py
make -n PYTHON=../../.venv-alpha/bin/python alpha-offline-application-validate
make -n PYTHON=../../.venv-alpha/bin/python alpha-offline-application-run
git diff --check
```

- [x] **Step 4: Commit**

```bash
git add tools/offline_guardian_scenario.py \
  tools/offline_application_rehearsal.py \
  tests/tools/test_offline_application_rehearsal.py Makefile
git commit -m "feat: add offline application rehearsal command"
```

## Task 10: Run the complete software gate and close the checkpoint

**Files:**

- Modify after fresh evidence only: `SUMMARY.md`
- Modify after fresh evidence only: `docs/STATUS.md`
- Append after fresh evidence only: `docs/CHECKPOINT.md`
- Modify after fresh evidence only: `docs/NEXT.md`
- Modify after fresh evidence only:
  `docs/superpowers/plans/2026-08-30-baby-monitor-ordered-delivery.md`

- [x] **Step 1: Run contract, focused and full tests**

```bash
../../.venv-alpha/bin/python -m pytest \
  tests/contracts/test_offline_application_rehearsal.py \
  tests/integration/test_visual_cross_risk.py \
  tests/integration/test_offline_application_history.py \
  tests/integration/test_offline_application_sinks.py \
  tests/integration/test_offline_application_rehearsal.py \
  tests/integration/test_offline_application_faults.py \
  tests/integration/test_offline_application_repetition.py \
  tests/integration/test_offline_application_report.py \
  tests/tools/test_offline_application_rehearsal.py -q
../../.venv-alpha/bin/python -m pytest -q
npm test
```

Record exact fresh counts. A public-corpus dependency skip remains a skip and blocks the
fixed command's exact PASS; do not relabel it.

- [x] **Step 2: Execute the actual fixed commands**

```bash
make PYTHON=../../.venv-alpha/bin/python alpha-offline-application-validate
make PYTHON=../../.venv-alpha/bin/python alpha-offline-application-run
```

Required actual run summary:

```text
result=PASS
functional_scenarios=12
functional_pass=12
full_iterations=10
full_iteration_pass=10
cross_risk_instances=50
cross_risk_pass=50
fault_cases=10
imported_scenarios=8
imported_lanes=13
imported_visual_clips=5
imported_frames=330
imported_skipped_frames=0
imported_dropped_frames=0
imported_decode_errors=0
imported_worker_errors=0
camera_access=0
camera_reply_enabled=0
ptz_commands=0
real_notifications=0
baby_care_writes=0
private_media_reads=0
no_baby_face_watch=0
no_baby_face_alert=0
no_baby_face_event=0
no_baby_face_notification=0
residual_reply_sessions=0
```

- [x] **Step 3: Inspect privacy, scope and reproducibility**

```bash
git diff --check
git status --short --branch
git diff --stat
git ls-files | rg '\.(wav|mp3|m4a|aac|pcm|flac|mp4|mov|mkv|avi|sqlite|db)$' || true
git grep -nE '(/Users/|/home/|BEGIN (RSA|OPENSSH|EC) PRIVATE KEY)' -- \
  packages services tools tests docs SUMMARY.md
```

Inspect the ignored report directly: permissions 0700/0600, no private strings/media,
all mandatory zero values and equivalent stable digests across ten iterations. Never
stage the report or runtime root.

- [x] **Step 4: Request independent review**

Use `superpowers:requesting-code-review` over the exact candidate diff. Review must
answer:

1. Is historical evidence excluded from fresh PASS?
2. Can any no-baby scenario create face watch/alert/event/notification?
3. Does positive face control still work and explicit recovery still notify?
4. Is `subject_outside` confirmed, non-notifying and independently paired with outside?
5. Are actual Voice/state/store/query boundaries exercised without real adapters?
6. Do ten/50 repetitions start fresh and prove ID uniqueness/digest stability?
7. Can any exception leak prose, leave a reply session, or suppress a sibling result?
8. Did any production adapter, private input, medication or Baby Care path initialize?

Fix all Critical/Important findings with RED/GREEN, rerun Steps 1-3, and record the
final review result.

- [x] **Step 5: Update factual docs and commit**

Record the exact candidate SHA, command output, test counts, report digest and review
result. Keep these states unchanged: live Feeding/diaper/burping `NOT_PROVEN`, visual
corpus `PARTIAL`, Camera Reply false, no release. Change the ordered handoff only to
"software rehearsal complete; panoramic gate awaits separate owner authority" if every
required value passed.

```bash
git add SUMMARY.md docs/STATUS.md docs/CHECKPOINT.md docs/NEXT.md \
  docs/superpowers/plans/2026-08-30-baby-monitor-ordered-delivery.md
git commit -m "docs: record offline application rehearsal gate"
```

- [ ] **Step 6: Final stop line**

Use `superpowers:verification-before-completion`, fetch the remote, prove a
fast-forward, and push only with explicit delivery authority. Stop after reporting.
Do not execute the panoramic checklist, resume live Stage 2 Step 3, enable Camera Reply,
capture household media, create/merge a PR or modify `main/stable`.
