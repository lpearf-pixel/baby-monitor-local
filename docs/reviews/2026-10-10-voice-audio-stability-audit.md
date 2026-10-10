# Voice audio chain stability audit

Date: 2026-10-10  
Scope: offline software audit and reversible local-output improvement only  
Camera Reply: disabled  
PTZ: not touched  
Baby Care database: not touched

## State and evidence boundary

The local repository was inspected at detached integration head `97b855c`
(`codex/visual-regression-corpus` remote head at the start of this audit). The
working tree's unrelated untracked `Interactive` and `test.sh` files were
preserved. The Baby Care repository was inspected separately at
`codex/m4-birth-ready-operations`; no Baby Care code or database was changed.

The following are software facts, not household playback acceptance:

- the video producer is a long-lived go2rtc Xiaomi producer;
- the audio worker reads an independent loopback audio consumer through a fixed
  FFmpeg decoder;
- Voice local playback uses a bounded `/usr/bin/afplay` process;
- Camera Reply uses a separate internal go2rtc generated-media consumer and
  remains disabled unless a private acceptance marker and setting authorize it;
- no test in this audit contacted the real go2rtc HTTP API or camera speaker.

## Root-cause hypothesis matrix

| ID | Location / evidence | Assessment | Offline verification | Priority |
|---|---|---|---|---|
| H1 | Pinned CS2 command dispatcher and bounded channel-0 handling in `patches/go2rtc-macos-hybrid-hd.patch`; lifecycle review tests cover queued responses, generation, ACK and quiet-window edges. | Confirmed historical failure mode; the current patch has the bounded/drop and response-drain fixes. | Go protocol tests in the patch; Python Camera Reply contract tests. | Closed in software; hardware pending |
| H2 | CS2 `WritePacket` hunk now copies `payload` after the header and includes `TestWritePacketCopiesPayload`; upstream PR #2406 describes the same duplicated-header defect. | Confirmed in the old pinned source; corrected in the local patch. | Deterministic packet fixture; no camera required. | Closed in software; hardware pending |
| H3 | `services/voice/camera_reply.py` serializes inspect → render → start → bounded wait → stop under an operation lock; transport binds stop to producer id/protocol/generation and rejects malformed/stale evidence. | Confirmed lifecycle boundary. The old four-reply/UDP-timeout/Voice-EOF sequence is consistent with a shared-session settlement failure, but exact firmware causality is not proven. | `tests/voice/test_camera_reply.py`, lifecycle review and synthetic transport fixtures. | Closed in software; hardware pending |
| H4 | `services/audio/source.py` opens one fixed loopback FFmpeg audio consumer; Camera Reply POSTs an internal generated-media consumer to existing `source`; `go2rtc` owns the external producer. | Confirmed architecture. Audio input and reply playback are separate consumers, but both depend on the shared producer. | Source/worker tests plus Camera Reply fixtures. | Important design constraint |
| H5 | Historical evidence: four local Camera Reply completions followed by CS2 UDP timeout and Voice audio EOF. | Plausible consequence of H1/H3, not a proven single root cause. | Reproducible synthetic lifecycle tests exist; no deterministic household reproduction. | Do not claim hardware root cause |
| H6 | `cmdMotorReq` is declared in the patched upstream but not called by the Camera Reply path; no PTZ command is emitted by this code path. | No evidence that Baby Monitor caused the observed physical turn. Mi Home tracking/cruise/firmware remain alternative explanations. | Static call-site audit and forbidden-command tests. | Keep PTZ disabled |
| H7 | Local TTS previously coupled rendering and `afplay` invocation inside `FixedVoiceSynthesizer`; Camera Reply had a separate output class. | Confirmed maintainability/coupling issue, not the historical CS2 failure itself. | New sink injection tests in this commit. | Fixed in this commit |

## GitHub / upstream survey

| Candidate | Evidence and license | Current-model fit | Decision |
|---|---|---|---|
| go2rtc Xiaomi MISS/CS2 | Official Xiaomi support documents CS2 and sendonly media; repository is MIT. The upstream issue/PR discussion reports the duplicated-header payload bug and a verified fix for a different Xiaomi model. | Our `MJSXJ17CM` source negotiates `cs2+udp`, HEVC and Opus; model-specific backchannel success is not established by generic support. | Keep pinned, patched, disabled-by-default experimental adapter. |
| Home Assistant + go2rtc/WebRTC | HA documents go2rtc as the stream integration; go2rtc documents backchannel as a sender codec. | Useful browser/UI pattern, but HTTPS microphone permission and camera model support remain separate. | Do not use it as proof of MJSXJ17CM speaker support. |
| Wyoming satellite / ESPHome audio | Wyoming satellite provides a local network voice-satellite protocol; ESPHome I2S media player requires an ESP32 and an external or internal DAC. ESP32-S3 boards vary: a bare MCU board is not a speaker/amplifier. | Good independent input/output endpoint, but adds hardware and a second local service. | Candidate for the independent speaker path, not this commit. |
| Snapcast | Mature local multiroom audio architecture; GPL-3.0. | Stable distribution but license and extra server/client complexity are not justified for one nursery speaker. | Future option only if multi-room audio becomes a requirement. |

Sources reviewed: go2rtc Xiaomi documentation and code, issue #1982, the
backchannel payload discussion/PR #2406, go2rtc backchannel documentation,
Home Assistant go2rtc documentation, ESPHome I2S media-player documentation,
Wyoming satellite and Snapcast repositories. Generic video support was never
treated as proof of two-way audio for `MJSXJ17CM`.

## A/B/C comparison and recommendation

| Option | Stability | Cost / latency | Main risk | Decision |
|---|---|---|---|---|
| A. Continue CS2 repair | Lowest additional hardware cost; current software lifecycle is bounded and fail-closed. | Low latency when it works. | Proprietary firmware/model behavior, shared-producer failure, no real success evidence for this model. | Keep as opt-in experiment only; stop if the next hardware gate fails. |
| B. Independent local speaker | Highest isolation from camera and Guardian; i9 `afplay` already works under bounded process control. | Minimal cost and latency on i9; a network speaker adds small LAN latency. | Echo/placement and device provisioning. | Preferred reliable production output. |
| C. Dual channel | Camera remains video/audio input; Voice Worker owns ASR/dialogue; Baby Care owns care facts; replaceable Audio Output Adapter owns playback. | One TTS path and one semantic output contract can serve A/B. | Requires explicit adapter status and one-flight/cancellation contracts. | Recommended target architecture. Camera Reply remains optional adapter. |

## Implemented offline improvement

The fixed semantic-code output now has explicit structural contracts:

- `AudioSink.play(RenderedReply, cancelled)` is the bounded low-level output
  boundary;
- `MacAudioSink` is the default local-only implementation and preserves the
  fixed volume, timeout and no-inherited-output behavior;
- `VoiceOutput.speak_code(...)` documents the common upper-level interface
  already shared by local output and Camera Reply adapters;
- `FixedVoiceSynthesizer` accepts an injected sink. A sink failure ends only the
  current response, resumes capture, deletes the temporary AIFF and permits the
  next response; it never restarts go2rtc or changes Guardian state.

No Camera Reply flag, camera connection, PTZ path, model, threshold, Guardian
risk rule or Baby Care integration was changed.

## Verification

Fresh focused command after the RED/GREEN cycle:

```text
.venv-alpha/bin/python -m pytest -q \
  tests/voice/test_tts.py tests/voice/test_camera_reply.py \
  tests/voice/test_listen_only.py tests/voice/test_listen_only_runtime.py \
  tests/voice/test_audio_pump.py tests/audio/test_worker.py
```

Result: `172 passed`.

The new tests specifically prove sink injection, temporary-file cleanup,
capture ducking/resume and recovery after one sink failure. The test suite does
not prove that a real `MJSXJ17CM` speaker produces audible sound.

## Remaining hardware gate and next M6 boundary

`HARDWARE_ACCEPTANCE_PENDING`: one supervised, one-second Camera Reply tone at
most, only after a separately approved gate, must verify source health before
and after, exactly one producer/consumer, no PTZ movement, no Voice EOF, and
bounded stop. Any failure keeps Camera Reply disabled.

M6 must depend on the `VoiceOutput`/semantic-code boundary, not on Camera Reply.
Baby Care continues to receive versioned candidates and remains the source of
truth for authenticated care records. The first production target is the i9
local speaker or a separately provisioned local speaker; camera playback stays
an experimental adapter.
