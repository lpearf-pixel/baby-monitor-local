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
