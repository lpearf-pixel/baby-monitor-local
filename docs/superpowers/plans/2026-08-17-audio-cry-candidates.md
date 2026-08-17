# Audio And Cry Candidate Implementation Plan

> **For Codex:** Execute this plan in order using TDD, completing each focused gate and
> updating the status documents before advancing.

**Goal:** Deliver a fail-closed, text-only local cry-candidate pipeline on the Intel i9
without persisting household audio or coupling independent Baby Guardian workers.

**Architecture:** A fixed loopback source feeds bounded in-memory PCM to deterministic
feature extraction and a pinned ONNX classifier boundary. A deterministic state machine
turns accepted observations into normalized Guardian events. The existing event store
and notification outbox persist only allow-listed text and scalar metadata.

**Tech Stack:** Python 3.11, Pydantic, NumPy, ONNX Runtime, FFmpeg/ffprobe, SQLite,
pytest, launchd.

**Owning design:**
`docs/superpowers/specs/2026-08-17-audio-cry-candidates-design.md`

## Stage A1: Strict Audio Contracts And Settings

**Status:** Complete on 2026-08-17

**Prerequisites:** Approved design; no real audio track is required.

**Codex work:** Add closed observation, failure and health contracts; add centralized
fixed audio settings with bounded sample rate, window, stride, memory and thresholds.
Reject arbitrary endpoints, absolute model paths and unknown fields.

**Human work:** None.

**Acceptance:** Invalid states, unsafe paths and incoherent timing are rejected; valid
defaults are frozen and serialize without private data.

**Test:** Write failing contract/settings tests, implement the minimum code, then run
the focused contract suite, Python compilation and `git diff --check`.

**Next:** Stage A2.

## Stage A2: Bounded In-Memory PCM Source

**Status:** Complete on 2026-08-17

**Prerequisites:** A1 complete.

**Codex work:** Implement the fixed decoder boundary and a bounded mono 16 kHz PCM
ring. Handle EOF, timeout, malformed frames and decoder exits as unavailable without
writing samples to disk or exposing source details.

**Human work:** None; tests use generated PCM and fake processes.

**Acceptance:** Memory never exceeds the configured 15-second ceiling; every source
failure maps to a closed reason; no persistence API exists.

**Test:** Focused source/ring tests, compilation and diff checks.

**Next:** Stage A3.

## Stage A3: Loudness And Dynamic Noise Floor

**Status:** Complete on 2026-08-17

**Prerequisites:** A2 complete.

**Codex work:** Add deterministic RMS/loudness features, bounded noise-floor adaptation
and a loudness gate that cannot update the baseline from an accepted loud episode.

**Human work:** None.

**Acceptance:** Generated quiet, changing background, adult-voice-like tones and loud
bursts exercise stable, bounded output; quiet input never becomes a cry candidate.

**Test:** Generated-signal unit tests and focused audio suite.

**Next:** Stage A4.

## Stage A4: Pinned ONNX Classifier Boundary

**Status:** Software boundary complete on 2026-08-17; production artifact approval pending

**Prerequisites:** A3 complete; an approved redistributable model and digest are
available before production enablement.

**Codex work:** Implement strict artifact validation, fixed tensor shape, bounded
outputs and fake-runner tests. Do not download a model at runtime or substitute an
untrained artifact.

**Human work:** Approve the chosen model/license if the repository does not already
contain an approved public artifact reference.

**Acceptance:** Missing, mismatched or failing models return unavailable; only a valid
pinned artifact can enable classification.

**Test:** Contract and fake-runtime tests plus artifact validation when available.

**Next:** Stage A5.

## Stage A5: Deterministic Cry State Machine

**Status:** Complete on 2026-08-17

**Prerequisites:** A1 and observation boundary from A4.

**Codex work:** Implement short observation, five-second normal, ten-second high,
30-second merge/escalation and explicit recovery. Source/model unavailability freezes
positive inference and never fabricates recovery.

**Human work:** None.

**Acceptance:** Boundary-time, interruption, restart, duplicate and clock-order tests
pass with fixed event kinds and severities.

**Test:** Table-driven state-machine tests and focused suite.

**Next:** Stage A6.

## Stage A6: Text-Only Event And Notification Integration

**Status:** Complete on 2026-08-17

**Prerequisites:** A5 complete.

**Codex work:** Map transitions into the existing event store and outbox using fixed
summaries and allow-listed scalar metadata. Add negative tests that reject samples,
paths, arbitrary model text and media fields.

**Human work:** None.

**Acceptance:** Restart-safe event order and deduplication pass; SQLite and notification
payloads contain no audio or private source detail.

**Test:** Focused event/outbox integration tests and schema inspection fixtures.

**Next:** Stage A7.

## Stage A7: Independent Worker And Installed Software Gate

**Status:** Ready

**Prerequisites:** A2-A6 complete.

**Codex work:** Add a standalone worker, bounded status, launchd template, Make targets,
operator documentation and side-effect-free acceptance command. Do not restart the full
Alpha stack for audio failures.

**Human work:** Install/activate the launchd worker only when requested on the i9.

**Acceptance:** Unit/software gates pass, the worker degrades independently, and its
automatic gate sends no real notification or production event.

**Test:** Focused deploy tests, shell syntax/ASCII/LF checks, full Python/frontend gate,
credential/private-data scan and `git diff --check`.

**Next:** Stage A8.

## Stage A8: Real-Device Audio And Accuracy Gate

**Status:** Waiting for A7; source-track prerequisite verified on 2026-08-17

**Prerequisites:** A7 complete. The installed Xiaomi/go2rtc source now exposes Opus on
the fixed loopback source and the audio-only alias; a bounded mono 16 kHz decode passed
without persistence. Sustained stability and household accuracy remain unaccepted.

**Codex work:** Run bounded health, latency, fail-closed and aggregate accuracy checks
without saving household audio.

**Human work:** Provide supervised quiet, adult-speech and real-cry household scenarios;
confirm that no household audio was persisted and review false positives/negatives.

**Acceptance:** The audio track remains stable, fail-closed cases are observed, approved
scenario thresholds pass, and privacy inspection finds no audio artifacts.

**Test:** Redacted real-device acceptance record followed by the applicable 24-hour and
72-hour release gates. Software completion alone does not satisfy this stage.

**Next:** Resume the ordered Guardian release plan and Baby Care read-only integration
only after its own approved design.
