# WS2021 Fixed Right-Corner ROI Tracking Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a fail-closed fixed lower-right WS2021 localization path that stabilizes a calibrated ROI before the existing reader consumes it.

**Architecture:** Add a small locator/stabilizer boundary under `services/gauge/` that consumes schema-v2 calibration and `CapturedFrame` metadata, validates bounded geometry drift, and returns the existing `GaugeLocation` contract. Wire it into the existing source only when fixed-ROI mode is selected; preserve the trained OpenVINO locator as the explicit fallback. Do not change OCR, event state, privacy persistence, or schema-v2 calibration.

**Tech Stack:** Python 3.11+, Pydantic models, NumPy/OpenCV already used by the gauge package, pytest, existing Make targets.

## Global Constraints

- Preserve fail-closed behavior: invalid, obstructed, reflective, missing, or unstable frames produce unavailable state and never fabricated readings.
- Keep live viewing independent from localization/model availability.
- Do not write household frames, crops, calibration data, or secrets to Git or logs.
- Do not change `main`, push, merge, or alter PTZ behavior.
- Keep schema-v2 calibration as the source of truth; no schema-v1 compatibility work.
- Run focused tests, `git diff --check`, and the relevant software gate after each task.

---

### Task 1: Define fixed-ROI localization contracts

**Files:**
- Create: `services/gauge/fixed_roi.py`
- Test: `tests/gauge/test_fixed_roi.py`

**Interfaces:**
- Consumes: `CapturedFrame`, `Ws2021Calibration`, `GaugeLocation`, `NormalizedRect`.
- Produces: `FixedRoiLocator.locate(frame) -> GaugeLocation` and bounded `FixedRoiError` codes.

- [ ] **Step 1: Write failing tests** for a lower-right calibration producing a normalized location, bounded drift acceptance, out-of-frame rejection, too-small rejection, and malformed calibration rejection.
- [ ] **Step 2: Run** `python -m pytest tests/gauge/test_fixed_roi.py -q` and verify the new tests fail because the module is absent.
- [ ] **Step 3: Implement** immutable settings with explicit maximum drift and minimum dimensions; derive the candidate from the calibrated `gauge_rect`; validate source dimensions and bounds; return the existing `GaugeLocation` with a fixed model version.
- [ ] **Step 4: Run** the focused test command and verify all new tests pass.
- [ ] **Step 5: Commit** `git add services/gauge/fixed_roi.py tests/gauge/test_fixed_roi.py && git commit -m "feat: add fixed ROI WS2021 locator"`.

### Task 2: Add bounded temporal stabilization

**Files:**
- Modify: `services/gauge/fixed_roi.py`
- Test: `tests/gauge/test_fixed_roi.py`

**Interfaces:**
- Consumes: `FixedRoiLocator` results and frame validity outcomes.
- Produces: `StableFixedRoiLocator.observe(frame) -> GaugeLocation | None`, resetting on any invalid frame.

- [ ] **Step 1: Write failing tests** for required consecutive-frame count, reset after one invalid frame, and no output before stability threshold.
- [ ] **Step 2: Run** `python -m pytest tests/gauge/test_fixed_roi.py -q` and verify the stabilization tests fail.
- [ ] **Step 3: Implement** a bounded counter with no unbounded frame retention; return only the latest validated normalized location after the threshold.
- [ ] **Step 4: Run** the focused test command and verify all tests pass.
- [ ] **Step 5: Commit** `git add services/gauge/fixed_roi.py tests/gauge/test_fixed_roi.py && git commit -m "feat: stabilize fixed ROI observations"`.

### Task 3: Wire fixed-ROI mode into WS2021 source

**Files:**
- Modify: `services/gauge/source.py`
- Modify: `services/environment/bootstrap.py:82-92`
- Test: `tests/gauge/test_source.py`
- Test: the relevant composition test under `tests/environment/`.

**Interfaces:**
- Consumes: `StableFixedRoiLocator` and existing `Ws2021GaugeSource` protocols.
- Produces: existing `EnvironmentReading` behavior with fixed-ROI unavailable reasons on instability.

- [ ] **Step 1: Write failing tests** proving fixed-ROI mode is selected for schema-v2 lower-right calibration, that unstable observations return unavailable, and that configured model fallback remains unchanged when fixed-ROI mode is disabled.
- [ ] **Step 2: Run** the focused source/composition tests and verify the wiring tests fail.
- [ ] **Step 3: Implement** the narrow composition seam; preserve existing reader, burst, freshness, and failure mappings; never let the OpenVINO locator override a configured fixed ROI.
- [ ] **Step 4: Run** `python -m pytest tests/gauge/test_source.py tests/environment/test_bootstrap.py -q` and verify pass.
- [ ] **Step 5: Commit** `git add services/gauge/source.py services/environment/bootstrap.py tests/gauge/test_source.py tests/environment/test_bootstrap.py && git commit -m "feat: use fixed ROI for WS2021 source"`.

### Task 4: Run regression and bounded live smoke verification

**Files:**
- Modify: `docs/STATUS.md`
- Modify: `SUMMARY.md`
- Modify: `docs/CHECKPOINT.md`

**Interfaces:**
- Consumes: completed fixed-ROI implementation and test results.
- Produces: redacted status evidence only; no media or calibration payloads.

- [ ] **Step 1: Run** `python -m pytest tests/gauge tests/environment -q` and `node --test tests/frontend/*.test.mjs`.
- [ ] **Step 2: Run** `make alpha-ws2021-model-check` and `make alpha-source-check`.
- [ ] **Step 3: Run** one bounded live smoke check that reports aggregate accepted/rejected/unstable counts only.
- [ ] **Step 4: Update** the three handoff documents to record software evidence, explicitly preserve the real-device gates, and set the next task to OCR only after stable ROI evidence.
- [ ] **Step 5: Run** `git diff --check` and sensitive-artifact scan; commit `git add docs/STATUS.md SUMMARY.md docs/CHECKPOINT.md && git commit -m "docs: record fixed ROI WS2021 status"`.

## Completion Criteria

- All fixed-ROI and source regression tests pass.
- Invalid/unstable/obstructed frames never produce a reading.
- Live viewing and independent workers remain unaffected.
- No private media or calibration payload is tracked.
- Documentation states that real-device accuracy, OCR, 30-group comparison, night/IR/occlusion/movement, 24-hour, browser, and 72-hour gates remain outstanding.
