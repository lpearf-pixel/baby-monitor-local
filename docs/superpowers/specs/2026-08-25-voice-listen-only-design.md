# Voice Listen-Only Design

**Date:** 2026-08-25  
**Status:** Approved for implementation planning  
**Project:** Baby Monitor Local / Voice Care  

## 1. Purpose

Add an independently supervised, continuous `listen-only` Voice mode on the Intel i9.
It listens to the existing Xiaomi `audio_analysis` stream and provides a Siri-like,
two-stage interaction using the exact local keyword `小小`: a standalone wake gets one
fixed acknowledgement and briefly arms the next utterance, while `小小` plus a command
in one utterance continues directly. Household input audio and ASR text remain
memory-only.

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
-> exact normalized 小小 wake classification
-> fixed i9 speaker acknowledgement / bounded armed window
-> immediate zeroize/discard
```

The standalone-wake acknowledgement is the source-controlled phrase `我在，请说。`.
The listen-only command acknowledgement is `我听到了。`. They mean only that `小小` or
one syntactically closed command was accepted. Neither may say that a feeding or other
care fact was saved.

## 4. Explicit Non-Goals

- No Baby Care API call, outbox entry, signed intent or database write.
- No Dad/Mom speaker enrollment, identification or authorization decision.
- No free-form assistant conversation or model-generated response.
- No indefinite open dialogue, repeated reprompt or always-armed microphone state.
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

Paraformer runs only on a completed bounded utterance. Its text exists in one local scope
long enough to classify the wake and is then discarded. Add a closed wake classifier
that distinguishes:

- `standalone_wake`: the normalized utterance is exactly `小小`;
- `wake_with_command`: the existing exact prefix and fixed lexical boundary accept
  `小小` followed by a non-empty command;
- `not_wake`: every other result.

The existing full-care `validate_wake_prefix` behavior remains unchanged: standalone
`小小` is still not a complete care command. Fuzzy matching, homophones, phrase repair,
repeated wake words and transcript rewriting remain prohibited.

Non-wake and malformed utterances produce no speech response and no external side
effect. A pure listen-only classifier may strip the existing explicit Dad/Mom claim
syntax and call the existing deterministic care parser only to decide whether the
remaining command is syntactically closed. It discards the result and never treats the
claim as verified identity. `wake_with_command` produces `我听到了。` only when this
closed classifier accepts it. `standalone_wake` enters the two-stage state machine
below. No speaker verifier, signed intent, outbox or Baby Care client is constructed in
listen-only mode.

## 8. Two-Stage Wake State Machine

The state machine is memory-only and starts in `idle` after every process start:

```text
idle
  + standalone_wake -> acknowledging -> armed
  + wake_with_closed_command -> acknowledge_once -> idle
  + wake_with_unknown_command -> idle silently
  + not_wake -> idle

armed
  + one completed utterance -> acknowledge_if_closed_command -> idle
  + no utterance before deadline -> idle silently
  + source/model/TTS/cancellation failure -> idle or bounded degraded retry
```

For `standalone_wake`, play `我在，请说。`, complete the playback guard, clear all audio
and VAD state, and only then start an eight-second monotonic armed deadline. During that
window the next completed utterance does not need to repeat `小小`. In listen-only mode
it is accepted only when the existing closed care parser recognizes a complete command;
the system then says `我听到了。` and returns to `idle` without writing the care fact.
The armed deadline bounds the wait for speech to begin. Once speech begins before the
deadline, the normal eight-second maximum-utterance bound applies; the worker does not
truncate a command merely because its final syllable occurs after the armed deadline.

If no next utterance arrives, or the next utterance is incomplete, unknown or malformed,
the worker returns to `idle` without another prompt. Any later interaction must say
`小小` again. The worker never extends the deadline, chains open-ended follow-ups or
persists dialogue state across restart.

## 9. Output And Acoustic Loop Protection

The acknowledgement is played through the existing bounded macOS synthesizer at its
fixed volume. The source-controlled reply may use the existing private temporary AIFF
lifecycle; it contains no household input and is unlinked after playback. Captured
household audio and transcripts never touch that path.

Before playback the audio pump enters duck mode, drops queued and newly arriving frames,
resets VAD/collector state and continues draining the decoder. It resumes only after the
existing post-playback guard with an empty queue. The armed deadline starts after this
resume boundary. The system must therefore never process its own reply as a new wake
phrase or clip the next command with stale playback audio.

TTS failure reports a fixed unavailable status and resumes listening after safe cleanup;
it cannot trigger a care write or restart another service.

## 10. Bounded Progress And No-Hang Contract

No state transition may wait forever or hold a shared lock across decoder, model or TTS
I/O. Use monotonic deadlines and settled cleanup for every owned operation:

- audio frame assembly has a fixed read deadline and bounded retry/backoff;
- Paraformer retains the existing bounded inference deadline and is terminated/settled
  before a replacement process starts;
- TTS retains its fixed generation/playback deadlines and always resumes ducking in a
  `finally` path;
- `acknowledging` and `armed` have fixed deadlines and return to `idle` on expiry;
- bounded frame queues drop stale data rather than blocking a producer or consumer;
- cancellation closes and settles each owned child before launchd considers the worker
  stopped.

After a recoverable source or model failure, only the Voice component retries. Status may
remain degraded during backoff, but the state machine must continue making progress and
must never require deletion of runtime request state to resume ordinary listening.

## 11. Status, Privacy And Failure Behavior

The only durable runtime output is the existing mode-0600 atomic status file. Status
schema v2 adds one closed `mode=disabled|listen_only|care` field to the existing
timestamp, worker state, fixed reason, processed count and bounded latency fields.
Add only fixed listen-only reasons such as `listen_only_idle`, `listen_only_ignored`,
`listen_only_acknowledging`, `listen_only_armed`, `listen_only_acknowledged`,
`listen_only_timeout`, `voice_audio_unavailable`, `voice_model_unavailable` and
`voice_output_unavailable`.

Status and logs exclude PCM, RMS tied to an utterance, probabilities, transcripts,
embeddings, prompt text, model prose, local paths, URLs, credentials and private network
values. Exceptions are collapsed to existing stable reason codes.

Cancellation must stop and settle the decoder, VAD/ASR model process and TTS child,
zeroize all mutable PCM buffers and leave no audio consumer or response file behind.

## 12. Operator Interfaces

Keep launchd ownership independent. Add short Make targets for listen-only install/start,
status and stop. Commands must not edit `main`, expose private configuration or enable
full Voice Care. Ordinary Guardian start/stop remains independent, and a listen-only
failure must not restart the Alpha stack.

The installed status command distinguishes `disabled`, `listen_only`, full `care` and
`degraded` without printing effective configuration.

## 13. Verification And Acceptance

Software acceptance uses TDD and must prove:

- disabled is still the default and listen-only/full-care modes are mutually exclusive;
- the production builder constructs only decoder, streaming Silero, collector,
  Paraformer, exact wake and fixed TTS for listen-only;
- it cannot construct or call Baby Care client, outbox, signing or speaker identity;
- partial audio reads become exact bounded frames and startup warm-up is discarded;
- non-wake utterances are silently discarded;
- standalone exact `小小` produces exactly one `我在，请说。`, begins its armed deadline
  only after playback/guard and accepts at most one next utterance;
- `小小` plus a closed command produces one `我听到了。` without entering an indefinite
  dialogue;
- armed timeout, incomplete command and unknown speech return silently to idle, and a
  later command requires `小小` again;
- playback ducking drains and drops input, resets state and prevents self-wake;
- decoder, model, TTS and armed-state deadlines all settle without deadlock, stale state
  or manual runtime-file deletion;
- PCM and transcript are absent from files, status, stdout/stderr and test artifacts;
- source/model/TTS/cancellation failures settle owned resources and do not affect sibling
  services;
- focused Voice tests, complete Voice tests, Python compilation, plist lint, shell
  syntax, Make dry-runs, privacy scans and `git diff --check` pass.

Installed i9 acceptance uses no baby and no care write. It requires:

1. fixed artifact and source preflight PASS;
2. listener ready after bounded warm-up;
3. at least five standalone exact `小小` trials each produce one `我在，请说。`;
4. at least three standalone wakes followed by a closed command acknowledge once and
   return to idle;
5. at least three standalone wakes with no next command time out silently, after which a
   command without a new `小小` receives no response;
6. at least five ordinary-speech/no-wake controls receive no acknowledgement;
7. one i9 reply produces no self-trigger;
8. source/model/TTS fault injection and stop/start recover without stuck `armed` state;
9. status contains only allowed aggregate fields;
10. no new household audio/transcript file and no Baby Care request/outbox entry;
11. stop leaves no Voice decoder/model/TTS child while Guardian video and environment
   remain healthy.

This acceptance proves only the local listen-only loop under the tested room conditions.
It does not prove Dad/Mom identity, care-record correctness, night/far-field accuracy,
replay/overlap rejection, camera backchannel or unattended safety.

## 14. Delivery Order

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
