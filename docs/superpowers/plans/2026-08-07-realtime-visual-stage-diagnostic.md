# Realtime Visual Stage Diagnostic Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a safe one-command i9 profiling entrypoint that identifies the dominant realtime visual processing stage without persisting household imagery.

**Architecture:** A testable Python CLI owns timing and redacted reporting. An ASCII Bash 3.2 wrapper owns launchd pause/restore, and the Makefile exposes the wrapper as `alpha-visual-diagnostic`.

**Tech Stack:** Python 3.11, OpenCV, NumPy, OpenVINO 2025.4.1, pytest, macOS launchctl, Bash 3.2, Make.

## Global Constraints

- Do not alter model settings, load thresholds, risk behavior, or `main`.
- Never persist or print frames, tensors, detections, paths, private addresses, or exceptions.
- Shell must be ASCII-only, LF, Bash 3.2-compatible, and pass `bash -n`.
- Use focused tests for this small feature slice.

---

### Task 1: Redacted timing core and CLI

**Files:**
- Create: `tools/realtime_visual_diagnostic.py`
- Create: `tests/tools/test_realtime_visual_diagnostic.py`

**Interfaces:**
- Produces: `nearest_rank_percentile(values: Sequence[float], percentile: float) -> float`
- Produces: `format_stage(name: str, values: Sequence[float]) -> str`
- Produces: `main(argv: list[str] | None = None) -> int`

- [ ] Write tests with literal timing samples proving median, nearest-rank P95, maximum, fixed stage ordering, and a redacted stable failure code.
- [ ] Run `./.venv/bin/pytest tests/tools/test_realtime_visual_diagnostic.py -q` and confirm failure because the module is absent.
- [ ] Implement the minimal timing helpers and one-frame diagnostic pipeline described by the spec.
- [ ] Rerun the focused test and confirm PASS.

### Task 2: macOS lifecycle wrapper and Make target

**Files:**
- Create: `tools/run_realtime_visual_diagnostic.sh`
- Create: `tests/deploy/test_realtime_visual_diagnostic_deploy.py`
- Modify: `Makefile`

**Interfaces:**
- Consumes: `tools/realtime_visual_diagnostic.py --settings runtime/settings.yaml`
- Produces: `make alpha-visual-diagnostic`

- [ ] Write subprocess tests with fake `launchctl`, fake Python, and a fake plist proving bootout before diagnostic and restoration after both exit 0 and nonzero.
- [ ] Run the deploy test and confirm failure because the wrapper and Make target are absent.
- [ ] Implement an EXIT-trapped ASCII Bash 3.2 wrapper and add the PHONY/help/target entries.
- [ ] Rerun the deploy test and confirm PASS.

### Task 3: Focused verification and delivery

**Files:**
- Modify only the task files above if verification exposes a defect.

- [ ] Run focused pytest for both new test files and related visual deployment tests.
- [ ] Run `bash -n tools/run_realtime_visual_diagnostic.sh`.
- [ ] Run Python compilation, ASCII/LF checks, and `make -n alpha-visual-diagnostic`.
- [ ] Review `git diff --check`, file scope, privacy terms, and repository status.
- [ ] Commit the focused implementation and push only `codex/xiaomi-alpha-visual-risk-core`; do not merge or modify `main`.
