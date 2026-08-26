# Voice Gate V3 Xiaomi Camera Reply Design

**Date:** 2026-08-26

**Status:** Approved

**Owning stage:** `docs/NEXT.md` Voice Gate V3, after P4 software completion and
before the P5 72-hour release gate

## Goal

Move the already accepted listen-only Voice replies from the Intel i9 speaker to the
confirmed Xiaomi MJSXJ17CM camera speaker without changing the wake, ASR or closed care
command semantics. The first enabled version may emit only the existing fixed replies:

- `listen_only_ready` -> `我在，请说。`
- `listen_only_received` -> `我听到了。`

This is a local response-output feature, not browser walkie-talkie, arbitrary TTS,
camera remote control or a Baby Care write path.

## Current evidence

- The installed Xiaomi source uses the existing go2rtc MISS path over `cs2+udp` and
  exposes HEVC video plus incoming Opus audio at 48 kHz stereo.
- The pinned go2rtc source commit is
  `b465651a94c1f637d566a8c660b4fad102b35153`. Its Xiaomi producer advertises an
  audio `sendonly` media when camera audio is present, calls the Xiaomi speaker-start
  command and accepts PCMA or Opus input.
- The go2rtc Xiaomi documentation describes two-way audio for the MISS integration,
  and the streams API documents sending a bounded audio source to an existing camera
  stream. The later `cs2+tcp` support does not require this known-good camera to move
  away from `cs2+udp`.
- Static inspection of the exact pinned source found a strong defect candidate in
  `pkg/xiaomi/miss/cs2/conn.go`: `WritePacket` copies the header into both the header
  and payload offsets. The expected second source is the provided encrypted payload.
  This is not considered proven until a deterministic Go regression test observes the
  serialized channel-3 packet.
- The current tracked compatibility patch changes only the UDP socket family and HEVC
  MP4 sample entry. No two-way-audio patch or regression test exists yet.
- Listen-only Voice is already accepted on the i9 with memory-only household PCM,
  fixed replies, capture ducking, a post-playback guard, silent armed timeout and no
  Baby Care client or write boundary.

Software and upstream documentation do not prove that this exact MJSXJ17CM firmware
will play a reply correctly. A supervised synthetic-tone device gate remains mandatory.

## Product boundaries

1. Only the i9 initiates camera reply playback. Browser microphones, live intercom,
   remote microphone forwarding and Mi Home automation are out of scope.
2. The camera and Mi Home continue to own camera firmware, microSD recording, manual
   two-way talk and recovery. This feature is an additional fixed local output path;
   it never disables or replaces Mi Home.
3. The implementation accepts semantic response codes, never caller-provided text,
   audio bytes, file paths, URLs, stream names, codecs, durations or go2rtc arguments.
4. Household microphone audio remains bounded in memory and is never persisted. Reply
   assets contain only repository-fixed synthetic speech and must not contain household
   recordings or private data.
5. The feature does not write the Baby Care database, create care facts, identify a
   family member, change Guardian events or expand the approved listen-only grammar.
6. Camera reply failure must not stop or restart camera ingest, go2rtc, Dashboard,
   Guardian, gauge, environment, audio or Voice input workers. It never triggers a
   full Alpha restart.
7. go2rtc administration remains loopback-only. No camera, speaker or go2rtc endpoint
   is exposed to the LAN, tailnet or public internet.
8. The software test command uses generated synthetic media only and never operates
   the real camera speaker. Real playback is a separate interactive command.

## Chosen architecture

### Existing protocol path

Keep the confirmed `cs2+udp` Xiaomi source and the pinned go2rtc build. Use go2rtc's
existing stream-to-camera routing rather than implementing a second Xiaomi client.
The project first proves the exact outbound packet bytes and, only if the regression
confirms the defect, extends the existing audited compatibility patch by one production
line plus its upstream-package Go test.

The build remains fixed to the current upstream commit. V3 does not upgrade go2rtc or
change the current receive/video behavior. The patch-scope contract must explicitly
allow only:

- `pkg/iso/codecs.go` for the existing `hev1` to `hvc1` change;
- `pkg/xiaomi/miss/cs2/conn.go` for the existing `udp4` change and the proven outbound
  payload correction;
- `pkg/xiaomi/miss/cs2/conn_test.go` for the deterministic synthetic packet test.

The build must run the focused upstream Go test before producing or installing a
candidate binary. Patch preconditions, patch digest, binary digest, stable macOS app
identity and rollback remain mandatory.

### Output adapter

Add one `CameraReplyOutput` behind the existing `speak_code(code, cancelled)` protocol.
It maps only `listen_only_ready` and `listen_only_received` to fixed generated reply
assets and sends one fixed go2rtc request to destination stream `source` through
`http://127.0.0.1:1984`.

The adapter has no generic media API. It owns:

- exact semantic-code allowlisting;
- fixed asset digest and format validation;
- one in-flight playback slot;
- a fixed maximum request and playback duration;
- a fixed cooldown;
- bounded stop and settlement;
- stable, redacted result codes and aggregate counters.

The operator-facing real-device probe uses a separate one-second generated tone. It
does not reuse Voice microphone input and cannot accept a path or URL. An empty source
may be sent only by the owned bounded stop operation for the exact `source` destination.

### Output selection and fallback

After the supervised camera-speaker gate passes, the camera becomes the primary reply
output. The i9 speaker is a pre-send fallback only:

1. If camera output is known unavailable before any send begins, play the fixed reply
   once on the existing i9 output.
2. If a camera send begins, times out or has an ambiguous result, do not play the same
   reply on the i9. This prevents duplicate or late responses.
3. A camera-output failure returns the Voice controller to its existing idle or closed
   failure path. It never retries indefinitely and never leaves Voice armed.

No automatic fallback is enabled until tests prove the output-selection state and the
real camera gate proves the primary output. Before that checkpoint, the i9 speaker
remains the production output.

### Capture ducking and echo protection

The existing Voice capture ducker remains the sole input/playback exclusion boundary.
It starts before either output backend and ends only after playback is settled plus the
existing bounded guard. During that interval the input pump is drained and discarded,
VAD and utterance state are reset, and no microphone samples are sent to ASR.

The two fixed replies do not contain the wake word `小小`. Tests must nevertheless
inject reply-shaped audio into the capture boundary and prove that playback cannot:

- open a new wake interaction;
- extend the armed deadline;
- produce a second reply;
- leave VAD, utterance collection or controller state armed after failure or timeout.

## State and diagnostics

Camera output exposes only these stable public codes:

- `CAMERA_REPLY_DISABLED`
- `CAMERA_REPLY_NOT_PROVEN`
- `CAMERA_REPLY_READY`
- `CAMERA_REPLY_BUSY`
- `CAMERA_REPLY_UNAVAILABLE`
- `CAMERA_REPLY_REJECTED`
- `CAMERA_REPLY_TIMEOUT`
- `CAMERA_REPLY_AMBIGUOUS`
- `CAMERA_REPLY_COMPLETE`

The bounded status may include backend (`camera`, `i9` or `none`), readiness, last code,
completed count, failed count and bounded latency. It must not include the camera URL,
stream URL, source configuration, local address, reply text, file path, payload,
exception, model, household transcript or raw subprocess/HTTP response.

`CAMERA_REPLY_COMPLETE` means the bounded local go2rtc operation completed. It does not
assert that a human heard the camera. Only supervised device evidence may record that.

## Failure handling

- Missing sendonly media, unsupported codec, invalid model metadata, malformed go2rtc
  status, an unhealthy source, missing or changed reply asset, unexpected listener
  scope or an unavailable API fails closed before playback.
- HTTP failure, timeout, cancellation, process exit or unknown completion after send is
  settled as unavailable, timeout or ambiguous. No second backend plays that reply.
- Stop is bounded and targets only the owned destination. Failure to confirm stop keeps
  output unavailable and does not restart go2rtc.
- A reply request arriving while one is active returns busy; it does not queue, replace
  or overlap playback.
- Repeated camera output failures may disable only the camera output adapter for a
  bounded cooldown. Voice capture remains independently supervised.
- An installed go2rtc candidate that fails source/video, audio receive or camera reply
  verification is rolled back through the existing go2rtc-only rollback path. No
  camera setting or URI is rewritten.

## Delivery gates

### V3A — Protocol and provenance gate

- Add an exact synthetic Go test proving channel 3 contains the complete header and
  supplied payload at their expected offsets.
- Observe the current pinned source fail that test before changing production code.
- If confirmed, add only the minimal payload-copy correction and update exact patch
  scope/digest contracts.
- Build the pinned darwin/amd64 binary, run the focused upstream Go test and preserve
  stable app signing and rollback.

### V3B — Supervised speaker feasibility gate

- Require current source, video and incoming audio health.
- Require one audio sendonly media compatible with the fixed generated tone.
- Send one one-second synthetic tone through the loopback stream-to-camera operation.
- A human confirms whether the tone came from the camera.
- Immediately verify camera source bytes, Dashboard stream, Voice input, Mi Home and
  microSD recording remain available.
- Record only PASS/FAIL and stable aggregate fields. Do not record audio, camera names,
  addresses or source configuration.

Failure leaves the i9 speaker unchanged and marks Camera Reply not proven.

### V3C — Fixed reply adapter software gate

- Generate or validate only the two fixed reply assets.
- Reject arbitrary codes, text, paths, URLs, stream names, formats and durations.
- Prove single-flight, timeout, cancellation, stop settlement, cooldown and redacted
  diagnostics using fake loopback transports.
- Prove software tests never contact the real go2rtc service or camera.

### V3D — Voice integration gate

- Preserve the accepted wake, follow-up, timeout and non-wake semantics.
- Prove camera-primary and pre-send-only i9 fallback selection.
- Prove no fallback after started, timed-out or ambiguous camera delivery.
- Prove capture ducking, reply echo rejection and idle recovery for every outcome.

### V3E — Supervised household acceptance

With no baby required and an adult supervising, record aggregate results for:

- at least five standalone wakes;
- at least three wake-plus-follow-up dialogues;
- at least three silent armed timeouts;
- at least five non-wake controls;
- both fixed replies audible from the camera;
- zero duplicate responses, self-triggers, stuck armed states or overlapping playback;
- unchanged camera source, Dashboard, Mi Home, microSD, Guardian, gauge and environment
  availability after the gate;
- no household raw audio, ordinary transcript or reply media persisted.

V3 is complete only after V3A-V3E pass. Software tests, protocol source inspection or a
single tone do not substitute for the supervised interaction counts.

## Queue and release relationship

P4 private-access software work remains the current independent implementation stage.
Camera Reply V3 is inserted after the P4 software checkpoint and before P5. P4's human
Tailscale installation and two-phone cellular acceptance may proceed independently;
they do not authorize or expose the camera speaker.

If V3 is enabled for the release candidate, its real acceptance must pass before P5
starts and Camera Reply must remain healthy throughout the final 72-hour gate. If V3
does not pass, it stays disabled and the accepted i9 speaker behavior remains the
release behavior; no partial camera-output claim is made.

## Explicitly deferred

- Browser or phone microphone forwarding and push-to-talk.
- Arbitrary/free-form TTS, model-generated speech and caller-provided media.
- Camera PTZ, actuator control or camera settings changes.
- Remote speaker endpoints through Tailscale, Dashboard or notifications.
- Baby Care writes, caregiver identity, corrections or care-record confirmation.
- Cry-response automation and unattended caregiver substitution.
- Updating go2rtc beyond the pinned commit solely to obtain newer Xiaomi behavior.
