# Dashboard Fullscreen and Digital Zoom Design

## Goal

Add browser-only fullscreen viewing and 1×/2×/3× digital zoom with bounded
dragging to the authenticated Alpha Dashboard. The camera source, go2rtc,
FFmpeg profile, MJPEG proxy, authentication, and network boundary remain
unchanged.

## Chosen approach

Use the browser Fullscreen API, CSS transforms, and Pointer Events inside the
existing server-rendered Dashboard. This adds no runtime dependency and does
not decode or transcode a second video stream on the Intel i9 Mac.

Canvas rendering is rejected because it adds a duplicate client-side drawing
loop and unnecessary battery use. Server-side crop/zoom is rejected because it
would add FFmpeg work, couple pan state across viewers, and increase latency.

## Viewer structure

The live MJPEG image sits in a `16:9` viewport with `overflow: hidden`. A compact
overlay contains four controls:

- `1×`, `2×`, and `3×` zoom buttons;
- one fullscreen enter/exit button.

The active zoom button exposes `aria-pressed="true"`. Buttons have Chinese
accessible labels, visible focus styles, and touch targets of at least 44 CSS
pixels. Existing snapshot, notification, and status controls remain outside the
viewer and keep their current behavior.

## Interaction behavior

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
- Pinch-to-zoom, mouse-wheel zoom, and camera PTZ are outside this Alpha scope.

Pointer capture keeps a drag stable if the pointer leaves the image. Dragging
is disabled at `1×`; the normal page remains scrollable outside the viewer.

## Failure and compatibility behavior

If Fullscreen API support is unavailable, the fullscreen control is disabled
with an accessible explanation while 1×/2×/3× zoom still works. A fullscreen
request rejection leaves the existing view and zoom state unchanged. The live
MJPEG stream is never reloaded merely because zoom or fullscreen changes.

## Verification

Automated tests must first fail against the existing Dashboard, then verify:

- the authenticated page exposes exactly the 1×/2×/3× controls and a fullscreen
  control with accessible state;
- the viewer has a bounded viewport and Pointer Events hooks;
- zoom reset, pan clamping, fullscreen toggling, and fullscreen-exit reset are
  present without changing `/live.mjpeg` or its authentication contract;
- all existing API and monitoring tests still pass.

The Intel i9/M2 real-browser gate checks continuous playback, each zoom level,
mouse drag, Android one-finger drag, fullscreen enter/exit, `Esc`, and absence
of a new FFmpeg process or material server CPU increase.

## Security and operational boundaries

- Dashboard Basic Auth stays required.
- go2rtc remains loopback-only.
- External access remains Tailscale Serve HTTPS only.
- Tailscale Funnel and router port forwarding remain prohibited.
- No credentials, private addresses, device identifiers, or household images
  enter source control, tests, logs, or browser status text.

