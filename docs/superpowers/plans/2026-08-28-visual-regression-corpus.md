# Visual Regression Corpus Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a checksum-pinned 10-to-20-clip infant-monitor corpus and a repeatable offline replay/baseline loop through the existing visual worker, isolated Guardian event store and Dashboard query projection.

**Architecture:** Track only strict manifests, source/license records, deterministic recipes, schemas and observational baselines. Keep downloaded and generated media in the ignored `runtime/test-corpus/visual` tree. Decode prepared files through a new `FfmpegFileFrameSource`, inject it into the existing `VisualWorker`, record current realtime observations/candidate transitions and optionally existing semantic review, then persist Guardian events only to a temporary store and compare structured results against an explicitly promoted baseline.

**Tech Stack:** Python 3.11+, Pydantic 2, urllib, hashlib, subprocess, ffmpeg/ffprobe, Pillow/OpenCV, pytest, existing VisualWorker/Guardian SQLite services, Make, JSON.

**Spec:** `docs/superpowers/specs/2026-08-28-visual-regression-corpus-design.md`

## Global Constraints

- Work only on `codex/visual-regression-corpus`; never modify `main` or `stable/xiaomi-alpha`.
- Preserve the root checkout's unrelated untracked `Interactive` and `test.sh`; do not reset, clean, merge, delete or force-push.
- The first-stage corpus contains 10 to 20 clips of 10 to 60 seconds and includes at least three real licensed `crib_wide`/`room_wide` clips.
- A real-wide set must cover infant-small-in-room, empty/object-only and adult-present/entering; `SYNTHETIC_SCALE` cannot satisfy this gate.
- Raw/normalized media, temporary databases and result runs stay below ignored `runtime/test-corpus/visual`; never commit household media, downloaded infant video, generated settings or SQLite files.
- Unknown redistribution means `redistribution_allowed=false` and `github_allowed=false`; authenticated/private sources are never bypassed.
- Keep real Xiaomi `transport=auto`; offline replay must not import Xiaomi authentication or create another camera producer.
- Reuse the existing `CapturedFrame`, `VisionFramePolicy`, `VisualWorker`, realtime analyzer/candidate machine, `VisualRiskEventPipeline`, `VisualRiskEventStore` and `GuardianEventQueryService` boundaries.
- Objective labels remain separate from current Guardian inference. Never name a generic person result `baby_detected_ratio`.
- Baselines are observational, identity-bound and explicitly promoted. Tests must not change Guardian rules, thresholds, detector output or labels to make a candidate pass.
- All CLIs emit fixed reason codes and bounded aggregate fields; no URL, path, raw exception, frame, transcript, credential or private network value is printed.
- User-facing shell stays ASCII/LF and macOS Bash 3.2 compatible. All subprocesses use fixed argv, bounded timeout and explicit cleanup.
- Implementation uses strict TDD. Each task records RED, minimal GREEN, focused verification and one focused commit before advancing.

## File and interface map

- `packages/contracts/visual_corpus.py`: immutable manifest, objective-label, preparation, replay-result and comparison contracts.
- `services/vision/corpus_manifest.py`: strict JSON load, canonical digest and first-stage admission checks.
- `services/vision/corpus_storage.py`: safe ignored layout, atomic publication and checksum helpers.
- `services/vision/corpus_download.py`: bounded HTTPS acquisition from manifest-owned URLs.
- `services/vision/corpus_prepare.py`: ffprobe validation and deterministic trim/transcode/derivative recipes.
- `services/stream/file_frame_source.py`: bounded ffmpeg decoder yielding existing `CapturedFrame` values.
- `services/vision/corpus_replay.py`: worker construction, observation recording, isolated events/query projection and replay metrics.
- `services/vision/corpus_baseline.py`: result-set identity, deterministic comparison and explicit promotion.
- `tools/visual_corpus.py`: thin `validate`, `prepare`, `replay`, `compare`, `promote` and `long-replay` CLI.
- `tools/visual_corpus_codec_gate.py`: optional isolated local go2rtc/HEVC compatibility gate.
- `tests/fixtures/visual_corpus/`: tracked manifest, license/checksum registry, baseline and contributor instructions; no media.
- `tests/contracts/test_visual_corpus.py`, `tests/vision/test_corpus_*.py`, `tests/stream/test_file_frame_source.py`, `tests/tools/test_visual_corpus*.py`: focused regression coverage.
- `Makefile`: fixed corpus entry points only.
- `SUMMARY.md`, `docs/STATUS.md`, `docs/CHECKPOINT.md`, `docs/NEXT.md`, `README.md`: final factual handoff and operator workflow.

---

### Task 1: Strict corpus contracts and tracked skeleton

**Files:**
- Create: `packages/contracts/visual_corpus.py`
- Create: `services/vision/corpus_manifest.py`
- Create: `tests/contracts/test_visual_corpus.py`
- Create: `tests/fixtures/visual_corpus/README.md`
- Create: `tests/fixtures/visual_corpus/manifest.json`
- Create: `tests/fixtures/visual_corpus/source/licenses.json`
- Create: `tests/fixtures/visual_corpus/source/checksums.json`

**Interfaces:**
- Produces: `VisualCorpusManifest`, `VisualCorpusClip`, `VisualCorpusSource`, `ObjectiveLabels`, `TemporalLabelSpan`, `NormalizationProfile`, `ReplayResult`, `ReplayResultSet`, `BaselineComparison`.
- Produces: `load_manifest(path: Path) -> VisualCorpusManifest`, `canonical_manifest_digest(manifest: VisualCorpusManifest) -> str`, `validate_first_stage(manifest: VisualCorpusManifest) -> None`.
- Consumes: `NormalizedPolygon` from `packages.contracts.vision` for clip-specific public-test crop/mask geometry.

- [x] **Step 1: Write manifest RED tests**

Create tests that construct a 12-clip fixture and assert strict rejection of extra keys, duplicate source/clip IDs, unknown labels, temporal spans outside the clip, non-HTTPS URLs, invalid SHA-256, unclear-license sources marked Git-allowed, derived clips without a parent/recipe, and inference labels placed in `objective_labels`.

```python
def test_first_stage_requires_three_distinct_real_wide_clips() -> None:
    manifest = valid_manifest()
    manifest["clips"] = [
        clip("WIDE-01", framing="room_wide", source_type="PUBLIC_DATASET"),
        *[clip(f"DAY-{index:02d}") for index in range(1, 10)],
    ]
    parsed = VisualCorpusManifest.model_validate(manifest)

    with pytest.raises(ValueError, match="visual_corpus_real_wide_required"):
        validate_first_stage(parsed)


def test_synthetic_scale_never_satisfies_real_wide_gate() -> None:
    manifest = first_stage_manifest(
        wide_source_types=("SYNTHETIC",) * 3,
        wide_recipe_kinds=("SYNTHETIC_SCALE",) * 3,
    )
    with pytest.raises(ValueError, match="visual_corpus_real_wide_required"):
        validate_first_stage(manifest)
```

- [x] **Step 2: Run the contract tests and record RED**

Run: `python -m pytest -q tests/contracts/test_visual_corpus.py`

Expected: collection fails because `packages.contracts.visual_corpus` does not exist.

- [x] **Step 3: Implement frozen Pydantic contracts and canonical loader**

Use `ConfigDict(extra="forbid", frozen=True)` throughout. Define controlled `StrEnum`
types for source type, framing, scale, camera angle, environment, lighting, visibility,
motion, adult visibility, object state, label provenance and replay status. Canonicalize
with `model_dump(mode="json")`, `json.dumps(sort_keys=True, separators=(",", ":"))`
and SHA-256.

```python
def load_manifest(path: Path) -> VisualCorpusManifest:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
        return VisualCorpusManifest.model_validate(payload)
    except (OSError, UnicodeError, json.JSONDecodeError, ValidationError) as exc:
        raise VisualCorpusManifestError("visual_corpus_manifest_invalid") from exc


def canonical_manifest_digest(manifest: VisualCorpusManifest) -> str:
    encoded = json.dumps(
        manifest.model_dump(mode="json"),
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("ascii")
    return hashlib.sha256(encoded).hexdigest()
```

`validate_first_stage` enforces 10-to-20 clips, 10-to-60-second duration, all required
scenario families, three real-wide clips and the three wide content roles. Count unique
prepared clip IDs, never derivative aliases.

- [x] **Step 4: Add the tracked media-free skeleton**

The initial manifest uses `schema_version=1`, an empty `clips` list and
`readiness="DESIGN_ONLY"`; `validate_first_stage` must reject it until Task 4 admits the
real clips. The README explains that media belongs under ignored runtime and that
license/checksum records are authoritative. License records include NNS, CribHD,
SmallSleeps and babyPose as excluded/deferred research entries plus reviewed Wikimedia
candidate entries.

- [x] **Step 5: Run focused GREEN and commit**

Run:

```bash
python -m pytest -q tests/contracts/test_visual_corpus.py
python -m compileall -q packages/contracts/visual_corpus.py services/vision/corpus_manifest.py
git diff --check
```

Expected: all tests PASS and the tracked fixture contains no media or private value.

Commit: `feat: define visual corpus contracts`

### Task 2: Private runtime layout and bounded source acquisition

**Files:**
- Create: `services/vision/corpus_storage.py`
- Create: `services/vision/corpus_download.py`
- Create: `tests/vision/test_corpus_storage.py`
- Create: `tests/vision/test_corpus_download.py`

**Interfaces:**
- Consumes: `VisualCorpusManifest`, `VisualCorpusSource`.
- Produces: `CorpusLayout.for_repository(root: Path) -> CorpusLayout` with `downloads`, `prepared`, `results`, `temp`.
- Produces: `sha256_file(path: Path, *, max_bytes: int) -> tuple[str, int]`.
- Produces: `CorpusDownloader.fetch(source: VisualCorpusSource) -> DownloadedSource`.

- [x] **Step 1: Write path/publication RED tests**

Tests cover repository/runtime parent symlinks, leaf symlink/hardlink/FIFO/socket,
wrong uid/mode, path traversal, final replacement, partial temp, checksum mismatch and
directory/file count limits. Use only `tmp_path`; do not touch repository runtime.

```python
def test_layout_rejects_runtime_parent_symlink(tmp_path: Path) -> None:
    outside = tmp_path / "outside"
    outside.mkdir()
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "runtime").symlink_to(outside, target_is_directory=True)
    with pytest.raises(CorpusStorageError, match="visual_corpus_storage_unsafe"):
        CorpusLayout.for_repository(repo)
```

- [x] **Step 2: Write downloader RED tests with a fake opener**

Require HTTPS, manifest-owned URL, maximum 128 MiB per source, maximum 256 MiB per
first-stage run, bounded redirects, fixed User-Agent, timeout, streaming hash, exact
byte count and SHA-256, no proxy inheritance and atomic no-replace publication.

```python
def test_download_checksum_mismatch_never_publishes(tmp_path: Path) -> None:
    downloader = CorpusDownloader(layout=layout(tmp_path), opener=fake_https(b"wrong"))
    with pytest.raises(CorpusDownloadError, match="visual_corpus_checksum_mismatch"):
        downloader.fetch(source(expected_sha256="0" * 64, expected_bytes=5))
    assert list(layout(tmp_path).downloads.iterdir()) == []
```

- [x] **Step 3: Run RED**

Run: `python -m pytest -q tests/vision/test_corpus_storage.py tests/vision/test_corpus_download.py`

Expected: imports fail because the storage/downloader modules do not exist.

- [x] **Step 4: Implement safe storage and downloader**

Open runtime directories without following symlinks, require the current uid, use 0700
directories and 0600 files, stream to a randomized private temp, fsync file and parent,
verify size/digest, then publish with the repository's established atomic no-replace
pattern. Redirects remain HTTPS and are allowed only to the manifest source host or an
explicit tracked mirror host. Error surfaces use fixed `visual_corpus_*` codes.

- [x] **Step 5: Run GREEN and commit**

Run:

```bash
python -m pytest -q tests/vision/test_corpus_storage.py tests/vision/test_corpus_download.py
python -m compileall -q services/vision/corpus_storage.py services/vision/corpus_download.py
git diff --check
```

Commit: `feat: acquire visual corpus sources safely`

### Task 3: Deterministic ffprobe and preparation recipes

**Files:**
- Create: `services/vision/corpus_prepare.py`
- Create: `tests/vision/test_corpus_prepare.py`
- Modify: `tests/fixtures/visual_corpus/manifest.json`

**Interfaces:**
- Consumes: downloaded source, clip segment, `NormalizationProfile`, `CorpusLayout`.
- Produces: `probe_media(path: Path, *, runner: CommandRunner) -> MediaProbe`.
- Produces: `CorpusPreparer.prepare_clip(clip: VisualCorpusClip) -> PreparedClip`.
- Produces fixed profiles `xiaomi_source_hd`, `xiaomi_live`, `analysis_realtime`, `analysis_slow`.

- [x] **Step 1: Write argv/probe RED tests**

Assert no shell execution, no caller-provided codec/filter arguments, fixed `-an`,
bounded timeout, one video stream, finite duration, and exact profile metadata. Reject
extra streams, unknown codecs, oversized dimensions, duration drift, stderr leakage,
partial output and mismatched ffprobe results.

```python
def test_source_hd_uses_fixed_hevc_profile() -> None:
    runner = RecordingRunner(valid_probe())
    CorpusPreparer(layout=layout(), runner=runner).prepare_clip(clip("DAY-01"))
    ffmpeg = runner.calls[0]
    assert ffmpeg[:3] == ("ffmpeg", "-nostdin", "-hide_banner")
    assert ("-c:v", "libx265") in adjacent_pairs(ffmpeg)
    assert ("-r", "10") in adjacent_pairs(ffmpeg)
    assert "scale=2560:1440" in ffmpeg
    assert "-an" in ffmpeg
```

- [x] **Step 2: Write deterministic derivative RED tests**

Support only tracked recipe kinds: `SOURCE_SEGMENT`, `SIMULATED_IR`, `LOW_CONTRAST`,
`BOUNDED_OCCLUSION`, `SYNTHETIC_SCALE`, `LOOP_TO_MINIMUM`. Each recipe has a fixed
filter builder and must preserve an explicit parent. Reject free-form filters.

- [x] **Step 3: Run RED**

Run: `python -m pytest -q tests/vision/test_corpus_prepare.py`

- [x] **Step 4: Implement ffprobe, fixed recipes and atomic prepared artifacts**

Use subprocess argv with `stdin=DEVNULL`, `stdout=PIPE`, `stderr=DEVNULL`, fixed timeout
and process-group cleanup. The deterministic base command removes audio and metadata,
normalizes SAR/pixel format and uses constant-frame-rate output. Record the ffmpeg
version digest in `PreparedClip`; do not assume bit-identical output across different
ffmpeg builds.

```python
PROFILE_ARGS = {
    "xiaomi_source_hd": ("scale=2560:1440", "10", "libx265"),
    "xiaomi_live": ("scale=1280:720", "10", "libx264"),
    "analysis_realtime": ("scale=960:540", "5", "mjpeg"),
    "analysis_slow": ("scale=960:540", "1", "mjpeg"),
}
```

If `libx265` is absent, the HEVC profile is `SKIP` with
`visual_corpus_hevc_encoder_unavailable`; it never silently changes codec.

- [x] **Step 5: Run GREEN and commit**

Run:

```bash
python -m pytest -q tests/vision/test_corpus_prepare.py
python -m compileall -q services/vision/corpus_prepare.py
git diff --check
```

Commit: `feat: prepare deterministic visual corpus clips`

### Task 4: Admit and label the first 10-to-20 clips

**Files:**
- Modify: `tests/fixtures/visual_corpus/manifest.json`
- Modify: `tests/fixtures/visual_corpus/source/licenses.json`
- Modify: `tests/fixtures/visual_corpus/source/checksums.json`
- Modify: `tests/fixtures/visual_corpus/README.md`
- Create: `tests/vision/test_first_stage_visual_corpus.py`

**Interfaces:**
- Consumes: Task 1 contracts and Task 3 recipe vocabulary.
- Produces: first-stage manifest with source/clip identities, objective labels, temporal spans and reviewed source metadata.

- [x] **Step 1: Add a RED acceptance test for the exact first-stage manifest**

```python
def test_tracked_first_stage_manifest_is_complete() -> None:
    manifest = load_manifest(FIXTURE_ROOT / "manifest.json")
    validate_first_stage(manifest)
    assert 10 <= len(manifest.clips) <= 20
    assert sum(clip.labels.framing in {"crib_wide", "room_wide"}
               and clip.source_type in {"REAL", "PUBLIC_DATASET"}
               for clip in manifest.clips) >= 3
```

Expected initial result: FAIL with `visual_corpus_first_stage_incomplete`.

- [x] **Step 2: Acquire only the reviewed small public candidates into a temporary research cache**

Use the Wikimedia original-file redirects for Infant active sleep, CDC 2-month movement,
CDC 9-month crawling, Safe Sleep for Babies and Infant babbling in crib. Record exact
bytes and SHA-256 after download; preserve the source-page SHA-1 separately where
available. Never commit the files.

- [x] **Step 3: Generate contact sheets and inspect exact time ranges**

Generate a local-only frame every two seconds, inspect it, then record only content that
is visibly supported. Assign `label_provenance=frame_review`; use `unknown` when not
supportable. Do not infer infant identity from a generic person detector.

- [x] **Step 4: Build 10-to-20 admitted clips or an honest PARTIAL set**

Use non-overlapping real source segments where possible and clearly parented
deterministic variants. Cover `DAY-01..03`, `WIDE-01..03`, `NIGHT-01..03`,
`OCC-01..03`, and `NEG-01..03`. Real wide clips must pass the three-content-role gate;
if the reviewed public sources do not provide all three roles, keep readiness
`PARTIAL`, report the missing role as `SKIP visual_corpus_real_wide_source_missing`,
continue software implementation, and do not fabricate the label.

Current result: 11 reviewed clips are admitted. `WIDE-02`, `OCC-03`, `NEG-01` and
`NEG-02` remain missing, so this step is complete only as the approved PARTIAL path;
it does not satisfy the READY admission gate.

- [x] **Step 5: Run manifest/license privacy gates and commit**

Run:

```bash
python -m pytest -q tests/contracts/test_visual_corpus.py tests/vision/test_first_stage_visual_corpus.py
git ls-files tests/fixtures/visual_corpus | rg '\.(mp4|mov|webm|ogv|mkv|avi|jpg|jpeg|png)$'
git diff --check
```

The media scan is expected to print no paths and return the normal no-match status.

Commit: `test: admit first visual regression corpus`

### Task 5: File-backed frame source

**Files:**
- Modify: `services/stream/frame_source.py`
- Create: `services/stream/file_frame_source.py`
- Create: `tests/stream/test_file_frame_source.py`

**Interfaces:**
- Produces: `FfmpegFileFrameSource(path: Path, *, fps: Literal[1, 5, 10], runner: DecoderFactory = ...)`.
- Produces: `iter_frames(*, started_at: datetime, pace: bool = False) -> Iterator[CapturedFrame]`.
- Consumes: prepared media metadata and existing `CapturedFrame`.

- [x] **Step 1: Write decoder lifecycle RED tests**

Cover fixed argv, JPEG pipe framing, aware deterministic timestamps, fps pacing,
non-monotonic prevention, output-size limits, malformed JPEG, early EOF, timeout,
cancel/close, stderr suppression and no child leakage.

```python
def test_frames_use_media_time_not_wall_clock(tmp_path: Path) -> None:
    source = FfmpegFileFrameSource(
        tmp_path / "clip.mp4", fps=5, decoder_factory=fake_decoder(three_jpegs())
    )
    frames = tuple(source.iter_frames(started_at=NOW, pace=False))
    assert [frame.captured_at for frame in frames] == [
        NOW,
        NOW + timedelta(milliseconds=200),
        NOW + timedelta(milliseconds=400),
    ]
```

- [x] **Step 2: Run RED**

Run: `python -m pytest -q tests/stream/test_file_frame_source.py`

- [x] **Step 3: Implement a bounded MJPEG pipe decoder**

Invoke ffmpeg with the prepared file as the only input, `-an`, fixed fps and
`image2pipe/mjpeg`. Reuse `Go2RtcControlledFrameSource._validate_jpeg` only after making
that validation a module-level internal helper, preserving all existing frame-source
tests. Read JPEG SOI/EOI with a 16 MiB cap and never buffer the full decoded video.

- [x] **Step 4: Run focused compatibility GREEN and commit**

Run:

```bash
python -m pytest -q tests/stream/test_frame_source.py tests/stream/test_file_frame_source.py
python -m compileall -q services/stream/frame_source.py services/stream/file_frame_source.py
git diff --check
```

Commit: `feat: replay files through captured frame source`

### Task 6: Realtime worker replay and structured metrics

**Files:**
- Create: `services/vision/corpus_replay.py`
- Create: `tests/vision/test_corpus_replay.py`

**Interfaces:**
- Consumes: `FfmpegFileFrameSource`, `VisualCorpusClip`, `VisionFramePolicy`, `VisualWorker`, `RealtimeVisualAnalyzer`, `RealtimeCandidateStateMachine`, `RealtimeLoadController`.
- Produces: `VisualCorpusReplay.run_clip(clip: VisualCorpusClip, profile: ReplayProfile) -> ReplayResult`.
- Produces: `RecordingRealtimeAnalyzer` that delegates to the current analyzer while collecting bounded aggregate observations.

- [x] **Step 1: Write worker-integration RED tests**

Drive synthetic JPEG frames through the real `VisionFramePolicy` and `VisualWorker` with
the current analyzer/candidate/load components. Assert total/processed/skipped counts,
scene-quality and current pose/face/bed/adult/head-face aggregates, candidate transitions,
model state, effective fps and p50/p95/max. Do not persist individual frame observations.

```python
def test_replay_uses_real_worker_and_returns_bounded_aggregates(tmp_path: Path) -> None:
    result = replay(fake_prepared_clip(tmp_path), profile=realtime_profile())
    assert result.frames_total == 20
    assert result.frames_processed + result.frames_skipped == 20
    assert result.observation_counts["scene_quality.usable"] <= 20
    assert result.frame_observations_persisted is False
```

- [x] **Step 2: Add fail-closed RED tests**

Test unavailable model, analyzer exception, decode error, worker exception, invalid clip
identity and result overflow. The result is `FAIL` or `SKIP` with one stable reason;
never fabricate zero-risk success.

- [x] **Step 3: Run RED**

Run: `python -m pytest -q tests/vision/test_corpus_replay.py`

- [x] **Step 4: Implement deterministic replay orchestration**

Use a full-frame public-test polygon unless the manifest supplies a reviewed clip ROI.
The normal public corpus has no household privacy mask, but still passes through
`VisionFramePolicy`. Create a fresh analyzer/candidate/load state per clip so no motion,
load or candidate state leaks between clips. Use media timestamps as worker monotonic
time and a separate performance counter for wall latency.

- [x] **Step 5: Run GREEN and commit**

Run:

```bash
python -m pytest -q tests/vision/test_worker.py tests/vision/test_realtime_analyzer.py tests/vision/test_realtime_candidates.py tests/vision/test_corpus_replay.py
python -m compileall -q services/vision/corpus_replay.py
git diff --check
```

Commit: `feat: replay corpus through visual worker`

### Task 7: Isolated Guardian events and Dashboard query projection

**Files:**
- Modify: `services/vision/corpus_replay.py`
- Create: `tests/vision/test_corpus_guardian_projection.py`
- Modify: `packages/contracts/visual_corpus.py`

**Interfaces:**
- Consumes: existing `VisualReviewRuntime`, `VisualRiskStateMachine`, `VisualRiskEventPipeline`, `VisualRiskEventStore`, `GuardianEventQueryService`.
- Extends: `ReplayResult.guardian` with semantic profile, transition/event counts and Dashboard projection counts.

- [ ] **Step 1: Write isolated-store RED tests**

Inject a fixed synthetic `VisualReview` sequence through the existing risk runtime and
pipeline, using `tmp_path / "events.sqlite3"`. Assert current Guardian confirmation,
dedup/recovery semantics and query projection. Assert the repository/runtime database,
notification dispatcher and evidence recorder are never opened.

```python
def test_guardian_projection_uses_only_ephemeral_store(tmp_path: Path) -> None:
    result = run_guardian_profile(
        reviews=confirmed_face_missing_sequence(),
        database=tmp_path / "events.sqlite3",
    )
    assert result.event_counts["face_not_visible.open"] == 1
    assert result.dashboard_event_count == 1
    assert result.production_state_touched is False
```

- [ ] **Step 2: Write optional semantic-profile RED tests**

`realtime_only` never invents Guardian events. `semantic_existing` uses only the current
bounded reviewer and reports `SKIP semantic_reviewer_unavailable` when unavailable.
Synthetic fixed reviews are allowed only in software tests and must report
`semantic_profile="synthetic_test"`.

- [ ] **Step 3: Run RED, implement wiring, then run GREEN**

Run:

```bash
python -m pytest -q tests/vision/test_corpus_guardian_projection.py tests/vision/test_risk_event_pipeline.py tests/events/test_guardian_query.py
```

Implement callback wiring without changing the existing state machines. Close the
scheduler/executor/store on every outcome and serialize only aggregate query fields.

- [ ] **Step 4: Commit**

Run `git diff --check` and commit: `feat: project corpus replay into guardian events`

### Task 8: Baseline, comparison and explicit promotion

**Files:**
- Create: `services/vision/corpus_baseline.py`
- Create: `tests/vision/test_corpus_baseline.py`
- Create: `tests/fixtures/visual_corpus/baselines/README.md`
- Create after actual replay: `tests/fixtures/visual_corpus/baselines/visual-baseline.v1.json`

**Interfaces:**
- Produces: `build_result_set(manifest_digest: str, profile: str, results: tuple[ReplayResult, ...]) -> ReplayResultSet`.
- Produces: `compare_result_sets(baseline: ReplayResultSet, candidate: ReplayResultSet) -> BaselineComparison`.
- Produces: `promote_baseline(candidate_path: Path, destination: Path, *, expected_digest: str) -> str`.

- [ ] **Step 1: Write identity/comparison RED tests**

Reject manifest/profile/model/recipe mismatches, missing/duplicate clips, non-finite
metrics, candidate errors and schema drift. Compare deterministic counts/codes exactly;
compare ratios and latency using source-controlled tolerances. Group deltas by framing,
scale, lighting, visibility and their intersections.

```python
def test_comparison_refuses_different_manifest() -> None:
    with pytest.raises(BaselineError, match="visual_baseline_identity_mismatch"):
        compare_result_sets(
            result_set(manifest_digest="a" * 64),
            result_set(manifest_digest="b" * 64),
        )
```

- [ ] **Step 2: Write promotion RED tests**

Promotion requires exact candidate digest, all mandatory clips `PASS`, no missing wide
group and no existing destination replacement. It writes canonical JSON atomically and
never promotes a `SKIP`/`FAIL` result.

- [ ] **Step 3: Run RED and implement minimal comparison**

Run: `python -m pytest -q tests/vision/test_corpus_baseline.py`

The comparison returns `PASS`, `REGRESSION`, `INCOMPARABLE` or `FAILED` plus bounded
per-group deltas. A regression never edits the baseline.

- [ ] **Step 4: Run GREEN and commit**

Run:

```bash
python -m pytest -q tests/vision/test_corpus_baseline.py
python -m compileall -q services/vision/corpus_baseline.py
git diff --check
```

Commit: `feat: compare visual corpus baselines`

### Task 9: CLI, Make entries and actual public replay

**Files:**
- Create: `tools/visual_corpus.py`
- Create: `tests/tools/test_visual_corpus.py`
- Modify: `Makefile`
- Modify: `tests/deploy/test_alpha_commands.py`

**Interfaces:**
- Produces: `make alpha-visual-corpus-validate`, `alpha-visual-corpus-prepare`, `alpha-visual-regression`, `alpha-visual-regression-compare`, `alpha-visual-regression-promote`, `alpha-visual-regression-long`.

- [ ] **Step 1: Write CLI/Make RED tests**

Assert fixed manifest/runtime locations, first-stage selection by default, no URL/path
override, explicit baseline digest for promotion, canonical JSON result file with 0600,
stable stdout, redacted errors and no production service commands.

```python
def test_make_replay_is_a_thin_fixed_entry() -> None:
    completed = subprocess.run(
        ["make", "-n", "alpha-visual-regression"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert completed.returncode == 0
    assert completed.stdout.strip() == (
        "./.venv-alpha/bin/python tools/visual_corpus.py replay --first-stage"
    )
```

- [ ] **Step 2: Run RED and implement thin CLI**

Run: `python -m pytest -q tests/tools/test_visual_corpus.py tests/deploy/test_alpha_commands.py`

Subcommands call service functions only. Output is fixed `key=value`; result details go
to canonical ignored JSON. Ctrl-C stops children, retains private partial state and exits
nonzero.

- [ ] **Step 3: Prepare and replay one to three actual public clips**

Run:

```bash
make alpha-visual-corpus-validate
make alpha-visual-corpus-prepare
make alpha-visual-regression
```

Record each clip as PASS/FAIL/SKIP. First run at least one close/medium and one true-wide
clip through `analysis_realtime`; run `xiaomi_source_hd` preparation for at least one
clip. Do not claim CS2/MISS validation.

- [ ] **Step 4: Generate observational candidate, compare and explicitly promote v1**

Run the comparison before promotion. Review the candidate's aggregate result and exact
identity, then run promotion with its printed SHA-256. Commit only the bounded baseline
JSON, never the ignored result/media cache.

- [ ] **Step 5: Run GREEN and commit**

Run:

```bash
python -m pytest -q tests/tools/test_visual_corpus.py tests/deploy/test_alpha_commands.py
make -n alpha-visual-corpus-validate alpha-visual-corpus-prepare alpha-visual-regression alpha-visual-regression-compare alpha-visual-regression-promote alpha-visual-regression-long
git diff --check
```

Commit: `feat: expose visual regression workflow`

### Task 10: Optional isolated HEVC/go2rtc gate, full regression and handoff

**Files:**
- Create: `tools/visual_corpus_codec_gate.py`
- Create: `tests/tools/test_visual_corpus_codec_gate.py`
- Modify: `Makefile`
- Modify: `tests/deploy/test_alpha_commands.py`
- Modify: `tests/fixtures/visual_corpus/README.md`
- Modify: `README.md`
- Modify: `SUMMARY.md`
- Modify: `docs/STATUS.md`
- Modify: `docs/CHECKPOINT.md`
- Modify: `docs/NEXT.md`
- Modify: this plan to mark completed tasks and record exact evidence.

**Interfaces:**
- Produces: `make alpha-visual-corpus-codec-gate` and the final operator/recovery workflow.
- Consumes: prepared `xiaomi_source_hd` HEVC clip; never consumes camera credentials or production go2rtc config.

- [ ] **Step 1: Write isolated codec-gate RED tests**

Assert generated config binds loopback ephemeral ports, contains only a local prepared
file source, starts the pinned local go2rtc binary with a bounded timeout, verifies frame
decode, and tears down only its owned process/temp directory. Reject a running process
identity mismatch and any camera/Xiaomi expression.

- [ ] **Step 2: Run RED and implement the optional gate**

Run: `python -m pytest -q tests/tools/test_visual_corpus_codec_gate.py`

When the local binary, HEVC encoder or loopback bind is unavailable, emit a precise
`SKIP`; never restart installed go2rtc. A PASS proves local HEVC ingest/decode only.

- [ ] **Step 3: Run the complete first-stage corpus regression**

Run all available 10-to-20 clips through `analysis_realtime`, compare with baseline and
record:

```text
clip counts and scenario coverage
frames total/processed/skipped
scene/pose/face/bed/adult/head-face aggregates
candidate and Guardian event deltas
decode/worker/model outcomes
inference p50/p95/max
pipeline p50/p95/max
dropped/backlog counts
```

If the real-wide source gate is incomplete, report the corpus gate as FAIL/SKIP rather
than relabeling synthetic clips.

- [ ] **Step 4: Run bounded 30-minute replay only after short corpus is green**

Repeat the prepared corpus until 30 minutes while sampling process RSS, queue/backlog,
decoder failures, duplicate events and event storms. Do not run one hour, 8 hours or 24
hours in this milestone. Store only bounded aggregates in ignored results.

- [ ] **Step 5: Run final software and privacy gates**

Run:

```bash
python -m pytest -q tests/contracts/test_visual_corpus.py tests/vision/test_corpus_storage.py tests/vision/test_corpus_download.py tests/vision/test_corpus_prepare.py tests/vision/test_first_stage_visual_corpus.py tests/stream/test_file_frame_source.py tests/vision/test_corpus_replay.py tests/vision/test_corpus_guardian_projection.py tests/vision/test_corpus_baseline.py tests/tools/test_visual_corpus.py tests/tools/test_visual_corpus_codec_gate.py
python -m pytest -q
node --test tests/frontend/*.test.mjs
python -m compileall -q packages services tools
make -n alpha-visual-corpus-validate alpha-visual-corpus-prepare alpha-visual-regression alpha-visual-regression-compare alpha-visual-regression-promote alpha-visual-regression-long alpha-visual-corpus-codec-gate
git diff --check
```

Also scan tracked changes for private IPs, credentials, keys/tokens, runtime paths,
SQLite/media/model artifacts and generated settings. Confirm `git status` contains only
planned tracked files and deliberately preserved ignored runtime data.

- [ ] **Step 6: Update factual documentation and commit**

Document separately what was software-tested, replayed with public media, codec-gated,
skipped for license/source reasons and still requires MJSXJ17CM/native-IR/household
acceptance. Record exact branch, local HEAD, remote state, test counts, corpus clip count,
scenario coverage and observed performance without claiming algorithm accuracy.

Commit: `docs: record visual regression corpus gate`

- [ ] **Step 7: Final branch delivery**

Review `git status`, `git diff --stat`, the full branch diff from the design checkpoint
and recent commits. Do not merge. Push only `codex/visual-regression-corpus` if the
current task authorization explicitly permits feature-branch push; otherwise report the
exact local HEAD and leave remote unchanged.
