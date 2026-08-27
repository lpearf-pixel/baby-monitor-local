# Xiaomi Camera Reply Lifecycle Repair Design

**Date:** 2026-08-26

**Status:** Approved 2026-08-26; software Tasks 1–6 completed at
`e66302ef1ab448705dc05d03086d52bf69f0e124`. Installed/device D0–D4 remains a
separately authorized supervised gate.

**Supersedes:** only the backchannel lifecycle and completion semantics in
`2026-08-26-xiaomi-camera-reply-design.md`. Its fixed reply vocabulary, privacy
boundary, loopback-only transport and supervised-device gates remain in force.

## Goal

Repair the pinned Xiaomi MISS backchannel so one camera reply has a symmetric,
observable and bounded start/write/stop lifecycle. A reply must never report local
completion after an unobserved channel-3 write failure, leave an old sender active, or
allow command responses to terminate the shared incoming media worker.

This design does not re-enable Camera Reply. The accepted Intel i9 speaker remains the
only production Voice output until the software gate and a separately approved
supervised device gate both pass.

## Root-cause decision

The required pure-software investigation reached `H1_H2_CONFIRMED`; H3 is also
confirmed.

- A synthetic test against the exact pinned upstream `cs2.Conn.worker` injected 11
  speaker-start responses into the capacity-10 command channel, followed by a media
  packet. The test failed with `cs2: pop buffer is full`; `ReadPacket` observed the
  shared media channel close.
- Five lifecycle tests all failed on the pinned code: start response consumption was
  0, overlapping start was accepted, audio still wrote after stop, the first channel-3
  error was not returned by Producer stop, and 20 cycles left 20 command responses
  pending.
- Four Streams tests all failed: empty-source stop returned without backchannel
  settlement, a stop failure was lost, natural source end did not settle, and cancel
  plus natural end had no exactly-once settlement.

All fixtures were synthetic and local to a temporary clone. They used no camera,
household audio, device address, credential or installed go2rtc service.

These results explain the observed source timeout and Voice EOF. They do not prove why
the camera physically moved. No current Camera Reply path emits `cmdMotorReq`; PTZ,
tracking and camera settings remain outside this repair.

## Safety invariants

1. Keep upstream commit `b465651a94c1f637d566a8c660b4fad102b35153`
   and `cs2+udp`. Do not upgrade go2rtc, switch transport or add a second camera
   connection in this repair.
2. Exactly one goroutine consumes MISS command responses after login. No speaker or
   media method may call `ReadCommand` independently.
3. Command parsing accepts only bounded frames and fixed command codes. Malformed,
   undecryptable, unknown or out-of-order data makes Camera Reply unavailable without
   logging payloads and without intentionally stopping incoming media.
4. At most one speaker generation may be `starting`, `active` or `stopping`. A stale
   sender cannot write into a newer generation.
5. Settlement disables new writes before issuing speaker stop. It is idempotent and
   exactly once across explicit empty-source stop, cancellation, timeout, natural
   source end and source error.
6. The first start, audio-write or stop failure is sticky for that generation. Later
   success cannot replace it.
7. HTTP success means the internal source stopped, the generation has no accepted new
   writes, the speaker-stop command received its CS2 transport ACK, and the lifecycle
   is closed. It does not mean a human heard the complete reply.
8. Camera Reply failure does not restart or deliberately close the camera source,
   Voice worker, go2rtc, Dashboard, Guardian, gauge or environment workers.
9. Camera Reply remains disabled and the old acceptance marker remains invalid
   throughout software implementation.

## Chosen architecture

### 1. Single command-response dispatcher

Login keeps its existing synchronous authentication exchange. Immediately after login,
the Client starts one connection-owned dispatcher which is the sole subsequent caller
of `ReadCommand`.

The dispatcher:

- decrypts `cmdEncoded` responses and extracts a fixed inner command code;
- continuously drains the bounded CS2 command channel;
- delivers an expected `cmdSpeakerStartRes` to exactly one registered waiter;
- records known but currently unawaited responses as bounded aggregate counts;
- converts malformed, unknown, duplicate or out-of-order responses into one stable
  Camera Reply failure stage while continuing to drain safely where possible;
- exits when the connection closes and settles every pending waiter with a fixed error.

A waiter is registered before its request is written. There is at most one speaker
waiter and every wait has a fixed timeout. Response bodies, ciphertext and exceptions
are never logged or returned through public status.

### 2. Generation-owned speaker session

Replace the stateless start-plus-sleep sequence with one Client-owned speaker session:

```text
closed -> starting -> active -> stopping -> closed
                    \-> failed -> stopping -> closed
```

`StartSpeaker` rejects every state other than `closed`, increments a bounded generation
counter, registers the start-response waiter, sends exactly one start request and waits
for exactly one accepted response. The arbitrary one-second readiness sleep is removed.

The returned session token owns all writes. Each write verifies both generation and
`active` state before channel 3 is touched. A stale generation, overlap, stop-in-progress
or prior failure rejects the write. The first channel-3 error atomically moves the
session to `failed` and remains the generation result.

`StopSpeaker` is generation-bound and idempotent. It first prevents new writes and
settles any in-flight writer, then sends the existing `cmdSpeakerStop`. Because the
pinned protocol exposes no separate stop-response code, the bounded CS2 transport ACK
is the approved stop proof. A duplicate stop returns the original settled result and
does not send another command.

### 3. Producer settlement boundary

The Xiaomi Producer owns the session and sender created by `AddTrack`. It exposes a
narrow backchannel-settlement interface to Streams. Settlement:

1. marks the generation stopping so stale handlers cannot write;
2. detaches/closes only the generation-owned sender;
3. surfaces the sticky first write error;
4. calls the idempotent protocol stop;
5. reports a fixed aggregate result without calling `Producer.Stop`, `StopMedia` or
   closing the shared incoming connection.

This interface is optional for other go2rtc consumers. Non-Xiaomi consumers retain
their current behavior.

### 4. Streams exactly-once playback lifecycle

Each `Play(source)` operation creates a bounded playback-generation record linking its
internal source and matched backchannel consumer. One `sync.Once`-equivalent settlement
path owns cleanup for every terminal cause.

- `Play("")` requests settlement and waits for its bounded result before returning.
- Natural source completion calls the same settlement path.
- Cancellation, start failure and source error call that same path.
- A race between explicit stop and natural completion performs one protocol stop and
  both callers observe the same result.
- The generation result remains available until the owning empty-source stop consumes
  it, so a natural-end failure cannot be lost before the Python adapter stops.

The existing Streams API already maps a non-nil `Play` error to HTTP 500. The Python
adapter therefore treats any settlement failure as `CAMERA_REPLY_AMBIGUOUS` or
`CAMERA_REPLY_UNAVAILABLE`; it never emits `CAMERA_REPLY_COMPLETE` for that generation.

### 5. Aggregate diagnostics

Only fixed labels, booleans, bounded integers and latency may be exposed:

```text
speaker_state
speaker_session_generation
speaker_start_requests
speaker_start_responses
speaker_stop_commands
speaker_write_failures
speaker_stop_failures
pending_command_responses
residual_sender_count
last_failure_stage
producer_generation
```

`last_failure_stage` uses only the closed list from the lifecycle review. No payload,
response body, audio byte, URL, address, credential, transcript, exception or local
path is emitted.

## Failure semantics

- Start response timeout/duplicate/mismatch: fail before active; run bounded cleanup;
  Camera Reply unavailable.
- Overlapping start: reject immediately as busy; no second command.
- Audio write failure: retain first error, reject later writes, settle once; never
  report complete.
- Stop ACK failure or bounded settlement timeout: return ambiguous, preserve failed
  aggregate state and disable further Camera Reply generations.
- Command dispatcher loss: settle any waiter, disable Camera Reply and leave source
  recovery to its existing independent supervision.
- Incoming source failure: Voice reports its existing audio-unavailable state; this
  repair does not restart the Alpha stack.

## Verification boundary

The software gate requires RED then GREEN for all nine named lifecycle tests in the
review, 20 successful synthetic cycles, exact patch allowlisting and digest invalidation,
the existing Camera Reply/Voice suites, Python compile, shell/Make checks, full Python
and frontend gates, diff validation and privacy scanning.

Software evidence can prove command draining, state transitions, exactly-once cleanup,
error propagation and no synthetic regression. It cannot prove audible output, camera
firmware behavior, absence of physical movement or household stability.

No real playback occurs under this specification until a later explicit approval.
That device gate must restart at D0/D1 and stop immediately on movement, source timeout,
Voice EOF, residual sender or ambiguous settlement.

## Approval gate

Approval of this document authorizes only the implementation plan's software Tasks
1–6 on the current feature branch. It does not authorize enabling Camera Reply,
changing private settings, running a camera probe, installing a candidate, pushing,
creating a PR, merging, modifying protected branches or executing D0–D4.
