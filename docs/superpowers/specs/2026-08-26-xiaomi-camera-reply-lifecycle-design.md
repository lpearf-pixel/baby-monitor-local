# Xiaomi Camera Reply Lifecycle Repair Design

**Date:** 2026-08-26

**Status:** Approved 2026-08-26; software Tasks 1–6 completed at
`e66302ef1ab448705dc05d03086d52bf69f0e124`. D0/D1 later passed, but D2 stopped
closed on cumulative interaction 4. The transport-auto and shared-producer diagnostic
amendment below was approved on 2026-08-27. Task 8 software is complete at
`f153cbdf9c46577831f8fe5fe3b31160118676ec`; Tasks 9–14 are complete through the
reviewed Task 14 business head `9bc032b0179ab672db9a0b99a174f149d5bc7a30`.
The installed preflight failed closed, the installed media diagnostic was skipped and
real playback remains unauthorized.

**Supersedes:** the backchannel lifecycle, completion semantics and fixed-UDP
acceptance assumption in `2026-08-26-xiaomi-camera-reply-design.md`. Its fixed reply
vocabulary, privacy boundary, loopback-only administration and supervised-device gates
remain in force. Browser or phone talkback remains deferred to a separate specification.

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

1. Keep upstream commit `b465651a94c1f637d566a8c660b4fad102b35153`.
   The Xiaomi source configuration must remain `transport=auto`; `cs2+udp` and
   `cs2+tcp` are observed negotiated results, never forced settings. Do not upgrade
   go2rtc or add a second camera connection in this repair.
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
10. The installed macOS gate requires the fixed signed `Go2RTC.app`, stable designated
    requirement, one launchd owner and the real logged-in user's Local Network and
    CoreAudio context. A sandbox PTY result is software evidence only.
11. Exactly one external Xiaomi producer owns authentication, key acquisition, MISS/CS2
    negotiation and camera media. Video, preview, audio analysis, Voice and reply
    playback are consumers derived from that producer; none may open another Xiaomi URI.
12. Video receive, camera-microphone receive, browser talkback and AI reply are four
    independent capability gates. Success of one never proves another.

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

## 2026-08-27 transport-auto and shared-producer diagnostic amendment

### Upstream provenance consulted

- Xiaomi integration contract:
  <https://github.com/AlexxIT/go2rtc/blob/master/internal/xiaomi/README.md>
- MISS/CS2 implementation:
  <https://github.com/AlexxIT/go2rtc/tree/master/pkg/xiaomi>
- MJSXJ17CM / `chuangmi.camera.039c01` support record:
  <https://github.com/AlexxIT/go2rtc/issues/1982>
- channel-3 payload correction and its commit:
  <https://github.com/AlexxIT/go2rtc/pull/2406> and
  `0655e8c37cedd30e47a2d8ce5c4614013ef7cbf0`

The model support record lists `cs2+tcp`, while this installation has negotiated
`cs2+udp` under `transport=auto`. Those are capability and runtime observations, not a
reason to force either transport. The project remains pinned to
`b465651a94c1f637d566a8c660b4fad102b35153` plus its reviewed local patch.

### Evidence entering the amendment

The installed i9 was inspected without changing settings or playing audio:

- the source configuration reports `transport=auto`;
- one external producer is active, with two current consumers;
- the observed producer protocol is `cs2+udp`, with H.265 video and positive source
  bytes;
- the pinned build metadata matches commit
  `b465651a94c1f637d566a8c660b4fad102b35153`, Go 1.24.13, the tracked patch digest and
  the installed darwin/amd64 binary digest;
- the installed app has the stable designated requirement
  `identifier "com.babymonitor.go2rtc"`, and one launchd-owned process owns the
  loopback API listener;
- Voice is healthy in `listen_only`, while the independent audio worker is unavailable;
- Camera Reply is disabled, its acceptance state is `NOT_PROVEN`, and no marker exists.

The project patch already changes the pinned upstream `WritePacket` second copy from
`hdr` to `payload` and ships `TestWritePacketCopiesPayload`. The build precondition,
postcondition and protocol gate all require that exact behavior. Upstream PR #2406 is
still draft/open and current upstream master still contains the duplicate-header bug;
therefore an unreviewed dependency upgrade would regress the installed fix.

D1 passed audibly without movement. D2 then completed two more interactions, but its
third tone—the fourth cumulative interaction—returned ambiguous after the shared CS2
source stopped receiving media for ten seconds and reconnected at generation zero.
The source and Voice recovered independently. This proves the failure boundary; it does
not prove whether the remaining cause is firmware speaker state, receive/write
contention, transport behavior, settlement ordering or macOS networking.

### macOS gate before protocol diagnosis

Every installed diagnostic begins with a side-effect-free macOS preflight:

1. verify `Go2RTC.app` and the exact stable designated requirement;
2. verify the installed launchd plist names that app executable and the ignored runtime
   config, and exactly one launchd PID owns the loopback listener;
3. report Local Network/firewall registration only as `available`, `blocked` or
   `unknown`; lack of permission to query it is never converted to PASS;
4. run camera-microphone and CoreAudio acceptance only from the real logged-in user
   context, never from a Codex sandbox PTY;
5. keep go2rtc administration and RTSP/WebRTC listeners loopback-only and never disable
   the firewall as a diagnostic shortcut.

Failure at this gate stops before any new loopback media diagnostic or speaker playback.
The preflight does not initiate Xiaomi authentication or open another camera connection;
the existing long-lived producer remains independently owned by go2rtc. Recovery may
restart only go2rtc or Voice according to the owning component; it never restarts the
full Alpha stack.

### protocol observation and acceptance ownership

The configuration intent is the closed value `auto`. Runtime inspection accepts only
the observed values `cs2+udp` and `cs2+tcp`. Camera Reply start records the actual
protocol and nonzero producer generation. Completion requires the same protocol and
generation to reach the closed lifecycle state. A missing value, unknown protocol,
protocol drift, generation zero, reconnect or replacement producer during playback is
ambiguous and cannot publish acceptance.

Acceptance marker schema v2 contains the existing build identity plus:

```text
schema_version = 2
transport_mode = auto
negotiated_protocol = cs2+udp | cs2+tcp
```

Publishing requires the protocol observed by the successful probe. Loading requires
the fixed `auto` intent, an allowlisted observed protocol and exact current build
metadata. Schema-v1 markers and markers for a different protocol or build fail closed.
A failed probe invalidates prior acceptance before accessing the camera.

### single external producer boundary

The runtime configuration contains one Xiaomi source expression named `source`.
`analysis`, `analysis_realtime`, `gauge`, `live`, `source_compat` and `audio_analysis`
must refer to `source`; none may contain a Xiaomi account, DID, address or independent
camera expression. Reply playback attaches one internal generated-media consumer to
the existing producer and removes only that consumer during settlement.

The diagnostic gate rejects zero or more than one external Xiaomi producer, a producer
replacement during a reply, a direct Xiaomi child alias, or a consumer teardown that
closes the shared producer. Reconnect remains owned by go2rtc and must be bounded; a
reply never creates a replacement connection, retries indefinitely or restarts go2rtc.

### redacted diagnostic contract

One fixed diagnostic command may expose only:

```text
macos_identity_state
launchd_owner_count
configured_transport
producer_count
negotiated_protocol
producer_generation
consumer_count
video_media_state
camera_audio_media_state
speaker_media_state
video_bytes_increased
audio_bytes_increased
speaker_state
speaker_start_requests
speaker_start_responses
speaker_stop_commands
speaker_write_failures
speaker_stop_failures
pending_command_responses
residual_sender_count
producer_replaced
last_failure_stage
```

Values are fixed labels, booleans and bounded integers. The command never emits account
data, session tokens, encryption keys, URI, host, address, producer/consumer IDs,
payload sizes tied to household speech, command bodies, audio, transcript, exception or
local path. It samples bounded before/after snapshots and writes no media or runtime
state.

### independent capability gates

1. **Camera video to i9:** prove one producer, H.265, expected dimensions and increasing
   receive bytes. This gate is currently PASS but must be rechecked around later work.
2. **Camera microphone to VAD/ASR:** prove Opus 48 kHz stereo at the source, bounded
   memory-only decode to the fixed Voice input format, VAD progression and an aggregate
   ASR outcome in the real user context. The independent audio worker being disabled or
   unavailable is reported separately from Voice input health.
3. **AI fixed reply to camera speaker:** prove negotiated send codec, generated input
   format, Opus frame timing, header/payload placement, sequence progression, nonempty
   encrypted payload and same-generation settlement. `sendonly OPUS`, HTTP 2xx or a
   compiled binary alone is not PASS.
4. **Browser microphone to camera speaker:** not implemented by this project and not
   authorized by this amendment. It requires a later specification for authenticated
   HTTPS, `getUserMedia`, same-origin WebRTC relay, push-to-talk ownership, cancellation
   and the same single-producer backchannel. AI reply evidence cannot satisfy it.

### root-cause decision after software diagnostics

The software phase must end with one explicit result:

- `D2_CAUSE_CONFIRMED`: one deterministic RED reproduces the read-side loss or producer
  replacement and a minimal GREEN closes it;
- `D2_BOUNDARY_HARDENED_CAUSE_UNPROVEN`: protocol-neutral acceptance and diagnostics
  are correct, but no software fixture proves the ten-second loss; Camera Reply remains
  disabled and no real replay occurs;
- `MACOS_PREFLIGHT_BLOCKED`: app identity, launchd ownership, Local Network or real-user
  audio context is not trustworthy; stop before protocol attribution.

No implementation may be justified only by correlation with the fourth interaction.
Forcing TCP, forcing UDP, adding a second connection or upgrading go2rtc requires a new
approved architecture after this decision gate.

## Verification boundary

The software gate requires RED then GREEN for all nine named lifecycle tests in the
review, 20 successful synthetic cycles, exact patch allowlisting and digest invalidation,
the existing Camera Reply/Voice suites, Python compile, shell/Make checks, full Python
and frontend gates, diff validation and privacy scanning.

Software evidence can prove command draining, state transitions, exactly-once cleanup,
error propagation and no synthetic regression. It cannot prove audible output, camera
firmware behavior, absence of physical movement or household stability.

No real playback occurs under this amendment until a later explicit approval. A future
device gate starts from a clean NOT_PROVEN state, runs one, then three, then six bounded
generated replies, and checks video plus camera-microphone health before and after each
stage. It stops immediately on movement, source timeout, Voice EOF, producer replacement,
protocol drift, residual sender or ambiguous settlement. Browser talkback has its own
future gate and is never inferred from those replies.

## Approval gate

The original approval authorized software Tasks 1–6. The 2026-08-27 approval authorized
recording this amendment and plan; later continuation instructions authorized software
Tasks 8–14. They are now complete. The installed preflight decision is
`MACOS_PREFLIGHT_BLOCKED`; no installed media diagnostic or playback followed.
Neither approval authorizes enabling Camera Reply,
changing private settings, running a camera probe, installing a candidate, forcing a
transport, adding a connection, pushing, creating a PR, merging or modifying protected
branches. Any new real-device playback requires separate explicit authorization.

## Approved V3E immediate-follow-up amendment

The 2026-08-27 V3E run proved that the fixed 0.5-second finite-file drain can outlive
the audible `我在，请说` prompt while `PlaybackDucker` still discards camera input.
This explains intermittent loss of a follow-up begun immediately after the prompt. The
approved correction keeps the speaker generation and stop settlement unchanged; it
does not resume ordinary live processing before settlement.

At the nominal rendered-media deadline, the ducker switches from discard to a fixed
five-frame tail-capture mode. The existing drain thread retains at most five exact
100 ms mono PCM frames in memory while the remaining 0.5-second FFmpeg drain and
same-generation stop complete. After closed settlement, `resume()` exposes those frames
to the normal VAD/collector before new decoder frames. The queue is never written to
disk, never logged, never included in status, and is zeroized on replacement, failure,
new playback, cancellation and close. Overflow fails closed by preserving the earliest
five frames and dropping later tail frames.

Replay provenance remains attached only in memory. If a replay-origin utterance is a
closed care command, the existing listen-only acknowledgement applies. A fixed reply
echo prefix may be stripped before the closed parser. Echo-only or other non-closed
replay-origin speech does not consume the armed turn; it remains bounded by the original
eight-second deadline. A non-replay invalid utterance keeps the existing return-to-idle
behavior. No fuzzy wake matching, AEC claim, care write, transcript persistence,
recognition-threshold change or second producer is introduced.

Software tests must prove the five-frame bound, FIFO replay, overflow policy,
zeroization/cleanup, capture-switch ordering before drain and stop, no pre-settlement
worker delivery, replay echo quarantine, combined echo-plus-command acceptance and all
existing timeout/cancellation/single-flight gates. Real playback remains separately
supervised and fails closed on movement, truncation, duplicate output or lifecycle
residuals.
