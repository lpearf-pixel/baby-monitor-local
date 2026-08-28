# Visual Regression Corpus Design

**Date:** 2026-08-28

**Status:** Approved on 2026-08-28 for corpus research, design and phased
implementation on an isolated feature branch. This approval does not authorize a
Guardian rule change, model promotion, production service mutation, public-port change,
protected-branch change or redistribution of media whose license is unclear.

## 1. Goal

Create a small, repeatable and privacy-safe infant-monitor video corpus that can replay
the existing Baby Monitor Local visual path with fixed inputs and structured outputs.
The first stage contains 10 to 20 clips of 10 to 60 seconds and must include both infant
close-ups and real licensed crib/room-wide views.

The durable loop is:

```text
pinned public source + deterministic recipe
  -> checksum-verified local media cache
  -> Xiaomi-compatible normalized profiles
  -> existing frame-source boundary and VisualWorker
  -> candidate state, Guardian event and Dashboard query projection
  -> structured replay result
  -> observational baseline/candidate comparison
  -> reviewed optimization
  -> repeat the same corpus and compare again
```

The corpus is a regression instrument. It does not prove clinical safety, replace
supervised household acceptance or turn the current model output into ground truth.

## 2. Non-goals and boundaries

- Do not change Guardian thresholds, deterministic risk rules, detector adapters,
  semantic prompts or model selection to make a baseline pass.
- Do not modify the Xiaomi producer lifecycle, Voice, Camera Reply, PTZ, audio, gauge,
  Baby Care or notification behavior.
- Do not write production event/evidence databases or start installed services during
  ordinary replay. Dashboard verification uses an isolated temporary store and the
  existing query/projection boundary.
- Do not claim file replay proves Xiaomi authentication, key acquisition, MISS/CS2
  negotiation, transport selection or real-device recovery.
- Do not download a large dataset by default, persist household media, or place raw
  infant video in Git merely because a source can be viewed publicly.
- Do not create strong Guardian risk labels where the source provides no reviewed
  ground truth.

## 3. Existing visual architecture and fixed profiles

The implementation reuses the current path:

```text
frame source
  -> VisionFramePolicy (bed-zone crop and privacy mask)
  -> RealtimeVisualAnalyzer
  -> RealtimeCandidateStateMachine
  -> optional bounded semantic review
  -> deterministic VisualRiskStateMachine
  -> Guardian event pipeline/store/query
  -> Dashboard projection
```

The repository's current Xiaomi source contract, not an assumed camera profile, defines
normalization. At this checkpoint the accepted profiles are:

| Profile | Resolution | Rate | Representation | Purpose |
| --- | --- | --- | --- | --- |
| `xiaomi_source_hd` | 2560x1440 | 10 fps | HEVC | source/decode compatibility |
| `xiaomi_live` | 1280x720 | 10 fps | normalized video | live-view-shaped replay |
| `analysis_realtime` | 960x540 | 5 fps | decoded frames | realtime worker replay |
| `analysis_slow` | 960x540 | 1 fps | decoded frames | low-rate fallback replay |

The real camera keeps `transport=auto`. An observed `cs2+udp` or `cs2+tcp` result is
diagnostic evidence, not a corpus setting. The preparation tool must read the tracked
profile definition rather than scatter these values through shell commands.

## 4. Source research and admission policy

Every source record contains `name`, `source_url`, `project_or_paper`, `license`,
`download_method`, `research_use_allowed`, `commercial_use`,
`redistribution_allowed`, `github_allowed`, `privacy_notes` and `local_only`.
Unclear redistribution is always treated as false.

### 4.1 Reviewed research datasets

| Source | Finding | First-stage decision |
| --- | --- | --- |
| [NNS Detection and Segmentation](https://github.com/ostadabbas/NNS-Detection-and-Segmentation) | The private clinical set is not public. The project describes 10 naturalistic public infant clips, but the dataset license and redistribution grant are not sufficiently explicit and the documented data endpoint was not reliably reachable during research. It is an infant action/sucking corpus, not a crib-wide safety corpus. | Optional local-only source after checksum and license review; never required and never redistributed. |
| [CribNet / CribHD](https://github.com/ostadabbas/CribNet) | CribHD-T/B/C cover toys, blankets and simulated hazards, but the published layout is an annotated image corpus rather than a continuous video corpus. A separate unambiguous dataset redistribution license was not found. | Phase-two occlusion/object reference; no raw files in Git. |
| [SmallSleeps](https://shaydamoezzi.github.io/InfantSleepWakeClassification/) | The project reports natural overnight in-crib recordings but states that raw videos cannot be released because of privacy. | Future application/evaluation dataset only; no authentication bypass. |
| [babyPose](https://zenodo.org/records/3891404) | Public CC BY 4.0 archive, approximately 3 GB, consisting primarily of 480x640 depth frames and pose annotations rather than RGB room video. | Phase-two pose validation reference; excluded from the default first-stage download. |

### 4.2 Initial small public seed candidates

The initial downloader may admit only individually reviewed files with a stable source
page, direct download, declared license, expected byte size and checksum. Current seed
candidates are:

- [Infant active sleep](https://commons.wikimedia.org/wiki/File:Infantactivesleep.webm),
  CC0, for active sleep and motion;
- [2 Month Milestone: smoother arm and leg movement](https://commons.wikimedia.org/wiki/File:2_Month_Milestone-_Makes_smoother_movements_with_arms_and_legs.webm),
  United States government public domain, for supine movement;
- [9 Month Milestone: Crawls](https://commons.wikimedia.org/wiki/File:9_Month_Milestone-_Crawls.webm),
  United States government public domain, for larger motion;
- [Safe Sleep for Babies](https://commons.wikimedia.org/wiki/File:Safe_Sleep_for_Babies.webm),
  United States government public domain, as a candidate source for crib, room-wide,
  adult-entry and negative segments.

No scenario label is assigned until a human reviews the exact downloaded revision and
time range. A source page's license metadata is recorded with the checksum. If a future
revision or redirect differs, preparation fails closed instead of silently accepting
new media.

### 4.3 Wide-room admission gate

First-stage corpus preparation is not complete until it includes at least three real,
licensed `crib_wide` or `room_wide` clips. Together they must cover:

1. an infant visible at small scale;
2. an empty crib/room or object-only negative;
3. an adult entering or present in the room.

A close-up placed on a large canvas, digitally zoomed out, composited onto a background
or otherwise transformed to simulate small scale is labelled `SYNTHETIC_SCALE`. It may
test decoding, sampling, queue behavior and small-subject robustness, but it cannot
satisfy this real-wide gate or support a real-room accuracy claim.

## 5. Storage and repository layout

Tracked assets follow existing test-fixture conventions:

```text
tests/fixtures/visual_corpus/
  README.md
  manifest.json
  baselines/
  source/
    licenses.json
    checksums.json
```

Downloaded media, normalized derivatives, temporary event stores and replay results are
ignored runtime data:

```text
runtime/test-corpus/visual/
  downloads/
  prepared/
  results/
  temp/
```

The implementation rejects symlinks, repository escape, unexpected owners/modes and
unknown files before publication. Preparation is idempotent: a valid existing artifact
is reused, a checksum mismatch fails, and interrupted output is never treated as ready.
Material retained artifacts are not automatically deleted.

## 6. Manifest and label model

The manifest is source controlled, schema versioned and deterministic. Each clip record
contains:

- stable `clip_id`, source record and source/segment checksums;
- `source_type`: `REAL`, `PUBLIC_DATASET` or `SYNTHETIC`;
- exact source time range and deterministic preparation recipe;
- normalized profile artifact digests;
- duration, fps, resolution and codec;
- license, redistribution, Git and privacy decisions;
- clip-level objective labels;
- optional temporal label spans;
- label provenance, reviewer state and confidence;
- expected pipeline behavior expressed only where independently supportable.

### 6.1 Objective labels

Labels describe observable content, not Guardian conclusions:

| Dimension | Values |
| --- | --- |
| `framing` | `close_up`, `medium`, `crib_wide`, `room_wide` |
| `subject_scale` | `tiny`, `small`, `medium`, `large`, plus measured frame-area ratio when reviewed |
| `camera_angle` | `overhead`, `high_oblique`, `eye_level`, `unknown` |
| `environment` | `crib`, `bed`, `playmat`, `room`, `other` |
| `lighting` | `day`, `low_light`, `native_ir`, `simulated_ir` |
| `baby_visibility` | `full`, `partial`, `face_occluded`, `mostly_not_visible`, `not_visible` |
| `motion` | `still`, `mild`, `active`, `adult_entering` |
| `adult_visibility` | `absent`, `partial`, `present` |
| `object_state` | `empty`, `blanket`, `toy`, `mixed`, `unknown` |

Temporal labels use half-open intervals `[start_ms, end_ms)` and the same controlled
vocabulary. Overlap is permitted, so one interval can be both `room_wide` and
`adult_entering`. Unknown and unreviewed values remain explicit rather than inferred by
the current model.

### 6.2 Guardian inference labels

`safe`, `needs_review` and `risk_candidate` are stored only in replay results as current
Guardian inference. They are never objective ground truth. A baseline change in these
values is surfaced for review, not automatically accepted or rejected as an accuracy
change.

## 7. First-stage scenario matrix

The target is 12 to 18 prepared clips, with no source download larger than the reviewed
first-stage budget and no default aggregate download of a research dataset.

| IDs | Required content |
| --- | --- |
| `DAY-01..03` | supine, side or side-like pose, and visible movement |
| `WIDE-01..03` | real licensed infant-small-in-room, empty/object-only, adult present/entering |
| `NIGHT-01..03` | sleeping, movement and low contrast; native IR is identified separately from deterministic simulated IR |
| `OCC-01..03` | partial blanket, face obstruction and mostly/not visible |
| `NEG-01..03` | empty crib, object-only and adult-only/present |

One clip may support multiple categories, but the report counts unique clips and label
intersections so duplicated derivatives cannot inflate source diversity.

## 8. Deterministic preparation

A repository entry point performs these bounded stages:

1. validate manifest and license decisions;
2. download only explicitly selected first-stage sources;
3. enforce maximum bytes and redirects, then verify expected checksum;
4. extract exact time spans without altering source files;
5. normalize fps, resolution, pixel format and codec with pinned ffmpeg arguments;
6. create explicitly labelled deterministic derivatives such as low contrast,
   grayscale/IR-like output, bounded overlay obstruction and empty/object controls;
7. probe each artifact and publish its digest and media metadata atomically;
8. refuse partial, unknown, mismatched or oversized artifacts.

The tool supports dry-run, source-only, one-clip and first-stage modes. It emits fixed
reason codes and bounded aggregate output, never raw media, local absolute paths or
download credentials. Public data requiring login, agreement or manual approval is not
downloaded automatically.

## 9. Replay architecture

### 9.1 Default worker replay

An `FfmpegFileFrameSource` implements the existing captured-frame boundary. It decodes
one prepared profile using fixed pacing and yields the same frame object consumed by the
current worker. It does not import or modify Xiaomi connection code.

The harness builds the existing frame policy, analyzer, candidate state machine,
deterministic risk machine and event pipeline with isolated dependencies. Networked
semantic review is disabled by default and reported as a distinct profile. A separately
selected semantic profile may use the existing bounded reviewer but never changes the
default baseline silently.

### 9.2 Codec/source compatibility replay

An optional isolated gate starts a temporary go2rtc instance with a generated local-only
configuration, temporary ports and the prepared HEVC artifact. It verifies ingest and
decode without touching installed launchd, the production configuration, camera URI or
long-lived Xiaomi producer. This gate is evidence for codec compatibility only.

### 9.3 Guardian and Dashboard projection

Events are written to a temporary isolated store through the current Guardian pipeline.
The harness reads them using the existing query service and Dashboard projection. It
does not start the production Dashboard, write the production SQLite file, send a
notification or export evidence.

## 10. Structured results and aggregation

Each replay result records only stable, non-private fields:

- clip, manifest and profile identifiers and digests;
- Git SHA and model artifact identifiers;
- `frames_total`, `frames_processed`, `frames_skipped` and dropped/backlog counts;
- scene-quality outcomes and existing observation/state counts;
- ratios that can be honestly derived from existing observations, including person,
  face, pose, adult and visibility-related states;
- candidate transitions, Guardian event codes/states and Dashboard projection counts;
- decode, worker and model stable reason codes;
- inference latency and total pipeline p50, p95 and maximum;
- wall duration, effective fps and bounded resource metrics where available.

The harness must not call a generic human/person result `baby_detected_ratio` unless the
active detector actually establishes infant identity. Reports aggregate by individual
labels and intersections, for example:

```text
room_wide + small + day
room_wide + adult_entering
crib_wide + low_light
close_up + face_occluded
room_wide + not_visible
```

This makes framing, scale, lighting and occlusion regressions visible instead of hiding
them in one overall score.

## 11. Baseline and optimization loop

The first baseline is observational: it records what the current version emits for the
same prepared inputs. It is keyed by manifest digest, normalization recipe digest,
runtime profile, model artifacts and Git SHA.

Comparison rules are:

- refuse comparison when corpus/profile identity differs;
- compare stable codes and counts exactly where deterministic;
- use reviewed tolerances for ratios and latency;
- show objective-label group and intersection deltas;
- distinguish missing model, skipped optional semantic review and actual failure;
- never modify a baseline automatically;
- promote a candidate baseline only with an explicit reviewed command and a clean
  result artifact.

The supported optimization loop is:

```text
record baseline
  -> change one approved visual component
  -> replay identical corpus/profile
  -> compare functional and performance deltas
  -> investigate by clip and temporal label span
  -> accept, revise or reject the candidate
  -> rerun before explicit baseline promotion
```

Tests and reports never weaken Guardian acceptance or rewrite expected inference to make
a candidate green.

## 12. Test and acceptance gates

Implementation follows TDD and includes:

1. manifest/schema, path, size, checksum and license fail-closed tests;
2. deterministic recipe and media-probe tests using tiny generated fixtures;
3. frame-source pacing, EOF, cancellation, decode-error and cleanup tests;
4. worker replay and isolated Guardian/Dashboard projection tests;
5. baseline identity, comparison and explicit-promotion tests;
6. at least one to three actual public-source replay results;
7. the full first-stage corpus replay when all admitted clips are locally available;
8. Python compilation, shell syntax/ASCII/LF, Make dry-run, frontend tests where the
   projection changes, full software tests, diff and privacy scans.

Every result is reported as `PASS`, `FAIL` or `SKIP`; every skip includes a fixed reason.
Software and public-video replay do not prove household accuracy, installed launchd
readiness, camera transport, real native IR, sustained performance or unattended care.

After short replay passes, a repeated 30-minute and then one-hour local replay may check
memory growth, queue backlog, decoder drift, worker crash, duplicate events and event
storms. Eight-hour and 24-hour replay remain later gates and are not first-stage work.

## 13. Delivery phases

1. confirm repository and visual architecture;
2. record source, license and privacy research;
3. add the approved design and executable implementation plan;
4. build manifest and directory contracts;
5. implement bounded preparation and normalization;
6. prepare 10 to 20 short clips including the real-wide gate;
7. connect file replay to the existing worker and isolated event/query path;
8. generate and compare the first observational baseline;
9. run first-stage functional/performance regression and update status documents;
10. commit focused slices on the feature branch; push only the approved branch, never
    merge or modify `main` or `stable/xiaomi-alpha`.

## 14. Completion criteria

The first milestone is complete only when fixed source revisions can be prepared again
from a clean ignored cache, all admitted files pass checksum/media validation, 10 to 20
clips include at least three real licensed wide views, the existing worker and isolated
Guardian/Dashboard path replay deterministically, a baseline/candidate comparison is
produced, focused/full software gates pass, and every unavailable dataset or device-only
gate is reported honestly.
