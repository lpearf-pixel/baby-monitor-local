# Xiaomi Camera Reply Lifecycle Repair Implementation Plan

> **Status:** Software Tasks 1–6 complete at
> `e66302ef1ab448705dc05d03086d52bf69f0e124`; Task 7 remains a separate
> real-device authorization and is not approved by the design.

**Goal:** Close the confirmed Xiaomi command-response, speaker-generation, write-error
and Streams-settlement defects without changing the pinned camera transport or breaking
the shared incoming source.

**Architecture:** Add one post-login command dispatcher, a generation-owned Xiaomi
speaker session, a narrow Producer settlement boundary and an exactly-once Streams
playback lifecycle. Keep Camera Reply disabled until software and later device gates
independently pass.

**Spec:**
`docs/superpowers/specs/2026-08-26-xiaomi-camera-reply-lifecycle-design.md`

## Global constraints

- Work only on the explicitly approved feature branch and exact pinned upstream commit
  `b465651a94c1f637d566a8c660b4fad102b35153`.
- Do not upgrade go2rtc, change `cs2+udp`, add a second connection, emit motor commands,
  modify camera settings or restart the full Alpha stack.
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

### Task 7: Supervised installed/device gates — not currently authorized

**Status:** software prerequisite complete; still blocked on separate explicit user
approval and an adult at the camera.

Follow D0–D4 from the lifecycle review. Start with Camera Reply disabled and verify the
source, i9 Voice output, Dashboard, Mi Home and microSD path. Install only the reviewed
candidate, then progress 1, 3 and 6 short synthetic interactions before the complete
Voice matrix. Stop immediately on movement, timeout, EOF, ambiguity, residual sender
or duplicate response.

This task requires the human to confirm audible playback and camera behavior. It is
not included in approval of the software design or plan.
