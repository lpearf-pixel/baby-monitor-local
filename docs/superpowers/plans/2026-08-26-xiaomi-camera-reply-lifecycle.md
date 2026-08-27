# Xiaomi Camera Reply Lifecycle Repair Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use
> `superpowers:subagent-driven-development` or `superpowers:executing-plans` to
> implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.
>
> **Status:** Software Tasks 1–6 complete at
> `e66302ef1ab448705dc05d03086d52bf69f0e124`; Task 7 stopped closed at D2.
> The 2026-08-27 transport-auto diagnostic amendment is approved for planning;
> Tasks 8–14 are not started and Task 15 real playback is not authorized.

**Goal:** Preserve the completed lifecycle fixes, diagnose the remaining D2 shared-source
timeout with `transport=auto`, and make video, camera microphone, AI reply and future
browser talkback independently verifiable without breaking the single Xiaomi producer.

**Architecture:** Retain the pinned post-login dispatcher, generation-owned speaker
session and exactly-once settlement. Add a redacted macOS/media preflight, observe rather
than force the negotiated CS2 transport, bind acceptance to one protocol and producer
generation, and diagnose the remaining timeout around one long-lived external producer.
Keep Camera Reply disabled; browser talkback remains a later independent specification.

**Spec:**
`docs/superpowers/specs/2026-08-26-xiaomi-camera-reply-lifecycle-design.md`

## Global Constraints

- Work only on the explicitly approved feature branch and exact pinned upstream commit
  `b465651a94c1f637d566a8c660b4fad102b35153`.
- Keep the source configuration at `transport=auto`. Do not force UDP or TCP, upgrade
  go2rtc, add a second connection, emit motor commands, modify camera settings or
  restart the full Alpha stack.
- Do not enable Camera Reply, publish an acceptance marker, install a candidate, call
  the real loopback service or play camera audio during Tasks 1–6.
- Tests use only synthetic command frames, RTP packets and generated media.
- Preserve the fixed semantic reply vocabulary and the accepted i9-speaker behavior.
- Add exact upstream paths and numstat to `ALLOWED_PATCH_CHANGES`; never allowlist an
  upstream directory.
- Every behavior change follows observed RED, minimal GREEN and focused rerun. A test
  failure is diagnosed, not weakened.
- No payload, audio, transcript, URL, address, credential, exception text, runtime
  settings or local deployment path enters tracked files or logs.
- No push, PR, merge or protected-branch change without separate approval.

## Evidence checkpoint — complete

- [x] Fixed upstream `TestRepeatedSpeakerResponsesDoNotCloseMediaChannel` RED:
  `cs2: pop buffer is full`, followed by shared media failure.
- [x] Five speaker lifecycle RED tests: response not consumed, overlap accepted,
  post-stop write accepted, first write error lost, 20 pending responses after 20
  cycles.
- [x] Four Streams RED tests: no empty-stop settlement, lost stop failure, no natural
  settlement, no exactly-once cancel/natural settlement.
- [x] Root-cause decision: `H1_H2_CONFIRMED`; H3 confirmed independently.

These temporary RED fixtures are evidence, not shipped implementation. Task 1 first
recreates them inside the audited patch/test pipeline and observes the same failures.

---

### Task 1: Make the lifecycle RED suite reproducible in the pinned patch pipeline

**Files:**
- Modify: `tests/monitoring/test_go2rtc_build.py`
- Modify: `packages/monitoring/go2rtc_build.py`
- Modify: `tools/go2rtc_build.py`
- Modify later in this plan: `patches/go2rtc-macos-hybrid-hd.patch`

**Codex can:** build synthetic fixed-upstream fixtures, run Go/Python tests and update
the exact build gate.

**Human required:** none.

- [x] Extend the synthetic upstream repository fixture with the exact current
  `client.go`, `backchannel.go`, `producer.go`, `cs2/conn.go` and `streams/play.go`
  preconditions needed by the lifecycle patch. Reject any unexpected upstream text.
- [x] Add repository tests requiring the nine named Go lifecycle tests and their exact
  fixed package test commands before `go build`.
- [x] Recreate the test-only upstream patch in a pristine temporary clone and run:

  ```bash
  go test ./pkg/xiaomi/miss/cs2 -run TestRepeatedSpeakerResponsesDoNotCloseMediaChannel -count=1
  go test ./pkg/xiaomi/miss -run 'TestSpeakerLifecycle|TestRepeatedSpeakerLifecycle' -count=1
  go test ./internal/streams -run 'TestPlayEmpty|TestNaturalSourceEnd|TestCancelAndNaturalEnd' -count=1
  ```

- [x] Record the expected REDs without retaining the temporary clone in Git.
- [x] Run the repository focused RED:

  ```bash
  .venv-alpha/bin/python -m pytest -q tests/monitoring/test_go2rtc_build.py
  ```

**Acceptance:** every test fails for its named old behavior, not from compilation,
network, camera access, missing dependency or a mirrored mock.

**Next:** implement only the command dispatcher.

---

### Task 2: Add the single post-login command-response dispatcher

**Upstream paths in tracked patch:**
- Modify: `pkg/xiaomi/miss/client.go`
- Modify if required by the smallest safe boundary: `pkg/xiaomi/miss/cs2/conn.go`
- Add/modify corresponding `*_test.go`

**Codex can:** implement and test the fixed dispatcher with synthetic encrypted frames.

**Human required:** none.

- [x] RED: require the 11th speaker response not to close incoming media; require one
  accepted response per waiter; require unknown, duplicate, malformed and connection-
  close cases to settle with fixed failures and no raw output.
- [x] Implement one post-login goroutine as the sole `ReadCommand` consumer. Register
  a waiter before sending its request, use fixed capacities/timeouts and settle all
  waiters on connection close.
- [x] Drain known unawaited responses without unbounded storage. Unknown or malformed
  input disables Camera Reply but does not intentionally stop incoming media.
- [x] GREEN:

  ```bash
  go test ./pkg/xiaomi/miss/cs2 -count=1
  go test ./pkg/xiaomi/miss -run 'Command|SpeakerResponse' -count=1
  ```

**Acceptance:** more than the old capacity can be handled with media continuity;
pending response count returns to zero and only fixed aggregate diagnostics exist.

**Next:** implement generation-owned speaker state.

---

### Task 3: Implement symmetric, generation-owned speaker lifecycle

**Upstream paths in tracked patch:**
- Modify: `pkg/xiaomi/miss/client.go`
- Modify: `pkg/xiaomi/miss/backchannel.go`
- Modify: `pkg/xiaomi/miss/producer.go`
- Add/modify corresponding `*_test.go`

**Codex can:** implement the state machine and 20-cycle synthetic gate.

**Human required:** none.

- [x] RED/GREEN `TestSpeakerLifecycleStartsAndStopsExactlyOnce`: one request, one
  accepted response and one stop transport ACK.
- [x] RED/GREEN `TestSpeakerLifecycleRejectsOverlappingStart`: no second command and a
  stable busy failure.
- [x] RED/GREEN `TestSpeakerLifecycleStopsWritesAfterStop`: stop marks the generation
  non-writable before the stop command and stale handlers cannot write into a newer
  generation.
- [x] RED/GREEN `TestSpeakerLifecycleSurfacesFirstWriteError`: preserve the first
  channel-3 failure through Producer settlement.
- [x] RED/GREEN `TestRepeatedSpeakerLifecycleLeavesNoActiveGeneration`: at least 20
  cycles with start/response/stop `20/20/20`, zero pending responses, zero residual
  sender and zero active generation.
- [x] Remove the unconditional one-second sleep only after the response-gated readiness
  test is GREEN.
- [x] Prove stop idempotency and failure stickiness under concurrent write/stop races.
- [x] Run:

  ```bash
  go test ./pkg/xiaomi/miss -count=1
  go test -race ./pkg/xiaomi/miss -run 'SpeakerLifecycle' -count=1
  ```

**Acceptance:** all state transitions are bounded; no write occurs after settlement;
the shared Producer incoming media connection is not stopped as normal cleanup.

**Next:** connect that settlement to Streams.

---

### Task 4: Make Streams stop and natural end settle exactly once

**Upstream paths in tracked patch:**
- Modify: `internal/streams/play.go`
- Modify only if required for error propagation: `internal/streams/producer.go`
- Add/modify corresponding `*_test.go`

**Codex can:** implement the optional settlement interface and concurrency tests.

**Human required:** none.

- [x] RED/GREEN `TestPlayEmptySettlesBackchannelBeforeSuccess`.
- [x] RED/GREEN `TestPlayEmptyPropagatesBackchannelStopFailure`.
- [x] RED/GREEN `TestNaturalSourceEndSettlesBackchannelOnce`.
- [x] RED/GREEN `TestCancelAndNaturalEndDoNotDoubleStop`.
- [x] Add cancellation, source-start failure, source-error and settlement-timeout cases.
- [x] Keep one playback-generation result until the owning empty-source stop observes
  it; do not lose a natural-end failure.
- [x] Ensure the optional interface does not alter non-Xiaomi consumers.
- [x] Run:

  ```bash
  go test ./internal/streams -count=1
  go test -race ./internal/streams -run 'PlayEmpty|NaturalSourceEnd|CancelAndNaturalEnd' -count=1
  ```

**Acceptance:** every terminal path invokes one settlement; explicit HTTP stop returns
only after the bounded result and propagates failures as non-success.

**Next:** integrate patch provenance and Python completion semantics.

---

### Task 5: Lock patch scope, diagnostics and Python fail-closed completion

**Files:**
- Modify: `patches/go2rtc-macos-hybrid-hd.patch`
- Modify: `packages/monitoring/go2rtc_build.py`
- Modify: `tools/go2rtc_build.py`
- Modify: `tests/monitoring/test_go2rtc_build.py`
- Modify: `services/voice/camera_reply.py`
- Modify: `tests/voice/test_camera_reply.py`
- Modify if required by CLI behavior: `tools/voice_camera_reply.py`
- Modify corresponding tool tests

**Codex can:** finalize the exact patch, provenance gate and fake-loopback Python tests.

**Human required:** none.

- [x] Generate the smallest upstream diff and set the exact path/numstat allowlist.
  Verify old preconditions before apply and new postconditions after apply.
- [x] Run all lifecycle Go packages before build. A missing test, altered upstream file,
  package failure or unexpected diff returns a stable build error.
- [x] Invalidate the old acceptance marker through the changed patch digest. Do not
  publish a replacement marker.
- [x] Update fake loopback tests so HTTP stop failure, timeout or malformed response
  can never return `CAMERA_REPLY_COMPLETE`; preserve no-fallback-after-send behavior.
- [x] Add only the approved fixed aggregate diagnostics and redaction tests.
- [x] Run:

  ```bash
  .venv-alpha/bin/python -m pytest -q tests/monitoring/test_go2rtc_build.py
  .venv-alpha/bin/python -m pytest -q tests/voice/test_camera_reply.py tests/tools/test_voice_camera_reply.py
  make alpha-voice-camera-test
  ```

**Acceptance:** pinned build provenance includes every lifecycle test; Python completion
requires successful protocol settlement; Camera Reply remains disabled.

**Next:** run the full software gate and independent review.

---

### Task 6: Full software verification, review and handoff

**Files:**
- Modify: lifecycle spec/plan status
- Modify minimally: `SUMMARY.md`, `docs/STATUS.md`, `docs/CHECKPOINT.md`, `docs/NEXT.md`

**Codex can:** run software gates, inspect the final diff, obtain code review and commit
approved focused slices.

**Human required:** none unless a review finding changes the approved architecture.

- [x] Run focused upstream Go packages, race tests, patch build tests, Camera Reply
  tests and Voice tests.
- [x] Run:

  ```bash
  make alpha-voice-test
  .venv-alpha/bin/python -m compileall -q packages services tools
  .venv-alpha/bin/python -m pytest -q
  node --test tests/frontend/*.test.mjs
  git diff --check
  ```

- [x] Validate changed shell with `bash -n`, Make entries with `make -n`, and scan the
  tracked diff for secrets, private network literals, media, transcripts, SQLite,
  runtime settings and local paths.
- [x] Request an independent review of concurrency, dispatcher ownership, settlement
  error propagation, patch provenance and privacy. Resolve every Critical/Important
  finding with RED/GREEN evidence.
- [x] Update the plan and handoff documents with exact commits and fresh counts.

**Acceptance:** all software gates pass from the committed tree; tracked worktree is
clean; no real camera action occurred; report explicitly says software does not prove
the camera issue solved.

**Execution evidence (2026-08-27):** exact pinned patch apply and three focused Go
packages plus their race gates passed; repository focused 106/106, Voice 431/431,
frontend 73/73 and full Python 1648/1648 passed. Independent review concluded
0 Critical / 0 Important after two fix rounds. No camera, installed service, household
audio or acceptance marker was used.

**Next:** stop and request separate authorization for Task 7.

---

### Task 7: Supervised installed/device gates — stopped at D2

**Status:** authorized and executed with an adult at the camera. D0 and D1 passed. D2
failed closed on its third tone (fourth cumulative interaction) when the shared Xiaomi
CS2 UDP media source timed out and reconnected at generation 0. D3/D4 were not run;
Camera Reply remains disabled. The exact stale D1 marker was removed; `59a8ab4` now
invalidates prior acceptance before any new probe and installed status is NOT_PROVEN.

Follow D0–D4 from the lifecycle review. Start with Camera Reply disabled and verify the
source, i9 Voice output, Dashboard, Mi Home and microSD path. Install only the reviewed
candidate, then progress 1, 3 and 6 short synthetic interactions before the complete
Voice matrix. Stop immediately on movement, timeout, EOF, ambiguity, residual sender
or duplicate response.

The human confirmed every attempted tone was audible and caused no camera movement.
The D2 software stop line still controls: no automatic retry, D3 or D4. Forcing TCP or
UDP, or adding a second connection, is outside this plan and requires a new approved
design. Keeping `transport=auto` may legitimately observe either allowlisted protocol.

---

### Task 8: Add the side-effect-free macOS media preflight

**Files:**
- Create: `packages/monitoring/xiaomi_macos_preflight.py`
- Create: `tools/xiaomi_macos_preflight.py`
- Create: `tests/monitoring/test_xiaomi_macos_preflight.py`
- Create: `tests/tools/test_xiaomi_macos_preflight.py`
- Modify: `Makefile`
- Test: `tests/deploy/test_alpha_commands.py`

**Interfaces:**
- Produces:

  ```python
  @dataclass(frozen=True, slots=True)
  class MacOSMediaPreflight:
      code: Literal[
          "ready",
          "unsupported",
          "app_identity_invalid",
          "launchd_owner_invalid",
          "listener_owner_invalid",
          "local_network_blocked",
          "local_network_unknown",
      ]
      app_identity_ready: bool
      launchd_owner_count: int
      listener_owned_by_launchd: bool
      local_network_state: Literal["available", "blocked", "unknown"]

  def run_macos_media_preflight(
      root: Path, *, runner: BoundedRunner
  ) -> MacOSMediaPreflight: ...
  ```

- Consumes the existing fixed app requirement from
  `packages.monitoring.go2rtc_build.GO2RTC_DESIGNATED_REQUIREMENT` and the installed
  launchd label `com.babymonitor.go2rtc`.

**Codex can:** implement and test the parser/runner with synthetic command output, then
run the real read-only preflight from the logged-in i9 context.

**Human required:** only if macOS reports a blocked/unknown Local Network state that
requires System Settings interaction. No password prompt is part of the automatic gate.

- [ ] **Step 1: Write RED tests for identity and ownership.** Require the exact signed
  app, reject `cdhash`, reject zero/two launchd owners, and require the launchd PID to
  own the loopback listener. Fake output contains no real path or PID.
- [ ] **Step 2: Write RED tests for permission uncertainty.** A firewall query failure
  must produce `local_network_unknown`, never `ready`; a blocked app must produce
  `local_network_blocked`.
- [ ] **Step 3: Run RED.**

  ```bash
  .venv-alpha/bin/python -m pytest -q \
    tests/monitoring/test_xiaomi_macos_preflight.py \
    tests/tools/test_xiaomi_macos_preflight.py
  ```

  Expected: collection or behavior failures because the preflight does not exist.
- [ ] **Step 4: Implement the minimal bounded runner and CLI.** Use fixed argv only,
  `shell=False`, ten-second maximum commands, `/dev/null` stdin and closed result codes.
  Do not print command output, executable paths, PIDs or exception text.
- [ ] **Step 5: Add `make alpha-xiaomi-media-preflight`.** It is read-only and never
  restarts, signs, registers, unblocks or opens an app.
- [ ] **Step 6: Run GREEN and static gates.**

  ```bash
  .venv-alpha/bin/python -m pytest -q \
    tests/monitoring/test_xiaomi_macos_preflight.py \
    tests/tools/test_xiaomi_macos_preflight.py \
    tests/deploy/test_alpha_commands.py
  .venv-alpha/bin/python -m py_compile \
    packages/monitoring/xiaomi_macos_preflight.py \
    tools/xiaomi_macos_preflight.py
  make -n alpha-xiaomi-media-preflight
  git diff --check
  ```
- [ ] **Step 7: Commit the focused slice.**

  ```bash
  git add Makefile packages/monitoring/xiaomi_macos_preflight.py \
    tools/xiaomi_macos_preflight.py \
    tests/monitoring/test_xiaomi_macos_preflight.py \
    tests/tools/test_xiaomi_macos_preflight.py \
    tests/deploy/test_alpha_commands.py
  git commit -m "feat: add redacted Xiaomi macOS preflight"
  ```

**Acceptance:** only `ready` permits later installed diagnostics. `unknown` is a stop,
not a warning. Software tests do not query the real firewall or launchd domain.

**Next:** prove configuration intent and the single external producer.

---

### Task 9: Add the transport-auto single-producer diagnostic

**Files:**
- Create: `packages/monitoring/xiaomi_media_diagnostic.py`
- Create: `tools/xiaomi_media_diagnostic.py`
- Create: `tests/monitoring/test_xiaomi_media_diagnostic.py`
- Create: `tests/tools/test_xiaomi_media_diagnostic.py`
- Modify: `Makefile`
- Modify: `tests/deploy/test_alpha_commands.py`

**Interfaces:**
- Produces:

  ```python
  NegotiatedProtocol = Literal["cs2+udp", "cs2+tcp", "unavailable"]

  @dataclass(frozen=True, slots=True)
  class XiaomiMediaSnapshot:
      configured_transport: Literal["auto"]
      producer_count: int
      negotiated_protocol: NegotiatedProtocol
      producer_generation: int
      consumer_count: int
      video_media_ready: bool
      camera_audio_media_ready: bool
      speaker_media_ready: bool
      video_bytes_increased: bool
      audio_bytes_increased: bool
      producer_replaced: bool

  def validate_single_source_config(payload: bytes) -> None: ...
  def parse_source_observation(payload: bytes) -> _SourceObservation: ...
  def compare_source_observations(
      before: _SourceObservation, after: _SourceObservation
  ) -> XiaomiMediaSnapshot: ...
  ```

  `_SourceObservation` retains the ephemeral producer ID only in memory so comparison
  can derive `producer_replaced`; the public snapshot and CLI never expose it.

- Consumes only the ignored `runtime/go2rtc.yaml` and fixed loopback
  `/api/streams?src=source`. Source expressions and API bodies stay in memory.

**Codex can:** implement the pure parsers, fake HTTP tests and a bounded read-only i9
snapshot. No camera settings or connections are changed.

**Human required:** none while the current producer is healthy.

- [ ] **Step 1: Write RED configuration tests.** A valid config has exactly one Xiaomi
  expression named `source`, no explicit `transport` query and only aliases derived
  from `source`. Reject explicit UDP/TCP, a second Xiaomi URI and a direct Xiaomi alias.
- [ ] **Step 2: Write RED API tests.** Accept exactly one producer with either allowlisted
  negotiated protocol; reject zero/two producers, malformed media, unknown protocol
  and a replacement between snapshots. Closed idle lifecycle generation 0 is valid;
  active Camera Reply generation 0 is rejected in Task 10.
- [ ] **Step 3: Write RED privacy tests.** CLI output must contain only the approved
  aggregate keys and must not contain fixture URI, address, account, DID, IDs or raw
  media descriptions.
- [ ] **Step 4: Run RED.**

  ```bash
  .venv-alpha/bin/python -m pytest -q \
    tests/monitoring/test_xiaomi_media_diagnostic.py \
    tests/tools/test_xiaomi_media_diagnostic.py
  ```
- [ ] **Step 5: Implement the pure parser and bounded two-snapshot collector.** The
  collector uses a five-second maximum interval, a 1 MiB response cap, proxy-free
  loopback HTTP and no persistence.
- [ ] **Step 6: Add `make alpha-xiaomi-media-diagnostic` and run GREEN.**

  ```bash
  .venv-alpha/bin/python -m pytest -q \
    tests/monitoring/test_xiaomi_media_diagnostic.py \
    tests/tools/test_xiaomi_media_diagnostic.py \
    tests/monitoring/test_alpha_quality.py \
    tests/deploy/test_alpha_commands.py
  make -n alpha-xiaomi-media-diagnostic
  git diff --check
  ```
- [ ] **Step 7: Commit the focused slice.**

  ```bash
  git add Makefile packages/monitoring/xiaomi_media_diagnostic.py \
    tools/xiaomi_media_diagnostic.py \
    tests/monitoring/test_xiaomi_media_diagnostic.py \
    tests/tools/test_xiaomi_media_diagnostic.py \
    tests/deploy/test_alpha_commands.py
  git commit -m "feat: diagnose the shared Xiaomi producer"
  ```

**Acceptance:** the installed result can say `configured_transport=auto`, exactly one
producer and the observed protocol without printing private connection data. Video byte
growth does not imply audio or speaker readiness.

**Next:** make Camera Reply acceptance protocol-neutral and generation-bound.

---

### Task 10: Bind Camera Reply to auto-negotiated protocol and marker schema v2

**Files:**
- Modify: `services/voice/camera_reply.py`
- Modify: `tools/voice_camera_reply.py`
- Modify: `tests/voice/test_camera_reply.py`
- Modify: `tests/tools/test_voice_camera_reply.py`

**Interfaces:**
- Replace the single `_PROTOCOL` value with:

  ```python
  _TRANSPORT_MODE = "auto"
  _NEGOTIATED_PROTOCOLS = frozenset({"cs2+udp", "cs2+tcp"})

  @dataclass(frozen=True, slots=True)
  class CameraReplyEvidence:
      source_ready: bool
      video_ready: bool
      incoming_audio_ready: bool
      sendonly_audio_ready: bool
      protocol: Literal["cs2+udp", "cs2+tcp"]
      video_codec: str
      incoming_audio_codec: str
      sendonly_audio_codec: str
      speaker_state: str = "closed"
      speaker_session_generation: int = 0
      speaker_start_requests: int = 0
      speaker_start_responses: int = 0
      speaker_stop_commands: int = 0
      speaker_write_failures: int = 0
      speaker_stop_failures: int = 0
      pending_command_responses: int = 0
      residual_sender_count: int = 0
      last_failure_stage: str = "none"
      producer_generation: int = 0

  CameraReplyAcceptance.publish(
      root: Path,
      build_metadata: BuildMetadata,
      evidence: CameraReplyEvidence,
  ) -> bool
  ```

- Marker schema v2 contains only build identity, `transport_mode=auto` and the observed
  allowlisted protocol. Schema v1 is stale.

**Codex can:** implement all parser, marker and fake-loopback behavior without accessing
the installed API or camera.

**Human required:** none.

- [ ] **Step 1: RED source parsing.** Test one UDP and one TCP producer; test active
  internal playback in both producer orders. Reject unknown protocol, missing/nonzero
  generation violations, two external producers and protocol drift.
- [ ] **Step 2: RED start/stop ownership.** Start records protocol and nonzero generation;
  stop returns COMPLETE only for the same protocol and generation in closed state.
  Reconnect, generation zero or producer replacement returns AMBIGUOUS.
- [ ] **Step 3: RED marker v2.** Publish/load both allowlisted protocols, reject schema v1,
  explicit transport intent, protocol mismatch and current-build mismatch. Failed probes
  still invalidate prior acceptance before camera access.
- [ ] **Step 4: Run RED.**

  ```bash
  .venv-alpha/bin/python -m pytest -q \
    tests/voice/test_camera_reply.py \
    tests/tools/test_voice_camera_reply.py
  ```
- [ ] **Step 5: Implement the minimal parser, transport ownership and schema-v2 marker.**
  Do not alter the runtime Xiaomi URI, reply request or go2rtc process.
- [ ] **Step 6: Run GREEN and the fixed Camera Reply gate.**

  ```bash
  .venv-alpha/bin/python -m pytest -q \
    tests/voice/test_camera_reply.py \
    tests/tools/test_voice_camera_reply.py
  make alpha-voice-camera-test
  .venv-alpha/bin/python -m py_compile \
    services/voice/camera_reply.py tools/voice_camera_reply.py
  git diff --check
  ```
- [ ] **Step 7: Commit the focused slice.**

  ```bash
  git add services/voice/camera_reply.py tools/voice_camera_reply.py \
    tests/voice/test_camera_reply.py tests/tools/test_voice_camera_reply.py
  git commit -m "fix: bind camera replies to negotiated transport"
  ```

**Acceptance:** `transport=auto` stays unchanged; UDP and TCP are observed values. A
protocol/generation change during playback can never produce COMPLETE or READY.

**Next:** attempt a deterministic software reproduction of the remaining D2 boundary.

---

### Task 11: Reproduce or classify the remaining D2 producer timeout

**Files:**
- Modify test first: `patches/go2rtc-macos-hybrid-hd.patch`
- Modify only after an observed RED: the exact affected upstream file among
  `pkg/xiaomi/miss/client.go`, `pkg/xiaomi/miss/producer.go`,
  `pkg/xiaomi/miss/backchannel.go`, `pkg/xiaomi/miss/cs2/conn.go` or
  `internal/streams/play.go`
- Modify if the tracked patch changes: `packages/monitoring/go2rtc_build.py`
- Modify: `tools/go2rtc_build.py`
- Modify: `Makefile`
- Test: `tests/monitoring/test_go2rtc_build.py`
- Test: `tests/deploy/test_alpha_commands.py`

**Interfaces:**
- Preserve the existing `SpeakerSession`, `SettleBackchannel` and playback settlement
  interfaces. No second connection or transport selector is introduced.
- Produce one safe entry point:

  ```text
  make alpha-go2rtc-protocol-test
  ```

  It clones the exact pinned commit into a temporary directory, verifies/applies the
  tracked patch, runs focused and race Go tests, then exits without building, signing,
  installing, restarting or changing runtime state.
- New synthetic tests are named exactly:

  ```text
  TestRepeatedSpeakerLifecycleKeepsMediaReadable
  TestPlaybackSettlementDoesNotReplaceProducer
  TestReconnectBackoffDoesNotDuplicateWorkers
  TestReadTimeoutClassificationIsPayloadFree
  ```

**Codex can:** use only synthetic CS2 frames, generated RTP and fake clocks/connections.

**Human required:** none. This task must not replay the fourth interaction on hardware.

- [ ] **Step 1: Add RED-capable stress fixtures.** Keep a media reader active while six
  speaker generations run; inject delayed response, write failure, read deadline,
  cancel/natural-end race and connection close one at a time.
- [ ] **Step 2: Add the protocol-test CLI/Make entry under RED.** Tests require the exact
  clone/checkout/patch/focused/race argv and prove install/sign/restart functions are not
  called.
- [ ] **Step 3: Run the exact pinned-patch tests.**

  ```bash
  make alpha-go2rtc-protocol-test
  ```
- [ ] **Step 4: Record one decision before production changes.**
  `D2_CAUSE_CONFIRMED` requires a deterministic failure in the current patched code.
  If all fixtures pass, record `D2_BOUNDARY_HARDENED_CAUSE_UNPROVEN`, leave production
  Go unchanged and stop this task after the diagnostic evidence.
- [ ] **Step 5: If and only if RED exists, implement one minimal GREEN.** Modify only the
  exact layer that failed. Do not force transport, extend timeouts, add retries or add a
  connection as a workaround.
- [ ] **Step 6: Run focused and race GREEN.**

  ```bash
  make alpha-go2rtc-protocol-test
  .venv-alpha/bin/python -m pytest -q tests/monitoring/test_go2rtc_build.py
  .venv-alpha/bin/python -m pytest -q tests/deploy/test_alpha_commands.py
  make -n alpha-go2rtc-protocol-test
  git diff --check
  ```
- [ ] **Step 7: Commit only if tracked evidence or a minimal fix changed.**

  ```bash
  git add Makefile patches/go2rtc-macos-hybrid-hd.patch \
    packages/monitoring/go2rtc_build.py \
    tools/go2rtc_build.py tests/monitoring/test_go2rtc_build.py \
    tests/deploy/test_alpha_commands.py
  git commit -m "test: classify Xiaomi reply source timeout"
  ```

**Acceptance:** the result names confirmed evidence or explicitly preserves unknown
causality. Correlation with cumulative interaction 4 is never treated as a software RED.

**Next:** validate camera-microphone receive independently.

---

### Task 12: Gate camera microphone, Opus decode, VAD and ASR independently

**Files:**
- Modify: `services/audio/feasibility.py`
- Modify if evidence requires: `services/audio/source.py`
- Modify if evidence requires: `services/voice/audio_pump.py`
- Modify: `tools/voice_audio_probe.py`
- Test: `tests/audio/test_feasibility.py`
- Test: `tests/audio/test_source.py`
- Test: `tests/voice/test_audio_pump.py`
- Test: `tests/tools/test_voice_audio_probe.py`

**Interfaces:**
- Preserve `audio_analysis` as the only fixed loopback source.
- Produce aggregate stages:

  ```text
  camera_audio_media_available
  opus_48000_stereo_available
  pcm_decode_available
  vad_progression_available
  asr_runtime_available
  raw_audio_persisted=false
  ```

**Codex can:** run generated Opus software tests. A later read-only live probe may decode
and immediately discard PCM only from the real logged-in user context.

**Human required:** none for software. Spoken household accuracy remains a separate
supervised Voice gate and is not part of this task.

- [ ] **Step 1: RED the chain boundaries.** Video-only media, wrong codec/rate/channels,
  decoder EOF, stalled PCM, invalid VAD progression and unavailable ASR runtime must
  fail their own stages without changing the source or Voice worker.
- [ ] **Step 2: Run RED.**

  ```bash
  .venv-alpha/bin/python -m pytest -q \
    tests/audio/test_feasibility.py tests/audio/test_source.py \
    tests/voice/test_audio_pump.py tests/tools/test_voice_audio_probe.py
  ```
- [ ] **Step 3: Implement only evidence-backed corrections.** Keep PCM bounded in memory,
  use the fixed RTSP/TCP loopback decoder boundary, preserve source ownership and emit
  no recognized text.
- [ ] **Step 4: Run GREEN and Voice isolation.**

  ```bash
  .venv-alpha/bin/python -m pytest -q \
    tests/audio tests/voice/test_audio_pump.py \
    tests/tools/test_voice_audio_probe.py
  make alpha-voice-v0-test
  make alpha-voice-test
  git diff --check
  ```
- [ ] **Step 5: Commit the focused slice only if production changed.**

  ```bash
  git add services/audio/feasibility.py services/audio/source.py \
    services/voice/audio_pump.py tools/voice_audio_probe.py \
    tests/audio tests/voice/test_audio_pump.py \
    tests/tools/test_voice_audio_probe.py
  git commit -m "fix: isolate Xiaomi microphone readiness"
  ```

**Acceptance:** camera microphone readiness is independent of video, the optional audio
worker and Camera Reply. No household audio or transcript is persisted or printed.

**Next:** verify generated AI reply bytes and settlement without hardware playback.

---

### Task 13: Gate AI reply encoding and channel-3 delivery independently

**Files:**
- Modify if tests expose a defect: `services/voice/camera_reply.py`
- Modify if tests expose a defect: `services/voice/tts.py`
- Modify test/provenance patch: `patches/go2rtc-macos-hybrid-hd.patch`
- Test: `tests/voice/test_camera_reply.py`
- Test: `tests/voice/test_tts.py`
- Test: `tests/monitoring/test_go2rtc_build.py`

**Interfaces:**
- Input remains the existing fixed semantic reply codes; no text, URL, path or caller
  audio interface is added.
- The wire gate proves the negotiated send codec, 48 kHz stereo Opus compatibility,
  bounded frame timing, monotonically advancing channel-3 sequence, header at the header
  offset and encrypted payload at the payload offset.

**Codex can:** use generated tones, fixed reply fixtures and `net.Pipe`; it must not call
the installed loopback service.

**Human required:** none for software.

- [ ] **Step 1: RED each false-positive completion.** Reject sendonly metadata without
  bytes, zero payload, duplicate header, wrong sample rate/channels, sequence reuse,
  HTTP 2xx without same-generation closed settlement and producer replacement.
- [ ] **Step 2: Run RED.**

  ```bash
  .venv-alpha/bin/python -m pytest -q \
    tests/voice/test_camera_reply.py tests/voice/test_tts.py \
    tests/monitoring/test_go2rtc_build.py
  ```
- [ ] **Step 3: Implement only the minimal proven correction.** The existing
  `copy(req[offset+hdrSize:], payload)` fix and its test remain mandatory and are not
  duplicated in another layer.
- [ ] **Step 4: Run GREEN plus exact Go/race gates.**

  ```bash
  make alpha-voice-camera-test
  make alpha-go2rtc-protocol-test
  git diff --check
  ```
- [ ] **Step 5: Commit only changed files.**

  ```bash
  git add services/voice/camera_reply.py services/voice/tts.py \
    patches/go2rtc-macos-hybrid-hd.patch \
    tests/voice/test_camera_reply.py tests/voice/test_tts.py \
    tests/monitoring/test_go2rtc_build.py
  git commit -m "fix: prove Xiaomi AI reply delivery"
  ```

**Acceptance:** software proves bytes and lifecycle, not audibility. Camera Reply stays
disabled and no acceptance marker is published.

**Next:** run the full software/review checkpoint.

---

### Task 14: Full software gate, independent review and documentation checkpoint

**Files:**
- Modify status only after evidence: `SUMMARY.md`, `docs/STATUS.md`,
  `docs/CHECKPOINT.md`, `docs/NEXT.md`
- Modify status: this spec and plan

**Codex can:** run all software gates, resolve ordinary failures, review the tracked diff
and commit focused documentation. It may rebuild a temporary candidate but may not
install or restart it.

**Human required:** only if review discovers a material architecture conflict.

- [ ] **Step 1: Run focused Python and Go gates from the committed tree.**

  ```bash
  make alpha-xiaomi-media-preflight
  make alpha-xiaomi-media-diagnostic
  make alpha-go2rtc-protocol-test
  make alpha-voice-camera-test
  make alpha-voice-test
  .venv-alpha/bin/python -m pytest -q tests/monitoring/test_go2rtc_build.py
  ```

  The two installed diagnostic commands are run only after their software tests and
  remain read-only; an unknown macOS permission state stops installed diagnosis.
- [ ] **Step 2: Run repository verification.**

  ```bash
  .venv-alpha/bin/python -m compileall -q packages services tools
  .venv-alpha/bin/python -m pytest -q
  node --test tests/frontend/*.test.mjs
  bash -n tools/*.sh
  git diff --check
  ```
- [ ] **Step 3: Scan the final tracked diff.** Reject credentials, private addresses,
  Xiaomi URI/session data, keys, command payloads, audio, transcripts, runtime settings,
  SQLite and generated local artifacts.
- [ ] **Step 4: Review concurrency and ownership.** Confirm one dispatcher, one producer,
  protocol/generation binding, exactly-once settlement, no post-stop write, no duplicate
  worker and no full-stack restart path.
- [ ] **Step 5: Record one root-cause decision.** Use only
  `D2_CAUSE_CONFIRMED`, `D2_BOUNDARY_HARDENED_CAUSE_UNPROVEN` or
  `MACOS_PREFLIGHT_BLOCKED`; do not claim device success.
- [ ] **Step 6: Update handoff documents and commit.**

  ```bash
  git add SUMMARY.md docs/STATUS.md docs/CHECKPOINT.md docs/NEXT.md \
    docs/superpowers/specs/2026-08-26-xiaomi-camera-reply-lifecycle-design.md \
    docs/superpowers/plans/2026-08-26-xiaomi-camera-reply-lifecycle.md
  git commit -m "docs: record Xiaomi media diagnostic gate"
  ```

**Acceptance:** tracked worktree is clean, software review has no Critical/Important,
Camera Reply remains disabled, and documentation separates all four capability gates.

**Next:** stop. Task 15 requires new explicit real-device authorization.

---

### Task 15: Supervised real-device verification — not authorized

**Prerequisites:** Tasks 8–14 committed and reviewed; macOS preflight `ready`; one
producer; `transport=auto`; source and camera-microphone gates healthy; Camera Reply
disabled and marker absent; adult physically at the camera.

**Codex can after separate authorization:** run only the fixed generated reply workflow,
collect approved aggregate fields and stop on the first failure.

**Human required:** confirm audibility and absence of camera movement after every reply.

- [ ] D0: verify app identity, one launchd owner, source, camera microphone, Dashboard,
  Mi Home and microSD without playback.
- [ ] D1: one generated reply, then verify the same protocol/generation lifecycle,
  source bytes and microphone bytes.
- [ ] D2: from a clean lifecycle, run three cumulative replies with the same checks
  after each.
- [ ] D3: only if D2 passes, run six cumulative replies and the complete Voice matrix.
- [ ] Stop immediately on movement, timeout, EOF, protocol drift, producer replacement,
  generation zero, pending response, residual sender or ambiguous settlement.
- [ ] Publish schema-v2 acceptance only after the complete gate passes. Failure leaves
  Camera Reply disabled and invalidates prior acceptance.

**Browser talkback boundary:** no browser microphone test is part of Task 15. A future
specification must first define authenticated HTTPS, `getUserMedia`, same-origin WebRTC,
push-to-talk ownership, cancellation and privacy. It must reuse this same external
producer and pass its own supervised gate.

**Acceptance:** human and machine evidence agree for every stage; software metadata,
`sendonly OPUS` or HTTP success never substitutes for audibility and continuity.
