# Voice Local Diagnostic Session Design

**Status:** Written specification approved on 2026-08-28. No diagnostic capture has
started.

## 1. Purpose

The listen-only Voice path currently keeps household PCM and ASR text in memory. That
is the production invariant and remains the default. During an explicitly supervised
local troubleshooting session, however, aggregate counters cannot show exactly which
utterance reached VAD, what Paraformer returned, or why the closed classifier rejected
it.

This design adds an opt-in, bounded, local-only diagnostic session. While the session
is active, the existing single Voice worker may persist each completed utterance as a
private WAV file and a correlated private JSON event containing the ASR text and fixed
pipeline metadata. The diagnostic artifacts stay under ignored runtime storage on the
i9. Normal service logs, status endpoints, Git and chat remain transcript-free.

## 2. Goals

- Correlate the exact PCM passed to Paraformer with its returned text and the final
  listen-only outcome.
- Diagnose wake misses, near-start rejects, VAD boundaries, replay involvement and
  output failures without adding another Xiaomi producer or another ASR pipeline.
- Bound a session to 30 minutes, 50 utterances and 16 MiB of complete artifacts.
- Preserve artifacts after diagnostic stop so the operator can inspect them locally.
- Keep production and ordinary listen-only operation memory-only by default.
- Keep Camera Reply disabled and Baby Care writes absent throughout this diagnostic.

## 3. Non-goals

- This is not continuous household recording, an evidence archive or a training-data
  collector.
- It does not persist raw camera Opus packets or continuous PCM between utterances.
- It does not change wake grammar, correction mappings, action classification, VAD,
  Paraformer, TTS, Xiaomi transport or producer lifecycle.
- It does not send audio or transcripts to the M2, Ollama, a cloud service, Git, normal
  logs, status endpoints or notifications.
- It does not automatically delete retained sessions. Deletion remains a separate,
  explicit operator action.
- It does not repair the independent macOS `AudioQueueStart failed (35)` output fault.

## 4. Authority and production boundary

The feature is disabled unless an operator explicitly creates a current diagnostic
session through the fixed repository command. No tracked setting enables it. The
ignored marker is runtime authority, not a general configuration switch.

The diagnostic start command must require all of the following:

- installed checkout is the intended candidate;
- `voice_care.enabled=false`;
- `voice_care.listen_only_enabled=true`;
- `voice_care.camera_reply_enabled=false`;
- no current unexpired diagnostic marker;
- private root and every existing parent component pass owner, type, mode and symlink
  checks.

Starting and stopping a diagnostic session may restart only the Voice worker and ASR
operator. It must not restart go2rtc, Dashboard, visual, gauge, environment or Guardian
workers. A normal Voice start never creates, renews or clears a diagnostic session.

Production deployment remains memory-only because no marker exists. A stale, malformed,
wrong-owner, permissive or symlinked marker is treated as diagnostics disabled and
reported with a fixed failure code; it never falls back to an arbitrary path.

## 5. Runtime layout and permissions

All diagnostic state lives below the ignored project-relative root:

```text
runtime/private/voice-diagnostics/
  active.json
  sessions/
    <32-lowercase-hex-session-id>/
      session.json
      audio/
        000001.wav
      events/
        000001.json
```

Requirements:

- `voice-diagnostics`, `sessions`, the session directory, `audio` and `events` are real
  directories owned by the current user with mode `0700`.
- `active.json`, `session.json`, WAV files and event files are regular, single-link
  files owned by the current user with mode `0600`.
- No component may be a symlink, FIFO, socket or device.
- Session IDs are generated with a cryptographically secure random source and are never
  accepted from caller input.
- All publication uses same-directory temporary files, `fsync`, no-replace publication
  and directory `fsync`. Existing final files are never overwritten.
- The repository `.gitignore` and privacy tests must reject these runtime artifacts from
  tracked scope.

## 6. Fixed session limits

The schema owns immutable limits; callers cannot override them:

| Limit | Value |
|---|---:|
| Wall-clock lifetime | 1,800 seconds |
| Complete utterances | 50 |
| Complete artifact bytes | 16,777,216 |
| One PCM utterance | existing 8,000 ms maximum |
| Transcript length | 256 Unicode code points |
| Writer queue | 2 utterances |
| Writer settlement | 5 seconds |

The active marker contains schema version, session ID, created epoch and expiry epoch.
The session manifest repeats those values and fixed limits. Clock rollback, expiry,
count exhaustion, byte exhaustion or incoherent metadata closes diagnostic admission.
Voice continues memory-only; it must not block or fabricate a complete diagnostic event.

## 7. Capture point and data flow

The diagnostic tap is inside the existing listen-only pipeline:

```text
single Xiaomi producer
  -> existing audio_analysis decoder
  -> existing VAD and UtteranceCollector
  -> completed bounded PCM utterance
  -> existing Paraformer transcribe call
  -> existing exact/corrected classifier and outcome
  -> optional bounded diagnostic queue
```

There is no second stream consumer and no second transcription. A small ASR observer
wraps the existing transcriber and retains only the current call's bounded result in
memory. After `ListenOnlyController.handle()` returns, the single worker correlates that
result with the same utterance PCM, pre-call phase, replay provenance, elapsed time and
fixed outcome. It then offers one immutable record to the diagnostic writer.

The writer owns a queue of at most two copied utterances. `offer()` is non-blocking. A
full queue, unavailable writer or closed session drops only the diagnostic record and
increments a fixed private diagnostic counter; it does not stop listening, repeat ASR,
change classifier output or retain the PCM elsewhere. The writer settles on Voice-only
stop for at most five seconds and never delays the independent go2rtc producer.

## 8. WAV and event contract

Each accepted diagnostic record publishes one standard RIFF/WAVE file containing the
same signed 16-bit little-endian, 16 kHz mono PCM bytes passed to ASR. It publishes one
correlated JSON event with a closed schema:

```json
{
  "schema_version": 1,
  "session_id": "32-lowercase-hex",
  "sequence": 1,
  "captured_epoch": 0.0,
  "duration_ms": 0,
  "pcm_bytes": 0,
  "from_replay": false,
  "phase_before": "idle",
  "asr_state": "available",
  "asr_text": "local private transcript",
  "normalized_text": "local private normalized transcript",
  "action_code": null,
  "match_kind": null,
  "outcome_reason": "listen_only_ignored",
  "latency_ms": 0,
  "audio_file": "audio/000001.wav"
}
```

Allowed values are fixed from existing Voice enums and action codes. Text is JSON
encoded, stripped of control characters and bounded to 256 code points. The schema does
not accept arbitrary metadata, model prose, paths outside the session, credentials,
speaker identity, Baby Care fields or medication slots.

The WAV is published first and the event second. Only a pair with both valid files is a
complete record. A crash after WAV publication may leave an orphan; status reports it as
an incomplete artifact without reading or printing its contents. A later session never
reuses a sequence or overwrites an orphan.

## 9. Commands and observable status

Add fixed Make interfaces backed by one repository tool:

```text
make alpha-voice-diagnostic-start
make alpha-voice-diagnostic-status
make alpha-voice-diagnostic-stop
```

`start` creates a new session, publishes `active.json`, performs Voice-only restart and
waits for a fresh healthy listen-only status. If restart fails, the marker is invalidated
and the command fails with a fixed code; the created private session remains available
for diagnosis.

`status` prints only fixed aggregate fields: active/inactive/expired, complete count,
incomplete count, bytes used, queue drops, writer failures and expiry remaining. It does
not print a path, session ID, transcript, filename or raw exception.

`stop` proves ownership of the current marker, makes admission inactive, performs a
Voice-only restart and reports fixed settlement status. It retains the session bundle.
Removing a retained bundle requires a separate future purge command or a manually
approved deletion; purge is not part of this implementation slice.

Normal `alpha-voice-status` may add only fixed aggregate diagnostic fields. It must not
expose session IDs, paths, audio, transcript or free-form writer errors.

## 10. Diagnostic log boundary

The private per-utterance JSON events are the only logs allowed to contain ASR text.
The following remain transcript-free:

- `runtime/logs/voice.log` and all launchd stdout/stderr;
- `runtime/status/voice.json` and CLI status output;
- Dashboard and health endpoints;
- checkpoint, summary, review and resolution documents;
- test output, CI logs, notifications, Git history and chat responses.

Codex may inspect aggregate diagnostic status. It must not paste a household transcript
or local path into chat or Git. The logged-in operator may inspect private event files
locally. Tests use synthetic text and generated PCM only.

## 11. Failure behavior

- Marker or storage validation failure: diagnostics disabled, fixed counter/reason,
  Voice continues memory-only.
- Queue full: current diagnostic record dropped and counted; PCM reference released.
- WAV/event write or `fsync` failure: no complete event claimed; writer closes admission
  for the session and releases queued PCM.
- Expiry or capacity reached: no new records; existing private artifacts retained.
- ASR unavailable: event may record fixed `asr_state=unavailable` with empty text only if
  the PCM/event pair can be published safely.
- Voice cancellation: writer receives no new work, settles for at most five seconds and
  then abandons uncommitted temporary artifacts without blocking worker shutdown.
- Diagnostic failure never enables Camera Reply, writes Baby Care, changes a recognition
  decision or causes a second Xiaomi producer.

## 12. Verification

TDD must cover:

- start/stop/status lifecycle, exact limits and fixed output;
- owner/mode/symlink/FIFO/socket/no-replace and parent-containment rejection;
- valid 16 kHz mono 16-bit WAV bytes and exact synthetic transcript correlation;
- transcript control-character handling and 256-code-point bound;
- queue capacity, expiry, byte/count limits and five-second settlement;
- crash/orphan, partial write and storage failure behavior;
- diagnostics-disabled production path retains no PCM or transcript;
- normal Voice logs/status remain transcript-free;
- no second decoder, producer or ASR invocation;
- Camera Reply false and no Baby Care/signing/outbox imports or calls;
- Voice focused/full tests, full repository tests, Python compilation, Make dry-runs,
  shell validation where applicable, diff check and privacy scan.

The first supervised local gate starts one 30-minute session, speaks a small bounded set
of synthetic care phrases, proves audio/event pairs locally, stops diagnostics and then
proves a later utterance creates no new artifact. It does not require Camera Reply or a
working i9 speaker. Restoring audible acknowledgement remains the separate documented
`coreaudiod` recovery.

## 13. Delivery and rollback

Software is delivered disabled by default. Installation changes no private setting and
starts no diagnostic session. Rollback is: stop the diagnostic session, Voice-only
restart, and leave retained artifacts untouched pending explicit deletion authority.

The final report must distinguish software tests, local diagnostic evidence and adult
supervised recognition. It must state that persisted diagnostic audio/text is private
household data, is not training data and must never be committed or uploaded.
