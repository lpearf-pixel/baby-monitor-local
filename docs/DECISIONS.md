# Architecture Decisions

## ADR-001: microSD is the continuous-recording source

The camera's 256GB microSD card provides continuous circular recording. The Mac stores only event clips, screenshots, readings, and logs.

## ADR-002: lightweight native Mac services

V1 uses native Intel macOS processes and does not deploy a full Frigate NVR. Video analysis is limited to a 3–5 FPS low-resolution stream.

## ADR-003: private remote access

Remote viewing uses Tailscale. Camera and go2rtc management ports are never exposed directly to the public Internet.

## ADR-004: public repository contains no household media

Calibration and testing in the repository use synthetic fixtures. Real household images and audio remain under the ignored local `runtime/` directory.

## ADR-005: detections are candidate alerts

Cry, movement, posture, exit, face-covering, and sleep results are candidate alerts only and are not medical or life-safety determinations.

## ADR-006: H.265 native first with on-demand (按需) compatibility encoding

The verified 2560×1440 camera source is H.265. At 2×/3× the Dashboard first
requests the fixed `native` profile. Browsers that cannot activate HEVC use the
fixed `source_compat` profile, which starts one shared 1440p H.264 VideoToolbox
producer only while compat consumers exist. The service never falls back to
software encoding, never accepts browser-supplied FFmpeg parameters, and keeps
the 720p MJPEG layer visible until the selected HD profile is playing.
