# Offline Guardian Scenario Flow Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add one offline command that runs fixed public/generated infant-monitor scenarios through the current visual, Guardian/Dashboard and Voice boundaries and writes a bounded JSON plus media-free HTML report.

**Architecture:** Keep visual observations, deterministic Guardian semantics and generated Voice behavior as independent lanes joined only by a strict scenario ID and aggregate result. Reuse `VisualCorpusReplay`, `GuardianReplayProjector`, `GuardianEventQueryService` and `ListenOnlyController`; all stores and reports live under ignored owner-private test runtime, and no live service or external client is initialized.

**Tech Stack:** Python 3.11+, Pydantic 2, pytest, SQLite through existing services, ffmpeg through the existing corpus preparation/replay path, standard-library HTML escaping and JSON.

**Spec:** `docs/superpowers/specs/2026-08-29-offline-guardian-scenario-flow-design.md`

## Global Constraints

- Do not access Xiaomi authentication, a camera URI, CS2, go2rtc, Ollama, ntfy, Baby Care or Camera Reply.
- Do not read or write production SQLite, evidence, calibration, model, audio or household-media state.
- Use only admitted public visual clips and generated Voice fixtures.
- Keep actual visual output observational and deterministic Guardian inputs explicitly marked `SYNTHETIC_SEMANTIC_ORACLE`.
- Create no public baseline and do not change public corpus readiness.
- Runtime roots are `0700`; JSON, HTML and SQLite artifacts are `0600`; symlinks, hard links, repository escape and unknown entries fail closed.
- Outputs contain no frames, media, audio, transcript, path, URL, host, IP, model prose or raw exception.
- Each task uses RED -> GREEN and a focused commit. No push, PR, merge or protected-branch change.

---

## File and interface map

- Create `packages/contracts/offline_guardian_scenario.py`: closed scenario, expectation, lane-result and aggregate-result contracts plus canonical serialization.
- Create `tests/fixtures/offline_guardian_scenarios/scenarios.v1.json`: four generated/public scenario definitions with no locators.
- Create `services/offline_guardian_scenario.py`: visual, Guardian and Voice lane adapters plus isolated orchestration.
- Create `services/offline_guardian_report.py`: canonical owner-private JSON and escaped static HTML publication.
- Create `tools/offline_guardian_scenario.py`: fixed `validate` and `run` CLI.
- Modify `Makefile`: add `alpha-offline-scenario-validate` and `alpha-offline-scenario-run`.
- Create `tests/contracts/test_offline_guardian_scenario.py`.
- Create `tests/integration/test_offline_guardian_scenario.py`.
- Create `tests/tools/test_offline_guardian_scenario.py`.
- Modify `SUMMARY.md`, `docs/STATUS.md`, `docs/CHECKPOINT.md`, `docs/NEXT.md` only after the real public-clip flow runs.

## Task 1: Closed scenario and result contracts

**Files:**
- Create: `packages/contracts/offline_guardian_scenario.py`
- Create: `tests/contracts/test_offline_guardian_scenario.py`
- Create: `tests/fixtures/offline_guardian_scenarios/scenarios.v1.json`

**Interfaces:**
- Produces `ScenarioLaneRequirement`, `ScenarioExpectation`, `OfflineGuardianScenarioV1`, `OfflineScenarioSuiteV1`, `ScenarioLaneResult`, `OfflineScenarioResultV1`, `OfflineScenarioRunV1`.
- Produces `load_offline_scenario_suite(path: Path) -> OfflineScenarioSuiteV1`.
- Produces `canonical_offline_scenario_bytes(value) -> bytes` and `canonical_offline_run_bytes(value) -> bytes`.

- [x] **Step 1: Write contract RED tests**

Test the four exact scenario IDs, unique IDs, allowed clip IDs, fixed profiles, ordered aware timestamps, bounded expected counts, closed provenance values and exact field sets. Reject locator-like keys recursively.

```python
def test_suite_rejects_locator_fields() -> None:
    payload = suite_payload()
    payload["scenarios"][0]["source_url"] = "https://example.invalid/video"
    with pytest.raises(ValidationError):
        OfflineScenarioSuiteV1.model_validate(payload)


def test_result_requires_isolation_proofs() -> None:
    payload = run_payload()
    payload["camera_opened"] = True
    with pytest.raises(ValidationError):
        OfflineScenarioRunV1.model_validate(payload)
```

- [x] **Step 2: Run RED**

```bash
../../.venv-alpha/bin/python -m pytest -q tests/contracts/test_offline_guardian_scenario.py
```

Expected: collection fails because the contract module does not exist.

- [x] **Step 3: Implement the minimum contracts and four-scenario fixture**

Use `extra="forbid"`, strict scalar types, maximum 8 scenarios, 64 expectation keys and 32 lane counts. Define the initial fixture mapping:

```text
SAFE-SLEEP-01       -> DAY-01  -> visual + guardian
FACE-OCCLUSION-01   -> OCC-02  -> visual + guardian
ADULT-INTERVENTION-01 -> NEG-03 -> visual + guardian
VOICE-FEEDING-01    -> generated-voice-feeding-v1 -> voice
```

The Guardian timelines use the current `VisualReview` field names and only declared ISO-8601 UTC timestamps. The Voice fixture declares opaque step IDs, not transcript text.

- [x] **Step 4: Run GREEN and static checks**

```bash
../../.venv-alpha/bin/python -m pytest -q tests/contracts/test_offline_guardian_scenario.py tests/contracts/test_visual_corpus.py
../../.venv-alpha/bin/python -m compileall -q packages/contracts/offline_guardian_scenario.py
git diff --check
```

- [x] **Step 5: Commit**

```bash
git add packages/contracts/offline_guardian_scenario.py tests/contracts/test_offline_guardian_scenario.py tests/fixtures/offline_guardian_scenarios/scenarios.v1.json
git commit -m "feat: define offline guardian scenarios"
```

## Task 2: Deterministic Guardian and Dashboard lane

**Files:**
- Create: `services/offline_guardian_scenario.py`
- Create: `tests/integration/test_offline_guardian_scenario.py`

**Interfaces:**
- Produces `run_guardian_lane(scenario: OfflineGuardianScenarioV1, runtime_root: Path) -> ScenarioLaneResult`.
- Converts declared timeline entries to `GuardianReplayReview` and delegates to `GuardianReplayProjector.run(semantic_profile="synthetic_test", reviews=...)`.
- Reopens the same isolated store only through `GuardianEventQueryService` for the final bounded projection.

- [ ] **Step 1: Write Guardian lane RED tests**

Cover safe zero-event, face-obstruction confirmation/dedup/recovery and adult-intervention audit. Assert a fresh database per scenario and these invariants:

```python
assert result.production_state_touched is False
assert result.notification_dispatch_attempted is False
assert result.evidence_persisted is False
assert result.actual_counts == scenario.guardian_expected_counts
```

Also reject an existing database, symlink root, expectation mismatch, invalid review order and more than 32 transitions.

- [ ] **Step 2: Run RED**

```bash
../../.venv-alpha/bin/python -m pytest -q tests/integration/test_offline_guardian_scenario.py -k guardian
```

Expected: import failure for `run_guardian_lane`.

- [ ] **Step 3: Implement the minimum Guardian adapter**

Create only a scenario-owned database below the supplied root. Map the existing aggregate to stable keys and compare exact dictionaries. Preserve `GuardianReplayProjector` reason codes; return `scenario_guardian_mismatch` when the projector passes but expectations differ.

- [ ] **Step 4: Run GREEN and adjacent gates**

```bash
../../.venv-alpha/bin/python -m pytest -q tests/integration/test_offline_guardian_scenario.py -k guardian tests/vision/test_corpus_guardian_projection.py tests/events/test_guardian_query.py
../../.venv-alpha/bin/python -m compileall -q services/offline_guardian_scenario.py
git diff --check
```

- [ ] **Step 5: Commit**

```bash
git add services/offline_guardian_scenario.py tests/integration/test_offline_guardian_scenario.py
git commit -m "feat: run isolated guardian scenario lane"
```

## Task 3: Public-video visual observation lane

**Files:**
- Modify: `services/offline_guardian_scenario.py`
- Modify: `tests/integration/test_offline_guardian_scenario.py`

**Interfaces:**
- Produces `run_visual_lane(scenario, manifest, prepared_resolver, model_backend) -> ScenarioLaneResult`.
- Delegates to `VisualCorpusReplay.run_clip` with a new `ReplayProfile` per scenario.
- Retains only `ReplayResult` aggregate fields; never forwards frame observations into the Guardian oracle.

- [ ] **Step 1: Write visual lane RED tests**

Generate a short H.264 Matroska fixture under `tmp_path`, select the tracked clip by exact ID, and exercise the real `FfmpegFileFrameSource`, `VisionFramePolicy` and `VisualWorker`. Assert frame accounting, no persisted observations, bounded metrics and no Guardian database.

Add fail-closed tests for missing clip, missing prepared artifact, decode failure, model unavailable, worker failure and clip-ID mismatch.

- [ ] **Step 2: Run RED**

```bash
../../.venv-alpha/bin/python -m pytest -q tests/integration/test_offline_guardian_scenario.py -k visual
```

Expected: `run_visual_lane` is missing.

- [ ] **Step 3: Implement the minimum visual adapter**

Use the injected prepared resolver and model backend. Map `ReplayResult` to bounded counts and metrics without interpreting them as expected safety labels. A model-degraded or failed replay returns the exact stable reason and makes the required lane FAIL.

- [ ] **Step 4: Run GREEN and adjacent gates**

```bash
../../.venv-alpha/bin/python -m pytest -q tests/integration/test_offline_guardian_scenario.py -k visual tests/vision/test_corpus_replay.py tests/vision/test_worker.py
git diff --check
```

- [ ] **Step 5: Commit**

```bash
git add services/offline_guardian_scenario.py tests/integration/test_offline_guardian_scenario.py
git commit -m "feat: replay public video in scenario lane"
```

## Task 4: Generated Voice lane

**Files:**
- Modify: `services/offline_guardian_scenario.py`
- Modify: `tests/integration/test_offline_guardian_scenario.py`

**Interfaces:**
- Produces `run_voice_lane(scenario, fixture_provider, vad, asr, synthesizer) -> ScenarioLaneResult`.
- `fixture_provider(step_id: str) -> bytes` returns generated mono PCM only.
- Uses `VoiceActivityDetector.observe` before `ListenOnlyController.handle` for
  standalone wake, Feeding command and negative steps; the recording synthesizer
  retains response codes only.

- [ ] **Step 1: Write Voice lane RED tests**

Use non-empty generated PCM and an injected strict ASR fixture that returns `AsrResult` objects for opaque step IDs. Verify exact wake -> `listen_only_ready`, exact Feeding -> one `listen_only_received`, no-wake -> silent and cancellation/unsupported -> silent. Assert PCM and text are absent from the lane result.

Test ASR exception, empty PCM, output failure, wrong response count, high-risk medication and replay-marked input as fail-closed or rejected according to the current controller.

- [ ] **Step 2: Run RED**

```bash
../../.venv-alpha/bin/python -m pytest -q tests/integration/test_offline_guardian_scenario.py -k voice
```

Expected: `run_voice_lane` is missing.

- [ ] **Step 3: Implement the minimum Voice adapter**

Do not construct `VoiceIntentOutbox`, `VoiceCareClient`, signer, Keychain, capture
decoder or Camera Reply. Consume generated PCM in fixed 100 ms frames through the
existing `VoiceActivityDetector` with a generated-fixture runner, then pass only
speech-positive complete fixture utterances to the controller. Zero local references
after each step and serialize only VAD/outcome/reply counters.

- [ ] **Step 4: Run GREEN and adjacent gates**

```bash
../../.venv-alpha/bin/python -m pytest -q tests/integration/test_offline_guardian_scenario.py -k voice tests/voice/test_listen_only.py tests/voice/test_tts.py
git diff --check
```

- [ ] **Step 5: Commit**

```bash
git add services/offline_guardian_scenario.py tests/integration/test_offline_guardian_scenario.py
git commit -m "feat: add generated voice scenario lane"
```

## Task 5: Isolated multi-lane orchestration

**Files:**
- Modify: `services/offline_guardian_scenario.py`
- Modify: `tests/integration/test_offline_guardian_scenario.py`

**Interfaces:**
- Produces `OfflineGuardianScenarioRunner.run(suite: OfflineScenarioSuiteV1) -> OfflineScenarioRunV1`.
- Constructor injects the visual manifest, prepared resolver, model backend, Voice
  fixture provider, VAD, ASR and recording synthesizer.
- Creates a mode-`0700` new session directory and one child directory per scenario.

- [ ] **Step 1: Write orchestration RED tests**

Run all four fixture scenarios and assert order, fresh state, aggregate PASS only when every required lane passes, optional SKIP preservation, first failure retention, no lane restart and all six isolation booleans false.

Add timeout/interruption and filesystem tests for symlink roots, pre-existing unknown entries, wrong modes, hard-linked output and more than eight scenarios.

- [ ] **Step 2: Run RED**

```bash
../../.venv-alpha/bin/python -m pytest -q tests/integration/test_offline_guardian_scenario.py -k runner
```

Expected: runner API is missing.

- [ ] **Step 3: Implement the minimum orchestrator**

Execute lanes in declared order, use fresh adapters per scenario and compute overall state from required lane states. The runner never catches `KeyboardInterrupt` as PASS and never creates output outside its supplied ignored root.

- [ ] **Step 4: Run GREEN**

```bash
../../.venv-alpha/bin/python -m pytest -q tests/integration/test_offline_guardian_scenario.py
../../.venv-alpha/bin/python -m compileall -q services/offline_guardian_scenario.py
git diff --check
```

- [ ] **Step 5: Commit**

```bash
git add services/offline_guardian_scenario.py tests/integration/test_offline_guardian_scenario.py
git commit -m "feat: orchestrate offline guardian scenarios"
```

## Task 6: Privacy-safe JSON and HTML report

**Files:**
- Create: `services/offline_guardian_report.py`
- Modify: `tests/integration/test_offline_guardian_scenario.py`

**Interfaces:**
- Produces `publish_offline_scenario_report(run: OfflineScenarioRunV1, destination: Path) -> tuple[Path, Path]`.
- Publishes `scenario-result.v1.json` and `scenario-report.html` with no-replace atomic semantics.

- [ ] **Step 1: Write report RED tests**

Assert canonical JSON round-trip, deterministic escaped HTML, scenario/lane states,
metrics and Dashboard counts. Search both outputs for fixture transcript, PCM marker,
paths, URLs, hostnames, IPs and model prose. Test no overwrite, symlink destination,
wrong directory mode, partial publication rollback and output size limits.

- [ ] **Step 2: Run RED**

```bash
../../.venv-alpha/bin/python -m pytest -q tests/integration/test_offline_guardian_scenario.py -k report
```

Expected: report module is missing.

- [ ] **Step 3: Implement the minimum renderer and publisher**

Use `html.escape`, a fixed template with no script and no external resource, maximum
256 KiB JSON and 512 KiB HTML. Create temp files as `0600`, fsync them, publish without
replacement, fsync the directory and retain no extra artifact.

- [ ] **Step 4: Run GREEN and privacy scan**

```bash
../../.venv-alpha/bin/python -m pytest -q tests/integration/test_offline_guardian_scenario.py
../../.venv-alpha/bin/python -m compileall -q services/offline_guardian_report.py
git diff --check
```

- [ ] **Step 5: Commit**

```bash
git add services/offline_guardian_report.py tests/integration/test_offline_guardian_scenario.py
git commit -m "feat: publish offline scenario report"
```

## Task 7: Fixed CLI, Make targets and real public-clip run

**Files:**
- Create: `tools/offline_guardian_scenario.py`
- Create: `tests/tools/test_offline_guardian_scenario.py`
- Modify: `Makefile`

**Interfaces:**
- `validate` loads and validates only the tracked suite.
- `run` prepares/reuses only the three referenced public clips, builds the current pinned realtime model, runs all scenarios and publishes one ignored report directory.
- Make targets: `alpha-offline-scenario-validate`, `alpha-offline-scenario-run`.

- [ ] **Step 1: Write CLI RED tests**

Assert exact parser surface, no caller paths/URLs/models/ports, fixed Make commands,
bounded stable output, no raw errors and safe cleanup. Patch the runner in CLI tests and
assert no production service constructor is referenced.

- [ ] **Step 2: Run RED**

```bash
../../.venv-alpha/bin/python -m pytest -q tests/tools/test_offline_guardian_scenario.py
```

Expected: CLI module and Make targets are missing.

- [ ] **Step 3: Implement validate and run**

Reuse `CorpusDownloader`, `CorpusPreparer`, `CorpusLayout` and the fixed model builder.
Select exactly `DAY-01`, `OCC-02` and `NEG-03`; reuse/download only their declared
sources and prepare only `analysis_realtime`. Generate Voice PCM in memory, pass it
through `VoiceActivityDetector` with the fixed generated runner and use the fixed
fixture ASR adapter; label that lane `GENERATED_AUDIO` and never claim real VAD/ASR
accuracy from it.

Output only result, scenario counts, lane counts, overall reason and the relative
ignored report name. Do not print absolute paths.

- [ ] **Step 4: Run focused GREEN and dry-runs**

```bash
../../.venv-alpha/bin/python -m pytest -q tests/tools/test_offline_guardian_scenario.py tests/integration/test_offline_guardian_scenario.py
make -n alpha-offline-scenario-validate
make -n alpha-offline-scenario-run
git diff --check
```

- [ ] **Step 5: Run the actual bounded flow**

```bash
../../.venv-alpha/bin/python tools/offline_guardian_scenario.py validate
../../.venv-alpha/bin/python tools/offline_guardian_scenario.py run
```

Require at least one real admitted public clip to decode and process. Record factual
PASS/FAIL/SKIP per lane. Do not change Guardian rules or fixture expectations after
seeing results; fix only implementation defects.

- [ ] **Step 6: Commit**

```bash
git add Makefile tools/offline_guardian_scenario.py tests/tools/test_offline_guardian_scenario.py
git commit -m "feat: run offline guardian scenario flow"
```

## Task 8: Full verification and handoff

**Files:**
- Modify: `SUMMARY.md`
- Modify: `docs/STATUS.md`
- Modify: `docs/CHECKPOINT.md`
- Modify: `docs/NEXT.md`
- Modify: this plan checkbox state

**Interfaces:**
- Records only aggregate software/public-fixture evidence and the exact report schema.
- Leaves private capture Task 8, public baseline, real Voice and device gates deferred.

- [ ] **Step 1: Run final focused and complete gates**

```bash
../../.venv-alpha/bin/python -m pytest -q tests/contracts/test_offline_guardian_scenario.py tests/integration/test_offline_guardian_scenario.py tests/tools/test_offline_guardian_scenario.py tests/vision/test_corpus_replay.py tests/vision/test_corpus_guardian_projection.py tests/voice/test_listen_only.py tests/api/test_alpha_app.py
../../.venv-alpha/bin/python -m pytest -q
node --test tests/frontend/*.test.mjs
../../.venv-alpha/bin/python -m compileall -q packages services tools
bash -n tools/*.sh
git diff --check
```

Run JSON parsing, Make dry-runs, tracked-media scan and added-line credential/private
literal scan. Confirm no camera/go2rtc/Ollama/notification/Baby Care process was opened.

- [ ] **Step 2: Independent review**

Request read-only review of contract closure, oracle separation, isolated state,
resource settlement, filesystem publication, HTML escaping, privacy and prohibited
client initialization. Resolve every Critical or Important finding with RED/GREEN.

- [ ] **Step 3: Update factual documents**

Record actual scenario/lane results and exact test counts. State separately what the
flow proves and what remains device-/model-/human-gated.

- [ ] **Step 4: Commit the closure**

```bash
git add SUMMARY.md docs/STATUS.md docs/CHECKPOINT.md docs/NEXT.md docs/superpowers/plans/2026-08-29-offline-guardian-scenario-flow.md
git commit -m "docs: record offline guardian scenario flow"
```

Do not push, create a PR or merge without separate approval.
