# Dashboard Hybrid HD Streaming Design

Date: 2026-08-04

## Goal

Make 2x and 3x zoom reveal detail from the Xiaomi camera's real
2560x1440 source while keeping the existing 1280x720, 10 FPS MJPEG view as the
lightweight 1x path. Prefer the camera's original H.265 bitstream and decode it
on the viewing device, as Mi Home does. If a browser cannot use that stream,
start one shared, on-demand 2560x1440 H.264 VideoToolbox compatibility stream
on the Intel i9 Mac.

The change must preserve continuous visible video during handoff, keep go2rtc
loopback-only, keep Dashboard HTTP Basic authentication, and never add a
permanent second transcode. Physical PTZ remains `PTZ_DISABLED` and is outside
this work.

## Confirmed root cause and media facts

The real-device evidence supersedes the earlier H.264 assumption:

- MJSXJ17CM quality subtype `3` produces `2560x1440` video over `cs2+udp`.
- The source media declaration is `video, recvonly, H265`.
- `live` remains an on-demand FFmpeg conversion of `source` to 1280x720,
  10 FPS MJPEG.
- The existing HD relay asks go2rtc only for H.264, so the H.265 producer
  cannot satisfy it. The browser receives a WebSocket but falls back before a
  playable first frame.
- Pinned go2rtc commit
  `b465651a94c1f637d566a8c660b4fad102b35153` advertises H.265 MSE as
  `hvc1.1.6.L153.B0` but writes an `hev1` MP4 sample entry. Modern browsers may
  reject that MIME/init-segment mismatch.
- The pinned go2rtc code supports the explicit VideoToolbox H.264 encoder and
  stops an on-demand FFmpeg producer after its final consumer disconnects.

Increasing a timeout cannot fix the codec mismatch. Re-adding the camera,
changing Xiaomi credentials, or exposing port 1984 is not a valid remedy.

## Chosen architecture

Use two fixed HD media profiles behind the existing authenticated same-origin
relay:

1. `native`: fixed go2rtc stream `source`, H.265 fMP4/MSE, no video encode.
2. `compat`: fixed go2rtc stream `source_compat`, 2560x1440 H.264 at 6 Mbit/s,
   encoded by VideoToolbox only.

The browser performs a local HEVC capability check. If it reports support, the
player tries `native` first. If native setup fails before the first frame, the
player performs exactly one automatic `compat` attempt while the working MJPEG
layer remains visible. A browser that reports no HEVC support requests
`compat` directly.

The browser can choose only the enum values `native` and `compat`. It cannot
submit a stream name, upstream URL, codec string, bitrate, FFmpeg arguments, or
duration. Server-side profile definitions own all media parameters.

2x and 3x remain render-layer zoom values. Moving from 2x to 3x changes only
the existing CSS transform and reuses the current HD connection. Quality
selection and digital zoom are separate responsibilities even though the
default automatic policy requests HD when zoom exceeds 1x.

Rejected alternatives:

- H.265-only is too dependent on browser, OS, and hardware support.
- A permanent H.264 transcode wastes i9 resources while nobody is viewing HD.
- Software H.264 fallback can overload the i9 and hides VideoToolbox failure.
- 2560x1440 MJPEG consumes excessive CPU and LAN bandwidth.
- Direct LAN access to go2rtc violates the loopback boundary.
- WebRTC adds negotiation complexity and still has uneven HEVC support.

## Auditable go2rtc compatibility build

The existing Intel macOS compatibility build is extended, not replaced.

Pinned inputs:

```text
upstream commit: b465651a94c1f637d566a8c660b4fad102b35153
platform: darwin/amd64
minimum Go: 1.24
patch 1: Xiaomi CS2 ListenUDP udp -> udp4
patch 2: H.265 MP4 sample entry hev1 -> hvc1
```

Both edits live in one repository patch and are applied only after the exact
upstream commit is verified. The build must fail closed if the commit, patch
context, expected pre-patch text, or expected post-patch text differs.

The installer builds to a temporary path, verifies the binary, signs it
ad-hoc, backs up the existing `.local/bin/go2rtc`, then installs atomically.
It records only non-sensitive metadata: upstream commit, Go version, patch
SHA256, binary SHA256, build time, and platform. It never commits a binary or
prints the local Xiaomi URI.

An existing binary without matching build metadata is rebuilt on the next
`make alpha-install`; an already matching binary is retained. Any build,
verification, or signing failure leaves the previous binary untouched.

## Fixed media profiles

The runtime go2rtc configuration contains these non-secret derived streams:

```yaml
streams:
  source: <existing local Xiaomi URI; never printed or committed>
  live: ffmpeg:source#video=mjpeg#width=1280#height=720#raw=-r 10
  source_compat: ffmpeg:source#video=h264#hardware=videotoolbox#width=2560#height=1440#bitrate=6M
```

`source_compat` is not started at service startup. go2rtc starts it when the
first compat MSE consumer arrives. Multiple allowed Dashboard consumers share
the same producer. Closing the last compat socket removes the last consumer
and stops FFmpeg.

`hardware=videotoolbox` is explicit. If hardware decoding or encoding fails,
the compat profile fails with `HD_TRANSCODE_UNAVAILABLE`; the system does not
silently start libx264. The original 720p MJPEG path remains usable.

`make alpha-quality-hd` and `make alpha-subtype-apply` add or repair the exact
derived `live` and `source_compat` values while preserving the Xiaomi URI,
unknown configuration keys, file mode, backup, and rollback behavior.

## Session and ticket contract

Authenticated `POST /api/hd-session` accepts exactly:

```json
{"profile":"native"}
```

or:

```json
{"profile":"compat"}
```

Unknown fields and unknown profile values return the normal validation error
before a ticket is issued. A successful response remains:

```json
{"ticket":"<opaque>","expires_in":10}
```

The profile is stored only in the in-memory ticket record and is selected when
the ticket is consumed. It is not trusted from any later WebSocket message.

Ticket security remains unchanged:

- at least 256 bits of randomness;
- ten-second expiry;
- atomic single use;
- never in a URL, DOM attribute, source file, or log;
- at most 64 outstanding valid tickets;
- no eviction of a valid ticket when full.

## Fixed upstream relay

After same-origin and ticket validation, the relay maps the stored profile to
one fixed upstream definition:

| Profile | Stream | Offered codec family | Final failure code |
|---|---|---|---|
| `native` | `source` | `hvc1` only | `HD_CODEC_UNSUPPORTED` |
| `compat` | `source_compat` | approved `avc1` list | `HD_TRANSCODE_UNAVAILABLE` |

The go2rtc base URL remains an HTTP(S) loopback IP without credentials,
queries, or fragments. The relay disables environment/system WebSocket
proxies. It forwards only one valid MSE description followed by bounded binary
fMP4 messages. Client text after the ticket is never proxied upstream.

The global two-connection gate remains in force. A native-to-compat handoff
closes and fully releases native before acquiring compat, so one page never
holds two HD slots at once. Browser disconnect, application shutdown, protocol
error, and every failure path close the upstream in `finally`.

Stable server results are:

- `HD_BUSY` for a full ticket or connection gate;
- `HD_CODEC_UNSUPPORTED` when native cannot provide the announced HEVC media;
- `HD_TRANSCODE_UNAVAILABLE` when the fixed compat stream cannot provide H.264;
- `HD_UPSTREAM_FAILED` for other relay connection/protocol failures.

Raw exceptions, internal addresses, stream inventories, and FFmpeg output are
not sent to the browser or application log.

## Browser player and fallback state machine

At zoom 1x the browser opens no HD session. At 2x or 3x:

1. keep MJPEG visible and show `HD_LOADING`;
2. evaluate `MediaSource.isTypeSupported` for the fixed HEVC MIME;
3. request `native` when supported, otherwise request `compat`;
4. validate the server MIME against the requested profile;
5. append fMP4 through one ordered, bounded SourceBuffer queue;
6. reveal video only after `playing`, then release MJPEG;
7. expose `HD_ACTIVE` and the active profile as a non-sensitive DOM dataset.

If the native attempt fails before activation, cleanup its WebSocket,
MediaSource, SourceBuffer, listeners, queue, timer, and object URL, then start
one compat attempt without hiding MJPEG. This automatic retry is not repeated.
If compat fails, or an already active HD stream later fails, restore or retain
the last working layer and report the specific safe result.

The player distinguishes:

- `HD_UNSUPPORTED`: MediaSource or WebSocket API absent;
- `HD_CODEC_UNSUPPORTED`: native codec negotiation or decode failed and compat
  was not available;
- `HD_TRANSCODE_UNAVAILABLE`: VideoToolbox compatibility stream failed;
- `HD_UPSTREAM_FAILED`: authenticated relay or media protocol failed;
- `HD_TIMEOUT`: no first playable frame within eight seconds for the final
  attempt;
- `HD_BUSY`: server capacity rejected the attempt;
- `HD_ACTIVE`: a first frame is visible.

No raw browser exception is rendered. Selecting 1x resets the blocked state;
selecting 2x/3x again is then an explicit retry.

The existing append constraints remain:

- 16 MiB maximum pending fragment bytes;
- 20-second maximum buffered live window;
- seek near the live edge when more than two seconds behind;
- generation-bound callbacks so old events cannot affect a new attempt.

## Handoff and lifecycle rules

- MJPEG remains visible until native or compat emits `playing`.
- After activation, replacing the MJPEG URL with the local blank sentinel
  releases the 720p request.
- Returning to 1x starts MJPEG and waits for its load event before closing HD.
- If MJPEG restoration fails, the last HD frame remains visible.
- 2x to 3x and 3x to 2x never open a new session.
- Fullscreen exit resets to 1x and follows the same restore path.
- Page unload and BFCache page hide close HD and restore MJPEG state.
- A final-attempt startup timeout is eight seconds; native failure may move to
  compat without producing an empty media plane.

Steady state therefore has:

- 1x: one `live` MJPEG consumer, no HD MSE consumer;
- native HD: one `source` MSE consumer, no `live` consumer, no HD encoder;
- compat HD: one `source_compat` MSE consumer, one shared VideoToolbox FFmpeg
  producer, no `live` consumer.

## Security and privacy boundaries

- Dashboard Basic Auth remains required before issuing a profile-bound ticket.
- go2rtc ports 1984, 8554, and 8555 remain bound to `127.0.0.1`.
- External access remains Tailscale Serve HTTPS only; Funnel and router port
  forwarding remain prohibited.
- Neither HTTP nor WebSocket inputs can select a stream, URL, codec argument,
  bitrate, encoder, or process command.
- Message sizes, startup time, outstanding tickets, and active connections are
  bounded.
- Xiaomi credentials, URI fields, tokens, UID, DID, MAC, private addresses,
  household media, and raw FFmpeg commands containing secrets never enter
  source control, tests, CI artifacts, responses, or logs.

## Automated verification

Tests must be written and observed failing before each implementation change.
They cover:

- exact native/compat profile validation and profile-bound single-use tickets;
- fixed stream mapping, fixed codec offers, loopback enforcement, proxy
  disabling, two-connection gate, message ordering, limits, and cleanup;
- stable classification of codec, transcode, upstream, timeout, and busy
  failures without exception disclosure;
- source codec detection reporting H.265 without exposing producer URLs;
- idempotent insertion of the exact `source_compat` profile while preserving
  credentials, unknown YAML keys, mode, backup, and rollback;
- patch applicability at the pinned go2rtc commit and post-patch `udp4` plus
  `hvc1` invariants;
- installer skip/rebuild/backup behavior based on non-sensitive metadata;
- browser native preference, direct compat selection when HEVC is unsupported,
  one native-to-compat retry, no duplicate HD socket, and final typed failures;
- unchanged no-black handoff, queue bounds, live-window maintenance,
  generation isolation, BFCache cleanup, zoom, drag, fullscreen, PTZ, snapshot,
  notification, and authentication contracts;
- full Python and Node suites, JSON schema validation, Python compilation,
  shell syntax checks, and `git diff --check`.

## Intel i9, M2, Safari, and Android acceptance gate

After CI succeeds, real-device acceptance must show:

- `make alpha-source-check` reports source codec `H265`, dimensions
  `2560x1440`, live dimensions `1280x720`, and no sensitive fields;
- M2 Chrome, M2 Safari, and Android Chrome each either activate native HEVC or
  automatically activate compat H.264 without a black frame;
- 2x/3x visibly reveal more native detail than the 720p 1x view;
- normal HD startup and steady playback remain approximately one to two
  seconds behind the source on the trusted LAN;
- 2x to 3x reuses one WebSocket and one profile;
- native active mode has no HD FFmpeg encoder;
- compat active mode has exactly one shared VideoToolbox FFmpeg producer;
- returning to 1x or closing the final compat client stops that producer;
- repeated switching, dragging, fullscreen, and `Esc` preserve visible video;
- go2rtc listeners remain loopback-only and PTZ remains `PTZ_DISABLED`.

PR #4 remains Draft until CI and this real-device gate pass.

## Upstream references

- go2rtc issue #2205: H.265 `hev1`/`hvc1` MSE mismatch
- pinned go2rtc `pkg/iso/codecs.go` and `pkg/mp4/mime.go`
- pinned go2rtc FFmpeg and stream lifecycle documentation
- FFmpeg VideoToolbox hardware acceleration documentation
