# Voice Gate V3 Xiaomi Camera Reply Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Deliver the two accepted listen-only Voice replies through the Xiaomi MJSXJ17CM camera speaker, with a proven pinned CS2 backchannel, pre-send-only i9 fallback and supervised real-device acceptance.

**Architecture:** Preserve the installed `cs2+udp` Xiaomi source and extend the exact pinned go2rtc compatibility patch only after a synthetic upstream Go test proves the outbound payload defect. Add a closed loopback camera-output adapter behind the existing `speak_code` boundary, then require an ignored acceptance marker matching the installed go2rtc build before production selects the camera over the i9 speaker.

**Tech Stack:** Go 1.24, pinned go2rtc, Python 3.11 standard library, pytest, macOS `/usr/bin/say`, loopback go2rtc Streams API, GNU Make and supervised Intel i9 device gates.

**Spec:** `docs/superpowers/specs/2026-08-26-xiaomi-camera-reply-design.md`

## Global Constraints

- Keep the pinned go2rtc commit `b465651a94c1f637d566a8c660b4fad102b35153`; do not perform a broad upstream update.
- Keep the confirmed Xiaomi transport `cs2+udp`; V3 does not switch the camera to `cs2+tcp`.
- Accept only `listen_only_ready` and `listen_only_received`; never accept caller text, audio, paths, URLs, stream names, codecs, durations or extra go2rtc arguments.
- The only destination is `source`; the only go2rtc origin is `http://127.0.0.1:1984`.
- Household audio remains memory-only. Tests use generated PCM/AIFF/WAV and synthetic protocol bytes only.
- Browser microphones, push-to-talk, remote speaker access, camera PTZ and Baby Care writes remain out of scope.
- Camera playback failure never restarts go2rtc, Dashboard, Guardian, Voice, gauge, environment or the Alpha stack.
- Camera output is disabled until a supervised marker matches the current upstream commit, patch digest and installed binary digest.
- The i9 fallback is allowed only when camera output is known unavailable before a send begins. Busy, timeout, cancellation and ambiguous post-send results never play a second reply.
- Software tests must not contact the installed go2rtc API or real camera. The real tone and interaction gates are separate controlling-TTY commands.
- Status and logs contain fixed codes and bounded counters only; never output source configuration, addresses, URLs, paths, reply text, household transcript, payloads or raw exceptions.
- Do not push, merge, modify `main`, change private settings or enable production camera output during software implementation.

## Gate mapping

| Approved gate | Plan tasks | Exit condition |
| --- | --- | --- |
| V3A protocol/provenance | Task 1 | Synthetic packet RED/GREEN and pinned build gate pass |
| V3B speaker feasibility | Task 4 and Task 8 Steps 1-3 | Generated tone heard from camera and post-health checks pass |
| V3C fixed reply adapter | Tasks 2-3 and 7 | Closed transport, fixed media, status and side-effect-free software command pass |
| V3D Voice integration | Tasks 5-6 | Camera-primary selection, pre-send-only fallback and echo recovery pass |
| V3E supervised acceptance | Task 8 Steps 4-7 | Required interaction matrix and final installed/software gates pass |

---

### Task 1: Prove and close the pinned CS2 outbound payload defect

**Files:**
- Modify: `patches/go2rtc-macos-hybrid-hd.patch`
- Modify: `packages/monitoring/go2rtc_build.py`
- Modify: `tools/go2rtc_build.py`
- Modify: `tests/monitoring/test_go2rtc_build.py`

**Interfaces:**
- Consumes: `GO2RTC_COMMIT`, `verify_and_apply_patch()` and the current atomic build/install/rollback flow.
- Produces: a patch that changes only the existing HEVC sample entry, UDP socket family, one CS2 payload-copy line and one upstream-package regression test.
- Produces: `run_upstream_protocol_gate(source_dir: Path, go: str, *, runner=...) -> None`, executed after patch application and before `go build`.

- [x] **Step 1: Extend the synthetic upstream fixture and write the failing patch-scope test**

Update `_source_repo()` with the pinned `WritePacket` body, including the current second
`copy(req[offset+hdrSize:], hdr)`. Require the applied patch to add
`pkg/xiaomi/miss/cs2/conn_test.go` and to produce this production line:

```go
copy(req[offset+hdrSize:], payload)
```

The Go regression uses `net.Pipe`, a 32-byte synthetic header and a distinct payload.
It reads exactly `12 + len(header) + len(payload)` bytes and asserts:

```go
if !bytes.Equal(got[12:12+hdrSize], header) {
	t.Fatal("header mismatch")
}
if !bytes.Equal(got[12+hdrSize:], payload) {
	t.Fatal("payload mismatch")
}
```

Also assert patch verification rejects an extra changed path, a production change
outside the allowlist and a missing regression test.

- [x] **Step 2: Run the repository RED**

```bash
.venv-alpha/bin/python -m pytest -q tests/monitoring/test_go2rtc_build.py -k 'patch or protocol'
```

Expected: the current patch leaves header bytes at the payload offset and does not add
the required Go regression.

- [x] **Step 3: Observe the exact pinned upstream Go RED before correcting production**

In a temporary clone at the fixed commit, apply a test-only copy of the new
`conn_test.go` while leaving `conn.go` unchanged, then run:

```bash
go test ./pkg/xiaomi/miss/cs2 -run TestWritePacketCopiesPayload -count=1
```

Expected: FAIL with only the synthetic payload mismatch. Do not contact the camera.

- [x] **Step 4: Add the minimal patch and build-time protocol gate**

Extend the tracked patch with the one `hdr` to `payload` correction and the focused Go
test. Change `ALLOWED_PATCH_CHANGES` to the exact final `git apply --numstat` map for
the three paths. `verify_and_apply_patch()` must assert the pre-patch defective line is
present exactly once and the corrected line is absent, then assert the inverse after
application.

Implement `run_upstream_protocol_gate()` with the fixed argv:

```python
(go, "test", "./pkg/xiaomi/miss/cs2", "-run", "TestWritePacketCopiesPayload", "-count=1")
```

Discard stdout/stderr on success and map any failure to
`GO2RTC_PROTOCOL_GATE_FAILED`. Call it before the existing `go build` command.

- [x] **Step 5: Run GREEN without installing a candidate**

```bash
.venv-alpha/bin/python -m pytest -q tests/monitoring/test_go2rtc_build.py
.venv-alpha/bin/python -m compileall -q packages/monitoring/go2rtc_build.py tools/go2rtc_build.py
git diff --check
```

Expected: all go2rtc build tests pass; no installed binary, app bundle or runtime
metadata changes.

- [x] **Step 6: Commit Task 1**

```bash
git add patches/go2rtc-macos-hybrid-hd.patch packages/monitoring/go2rtc_build.py tools/go2rtc_build.py tests/monitoring/test_go2rtc_build.py
git commit -m "fix: preserve Xiaomi CS2 audio payloads"
```

---

### Task 2: Add a closed camera-reply protocol and loopback transport

**Files:**
- Create: `services/voice/camera_reply.py`
- Create: `tests/voice/test_camera_reply.py`

**Interfaces:**
- Produces: `CameraReplyCode(StrEnum)` with the nine codes defined by the spec.
- Produces: immutable `CameraReplyEvidence`, `CameraReplyResult` and `CameraReplyStatus` dataclasses.
- Produces: `parse_source_media(payload: bytes) -> CameraReplyEvidence`.
- Produces: `LoopbackCameraReplyTransport.inspect()`, `start(media: Path)` and `stop()`.
- Produces: `CameraReplyStatusWriter.write(status: CameraReplyStatus) -> None` with atomic mode-0600 publication.
- Consumes: only generated regular files owned by the current user under its caller-owned mode-0700 temporary directory.

- [x] **Step 1: Write strict evidence-parser RED tests**

Use synthetic go2rtc JSON fixtures. Accept exactly one `source` stream with current
HEVC receive media, incoming Opus `48000/2` and one audio sendonly Opus `48000/2`
media. Reject malformed/non-object/oversized JSON, absent source, multiple source
objects, missing sendonly, PCMA-only, unknown codec, wrong rate/channels and fields of
the wrong type. Set the input cap to 1,048,576 bytes.

Assert the returned object contains booleans and closed codec/protocol labels only. It
must not preserve a producer URL, address, username, token, stream payload or raw JSON.

- [x] **Step 2: Write transport RED tests**

Inject a recording HTTP opener and assert all calls use two-second connection/read
timeouts, maximum 1,048,576-byte responses and no proxy environment. Inspection may
request only:

```text
GET http://127.0.0.1:1984/api/streams?src=source
```

Playback may issue only a percent-encoded equivalent of:

```text
POST /api/streams?dst=source&src=ffmpeg:{validated_generated_path}#audio=opus#input=file
```

Stop may issue only:

```text
POST /api/streams?dst=source&src=
```

Assert non-loopback origins, caller query fragments, symlinks, non-regular files,
wrong owner/mode, paths outside the supplied temporary directory, oversized files,
timeouts and non-success HTTP status all fail closed without a retry.

- [x] **Step 3: Run RED**

```bash
.venv-alpha/bin/python -m pytest -q tests/voice/test_camera_reply.py
```

Expected: collection fails because `services.voice.camera_reply` does not exist.

- [x] **Step 4: Implement the pure contract and bounded transport**

Use `urllib.request` with a fixed opener that ignores environment proxy settings.
`start()` returns `CameraReplyResult(code, delivery_started)` and sets
`delivery_started=True` only after the POST request is issued. Any exception after
that point maps to `CAMERA_REPLY_AMBIGUOUS`; pre-send validation failures map to
`CAMERA_REPLY_REJECTED` or `CAMERA_REPLY_UNAVAILABLE`.

Guard the transport with one nonblocking lock. A concurrent call returns
`CAMERA_REPLY_BUSY`; it is never queued. Do not expose the constructed URL or input
path through a return value or exception.

- [x] **Step 5: Prove timeout, cap and settlement behavior**

Use local fake openers that block, return oversized data and mutate after cancellation.
Assert each public method returns within its bound, closes the response, leaves no
background thread and emits no raw response. Assert repeated `stop()` is bounded and
idempotent.

- [x] **Step 6: Run GREEN and commit**

```bash
.venv-alpha/bin/python -m pytest -q tests/voice/test_camera_reply.py
.venv-alpha/bin/python -m compileall -q services/voice/camera_reply.py
git diff --check
git add services/voice/camera_reply.py tests/voice/test_camera_reply.py
git commit -m "feat: add closed Xiaomi camera reply transport"
```

---

### Task 3: Generate and play only the two fixed replies

**Files:**
- Modify: `services/voice/camera_reply.py`
- Modify: `tests/voice/test_camera_reply.py`
- Modify: `services/voice/tts.py`
- Modify: `tests/voice/test_tts.py`

**Interfaces:**
- Produces: immutable `RenderedReply(path: Path, duration_seconds: float, temporary_root: Path)`.
- Produces: `FixedReplyRenderer.render(code, cancelled) -> RenderedReply | None`.
- Produces: `CameraReplyOutput.speak_code(code, cancelled) -> bool` and `deliver_code(code, cancelled) -> CameraReplyResult`.
- Reuses: `RESPONSE_PHRASES`, `BoundedCommandRunner` and the existing `CaptureDucker` protocol.

- [x] **Step 1: Write renderer and output RED tests**

For each accepted code, assert the renderer calls `/usr/bin/say` with the fixed voice,
rate and linear PCM AIFF format, reads the phrase from stdin and writes only to a
caller-owned temporary directory. Reject every other semantic code before creating a
file or subprocess.

Accept only a current-user-owned regular mode-0600 AIFF file between 1 byte and
1,048,576 bytes, 16 kHz mono signed 16-bit PCM and 0.20-4.00 seconds. Reject symlink,
hardlink count above one, FIFO/socket, wrong mode, malformed headers and excess
duration. Unlink the generated file after stop settlement on every success, failure,
timeout and cancellation path.

- [x] **Step 2: Write lifecycle RED tests**

Assert `CameraReplyOutput` performs this exact order:

```text
ducker.pause -> inspect -> render -> start -> bounded wait -> stop -> unlink -> guard -> ducker.resume
```

It must call stop after every started send, never after a pre-send failure, and wait in
at most 50 ms cancellation increments. The maximum total reply operation is ten
seconds. `CAMERA_REPLY_COMPLETE` requires a successful start, bounded media-duration
wait and successful stop; stop failure becomes `CAMERA_REPLY_AMBIGUOUS`.

- [x] **Step 3: Run RED**

```bash
.venv-alpha/bin/python -m pytest -q tests/voice/test_camera_reply.py tests/voice/test_tts.py
```

Expected: renderer/output cases fail because the new classes do not exist.

- [x] **Step 4: Extract the fixed renderer and implement camera output**

Keep `phrase_for_semantic_code()` authoritative. Preserve `FixedVoiceSynthesizer`'s
public behavior by composing the renderer with `/usr/bin/afplay`; do not broaden its
accepted codes or command vectors. Add camera output using the same renderer and
ducker, with single cleanup ownership and no persisted reply asset. After each result,
atomically write only backend, readiness, last stable code, completed count, failed
count and bounded latency through `CameraReplyStatusWriter`; discard status failures.

- [x] **Step 5: Run GREEN and commit**

```bash
.venv-alpha/bin/python -m pytest -q tests/voice/test_camera_reply.py tests/voice/test_tts.py
.venv-alpha/bin/python -m compileall -q services/voice/camera_reply.py services/voice/tts.py
git diff --check
git add services/voice/camera_reply.py services/voice/tts.py tests/voice/test_camera_reply.py tests/voice/test_tts.py
git commit -m "feat: play fixed replies through Xiaomi camera"
```

---

### Task 4: Add the supervised synthetic-tone gate and acceptance marker

**Files:**
- Create: `tools/voice_camera_reply.py`
- Create: `tests/tools/test_voice_camera_reply.py`
- Modify: `services/voice/camera_reply.py`
- Modify: `tests/voice/test_camera_reply.py`

**Interfaces:**
- Produces CLI subcommands `status`, `probe` and `verify-marker`.
- Produces: `CameraReplyAcceptance.load(root, build_metadata) -> CameraReplyEvidence`.
- Writes only: `runtime/status/voice-camera-reply-acceptance.json` and `runtime/status/voice-camera-reply.json` as mode-0600 regular files under verified non-symlink parents.

- [x] **Step 1: Write acceptance-marker RED tests**

Accept this exact schema with no additional fields:

```json
{
  "schema_version": 1,
  "accepted": true,
  "upstream_commit": "0000000000000000000000000000000000000000",
  "patch_sha256": "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
  "binary_sha256": "bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",
  "protocol": "cs2+udp",
  "audio_codec": "opus"
}
```

The values must match `runtime/build/go2rtc.json`. Reject malformed JSON, wrong mode,
wrong owner, symlink in any parent or leaf, FIFO/socket, stale digest, alternate
protocol/codec and unknown fields. Never chmod, delete or repair invalid state.

- [x] **Step 2: Write operator-probe RED tests**

Require Darwin x86_64, a controlling TTY, exact installed app identity, current build
metadata, healthy source/media evidence and no active camera reply. Generate a one
second 880 Hz mono 16 kHz signed-16 WAV in a mode-0700 system temporary directory.

The only prompt is:

```text
camera_reply_tone_started=true
type_yes_if_tone_heard_from_camera=
```

Only exact `YES` from `/dev/tty` may confirm. Piped stdin, environment variables and
other text cannot confirm. After confirmation, rerun the existing source health check,
Dashboard health, Voice status and camera media inspection before atomically publishing
the marker. A failed check leaves the old marker absent or unchanged.

- [x] **Step 3: Run RED**

```bash
.venv-alpha/bin/python -m pytest -q tests/tools/test_voice_camera_reply.py tests/voice/test_camera_reply.py -k 'acceptance or probe or marker'
```

Expected: collection or attribute failure for the missing operator/marker interfaces.

- [x] **Step 4: Implement the bounded operator flow**

Use injected subprocess, TTY, clock and transport dependencies. Invoke the existing
source checker through its fixed repository interface; never accept a command override.
The probe must always issue its owned stop in `finally` when delivery started, then
remove its generated WAV and temporary directory.

Print only these allowlisted fields. The code value must be one of the spec constants
and every other value must be a lowercase boolean. A successful example is:

```text
camera_reply_code=CAMERA_REPLY_COMPLETE
camera_reply_ready=true
tone_started=true
tone_confirmed=true
source_healthy=true
voice_healthy=true
acceptance_marker_current=true
raw_audio_persisted=false
```

- [x] **Step 5: Run GREEN and commit**

```bash
.venv-alpha/bin/python -m pytest -q tests/tools/test_voice_camera_reply.py tests/voice/test_camera_reply.py
.venv-alpha/bin/python -m compileall -q tools/voice_camera_reply.py services/voice/camera_reply.py
git diff --check
git add tools/voice_camera_reply.py services/voice/camera_reply.py tests/tools/test_voice_camera_reply.py tests/voice/test_camera_reply.py
git commit -m "feat: gate Xiaomi camera speaker acceptance"
```

---

### Task 5: Select camera primary with pre-send-only i9 fallback

**Files:**
- Modify: `packages/contracts/settings.py`
- Modify: `config/settings.example.yaml`
- Modify: `services/voice/camera_reply.py`
- Modify: `services/voice/listen_only_runtime.py`
- Modify: `tests/contracts/test_voice_settings.py`
- Modify: `tests/voice/test_camera_reply.py`
- Modify: `tests/voice/test_listen_only_runtime.py`

**Interfaces:**
- Adds: `VoiceCareSettings.camera_reply_enabled: bool = False`.
- Produces: `CameraPreferredVoiceOutput(camera, fallback).speak_code(code, cancelled) -> bool`.
- Consumes: a current Task 4 acceptance marker and existing `FixedVoiceSynthesizer` fallback.

- [ ] **Step 1: Write settings RED tests**

Assert the example keeps `camera_reply_enabled: false`. Reject camera reply when
`listen_only_enabled` is false or full-care `enabled` is true. The setting alone never
proves readiness; a missing or stale marker must still build the i9-only path.

- [ ] **Step 2: Write output-selection RED tests**

Use a table that locks this policy:

| Camera result | delivery started | i9 fallback calls | final result |
| --- | ---: | ---: | ---: |
| disabled | false | 1 | fallback result |
| not proven | false | 1 | fallback result |
| unavailable | false | 1 | fallback result |
| busy | false | 0 | false |
| rejected | false | 0 | false |
| timeout | true | 0 | false |
| ambiguous | true | 0 | false |
| complete | true | 0 | true |

Assert cancellation before selection calls neither backend. Assert fallback failure
returns false and does not retry.

- [ ] **Step 3: Run RED**

```bash
.venv-alpha/bin/python -m pytest -q tests/contracts/test_voice_settings.py tests/voice/test_camera_reply.py tests/voice/test_listen_only_runtime.py -k 'camera_reply or fallback'
```

Expected: failures for the absent setting and selector.

- [ ] **Step 4: Implement settings and production composition**

In `build_listen_only_worker()`, construct the existing i9 synthesizer unconditionally.
Construct camera output only when the configuration flag is true and the Task 4 marker
matches the current installed build; otherwise pass a fixed not-proven camera result to
the selector. Keep endpoints, stream labels, timing and format values in the camera
module constants rather than settings.

- [ ] **Step 5: Run GREEN and commit**

```bash
.venv-alpha/bin/python -m pytest -q tests/contracts/test_voice_settings.py tests/voice/test_camera_reply.py tests/voice/test_listen_only_runtime.py
.venv-alpha/bin/python -m compileall -q packages/contracts/settings.py services/voice/camera_reply.py services/voice/listen_only_runtime.py
git diff --check
git add packages/contracts/settings.py config/settings.example.yaml services/voice/camera_reply.py services/voice/listen_only_runtime.py tests/contracts/test_voice_settings.py tests/voice/test_camera_reply.py tests/voice/test_listen_only_runtime.py
git commit -m "feat: prefer proven camera Voice replies"
```

---

### Task 6: Preserve wake semantics and close camera-echo loops

**Files:**
- Modify: `services/voice/listen_only.py`
- Modify: `services/voice/listen_only_runtime.py`
- Modify: `tests/voice/test_listen_only.py`
- Modify: `tests/voice/test_listen_only_runtime.py`

**Interfaces:**
- Preserves: `ListenOnlyController.handle()`, `on_speech_started()`, `expire()` and `reset()`.
- Consumes: the unchanged `Synthesizer.speak_code()` protocol and existing `PlaybackDucker`.

- [ ] **Step 1: Write echo and recovery RED tests**

Inject synthetic utterances matching `我在，请说。`, `我听到了。`, their punctuation-
free ASR forms and the two replies followed by valid care words. During playback and
the guard, assert the worker sends none of them to ASR. After resume, assert reply text
without `小小` is ignored and cannot arm, extend a deadline or generate output.

For complete, pre-send fallback, busy, rejected, timeout, ambiguous, cancellation and
exception cases, assert:

- capture is resumed exactly once;
- VAD and collector are reset;
- the controller is idle unless a successfully delivered standalone wake intentionally
  opened the existing eight-second armed window;
- no output call overlaps another;
- the worker remains runnable on the next synthetic frame.

- [ ] **Step 2: Run RED**

```bash
.venv-alpha/bin/python -m pytest -q tests/voice/test_listen_only.py tests/voice/test_listen_only_runtime.py -k 'echo or camera or output'
```

Expected: at least the camera-result recovery matrix fails before the runtime owns the
new output lifecycle.

- [ ] **Step 3: Implement only the required state cleanup**

Keep the current exact wake classifier, closed feeding grammar, reply phrases and
eight-second deadline unchanged. Route camera results through the existing boolean
synthesizer boundary, and ensure every false or exception path calls the same controller
reset already used by i9 output failure. Do not add transcript matching as the primary
echo guard; the input ducker and state reset remain authoritative.

- [ ] **Step 4: Run Voice GREEN and commit**

```bash
.venv-alpha/bin/python -m pytest -q tests/voice/test_camera_reply.py tests/voice/test_tts.py tests/voice/test_listen_only.py tests/voice/test_listen_only_runtime.py
make alpha-voice-test
.venv-alpha/bin/python -m compileall -q services/voice
git diff --check
git add services/voice/listen_only.py services/voice/listen_only_runtime.py tests/voice/test_listen_only.py tests/voice/test_listen_only_runtime.py
git commit -m "fix: prevent camera reply echo loops"
```

---

### Task 7: Add side-effect-free commands, installed checks and runbook

**Files:**
- Modify: `Makefile`
- Modify: `tools/test_guardian.sh`
- Modify: `tests/deploy/test_alpha_commands.py`
- Modify: `tests/deploy/test_voice_worker_deploy.py`
- Modify: `tests/deploy/test_go2rtc_ci.py`
- Modify: `docs/runbooks/XIAOMI_CS2_MACOS_TROUBLESHOOTING.md`
- Modify: `README.md`

**Interfaces:**
- Produces: `make alpha-voice-camera-test`, `make alpha-voice-camera-status` and `make alpha-voice-camera-probe`.
- Extends: the installed Guardian artifact/provenance checks without operating the speaker.

- [ ] **Step 1: Write Make/deployment RED tests**

Require:

```make
alpha-voice-camera-test:
	@$(PYTHON) -m pytest -q tests/voice/test_camera_reply.py tests/tools/test_voice_camera_reply.py

alpha-voice-camera-status:
	@$(PYTHON) tools/voice_camera_reply.py status

alpha-voice-camera-probe:
	@$(PYTHON) tools/voice_camera_reply.py probe
```

Assert `alpha-voice-camera-test` contains no live URL, `curl`, real source mutation or
camera operation. Assert only the probe target can play the tone and it requires a TTY.
Assert Guardian automatic acceptance checks patch, binary, test provenance and marker
state but does not invoke the probe or synthesize a reply.

- [ ] **Step 2: Run deployment RED**

```bash
.venv-alpha/bin/python -m pytest -q tests/deploy/test_alpha_commands.py tests/deploy/test_voice_worker_deploy.py tests/deploy/test_go2rtc_ci.py -k 'camera or go2rtc or voice'
```

Expected: failures for missing Make targets and installed checks.

- [ ] **Step 3: Add commands and operator documentation**

Document this exact safe order:

```bash
make alpha-source-check
make alpha-voice-listen-status
make alpha-go2rtc-info
make alpha-voice-camera-status
make alpha-voice-camera-probe
make alpha-source-check
make alpha-voice-listen-status
```

State that probe emits a generated tone, requires an adult at the camera, never records
audio, and does not enable production. Document that activation requires the valid
marker plus private `camera_reply_enabled: true`, followed by a Voice-only restart.
Document Voice-only rollback by restoring the flag to false and restarting only Voice;
go2rtc rollback remains a separate existing command if the protocol build itself fails.

- [ ] **Step 4: Run documentation and deployment GREEN**

```bash
.venv-alpha/bin/python -m pytest -q tests/deploy/test_alpha_commands.py tests/deploy/test_voice_worker_deploy.py tests/deploy/test_go2rtc_ci.py
make -n alpha-voice-camera-test
make -n alpha-voice-camera-status
make -n alpha-voice-camera-probe
bash -n tools/test_guardian.sh
git diff --check
```

- [ ] **Step 5: Run the full software and privacy gate**

```bash
make alpha-voice-test
make alpha-voice-camera-test
.venv-alpha/bin/python -m pytest -q
node --test tests/frontend/*.test.mjs
.venv-alpha/bin/python -m compileall -q packages services tools
git diff --check
```

Scan the tracked diff for credentials, private addresses, household media/audio,
SQLite files, generated settings, runtime paths and unrestricted speaker/go2rtc inputs.

- [ ] **Step 6: Commit Task 7**

```bash
git add Makefile tools/test_guardian.sh tests/deploy/test_alpha_commands.py tests/deploy/test_voice_worker_deploy.py tests/deploy/test_go2rtc_ci.py docs/runbooks/XIAOMI_CS2_MACOS_TROUBLESHOOTING.md README.md
git commit -m "docs: add Xiaomi camera reply operations"
```

---

### Task 8: Run installed i9 gates and record the V3 checkpoint

**Files:**
- Modify after evidence: `docs/CHECKPOINT.md`
- Modify after evidence: `docs/STATUS.md`
- Modify after evidence: `docs/NEXT.md`
- Modify after evidence: `SUMMARY.md`
- Modify: `docs/superpowers/plans/2026-08-26-xiaomi-camera-reply.md`

**Interfaces:**
- Consumes: the exact Task 1-7 implementation head and supervised Task 4 operator gate.
- Produces: aggregate V3A-V3E evidence and the next ordered project stage.

- [ ] **Step 1: Verify the installed environment before mutation**

```bash
uname -srm
make alpha-status
make alpha-source-check
make alpha-voice-listen-status
make alpha-go2rtc-info
make alpha-voice-camera-status
```

Require Darwin x86_64, current source PASS, Voice healthy, one exact go2rtc listener
and matching pinned metadata. Stop on a first stable blocker; do not restart the stack.

- [ ] **Step 2: Rebuild and verify only the pinned go2rtc component**

```bash
make alpha-go2rtc-rebuild
make alpha-go2rtc-restart
make alpha-source-check
make alpha-voice-v0-probe
make alpha-voice-camera-test
```

Require source H.265, incoming Opus, positive bytes, stable app identity, Voice V0 PASS
and all camera software tests. If any gate fails, use the existing go2rtc-only rollback,
then re-run source and Voice checks. Do not touch the camera URI or private settings.

- [ ] **Step 3: Run the supervised tone gate**

```bash
make alpha-voice-camera-probe
```

An adult confirms exact `YES` only after hearing the generated tone from the camera.
The command must then pass its post-health checks and publish a current marker. A tone
not heard, uncertain origin, duplicate playback or health regression is a FAIL.

- [ ] **Step 4: Enable the private flag and restart Voice only**

Set `voice_care.camera_reply_enabled: true` only in the ignored installed settings,
then run:

```bash
make alpha-voice-listen-stop
make alpha-voice-listen-start
make alpha-voice-listen-status
make alpha-voice-camera-status
make alpha-source-check
```

Require `CAMERA_REPLY_READY`, healthy listen-only Voice and unchanged source health.

- [ ] **Step 5: Complete V3E supervised interactions**

Record aggregate counts only: at least 5 standalone wakes, 3 wake-plus-follow-up
dialogues, 3 silent timeouts and 5 non-wake controls. Confirm both fixed replies come
from the camera, with zero duplicate replies, self-triggers, overlaps or stuck armed
states. Re-run source, Dashboard, Guardian, gauge, environment and Voice status after
the interactions, and confirm Mi Home and microSD remain available.

- [ ] **Step 6: Run the final exact-head software gate**

```bash
make alpha-guardian-test
make alpha-voice-test
make alpha-voice-camera-test
.venv-alpha/bin/python -m pytest -q
node --test tests/frontend/*.test.mjs
git diff --check
```

This gate proves software and installed component contracts only. It does not replace
the supervised hearing/interaction evidence or the final 72-hour release gate.

- [ ] **Step 7: Record the checkpoint and commit**

Check V3A-V3E in this plan. Record exact implementation HEAD, fresh counts and only
aggregate device results. Mark Camera Reply complete and P5 eligible only if P4 and
every other V1 prerequisite are also complete; otherwise retain the actual first
pending prerequisite.

```bash
git add docs/superpowers/plans/2026-08-26-xiaomi-camera-reply.md docs/CHECKPOINT.md docs/STATUS.md docs/NEXT.md SUMMARY.md
git commit -m "docs: record Xiaomi camera reply acceptance"
```

Do not push, merge, tag or modify `main` without a separate explicit instruction.
