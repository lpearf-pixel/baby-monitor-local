# Offline Guardian Scenario Flow Design

**Date:** 2026-08-29

**Status:** Proposed for review. This document does not authorize implementation,
camera access, household-media access, production database writes, notification
delivery, Camera Reply, PTZ, baseline promotion or protected-branch changes.

## 1. Goal

Provide one repeatable offline command that demonstrates how the current product
components behave for fixed infant-monitor scenarios. The flow must use public or
generated fixtures, exercise the existing production boundaries, publish a bounded
structured report and provide a human-viewable isolated Dashboard result.

The first complete flow is:

```text
public test video
  -> existing file frame source
  -> VisionFramePolicy and VisualWorker
  -> current realtime observations and candidate transitions
  -> observational visual result

fixed reviewed scenario timeline
  -> existing VisualRiskStateMachine
  -> existing VisualRiskEventPipeline
  -> new temporary SQLite event store
  -> existing GuardianEventQueryService
  -> isolated Dashboard projection

generated test audio
  -> existing VAD / ASR fixture boundary
  -> wake and closed intent controller
  -> recording TTS sink
  -> observational Voice result

all lane results
  -> one bounded scenario report
```

This is a system regression and demonstration flow. It does not prove model accuracy,
household-scene accuracy, camera compatibility, notification delivery or unattended
care safety.

## 2. Why the lanes remain separate

Video, Guardian semantics and Voice have different evidence sources. Combining them
into one opaque PASS would hide which layer failed and would encourage treating current
model output as ground truth. The runner therefore shares one scenario identity and
timeline but keeps three independently scored lanes:

1. `visual_observation`: actual current-worker output from the video;
2. `guardian_deterministic`: fixed reviewed semantic observations through the current
   deterministic event logic;
3. `voice_generated`: generated/public audio through the current Voice boundary.

The aggregate is PASS only when every required lane passes. A skipped optional lane is
reported as SKIP and never converted to PASS. Failure in one lane does not mutate or
restart another worker.

## 3. Existing components to reuse

The implementation reuses these existing boundaries without changing their behavior:

- `FfmpegFileFrameSource` for deterministic decoded frames;
- `VisualCorpusReplay` for `VisionFramePolicy`, `VisualWorker`, realtime analysis,
  candidates and performance aggregates;
- `GuardianReplayProjector` for the current semantic runtime, risk state machine,
  event pipeline and isolated event store;
- `GuardianEventQueryService` for the exact Dashboard event projection;
- the existing authenticated Dashboard application factory in an isolated test
  configuration;
- generated Voice fixtures, the current VAD/ASR result boundary,
  `ListenOnlyController` and a recording synthesizer sink;
- current strict contracts for visual corpus results, Guardian events and Voice
  listen-only outcomes.

The flow does not import Xiaomi authentication, open a CS2 connection, start go2rtc,
call Ollama, send ntfy messages or initialize production evidence storage.

## 4. Scenario contract

Create a separate closed `OfflineGuardianScenarioV1` contract. It is not added to the
public corpus manifest and does not change public readiness or baseline contracts.

Each tracked scenario contains only:

- `schema_version=1`;
- a stable ASCII `scenario_id`;
- one existing public `clip_id` or one generated visual fixture ID;
- a `visual_profile` of `analysis_realtime` or `analysis_slow`;
- an ordered semantic timeline made from the existing `VisualReview` schema;
- expected Guardian transition counts, event counts and Dashboard counts;
- an optional generated Voice fixture ID and expected closed Voice outcome;
- lane requirements and bounded time/frame limits;
- a statement of evidence provenance: `PUBLIC_VIDEO`, `GENERATED_VISUAL`,
  `GENERATED_AUDIO` or `SYNTHETIC_SEMANTIC_ORACLE`.

It may not contain URLs, filesystem paths, hosts, credentials, camera identifiers,
household labels, model prose, raw transcript text or production database locations.
Unknown fields, duplicate scenario IDs, unordered timestamps, unsupported profiles,
unbounded counts and mismatched expectations fail before any lane starts.

## 5. First scenario set

The first implementation contains four small scenarios. They reuse already admitted
public clips when suitable; generated fixtures are used where a public clip cannot
honestly support the transport condition.

### 5.1 SAFE-SLEEP-01

- Video lane: run a current admitted sleeping/supine clip through the real worker.
- Guardian oracle: repeated visible, clear-face, supine, inside-bed observations.
- Expected deterministic effect: zero Guardian events and an empty Dashboard list.
- Voice lane: omitted.

### 5.2 FACE-OCCLUSION-01

- Video lane: run the admitted obstruction candidate and record actual current output.
- Guardian oracle: two qualifying face-not-visible observations separated by the
  current confirmation interval, one duplicate qualifying observation, then the
  current required clear recovery sequence.
- Expected deterministic effect: one event opens, no duplicate event is created, the
  same event recovers, and the Dashboard count changes from one open event to one
  recovered event.
- The report must not say the video model detected the obstruction unless the
  `visual_observation` lane actually records it.

### 5.3 ADULT-INTERVENTION-01

- Video lane: run an admitted adult-in-frame public segment.
- Guardian oracle: an active reviewed risk followed by an adult-present observation and
  the existing clear/recovery sequence.
- Expected deterministic effect: existing adult-intervention audit behavior is
  observable without inventing a new risk type.

### 5.4 VOICE-FEEDING-01

- Visual and Guardian lanes: omitted.
- Voice lane: generated audio fixtures cover exact wake, one supported Feeding command,
  the fixed acknowledgement sink, a no-wake negative and a cancellation/unsupported
  negative.
- Expected effect: exactly one accepted closed intent and one recording-sink response;
  negatives remain silent. No Baby Care client, signer, outbox or write path is built.

Diaper and burping generated scenarios may be added only after this first flow is green.
Medication remains excluded because its high-risk design and acceptance are separate.

## 6. Execution and isolation

The runner creates one mode-`0700` temporary root below ignored test runtime. Every
generated report and SQLite file is mode `0600`. It rejects symlinks, pre-existing
unexpected entries, non-owner files, hard links, repository escape and more than the
fixed scenario/report limits.

Each scenario receives a fresh visual worker state, Guardian state machine, SQLite
store, query service and Voice controller. No state carries between scenarios. The
runner closes iterators, stores, schedulers and recording sinks on success, failure,
timeout and interruption.

Production database paths, evidence paths and notification dispatchers are rejected at
construction time. The runner must prove `production_state_touched=false`,
`notification_dispatch_attempted=false`, `evidence_persisted=false`,
`camera_opened=false` and `raw_audio_persisted=false` in its aggregate.

## 7. Human-viewable result

The command writes two ignored artifacts:

- `scenario-result.v1.json`: canonical machine-readable aggregates;
- `scenario-report.html`: a static, media-free report.

The HTML report is generated from the same validated aggregate and contains no video,
frame, audio, transcript, paths, URLs or model prose. It shows:

- scenario and lane PASS/FAIL/SKIP;
- frame/decode/worker accounting and p50/p95/max;
- bounded observation and candidate counts;
- expected versus actual Guardian transition/event/Dashboard counts;
- final Dashboard event state using the existing query projection;
- Voice wake/intent/outcome counts and recording-sink response count;
- stable reason codes and explicit non-proof statements.

The first version does not start an HTTP listener. The report can be opened locally as
a static ignored artifact after the runner finishes. A future authenticated interactive
demo requires a separate decision and is not needed to prove this flow.

## 8. Result and gate semantics

Every lane has a closed result envelope:

- `PASS`: the required production boundary ran and all fixed invariants matched;
- `FAIL`: a boundary ran but failed, timed out, mismatched expectations or leaked state;
- `SKIP`: an explicitly optional dependency was unavailable before state creation.

Visual model output is observational. It is compared with the previous promoted public
baseline only after the public corpus becomes READY; this scenario flow does not create
or promote a baseline while readiness is PARTIAL.

Guardian deterministic expectations are exact software assertions because their input
is a declared synthetic semantic oracle. They are not claims about the video content.

Voice generated-audio expectations prove only fixture-path behavior. They do not prove
far-field Xiaomi microphone recall, adult speech accuracy or speaker audibility.

## 9. Failure handling

- Preserve the first stable failure code and suppress raw exceptions.
- A visual failure does not fabricate Guardian success from model output. The separate
  deterministic lane may still run, but the aggregate remains FAIL.
- A Guardian mismatch keeps the temporary store for bounded local diagnosis and never
  copies it to production.
- A Voice failure records counts only; generated audio and transcripts are not included
  in the report.
- Timeout and interruption terminate owned child processes, close resources and leave
  no running server or worker.
- Report rendering failure makes the flow FAIL even when the machine result exists.

## 10. Alternatives considered

### One opaque end-to-end PASS

Rejected. It would make model accuracy, deterministic Guardian behavior and Voice
behavior indistinguishable and could hide a fail-open boundary.

### Feed current video-model output directly into Guardian as the oracle

Rejected. Current model output is the system under test, not ground truth. It remains an
observation lane until independently reviewed labels exist.

### Start the production Dashboard and services during replay

Rejected. It risks production event writes, notifications and interference with live
workers. The isolated static report and existing query projection provide the necessary
first-stage effect.

## 11. Verification

Implementation must use TDD and include:

- contract rejection tests for unknown, private and unbounded fields;
- real generated-video decode through `VisualCorpusReplay`;
- deterministic safe, confirmation, deduplication, recovery and adult-intervention
  Guardian tests through an isolated SQLite store;
- Dashboard query projection and static report escaping/privacy tests;
- generated Voice positive and negative tests with a recording sink;
- lane timeout, cancellation, cleanup and cross-scenario isolation tests;
- proof that camera, go2rtc, Ollama, ntfy, production SQLite, evidence and Baby Care
  clients are never initialized;
- focused tests, the complete Python suite, frontend tests, compile checks, Make dry-run,
  JSON validation, `git diff --check` and final privacy/media scans.

At least one real admitted public clip must run through the completed flow before it is
reported working. Each skipped scenario must have one exact reason.

## 12. Delivery sequence

1. closed scenario and result contracts;
2. isolated multi-lane orchestrator with generated fixtures;
3. visual public-clip lane;
4. deterministic Guardian event and Dashboard projection lane;
5. static privacy-safe report;
6. generated Voice lane;
7. first four-scenario execution and factual documentation;
8. later expansion to additional infant behaviors and Voice actions;
9. private capture, real Baby Care writes, Camera Reply and remote access remain
   separate later gates.
