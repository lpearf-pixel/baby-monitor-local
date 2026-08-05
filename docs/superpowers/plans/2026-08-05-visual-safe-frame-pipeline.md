# Visual Safe Frame Pipeline Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ensure only a bounded, bed-zone-cropped, privacy-masked 960×540 JPEG can enter the future M2 reviewer or event evidence pipeline, and retain those prepared frames only in a 40-second in-memory ring.

**Architecture:** Extend the strict vision contracts with normalized polygons, then put all pixel handling in `services/vision/frame_policy.py`. The policy consumes the existing controlled `CapturedFrame`, expands the bed-zone bounding box by 15%, applies source-coordinate privacy masks before resize and JPEG encode, and returns an immutable `PreparedAnalysisFrame`; `services/vision/frame_ring.py` owns time/capacity eviction and deterministic four-frame selection without filesystem I/O.

**Tech Stack:** Python 3.11, Pydantic 2, Pillow 11+, pytest.

## Global Constraints

- `bed_zone` has no default; missing or invalid geometry fails closed with `VISUAL_BED_ZONE_REQUIRED` or `VISUAL_ZONE_INVALID`.
- All normalized coordinates are within `0.0..1.0`; polygons require at least three distinct points and non-zero area.
- The crop is the bed-zone bounding rectangle expanded by 15% on every side and clamped to source bounds.
- Every privacy polygon is painted solid black in source/crop coordinates before resize or JPEG encoding.
- Output is exactly 960×540 JPEG at quality 80 and no more than 1 MiB.
- Input URLs, stream names, FFmpeg arguments, file paths, identities, or room names never enter these interfaces.
- The ring retains at most 40 seconds and 21 prepared frames, accepts only monotonic aware timestamps, and performs no disk I/O.
- Tests use generated colored images only; no household media enters Git.

---

### Task 1: Normalized geometry contracts and fail-closed policy construction

**Files:**
- Modify: `packages/contracts/vision.py`
- Modify: `packages/contracts/__init__.py`
- Create: `services/vision/frame_policy.py`
- Create: `tests/vision/test_frame_policy.py`

**Interfaces:**
- Produces: `NormalizedPoint(x: float, y: float)`, `NormalizedPolygon(points: tuple[NormalizedPoint, ...])`, `FramePolicyError`, and `VisionFramePolicy(bed_zone, privacy_masks=())`.

- [ ] **Step 1: Write failing geometry tests**

Test a valid rectangle, missing bed zone, out-of-range coordinates, fewer than three distinct points, and collinear zero-area points. The production mutation each test catches is accepting an unsafe full-frame or ambiguous crop.

- [ ] **Step 2: Verify RED**

Run: `.venv-alpha/bin/pytest tests/vision/test_frame_policy.py -q`  
Expected: collection fails because geometry and policy modules do not exist.

- [ ] **Step 3: Implement strict geometry and policy validation**

Use frozen Pydantic contracts and the shoelace formula. `VisionFramePolicy(None)` raises `FramePolicyError("VISUAL_BED_ZONE_REQUIRED")`; invalid polygons raise `FramePolicyError("VISUAL_ZONE_INVALID")`. Privacy masks may be empty but every supplied mask must pass the same validation.

- [ ] **Step 4: Verify GREEN and commit**

Run: `.venv-alpha/bin/pytest tests/vision/test_frame_policy.py tests/contracts/test_vision_review.py -q`  
Expected: all tests pass.

```bash
git add packages/contracts/vision.py packages/contracts/__init__.py services/vision/frame_policy.py tests/vision/test_frame_policy.py
git commit -m "feat: validate visual analysis zones"
```

### Task 2: Crop, privacy mask, resize, and bounded JPEG output

**Files:**
- Modify: `services/vision/frame_policy.py`
- Modify: `tests/vision/test_frame_policy.py`

**Interfaces:**
- Consumes: `services.stream.frame_source.CapturedFrame`.
- Produces: `PreparedAnalysisFrame(jpeg, captured_at, width=960, height=540, crop_box)` through `VisionFramePolicy.prepare(frame)`.

- [ ] **Step 1: Write failing pixel-behavior tests**

Generate a 200×100 RGB image with four colored quadrants. Use bed zone `(0.25,0.20)..(0.75,0.80)` and assert the crop box is `(35, 11, 165, 89)` after expanding each side by 15% of the bed bounding box's own width or height. Add a privacy mask whose center would otherwise be red and assert its prepared-frame center is near black while an unmasked control point retains its expected dominant channel. Add malformed JPEG, declared-dimension mismatch, naive timestamp, and output shape/size tests.

- [ ] **Step 2: Verify RED**

Run: `.venv-alpha/bin/pytest tests/vision/test_frame_policy.py -q`  
Expected: new tests fail because `prepare()` is absent.

- [ ] **Step 3: Implement the safe pixel pipeline**

Decode with Pillow, verify JPEG and declared dimensions, calculate integer clamped crop bounds, crop, transform privacy polygon coordinates into crop-local pixels, paint masks black with `ImageDraw.polygon`, resize to `(960, 540)`, and encode JPEG quality `80` with metadata omitted. Raise only stable `VISUAL_FRAME_INVALID` or `VISUAL_FRAME_TOO_LARGE` errors.

- [ ] **Step 4: Verify GREEN and commit**

Run: `.venv-alpha/bin/pytest tests/vision/test_frame_policy.py -q`  
Expected: all tests pass and output stays below 1 MiB.

```bash
git add services/vision/frame_policy.py tests/vision/test_frame_policy.py
git commit -m "feat: apply privacy-safe visual frame policy"
```

### Task 3: Forty-second in-memory frame ring

**Files:**
- Create: `services/vision/frame_ring.py`
- Create: `tests/vision/test_frame_ring.py`
- Modify: `docs/STATUS.md`
- Modify: `docs/CHECKPOINT.md`
- Modify: `docs/NEXT.md`

**Interfaces:**
- Consumes: `PreparedAnalysisFrame` from Task 2.
- Produces: `AnalysisFrameRing.add(frame)`, `len(ring)`, and `select_review_frames(count=4, spacing_seconds=2) -> tuple[PreparedAnalysisFrame, ...]`.

- [ ] **Step 1: Write failing ring tests**

Use tiny in-memory JPEG byte strings and aware timestamps to prove age eviction, 21-frame capacity, chronological selection of frames at approximately two-second spacing, insufficient-frame empty selection, and rejection of naive or decreasing timestamps.

- [ ] **Step 2: Verify RED**

Run: `.venv-alpha/bin/pytest tests/vision/test_frame_ring.py -q`  
Expected: collection fails because `frame_ring` does not exist.

- [ ] **Step 3: Implement bounded ring behavior**

Use `collections.deque(maxlen=21)`. On add, reject timestamp rollback, append, and remove frames older than `newest - 40 seconds`. For selection, work backward from the newest timestamp, choose the nearest not-yet-used frame for targets `latest-6`, `latest-4`, `latest-2`, `latest`, require each selected frame to be within one spacing interval of its target, and return chronological order; otherwise return an empty tuple.

- [ ] **Step 4: Run R2 stage verification**

```bash
.venv-alpha/bin/pytest tests/vision tests/contracts/test_vision_review.py -q
.venv-alpha/bin/pytest -q
node --test tests/frontend/*.test.mjs
.venv-alpha/bin/python -m compileall -q apps packages services tools
git diff --check
```

- [ ] **Step 5: Record honest R2 status and commit**

Record only the safe pixel boundary and in-memory ring as complete. Keep real camera capture, freeze detection, scheduler, M2/Ollama, evidence export, notifications, Dashboard feedback, and household validation pending.

```bash
git add services/vision/frame_ring.py tests/vision/test_frame_ring.py docs/STATUS.md docs/CHECKPOINT.md docs/NEXT.md
git commit -m "feat: add bounded visual frame ring"
```

## Plan self-review

- Every R2 deliverable in this slice has a mutation-catching test and stable failure code.
- Pixel masking precedes resize and encode by construction; no alternate public preparation path exists.
- Contracts and method names are consistent across tasks.
- Camera freeze detection and single-flight scheduling remain explicit next slices because neither belongs in the pixel/ring modules.
