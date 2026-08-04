# Dashboard Clear Zoom with On-Demand MSE Design

## Goal

Make 2x and 3x zoom reveal detail from the verified 2560x1440 Xiaomi source
while keeping the current 1280x720, 10 FPS MJPEG path as the lightweight 1x
view. Normal HD playback and a normal transition should remain about one to two
seconds behind the source. The change must not add a second permanent
transcode, expose go2rtc to the LAN, or weaken the Dashboard authentication
boundary.

This design extends the approved fullscreen, digital zoom, drag, and guarded
PTZ design. Physical PTZ remains `PTZ_DISABLED` and is not part of this work.

## Confirmed media facts

- The Xiaomi stream named `source` is verified as H.264 at 2560x1440 with
  `subtype=3` over `cs2+udp`.
- The stream named `live` is an on-demand FFmpeg conversion of `source` to
  1280x720, 10 FPS MJPEG.
- The current 1x, 2x, and 3x controls all transform the same 720p `<img>`, so
  zoom enlarges pixels without adding source detail.
- go2rtc MSE is fragmented MP4 over WebSocket. The upstream MSE consumer is
  removed when its WebSocket closes, and an on-demand FFmpeg producer stops
  after its last consumer disconnects.

## Chosen architecture

Use an authenticated same-origin WebSocket relay between the Dashboard and the
loopback-only go2rtc MSE endpoint. The relay requests only the fixed `source`
stream and forwards its H.264 fragmented MP4 messages to a browser `MediaSource`
player. It is not a generic go2rtc proxy and does not accept a stream name,
upstream URL, codec, or arbitrary upstream command from the browser.

The existing MJPEG `<img>` and a new muted `playsinline` `<video>` occupy the
same media plane. The current layer remains visible until the target layer has
rendered its first frame. This bounded overlap prevents a black frame during a
handoff; it is not a second permanent viewing path.

The implementation keeps responsibilities isolated:

- an HD stream module owns tickets, connection limits, upstream validation,
  and relay cleanup;
- an authenticated API route issues tickets and a WebSocket route delegates to
  that module;
- a dependency-free HD player module owns MediaSource, SourceBuffer, and layer
  handoff lifecycle;
- the existing viewer module asks the HD player for `mjpeg` or `hd` mode when
  zoom/fullscreen state changes, without learning the upstream protocol.

The Python relay adds an explicit WebSocket client runtime dependency. The
browser implementation adds no package or CDN dependency.

Rejected approaches:

- 2560x1440 MJPEG adds unnecessary i9 CPU use and LAN bandwidth.
- A second FFmpeg H.264 encode duplicates work that the verified H.264 source
  does not need.
- Progressive MP4 and screenshot polling have either high startup delay or no
  continuous motion.
- Direct browser access to port 1984 would violate the loopback-only boundary.
- WebRTC adds negotiation and relay complexity that is unnecessary for the
  accepted one-to-two-second delay.

## Components and responsibilities

### One-time HD access tickets

An authenticated `POST /api/hd-session` issues an opaque, in-memory ticket.
The existing HTTP Basic dependency protects this route. A ticket:

- contains at least 256 bits of randomness;
- expires after 10 seconds;
- is consumed atomically on first valid use;
- cannot be reused, refreshed, or supplied in a URL;
- is never written to logs or returned after consumption.

The successful response contains only `{"ticket":"<opaque>","expires_in":10}`.
Expired entries are removed before issue and consume operations. The store
holds at most 64 outstanding tickets; when that bound is reached after cleanup,
issue fails with `HD_BUSY` instead of evicting a valid ticket.

The browser opens the same-origin `/live-hd.ws` endpoint and sends the ticket
as its first WebSocket message. This avoids embedding the Dashboard password in
JavaScript or a WebSocket URL, and avoids relying on browser-specific Basic
Auth behavior during a WebSocket upgrade. The server accepts no media action
until the ticket is validated. The first message is limited to 1 KiB and must
arrive within three seconds.

The WebSocket handshake also requires a same-origin `Origin` authority. Direct
LAN requests compare it with `Host`. A forwarded host is considered only when
the immediate peer is loopback, so a future local Tailscale Serve proxy can
preserve the same-origin rule without trusting arbitrary LAN forwarding
headers. Uvicorn proxy-header rewriting is explicitly disabled so
`websocket.client` remains the raw transport peer rather than an address copied
from `X-Forwarded-For`. An invalid, expired, reused, oversized, or late ticket
closes before any go2rtc connection is created.

### Fixed upstream MSE relay

After ticket consumption, the relay connects only to the configured loopback
go2rtc base URL and the server-owned HD stream name, default `source`. HTTP maps
to `ws` and HTTPS maps to `wss`; any non-loopback upstream host is rejected at
runtime construction. The resulting upstream shape is fixed as
`ws://127.0.0.1:1984/api/ws?src=source` under the default local configuration.
System and environment WebSocket proxies are explicitly disabled for this
loopback connection.

The relay sends the fixed go2rtc MSE request itself. It does not forward later
client text or binary messages upstream. It accepts only:

1. one upstream `mse` description whose value is a supported H.264
   `video/mp4` MIME type; and
2. the following binary fragmented MP4 data.

Unexpected text, an unsupported codec, an oversized message, connection
failure, or protocol disorder closes the relay with a stable public result and
without exposing an upstream address or raw exception. Client disconnect,
application shutdown, and every error path close the upstream socket in
`finally`, allowing go2rtc to release the consumer. The relay watches upstream
media and downstream disconnect concurrently, so a silent or stalled go2rtc
connection cannot retain a connection-gate slot after the browser leaves.

The client state machine opens at most one HD socket per Dashboard page. The
Alpha process accepts at most two concurrent HD sockets and does not queue a
third. A rejected authenticated attempt receives only `HD_BUSY` before close.
There is no automatic reconnect or retry loop in this phase.

### Browser MSE player

The Dashboard adds a `<video>` layer but does not load HD media at page load.
The player is created only when zoom changes from 1x to 2x or 3x and both
`MediaSource` and `WebSocket` are available.

The client flow is:

1. keep the MJPEG image visible and report `HD_LOADING`;
2. request one HD ticket;
3. open the same-origin WebSocket and authenticate with that ticket;
4. validate the announced MIME type with `MediaSource.isTypeSupported`;
5. append init and media fragments through one ordered `SourceBuffer` queue;
6. after the video fires `playing`, reveal it and release the MJPEG request;
7. report `HD_ACTIVE` without exposing transport or device details.

The source buffer keeps a bounded live window. Old data beyond 20 seconds is
removed only while the buffer is not updating. If playback falls more than two
seconds behind the buffered end, the player seeks near the live edge. Pending
fragments are capped at 16 MiB while the buffer is busy; overflow fails to the
same safe MJPEG path instead of growing browser memory without bound. Media
continues to append after the first `playing` event. The video is muted and uses
`playsinline` so autoplay does not request microphone or audio permission.

Every asynchronous MediaSource, SourceBuffer, playback, and media event is
bound to the generation and resource that created it. Cleanup removes those
listeners before a new attempt, so a late callback from an old attempt cannot
activate or tear down the current stream. SourceBuffer and MediaSource error
events use the same no-black-frame fallback path.

Switching between 2x and 3x reuses the same HD socket and only changes the
existing CSS transform. Dragging, pan clamping, fullscreen, and PTZ controls
retain their existing semantics.

### Layer handoff and release rules

Only a ready layer replaces the currently visible layer:

- On 1x to 2x/3x, MJPEG remains visible until HD fires `playing`. The browser
  then swaps the visible layer and changes the image to a local blank sentinel,
  which closes `/live.mjpeg` and lets go2rtc stop the on-demand MJPEG producer.
- On 2x/3x to 1x, the browser starts a fresh `/live.mjpeg` request while keeping
  the last HD frame visible. After the first MJPEG frame loads, it reveals the
  image, closes the HD socket, clears the MSE queue, revokes the object URL, and
  resets the video element.
- Exiting fullscreen already resets zoom to 1x, so it follows the same HD to
  MJPEG release path.
- A handoff overlap has an eight-second hard limit. If the target does not
  become ready, its attempt is cancelled and the currently working layer stays
  visible.
- A normal page unload closes HD immediately. A back-forward-cache page hide
  also releases HD but restores the MJPEG element and may start a fresh HD
  attempt after a persisted page show only when the hidden session was healthy.
  Failed or blocked sessions remain blocked until an explicit 1x reset, and no
  waiting continuation may start HD while the page is suspended. Browser
  history restoration therefore does not return to a destroyed player, blank
  sentinel, or hidden retry.

This creates at most a short transition overlap. Steady 1x has only the MJPEG
consumer; steady 2x/3x has only the source MSE consumer.

## Failure behavior

- Missing browser MSE/WebSocket support keeps the MJPEG image and applies the
  existing CSS zoom. Status becomes `HD_UNSUPPORTED`.
- Ticket, WebSocket, codec, MSE, append, autoplay, or first-frame failure keeps
  or restores MJPEG at the selected zoom. Status becomes `HD_FALLBACK`.
- An HD socket that closes after activation restores MJPEG without resetting
  the user's 2x/3x zoom or pan.
- A failed return to MJPEG keeps the last working HD layer visible and reports
  `HD_FALLBACK`; it does not show an empty media plane.
- The browser performs no hidden retry loop. Selecting 1x and then 2x/3x is an
  explicit retry.
- PTZ state, camera direction, snapshot behavior, recording, and notifications
  are unaffected by any HD failure.

Public UI and API results are limited to `HD_LOADING`, `HD_ACTIVE`,
`HD_FALLBACK`, `HD_UNSUPPORTED`, and `HD_BUSY`. Raw errors, URLs, tickets,
credentials, private addresses, stream inventories, and device identifiers are
never shown to the browser or written to application logs.

## Security and network boundaries

- Dashboard HTTP Basic Auth remains required to issue an HD ticket.
- The HD ticket travels only in the first WebSocket message, never in a query
  string, page source, DOM attribute, or log field.
- go2rtc remains bound to `127.0.0.1` on ports 1984, 8554, and 8555.
- The relay uses the server-owned `source` name; no request parameter can select
  another stream or URL.
- Browser-to-relay and relay-to-go2rtc message sizes and startup times are
  bounded.
- External access remains Tailscale Serve HTTPS only. Funnel and router port
  forwarding remain prohibited.
- No Xiaomi URI, account, token, UID, DID, MAC, household image, private
  address, or raw media fixture enters source control, tests, CI, responses, or
  logs.

## Automated verification

Tests are written and observed failing before implementation. They cover:

- authenticated ticket issue, expiry, atomic single use, reuse rejection, and
  bounded storage cleanup;
- WebSocket rejection before upstream access for missing, invalid, late,
  oversized, cross-origin, and reused tickets;
- fixed `source` selection, loopback enforcement, two-connection limit, fixed
  MSE request, disabled system proxying, message ordering, size limits,
  downstream-disconnect detection, and upstream cleanup;
- page structure and authentication for the new player asset and session route;
- 1x not opening HD, 2x opening once, 2x/3x reuse, 1x/fullscreen-exit release,
  ordered and continuous SourceBuffer appends, bounded pending bytes,
  generation-isolated callbacks, live-window trimming, and live-edge
  correction;
- first-frame handoff without an empty layer, bounded transition overlap, and
  MJPEG preservation/restoration on every failure class, including active
  append and media error events;
- Uvicorn startup preserving the immediate peer and browser page/BFCache
  lifecycle cleanup;
- unchanged zoom, drag, fullscreen, PTZ, snapshot, notification, and Basic Auth
  contracts;
- unchanged loopback listener configuration and absence of sensitive values.

CI continues to run the complete Python and Node suites, schema validation,
Python compilation, and shell syntax checks.

## Intel i9, M2, and Android acceptance gate

After CI succeeds, the i9 real-device gate must show:

- 1x uses 1280x720 MJPEG and 2x/3x visibly reveal additional 2560x1440 detail;
- steady HD playback and a normal 1x to HD handoff remain approximately one to
  two seconds behind the source under the trusted LAN test;
- 2x to 3x does not open a second HD socket;
- steady 1x has no MSE consumer and steady 2x/3x releases the MJPEG FFmpeg
  consumer after handoff;
- no more than one FFmpeg producer exists, and HD mode performs no FFmpeg
  video encode;
- repeated 1x/2x/3x switching, dragging, fullscreen, and `Esc` preserve
  continuous visible video on M2 Chrome/Safari and Android Chrome;
- disconnecting HD or rejecting MSE leaves a usable MJPEG view;
- go2rtc listeners remain loopback-only and PTZ remains `PTZ_DISABLED`.

PR #4 remains Draft until CI and this real-device gate both pass.

## Upstream references

- [go2rtc MP4/MSE module](https://github.com/AlexxIT/go2rtc/blob/master/internal/mp4/README.md)
- [go2rtc MSE WebSocket consumer lifecycle](https://github.com/AlexxIT/go2rtc/blob/master/internal/mp4/ws.go)
- [go2rtc on-demand FFmpeg behavior](https://github.com/AlexxIT/go2rtc/blob/master/internal/ffmpeg/README.md)
