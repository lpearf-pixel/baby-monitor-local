# Voice Care v1 Delivery Plan

## Scope

This plan covers the next executable slice after current audio/cry work: **Gate V0**
audio feasibility for Voice Care v1 on the confirmed Xiaomi + i9 + M2 topology.

The governing design remains:
`docs/superpowers/specs/2026-08-19-voice-care-v1-design.md`

Gate V0 is explicitly low-impact and non-invasive: no Baby Care writes, no household
audio persistence, no ASR/care logic enablement, and no production behavior changes
beyond the fixed decoder timeout/cleanup lifecycle required by the probe gate.

**Overall status:** Complete on 2026-08-20. Gate V0 proves only inbound audio and the
bounded receive/decode boundary. It does not approve a cry/ASR model, speaker identity,
household accuracy or Baby Care writes.

## Stage V0-a: Source media feasibility (pre-flight)

**Status:** Complete on 2026-08-20

**Prerequisites:** Existing audio source and worker hardening up to A7 complete.

**Codex can:**
- Verify the installed source reports active Opus inbound media in a receive-only path.
- Record reproducible bounded evidence commands for media discovery and stream metadata.
- Verify worker/bridge isolation does not couple `audio.enabled=false` to critical
  services.

**Human work:** none.

**Acceptance:**
- `source` shows HEVC + Opus availability and fixed `audio_analysis` alias exposes Opus.
- The probe never uses household room names, credentials or private addresses in output.
- Any failure is fail-closed (`audio_status=unavailable` is acceptable pre-enablement).

**Tests:**
- `python tools/voice_audio_probe.py media` passed on the installed i9: source
  HEVC+Opus and the fixed alias Opus were available. The supported Xiaomi inbound
  format was 48 kHz stereo; the fixed decoder normalized it to 16 kHz mono PCM.
- Output contained only bounded derived media fields.

**Next:** V0-b

## Stage V0-b: Independent audio probe + stability

**Status:** Complete on 2026-08-20

**Prerequisites:** Stage V0-a pass.

**Codex can:**
- Stand up and validate an independent i9-only probe process for bounded Opus
  capture.
- Execute 60-second probe windows and collect heartbeat-style health outputs.
- Validate deterministic startup/stop and no residual consumer processes after stop.

**Human work:** no manual action was needed for this run. The existing macOS Terminal
launch path was required to preserve the camera's local-network permission boundary.

**Acceptance:**
- Probe runs for fixed windows, exits cleanly, and releases sockets/files promptly.
- No decode hang, no raw data persistence, no route to media path leakage.
- 10-minute bounded stability (no regressions that would make the stream unavailable
  as expected by spec).

**Tests:**
- `.venv-alpha/bin/python tools/voice_audio_probe.py live --duration 60`: 60.000
  decoded seconds and 1,920,000 PCM bytes,
  discarded immediately.
- `.venv-alpha/bin/python tools/voice_audio_probe.py live --duration 600`: 600.000
  decoded seconds and 19,200,000 PCM bytes,
  discarded immediately.
- Both runs exited 0 and left no `audio_analysis` ffmpeg consumer.

**Next:** V0-c

## Stage V0-c: Codec and synthetic OPUS compatibility

**Status:** Complete on 2026-08-20

**Prerequisites:** Stage V0-b pass.

**Codex can:**
- Run synthetic OPUS fixtures through the same decode boundary used by real media.
- Validate codec, sample rate, channel count and frame stride contract boundaries.
- Keep all tests to generated fixtures and no household audio payloads.

**Human work:** none.

**Acceptance:**
- Supported Opus input is normalized to the fixed mono 16 kHz PCM target and bounded
  frame shape configured in approved settings.
- Incompatible codecs or malformed payloads map to closed/fail statuses.

**Tests:**
- `make alpha-voice-v0-test`: 61 passed plus an actual one-second in-memory synthetic
  Opus encode/decode PASS.
- `make alpha-audio-test`: 69 passed.
- Full regression: Python 919 passed and Dashboard Node 73 passed.
- FFmpeg 8 compatibility uses its supported `-timeout` RTSP input option; unsupported
  or malformed input remains fail-closed.

**Next:** V0-d

## Stage V0-d: Cleanup, isolation and go-live readiness

**Status:** Complete on 2026-08-20

**Prerequisites:** Stage V0-c pass.

**Codex can:**
- Add/refresh a simple fail-closed verification checklist for probe stop/restart,
  cleanup, and service boundaries.
- Verify that audio worker failure does not restart sibling services.

**Human work:** none remaining for Gate V0.

**Acceptance:**
- Probe start/stop complete without worker leakage.
- No cross-service dependency; video viewing, gauge, visual, and storage continue
  independently.
- Gate V0 exit criteria reached: inbound audio media confirmed, codec compatibility
  confirmed, bounded 10-minute behavior validated, isolation confirmed.

**Tests:**
- `make alpha-audio-test`
- Live pre/post checks kept the same visual, gauge and environment-watchdog PIDs;
  Dashboard health stayed OK, realtime visual stayed available at 5 FPS, and go2rtc
  stayed available. No audio probe process remained after either window.

**Next:** Return to `docs/superpowers/plans/2026-08-17-audio-cry-candidates.md` Stage A8
and run supervised household A8 scenarios only after production model/license approval.
