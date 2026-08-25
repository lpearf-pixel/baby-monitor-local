# Voice Listen-Only Design

**Date:** 2026-08-25  
**Status:** Approved for implementation planning  
**Project:** Baby Monitor Local / Voice Care  

## 1. Purpose

Add an independently supervised, continuous `listen-only` Voice mode on the Intel i9.
It listens to the existing Xiaomi `audio_analysis` stream, recognizes an exact local
`小小` wake prefix and gives one fixed response through the i9 speaker. Household input
audio and ASR text remain memory-only.

This mode exists to make the receive/VAD/ASR/wake/output loop usable before Dad/Mom
speaker enrollment and Baby Care write acceptance are complete. It is not the full Voice
Care mode and must not create, update, cancel or confirm a care record.

## 2. Current State And Gap

The repository already has the bounded `VoiceWorker`, utterance collector, exact wake
validator, Paraformer runtime, fixed TTS, launchd ownership and privacy tests. The
installed worker remains disabled, and `tools/run_voice_worker.py` has no production
factory that composes those parts. One-shot fixed-window capture also opens a fresh RTSP
decoder for each attempt; real i9 evidence showed strong PCM input but repeated Silero
zero-span results, while a direct memory-only Paraformer probe produced a near match at
683 ms and missed the leading wake decision. A persistent, prewarmed decoder removes
that one-shot startup boundary from normal listening.

## 3. Scope

Listen-only mode performs this fixed local pipeline:

```text
Xiaomi audio_analysis
-> continuously drained, bounded PCM pump
-> streaming Silero VAD
-> 500 ms pre-roll / 800 ms terminal silence / 8 s maximum utterance
-> local Paraformer ASR
-> exact normalized 小小 prefix validation
-> fixed i9 speaker acknowledgement
-> immediate zeroize/discard
```

The acknowledgement phrase is source-controlled and means only that the wake phrase was
accepted. It must not say that a feeding or other care fact was saved.

## 4. Explicit Non-Goals

- No Baby Care API call, outbox entry, signed intent or database write.
- No Dad/Mom speaker enrollment, identification or authorization decision.
- No free-form assistant conversation or model-generated response.
- No household audio, waveform, transcript, embedding or ASR alternative persisted to
  files, SQLite, status, logs or network services.
- No cloud ASR, Ollama dependency or M2 dependency.
- No camera backchannel. The i9 speaker remains the V1 output; Xiaomi camera output is a
  later Gate V3 adapter.
- No automatic enablement of full Voice Care and no weakening of the existing ASR/VAD,
  replay, overlap or identity acceptance gates.

## 5. Runtime Mode And Configuration

Add a disabled-by-default `listen_only_enabled` flag to `VoiceCareSettings`. It is
mutually exclusive with the existing full-care `enabled` flag. Full-care `enabled`
continues to mean the gated identity/write pipeline; this slice must not make that path
constructible.

The ignored runtime settings select listen-only mode. The fixed
`runtime/config/voice-care-models.json` supplies only the pinned Paraformer and Silero
artifact digests to this mode. Listen-only runtime must not read the private calibration
corpus, its Keychain key, an enrolled speaker profile, a Baby Care credential or a family
identifier.

The worker status explicitly reports `listen_only`; it must never report full Voice Care
as enabled or a care record as saved.

## 6. Continuous Audio Boundary

A single Voice-owned audio pump keeps one `FixedAudioDecoder` open. On startup it drains
and discards a bounded warm-up interval before reporting ready. This prevents stale RTSP
startup audio and clipped leading syllables from becoming the first utterance.

The pump assembles exact 100 ms mono 16 kHz signed-16-bit frames. Partial FFmpeg reads
remain inside a bounded assembler until one exact frame is available. Total buffered
household audio across the pump, pre-roll and active utterance remains below the existing
15-second memory limit. There is no spill-to-disk path.

On source failure the Voice worker alone becomes degraded, closes its decoder and uses a
bounded retry/backoff. It does not restart go2rtc, Dashboard, Guardian, visual, gauge,
environment, cry or any other worker.

## 7. VAD, ASR And Wake Semantics

Silero is stateful across consecutive 100 ms frames and resets at a completed utterance,
source discontinuity, TTS duck or worker restart. VAD opens one collector only after
speech and closes it at 800 ms terminal silence or the fixed eight-second maximum.

Paraformer runs only on the completed bounded utterance. Its text exists in one local
scope long enough to call the existing exact `validate_wake_prefix` function and is then
discarded. Normalization and the fixed care-vocabulary lexical boundary remain
unchanged; fuzzy matching, homophones, phrase repair and transcript rewriting are
prohibited.

Non-wake and malformed utterances produce no speech response and no external side
effect. An exact wake produces only the fixed `listen_only_ack` response. No downstream
care parser or identity component is constructed in this mode.

## 8. Output And Acoustic Loop Protection

The acknowledgement is played through the existing bounded macOS synthesizer at its
fixed volume. The source-controlled reply may use the existing private temporary AIFF
lifecycle; it contains no household input and is unlinked after playback. Captured
household audio and transcripts never touch that path.

Before playback the audio pump enters duck mode, drops queued and newly arriving frames,
resets VAD/collector state and continues draining the decoder. It resumes only after the
existing post-playback guard with an empty queue. The system must therefore never process
its own reply as a new wake phrase.

TTS failure reports a fixed unavailable status and resumes listening after safe cleanup;
it cannot trigger a care write or restart another service.

## 9. Status, Privacy And Failure Behavior

The only durable runtime output is the existing mode-0600 atomic status file. Status
schema v2 adds one closed `mode=disabled|listen_only|care` field to the existing
timestamp, worker state, fixed reason, processed count and bounded latency fields.
Add only fixed listen-only reasons such as `listen_only_idle`, `listen_only_ignored`,
`listen_only_acknowledged`, `voice_audio_unavailable`, `voice_model_unavailable` and
`voice_output_unavailable`.

Status and logs exclude PCM, RMS tied to an utterance, probabilities, transcripts,
embeddings, prompt text, model prose, local paths, URLs, credentials and private network
values. Exceptions are collapsed to existing stable reason codes.

Cancellation must stop and settle the decoder, VAD/ASR model process and TTS child,
zeroize all mutable PCM buffers and leave no audio consumer or response file behind.

## 10. Operator Interfaces

Keep launchd ownership independent. Add short Make targets for listen-only install/start,
status and stop. Commands must not edit `main`, expose private configuration or enable
full Voice Care. Ordinary Guardian start/stop remains independent, and a listen-only
failure must not restart the Alpha stack.

The installed status command distinguishes `disabled`, `listen_only`, full `care` and
`degraded` without printing effective configuration.

## 11. Verification And Acceptance

Software acceptance uses TDD and must prove:

- disabled is still the default and listen-only/full-care modes are mutually exclusive;
- the production builder constructs only decoder, streaming Silero, collector,
  Paraformer, exact wake and fixed TTS for listen-only;
- it cannot construct or call Baby Care client, outbox, signing or speaker identity;
- partial audio reads become exact bounded frames and startup warm-up is discarded;
- non-wake utterances are silently discarded;
- an exact `小小` utterance produces exactly one fixed acknowledgement;
- playback ducking drains and drops input, resets state and prevents self-wake;
- PCM and transcript are absent from files, status, stdout/stderr and test artifacts;
- source/model/TTS/cancellation failures settle owned resources and do not affect sibling
  services;
- focused Voice tests, complete Voice tests, Python compilation, plist lint, shell
  syntax, Make dry-runs, privacy scans and `git diff --check` pass.

Installed i9 acceptance uses no baby and no care write. It requires:

1. fixed artifact and source preflight PASS;
2. listener ready after bounded warm-up;
3. at least five supervised exact `小小` trials acknowledged once each;
4. at least five ordinary-speech/no-wake controls with zero acknowledgement;
5. one i9 reply with no self-trigger;
6. status contains only allowed aggregate fields;
7. no new household audio/transcript file and no Baby Care request/outbox entry;
8. stop leaves no Voice decoder/model/TTS child while Guardian video and environment
   remain healthy.

This acceptance proves only the local listen-only loop under the tested room conditions.
It does not prove Dad/Mom identity, care-record correctness, night/far-field accuracy,
replay/overlap rejection, camera backchannel or unattended safety.

## 12. Delivery Order

1. Commit this approved design and write an implementation plan.
2. Treat the aggregate capture-diagnostic commit `6542e0f` as completed prerequisite
   evidence; do not reimplement it in the listen-only slice.
3. Implement listen-only configuration and production composition with TDD.
4. Implement continuous pump, warm-up and TTS duck/drop behavior with TDD.
5. Add launchd/Make lifecycle and bounded status gates.
6. Run software gates and install on the i9.
7. Run the supervised 5-positive/5-negative listen-only acceptance.
8. Keep full Voice Care disabled and return to Dad/Mom Gate V2 only after the unchanged
   ASR/VAD and identity gates pass.
