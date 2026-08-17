# Local Audio And Cry Candidate Design

**Status:** Approved on 2026-08-17

## Purpose

Add an independent Intel i9 audio worker that can raise bounded, non-medical cry
candidates without making live viewing, camera recording, environment monitoring or
visual Guardian availability depend on audio or a model.

This approval resequences software work only. Real-device acceptance still requires a
verified audio track from the fixed loopback go2rtc source. Until that evidence exists,
the production state is `audio_source_unavailable` and no cry candidate may be emitted.

## Privacy Boundary

Household audio is never persisted. Decoded PCM exists only in a bounded in-memory
buffer and is discarded after analysis. The worker must not write audio files, database
BLOBs, event evidence, debug payloads, model requests, notification attachments or
replay data. Logs and health responses contain stable status codes and aggregate
metrics only.

Persisted output is limited to normalized text events and bounded numeric aggregates,
such as duration, confidence band and rule version. Tests use generated or explicitly
licensed public audio; no household recording enters Git.

## Architecture

The worker reads one fixed, loopback-only go2rtc audio source through a bounded decoder
process. It converts audio to mono 16 kHz signed 16-bit PCM and retains at most 15
seconds in memory. Source names, decoder arguments and endpoints are fixed by reviewed
configuration; no API accepts an arbitrary media URL or command.

The pipeline has four isolated stages:

1. Source health validates that a supported audio track is present and fresh.
2. Feature extraction maintains a bounded dynamic noise floor and calculates loudness.
3. A pinned local ONNX classifier produces a bounded cry observation only after the
   loudness gate. It runs on the i9 and has no Ollama, M2, cloud or runtime-download
   dependency.
4. A deterministic state machine owns alert timing, recovery, deduplication and event
   severity. Model prose never enters this path.

Decoder, classifier or storage failure fails closed. The worker records a degraded
status and emits no positive cry candidate from missing, stale, malformed or
low-confidence input.

## Contracts And Timing

Audio observations use a closed state set: `quiet`, `sound`, `cry_candidate` and
`unavailable`. Unavailable observations use a closed reason set including
`audio_source_unavailable`, `audio_track_unsupported`, `audio_stale`,
`decoder_failed`, `model_missing`, `model_invalid`, `model_failed` and
`internal_error`.

The deterministic rule version implements:

- a short candidate as text-only observation without notification;
- five continuous seconds of accepted cry observations as a normal event;
- ten continuous seconds as a high event;
- a repeated accepted episode within 30 seconds as a merged escalation rather than a
  notification burst;
- explicit recovery after a sustained non-cry interval, without fabricating recovery
  when the source becomes unavailable.

Exact window stride, confidence threshold and recovery interval are strict centralized
settings covered by contract tests. They may not be relaxed merely to pass household
acceptance.

## Event And Integration Boundary

Accepted state transitions are stored through the existing Guardian `CandidateEvent`
store with a closed audio kind, fixed summary text, confidence, rule version and
allow-listed scalar metadata. Raw features, sample arrays, paths, addresses, model
output and arbitrary strings are forbidden.

Notifications are text-only and use the existing outbox ordering and retry behavior.
A future Baby Care integration may read normalized Guardian events through a read-only
contract. Guardian never writes the Baby Care database directly.

## Operations And Failure Isolation

The audio worker has its own launchd definition, status file and restart policy. Its
failure must not restart go2rtc, Dashboard, visual Guardian, gauge, environment
watchdog or the Ollama tunnel. Health output is bounded to state, reason, observation
age and aggregate counters.

Software tests prove contract validation, memory bounds, fail-closed behavior, timing,
deduplication and text-only persistence. They do not prove Xiaomi audio availability,
household cry accuracy, safe unattended care, notification delivery or sustained i9
performance. Those remain separate real-device gates.

## Out Of Scope

Audio recording or playback, audio evidence, two-way talk, cloud inference, medical
diagnosis, arbitrary source selection, Baby Care database writes and household-audio
training are excluded from this phase.
