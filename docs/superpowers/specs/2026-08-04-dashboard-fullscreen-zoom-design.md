# Dashboard Fullscreen, Digital Zoom, and Step PTZ Design

## Goal

Add browser-only fullscreen viewing, 1×/2×/3× digital zoom with bounded
dragging, and authenticated one-click camera pan/tilt steps to the Alpha
Dashboard.

Fullscreen and digital zoom remain presentation-only. PTZ changes the physical
camera view through a separate, guarded control path. The Xiaomi source,
FFmpeg profile, MJPEG proxy, and network boundary otherwise remain unchanged.

## Confirmed device boundary

The real device is Xiaomi MJSXJ17CM, model `chuangmi.camera.039c01`. Its
published MIoT specification reports PTZ capability, but does not expose
directional movement as a public writable MIoT property or action.

The current upstream go2rtc Xiaomi implementation supports streaming and
two-way audio. It defines the MISS motor command identifiers but does not expose
a supported PTZ API. Upstream PTZ support remains an open enhancement.

Therefore the implementation must not guess a motor payload or send an
unverified command to the real camera. The PTZ adapter remains disabled until
the exact MJSXJ17CM command format has evidence, automated fixture coverage, and
a controlled real-device gate.

## Chosen viewer approach

Use the browser Fullscreen API, CSS transforms, and Pointer Events inside the
existing server-rendered Dashboard. This adds no runtime dependency and does
not decode or transcode a second video stream on the Intel i9 Mac.

Canvas rendering is rejected because it adds a duplicate client-side drawing
loop and unnecessary battery use. Server-side crop/zoom is rejected because it
would add FFmpeg work, couple pan state across viewers, and increase latency.

## Viewer structure

The live MJPEG image sits in a `16:9` viewport with `overflow: hidden`. A
compact overlay contains:

- `1×`, `2×`, and `3×` zoom buttons;
- one fullscreen enter/exit button;
- four physical PTZ step buttons: up, down, left, and right.

The active zoom button exposes `aria-pressed="true"`. Every control has a
Chinese accessible label, visible focus style, and touch target of at least
44 CSS pixels. PTZ controls remain visible in normal and fullscreen modes.
Existing snapshot, notification, and status controls remain outside the viewer
and keep their current behavior.

Digital pan and physical PTZ are visually separated: dragging moves only the
zoomed browser image, while the direction pad moves the camera itself.

## Fullscreen and digital zoom behavior

- Initial state is `1×` with the image centered.
- Selecting `2×` or `3×` enlarges around the current center.
- At zoom above `1×`, a mouse or one-finger Pointer Events drag pans the image.
- Pan is clamped so the viewport cannot be dragged beyond the zoomed image into
  an empty area.
- Selecting a lower zoom clamps the current pan to the new bounds.
- Selecting `1×` resets pan to the center.
- The fullscreen button enters or exits fullscreen for the viewer only.
- Double-clicking the live image toggles fullscreen.
- Browser-native `Esc` exits fullscreen; a `fullscreenchange` handler updates
  the button label and resets zoom and pan after exit.
- The layout fills the screen in fullscreen and adapts to portrait or landscape
  without requesting an orientation lock.
- Pinch-to-zoom and mouse-wheel zoom remain outside this Alpha scope.

Pointer capture keeps a drag stable if the pointer leaves the image. Dragging
is disabled at `1×`; the normal page remains scrollable outside the viewer.

## PTZ interaction and safety behavior

The first PTZ version is click-to-step only:

- one click submits exactly one of `up`, `down`, `left`, or `right`;
- press-and-hold, auto-repeat, diagonals, presets, cruise, and automatic tracking
  are excluded;
- a direction button is disabled while its request is in flight;
- the four buttons are briefly disabled after an accepted command to enforce a
  server-defined minimum interval;
- the UI shows only stable outcomes such as `PTZ_OK`, `PTZ_BUSY`,
  `PTZ_DISABLED`, or `PTZ_UNAVAILABLE`;
- a failed PTZ request never reloads or stops the live MJPEG stream.

The authenticated local endpoint accepts a closed direction enum and no
arbitrary device identifier, duration, speed, payload, URL, or shell command.
The server serializes motor commands so only one can run at a time, applies a
minimum command interval, uses a bounded timeout, and rejects PTZ by default
until the verified adapter is explicitly enabled.

Only the server-side adapter may access existing Xiaomi connection material.
Credentials, Xiaomi URI fields, private addresses, device identifiers, raw
commands, and household images must never be returned to the browser or written
to application logs.

## Protocol enablement gate

PTZ is enabled in three stages:

1. **Disabled adapter:** Dashboard and API behavior are fully testable, but the
   device adapter returns `PTZ_DISABLED` and sends no network command.
2. **Protocol fixture:** The exact MJSXJ17CM motor request and response are
   represented by synthetic, credential-free fixtures. Direction mapping,
   single-step bounds, response validation, timeout handling, and log redaction
   pass automated tests.
3. **Controlled real-device gate:** With the crib and camera movement path
   observed, issue one minimum left step and one minimum right step to return
   approximately to the starting view. If either command, response, or live
   stream check fails, disable PTZ immediately. Only after this gate may all
   four Dashboard direction buttons be enabled.

No blind `0–5` motor scan, arbitrary payload probing, continuous movement, or
unbounded retry is allowed.

## Failure and compatibility behavior

If the Fullscreen API is unavailable, the fullscreen control is disabled with
an accessible explanation while digital zoom still works. A fullscreen request
rejection leaves the current view and zoom state unchanged. The live MJPEG
stream is never reloaded merely because zoom or fullscreen changes.

If PTZ is unsupported, disabled, busy, rate-limited, times out, or returns an
unknown response, the camera control buttons remain fail-closed and the video
viewer continues normally. An unknown device model may not inherit the
MJSXJ17CM adapter automatically.

## Verification

Automated tests must first fail against the existing Dashboard and API, then
verify:

- the authenticated page exposes exactly the 1×/2×/3× controls, fullscreen
  control, and four PTZ step controls with accessible state;
- the viewer has a bounded viewport and Pointer Events hooks;
- zoom reset, pan clamping, fullscreen toggling, and fullscreen-exit reset are
  present without changing `/live.mjpeg` or its authentication contract;
- unauthenticated PTZ requests are rejected;
- directions outside the four-value enum are rejected before adapter access;
- concurrent, too-frequent, disabled, timeout, and unknown-response PTZ paths
  fail closed with stable redacted errors;
- one accepted click maps to one adapter call and never auto-repeats;
- all existing API and monitoring tests still pass.

The Intel i9/M2 real-browser gate checks continuous playback, each zoom level,
mouse drag, Android one-finger drag, fullscreen enter/exit, `Esc`, PTZ button
layout in normal/fullscreen modes, and absence of a new FFmpeg process or
material server CPU increase.

The separate MJSXJ17CM PTZ gate checks only the minimum left/right recovery pair
before enabling the complete four-direction control.

## Security and operational boundaries

- Dashboard Basic Auth stays required for viewing and PTZ.
- go2rtc remains loopback-only.
- External access remains Tailscale Serve HTTPS only.
- Tailscale Funnel and router port forwarding remain prohibited.
- No credentials, private addresses, device identifiers, raw motor payloads, or
  household images enter source control, CI artifacts, tests, logs, or browser
  status text.
- PTZ is convenience control for an attended household camera, not an
  autonomous safety function.
