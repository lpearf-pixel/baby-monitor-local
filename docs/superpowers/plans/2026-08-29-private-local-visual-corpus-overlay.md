# Private Local Visual Corpus Overlay Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a strictly private, optional local visual-corpus overlay that validates
owner-authorized video without changing the existing public corpus contract or using
private media to claim public readiness.

**Architecture:** Keep `VisualCorpusManifest` and every public download/replay path
unchanged. Add a separate discriminated private descriptor, an ignored owner-private
asset resolver and explicit local-only commands. Public and local readiness are emitted
separately, and private replay has no baseline generation, comparison or promotion path.

**Tech Stack:** Python 3.11+, Pydantic 2, pytest, JSON, hashlib, ffmpeg/ffprobe, existing
Xiaomi producer diagnostics, Make.

**Spec:** `docs/superpowers/specs/2026-08-29-private-local-visual-corpus-overlay-design.md`

## Global Constraints

- Preserve the existing `PUBLIC_DATASET + DIRECT_HTTPS` contract byte-for-byte.
- `PRIVATE_LOCAL_CAPTURE` is accepted only by the private overlay contract and is
  rejected by the public manifest.
- Tracked private metadata contains only the exact allowlist in the spec; it contains
  no URL, path, host, IP, port, camera identity or prose.
- Actual file mappings and all media remain below ignored mode-`0700` runtime; every
  file is mode `0600` and never uploaded or redistributed.
- Public readiness and `LOCAL_READY` are independent. Private media never turns public
  `PARTIAL` into `READY`.
- Camera Reply remains false; capture never calls speaker or PTZ and never creates a
  second Xiaomi producer.
- Private baseline generation, comparison and promotion fail before output creation.
- Tests use generated media and temporary directories only. Real capture requires a
  separate owner-supervised authority after software review.
- Do not modify `main` or `stable/xiaomi-alpha`, create a PR, merge or push unless a
  later user turn explicitly authorizes that operation.

---

## File and interface map

- Create `packages/contracts/private_visual_overlay.py`: closed tracked descriptor,
  review states, local readiness and canonical serialization.
- Create `services/vision/private_visual_overlay.py`: ignored overlay resolution,
  permission/identity/media validation and local readiness aggregation.
- Create `tools/private_visual_corpus.py`: fixed local validate, capture-preflight,
  capture and review-preparation commands with bounded redacted output.
- Modify `Makefile`: expose explicit `alpha-visual-private-*` targets without changing
  public targets.
- Create `tests/contracts/test_private_visual_overlay.py`: source exclusivity and
  tracked metadata allowlist.
- Create `tests/vision/test_private_visual_overlay.py`: filesystem, media, review,
  multi-scenario and readiness gates.
- Create `tests/tools/test_private_visual_corpus.py`: parser, capture arguments,
  video-only output, bounded cleanup and privacy output.
- Modify `tests/contracts/test_visual_corpus.py`: prove public contract rejection of
  `PRIVATE_LOCAL_CAPTURE` and unchanged public canonical digest.
- Modify `tests/vision/test_corpus_baseline.py`: prove private result envelopes cannot
  enter public baseline operations.
- Create `config/private_visual_overlay.example.json`: generated-only structural
  example using a synthetic opaque ID and digest; no private values.
- Modify visual-corpus README/runbook and handoff documents only after software gates.

## Task 1: Add the mutually exclusive private descriptor contract

**Files:**
- Create: `packages/contracts/private_visual_overlay.py`
- Create: `tests/contracts/test_private_visual_overlay.py`
- Modify: `tests/contracts/test_visual_corpus.py`
- Create: `config/private_visual_overlay.example.json`

**Interfaces:**
- Produces `PrivateSourceType`, `PrivateReviewState`, `LocalOverlayReadiness`,
  `PrivateAssetMetadata`, `PrivateOverlayDescriptor`,
  `load_private_overlay_descriptor(path: Path) -> PrivateOverlayDescriptor` and
  `canonical_private_overlay_bytes(value: PrivateOverlayDescriptor) -> bytes`.
- Preserves `VisualCorpusManifest`, `VisualCorpusSource`, `SourceType` and
  `DownloadMethod` without adding an enum value or field.

- [x] **Step 1: Write public-compatibility RED tests**

Add tests proving the current manifest digest is unchanged and that a public source
with `source_type="PRIVATE_LOCAL_CAPTURE"` is rejected.

```python
def test_public_manifest_rejects_private_local_capture() -> None:
    payload = first_stage_payload()
    payload["clips"][0]["source_type"] = "PRIVATE_LOCAL_CAPTURE"
    with pytest.raises(ValidationError):
        VisualCorpusManifest.model_validate(payload)
```

- [x] **Step 2: Write private descriptor RED tests**

Cover the exact structural/asset allowlist, `plc-[0-9a-f]{32}`, lowercase SHA-256,
128 MiB maximum, 10–60 second duration, finite positive fps, unique scenario IDs and
closed review states. Parametrize rejection of every public source/download type.

```python
@pytest.mark.parametrize("forbidden", [
    {"source_url": "https://example.invalid/a.mp4"},
    {"path": "asset.mp4"},
    {"host": "localhost"},
    {"camera_uri": "rtsp://example.invalid/source"},
])
def test_private_metadata_rejects_locator_fields(forbidden: dict[str, str]) -> None:
    payload = private_descriptor_payload()
    payload["assets"][0].update(forbidden)
    with pytest.raises(ValidationError):
        PrivateOverlayDescriptor.model_validate(payload)
```

- [x] **Step 3: Run RED**

```bash
../../.venv-alpha/bin/python -m pytest -q \
  tests/contracts/test_private_visual_overlay.py \
  tests/contracts/test_visual_corpus.py
```

Expected: new private module/import tests fail; all pre-existing public tests remain
green.

- [x] **Step 4: Implement the minimal closed models**

Use frozen Pydantic models with `extra="forbid"`. Keep the new literal separate:

```python
class PrivateSourceType(StrEnum):
    PRIVATE_LOCAL_CAPTURE = "PRIVATE_LOCAL_CAPTURE"

class PrivateReviewState(StrEnum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"

class LocalOverlayReadiness(StrEnum):
    LOCAL_UNAVAILABLE = "LOCAL_UNAVAILABLE"
    LOCAL_PARTIAL = "LOCAL_PARTIAL"
    LOCAL_READY = "LOCAL_READY"
```

Implement the exact fields from the spec and a bounded defensive scan that maps every
locator-shaped value to `private_overlay_forbidden_locator` without returning the value.
The example descriptor uses only synthetic repeated hexadecimal values and pending
review states.

- [x] **Step 5: Run GREEN and public regression**

Run the Step 3 command, then:

```bash
../../.venv-alpha/bin/python -m pytest -q \
  tests/contracts/test_visual_corpus.py \
  tests/tools/test_visual_corpus.py \
  tests/vision/test_corpus_baseline.py
```

Expected: the new contract tests pass and all 42 pre-existing focused cases remain
green; the added public-compatibility case makes the current command 43/43.

- [x] **Step 6: Commit the contract slice**

```bash
git add packages/contracts/private_visual_overlay.py \
  tests/contracts/test_private_visual_overlay.py \
  tests/contracts/test_visual_corpus.py \
  config/private_visual_overlay.example.json
git commit -m "feat: define private visual overlay contract"
```

## Task 2: Validate ignored overlay identity and media

**Files:**
- Create: `services/vision/private_visual_overlay.py`
- Create: `tests/vision/test_private_visual_overlay.py`

**Interfaces:**
- Consumes `PrivateOverlayDescriptor` and a canonical overlay root supplied by the
  fixed tool boundary.
- Produces `PrivateOverlayValidation(readiness, reason, asset_count, scenario_count)`
  and `validate_private_overlay(descriptor, overlay_root, *, probe) ->
  PrivateOverlayValidation`.
- The injected `probe(path: Path) -> PrivateMediaFacts` returns only aggregate facts:
  bytes, SHA-256, stream counts, duration, codec, width, height and fps.

- [x] **Step 1: Write filesystem RED tests**

Use `tmp_path` to cover missing overlay, root/file modes, owner mismatch through an
injected stat result, symlinked parents/files, hard links, escape paths, duplicate
mapping entries, unknown inventory entries and a mapping to the wrong asset ID.

- [x] **Step 2: Write media RED tests**

Cover exact bytes/hash success and failures for changing file, mismatched digest,
duration, codec, dimensions and fps. Require exactly one video stream and reject any
audio, subtitle or data stream with `private_overlay_audio_present` or
`private_overlay_media_invalid`.

- [x] **Step 3: Run RED**

```bash
../../.venv-alpha/bin/python -m pytest -q \
  tests/vision/test_private_visual_overlay.py
```

Expected: collection fails because `services.vision.private_visual_overlay` is absent.

- [x] **Step 4: Implement descriptor-bound validation**

Resolve `index.json` only below the canonical root. Open each asset descriptor-first,
compare `fstat` identity to the directory entry, hash the held descriptor, probe the
same `/dev/fd` or immutable owner-private snapshot and recheck identity before success.
Never unlink ambiguous input. Return only stable reason codes.

- [x] **Step 5: Run GREEN and diff checks**

```bash
../../.venv-alpha/bin/python -m pytest -q \
  tests/contracts/test_private_visual_overlay.py \
  tests/vision/test_private_visual_overlay.py
../../.venv-alpha/bin/python -m compileall -q \
  packages/contracts/private_visual_overlay.py \
  services/vision/private_visual_overlay.py
git diff --check
```

- [x] **Step 6: Commit the validator slice**

```bash
git add services/vision/private_visual_overlay.py \
  tests/vision/test_private_visual_overlay.py
git commit -m "feat: validate private visual overlay assets"
```

## Task 3: Separate public and local readiness and clip identity

**Files:**
- Modify: `services/vision/private_visual_overlay.py`
- Modify: `tests/vision/test_private_visual_overlay.py`
- Modify: `services/vision/corpus_replay.py`
- Modify: `tests/vision/test_corpus_replay.py`

**Interfaces:**
- Produces `local_overlay_status(public_readiness, validation, required_scenarios) ->
  LocalOverlayStatus` with separate `public_readiness` and `local_readiness` fields.
- Produces one ephemeral private clip identity per `private_asset_id` and projects every
  unique `scenario_id` into comparison groups without creating another clip.

- [x] **Step 1: Write readiness RED tests**

Assert absent overlay gives `LOCAL_UNAVAILABLE` and valid media without a digest-bound
human-review capability gives `LOCAL_PARTIAL`, even when tracked review fields say
approved. Use a generated review-complete validation capability to prove one approved
asset with `("WIDE-02", "NEG-01")` can give `LOCAL_READY` while public readiness
remains `PARTIAL`. The production media-only validator must never set that capability.

- [x] **Step 2: Write multi-scenario RED tests**

Assert one asset produces one result with `scenario:WIDE-02` and `scenario:NEG-01`
exactly once in sorted order. Reject two clip identities backed by one digest or mapping.

- [x] **Step 3: Run RED**

```bash
../../.venv-alpha/bin/python -m pytest -q \
  tests/vision/test_private_visual_overlay.py \
  tests/vision/test_corpus_replay.py
```

- [x] **Step 4: Implement the minimal local aggregation**

Keep public manifest validation independent. Add a pure private comparison projection
that accepts unique assets and mapping identities; do not change public clip IDs,
`ReplayResultSet` or public readiness. Media validation retains
`content_review_complete=false`; only Task 5's digest-bound receipt validation may
produce that future capability.

- [x] **Step 5: Run GREEN**

Run the Step 3 command and the existing public focused gate (currently 43 cases after
the Task 1 source-exclusivity regression).

- [x] **Step 6: Commit the readiness slice**

```bash
git add services/vision/private_visual_overlay.py \
  tests/vision/test_private_visual_overlay.py \
  services/vision/corpus_replay.py \
  tests/vision/test_corpus_replay.py
git commit -m "feat: report private visual local readiness"
```

## Task 4: Add a bounded video-only capture boundary

**Files:**
- Create: `tools/private_visual_corpus.py`
- Create: `tests/tools/test_private_visual_corpus.py`
- Modify: `Makefile`

**Interfaces:**
- Provides `validate`, `capture-preflight`, `capture --duration {20,25,30}` and
  `review-prepare --private-asset-id <opaque-id>` commands.
- `capture` consumes injected read-only Camera Reply and Xiaomi producer snapshots in
  tests. Production uses fixed existing status/parsing boundaries and the fixed
  loopback shared `source` alias.
- Produces only bounded fields: result, reason, opaque asset ID, bytes, SHA-256,
  duration, codec, dimensions, fps and stream counts.

- [x] **Step 1: Write parser and preflight RED tests**

Assert there is no source URL, destination, host, port, camera ID, codec override,
ffmpeg argument or baseline subcommand. Reject Camera Reply not explicitly false,
pending speaker state, missing/second/replaced producer and any non-`auto` configuration.

- [x] **Step 2: Write capture RED tests**

Use fake ffmpeg/ffprobe executables. Assert fixed input is the shared loopback `source`
alias, `-map 0:v:0` and `-an` are present, captures are sequential, duration is one of
20/25/30, umask/permissions are private, output publication is atomic and timeout or
interrupt leaves no accepted mapping.

- [x] **Step 3: Run RED**

```bash
../../.venv-alpha/bin/python -m pytest -q \
  tests/tools/test_private_visual_corpus.py
```

- [x] **Step 4: Implement fixed commands**

Use an owner-private `.tmp` file with an explicit container format, one bounded ffmpeg
process and TERM/KILL settlement. Persist no audio byte. Validate the settled file
before atomically updating ignored `index.json`. Do not start/restart go2rtc or call any
Voice, Camera Reply, speaker or PTZ operation.

- [x] **Step 5: Add Make targets and run GREEN**

Add only:

```text
alpha-visual-private-validate
alpha-visual-private-capture-preflight
alpha-visual-private-capture
alpha-visual-private-review-prepare
```

Run:

```bash
../../.venv-alpha/bin/python -m pytest -q \
  tests/tools/test_private_visual_corpus.py \
  tests/vision/test_private_visual_overlay.py
make -n alpha-visual-private-validate
make -n alpha-visual-private-capture-preflight
make -n alpha-visual-private-capture
make -n alpha-visual-private-review-prepare
git diff --check
```

No live capture command runs in this task.

- [x] **Step 6: Commit the capture software slice**

```bash
git add tools/private_visual_corpus.py \
  tests/tools/test_private_visual_corpus.py Makefile
git commit -m "feat: add bounded private visual capture boundary"
```

## Task 5: Bind human review to the exact digest

**Files:**
- Modify: `tools/private_visual_corpus.py`
- Modify: `services/vision/private_visual_overlay.py`
- Modify: `tests/tools/test_private_visual_corpus.py`
- Modify: `tests/vision/test_private_visual_overlay.py`

**Interfaces:**
- `review-prepare` extracts one frame per 500 ms plus explicit first/last frames into
  ignored mode-`0600` artifacts.
- `review-status` reads an ignored digest-bound review receipt and never prints notes,
  frames or paths.
- Tracked `authorization_review` and `privacy_review` can be `approved` only when the
  ignored receipt matches the same SHA-256.

- [ ] **Step 1: Write review RED tests**

Cover sampling interval, first/last frames, real-time-playback acknowledgement,
digest mismatch, pending/rejected state, changed media and model-only review attempts.

- [ ] **Step 2: Run RED**

```bash
../../.venv-alpha/bin/python -m pytest -q \
  tests/tools/test_private_visual_corpus.py \
  tests/vision/test_private_visual_overlay.py
```

- [ ] **Step 3: Implement local review preparation and receipt checks**

The command prepares review material but never decides content. Human approval is a
separate explicit action bound to the opaque ID and digest. Keep review detail only in
ignored storage; tracked metadata records only the two closed states.

- [ ] **Step 4: Run GREEN and privacy scan**

Run the Step 2 command, compile changed Python and scan added lines for paths, URLs,
hostnames, private addresses, camera identities and media names.

- [ ] **Step 5: Commit the review slice**

```bash
git add tools/private_visual_corpus.py \
  services/vision/private_visual_overlay.py \
  tests/tools/test_private_visual_corpus.py \
  tests/vision/test_private_visual_overlay.py
git commit -m "feat: bind private visual review to asset digest"
```

## Task 6: Enforce the private baseline prohibition

**Files:**
- Modify: `services/vision/corpus_baseline.py`
- Modify: `tests/vision/test_corpus_baseline.py`
- Modify: `tools/private_visual_corpus.py`
- Modify: `tests/tools/test_private_visual_corpus.py`

**Interfaces:**
- Public `build_result_set`, `compare_result_sets` and `promote_baseline` retain their
  current public inputs and output format.
- Private result envelopes use a distinct schema and are rejected by public baseline
  loading. The private CLI exposes no generate, compare or promote command.

- [ ] **Step 1: Write baseline-boundary RED tests**

Assert private envelopes fail before destination creation with
`private_baseline_operation_forbidden`; assert public promotion behavior and its
canonical digest remain unchanged.

- [ ] **Step 2: Run RED**

```bash
../../.venv-alpha/bin/python -m pytest -q \
  tests/vision/test_corpus_baseline.py \
  tests/tools/test_private_visual_corpus.py
```

- [ ] **Step 3: Implement the minimum scope guard**

Do not add private fields to `ReplayResultSet`. Reject the distinct private envelope at
the boundary and keep private aggregate files below ignored runtime. Do not silently
drop private clips and continue with a public subset.

- [ ] **Step 4: Run GREEN and the existing public gate**

Run the Step 2 command and the 42-test focused public corpus gate.

- [ ] **Step 5: Commit the baseline guard**

```bash
git add services/vision/corpus_baseline.py \
  tests/vision/test_corpus_baseline.py \
  tools/private_visual_corpus.py \
  tests/tools/test_private_visual_corpus.py
git commit -m "fix: reject private visual baseline operations"
```

## Task 7: Software closure and documentation

**Files:**
- Modify: `tests/fixtures/visual_corpus/README.md`
- Create: `docs/runbooks/PRIVATE_VISUAL_CORPUS_OVERLAY.md`
- Modify: `SUMMARY.md`
- Modify: `docs/STATUS.md`
- Modify: `docs/CHECKPOINT.md`
- Modify: `docs/NEXT.md`

**Interfaces:**
- Documents public/local readiness separately and provides short ASCII-only commands.
- Does not add a real private descriptor or media.

- [ ] **Step 1: Run all overlay and public focused tests**

```bash
../../.venv-alpha/bin/python -m pytest -q \
  tests/contracts/test_private_visual_overlay.py \
  tests/contracts/test_visual_corpus.py \
  tests/tools/test_private_visual_corpus.py \
  tests/tools/test_visual_corpus.py \
  tests/vision/test_private_visual_overlay.py \
  tests/vision/test_corpus_replay.py \
  tests/vision/test_corpus_baseline.py
```

- [ ] **Step 2: Run complete software and static gates**

```bash
../../.venv-alpha/bin/python -m pytest -q
../../.venv-alpha/bin/python -m compileall -q packages services tools
bash -n tools/*.sh
git diff --check
```

Run JSON parsing, Make dry-runs, tracked-media checks and a final added-line privacy
scan. Verify the existing public command still reports 13 clips, `PARTIAL` and two
missing scenarios.

- [ ] **Step 3: Independent review before local commit**

Request a review of the complete implementation for source exclusivity, path
containment, TOCTOU, permission enforcement, no-audio behavior, readiness isolation,
baseline rejection and producer lifecycle safety. Resolve every Critical or Important
finding with RED/GREEN tests before committing.

- [ ] **Step 4: Update factual handoff documents**

Record software evidence only. State that no household media was captured, no local
asset was admitted and `LOCAL_READY` was not achieved.

- [ ] **Step 5: Commit the closure**

```bash
git add tests/fixtures/visual_corpus/README.md \
  docs/runbooks/PRIVATE_VISUAL_CORPUS_OVERLAY.md \
  SUMMARY.md docs/STATUS.md docs/CHECKPOINT.md docs/NEXT.md
git commit -m "docs: document private visual overlay operations"
```

Do not push, create a PR or merge without a later explicit instruction.

## Task 8: Owner-supervised local capture and admission

**Files:**
- Future tracked metadata only after approval:
  `tests/fixtures/visual_corpus/private_overlay.json`
- Ignored runtime only: private overlay index, original video, review frames, receipts
  and local results.

**Interfaces:**
- Consumes the reviewed software head and explicit owner authority for one capture
  session.
- Produces at most two distinct 20–30 second candidates and admits at most one opaque
  asset carrying `("WIDE-02", "NEG-01")`.

- [ ] **Step 1: Reconfirm runtime preconditions without mutation**

Require Camera Reply false, no pending speaker state, one existing `transport=auto`
Xiaomi producer and no replacement. Stop if any value is unknown.

- [ ] **Step 2: Capture candidates sequentially**

The owner prepares one room-wide empty-crib take and one crib-wide empty-crib take.
Capture video only for 20, 25 or 30 seconds. Do not restart go2rtc or move the camera.

- [ ] **Step 3: Validate aggregate media facts**

Require mode `0600`, exact hash/bytes, one video stream, no other streams, permitted
duration and matching codec/dimensions/fps. Confirm the shared producer identity did not
change and its consumer count returned to the pre-capture state.

- [ ] **Step 4: Complete human content review**

Review every 500 ms, first/last frames and one real-time playback for people, babies,
reflections, privacy identifiers, transitions and camera movement. Reject any failing
candidate without editing tracked metadata.

- [ ] **Step 5: Propose one tracked descriptor**

Only after one candidate passes, propose the exact allowlisted metadata for review.
Do not include the ignored mapping or any path. One asset carries both scenario IDs;
do not create a second clip from the same frames.

- [ ] **Step 6: Validate local readiness without baseline use**

After owner approval of the descriptor, local validation may report
`local_readiness=LOCAL_READY` while public validation remains `PARTIAL`. Do not run any
baseline command. Stop and request a separate baseline-use decision.

## Current exact next action

Tasks 1–4 are complete at `0bd6e1a`, `e24eaf7`, `5cf6b0a` and `271badc`. Task 4 added
the bounded video-only capture software without running a live capture. The exact next
slice is Task 5 digest-bound human-review software; do not capture household media or
create a real private descriptor during software Tasks 1–7.
Task 8 always requires a fresh explicit owner-supervised capture authority.
