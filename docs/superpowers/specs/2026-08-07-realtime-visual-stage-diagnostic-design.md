# Realtime Visual Stage Diagnostic Design

**Date:** 2026-08-07

**Status:** Approved from the previously presented command design

**Parent:** `2026-08-07-realtime-visual-production-metrics-design.md`

## Goal

The i9 production gate reported a stable 1 FPS with processing P95 near 534 ms. Add a local, one-shot diagnostic that attributes that aggregate duration to frame policy, JPEG decode, YuNet face detection, pose preprocessing, OpenVINO pose inference, pose decoding, semantic backend total, and production analyzer total.

The diagnostic gathers evidence only. It must not change model settings, load-control thresholds, risk behavior, or production data.

## Selected approach

Use a repository-owned ASCII shell lifecycle wrapper plus a Python diagnostic CLI. The shell wrapper pauses only `com.babymonitor.visual`, runs the CLI, and restores the worker through an EXIT trap. The Python CLI captures one validated frame from the loopback `analysis_realtime` stream, applies the configured privacy/crop policy in memory, loads the pinned model backend, warms each model stage, and prints aggregate timing only.

Alternatives rejected:

- Running beside the production worker would create CPU contention and invalidate the result.
- Pasting a temporary script into Terminal is unreliable and violates the macOS delivery rule.
- Refactoring the production backend to expose profiling hooks expands the performance-change surface before the bottleneck is known.

## Output and privacy contract

Successful output contains only these stage names with P50, nearest-rank P95, and maximum milliseconds:

- `frame_policy_excluded_from_metric`
- `jpeg_decode`
- `yunet_face`
- `pose_preprocess`
- `pose_inference`
- `pose_decode`
- `semantic_backend_total`
- `production_analyzer_total`

It ends with `diagnostic=PASS`. Failures print one stable code such as `diagnostic=FAIL reason=model_backend_unavailable` and return nonzero. The tool never saves or prints a frame, path, tensor, detection, camera identifier, exception, environment value, or private address.

## Lifecycle and compatibility

- `make alpha-visual-diagnostic` is supported only on macOS with an installed launchd plist.
- The wrapper verifies the worker is loaded before stopping it.
- The EXIT trap restores the worker after Python success, Python failure, or interruption.
- The wrapper is ASCII-only and compatible with macOS Bash 3.2 and BSD tools.
- The CLI uses the configured loopback go2rtc host/port and pinned local model directory.
- One frame remains in memory only for the duration of the process.

## Verification

Automated tests prove deterministic percentile calculation and redacted stage output, stable failure behavior, Make target invocation, and wrapper restoration on both success and failure. Static checks include `bash -n`, ASCII/LF validation, Python compilation, focused pytest, and a dry-run of the Make target.
