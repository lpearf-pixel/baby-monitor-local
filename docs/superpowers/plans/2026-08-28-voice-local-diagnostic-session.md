# Voice Local Diagnostic Session Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use
> `superpowers:subagent-driven-development` (recommended) or
> `superpowers:executing-plans` to implement this plan task-by-task. Steps use checkbox
> (`- [ ]`) syntax for tracking.

**Goal:** Add a disabled-by-default, bounded local diagnostic session that correlates
each existing listen-only utterance WAV with its Paraformer text and fixed pipeline
outcome without changing recognition behavior or the single Xiaomi producer.

**Architecture:** A new private diagnostic module validates an ignored runtime marker,
owns a two-record asynchronous writer and publishes no-replace WAV/JSON pairs under a
fixed private root. A single-call ASR tap keeps the current transcription in memory
until `ListenOnlyVoiceWorker` correlates it with the controller outcome. Fixed
start/status/stop commands control only the Voice worker; ordinary production remains
memory-only.

**Tech Stack:** Python 3.11, existing Pydantic settings, RIFF/WAVE, JSON, POSIX file
descriptors and permissions, macOS launchd/Make, pytest.

**Spec:**
`docs/superpowers/specs/2026-08-28-voice-local-diagnostic-session-design.md`

**Status:** Approved specification translated into an inline execution plan on
2026-08-28. Tasks 1–6 private artifacts, writer, worker integration, fixed lifecycle,
privacy governance and the full software/review gate are complete at business head
`fb7b17bd7ccae49f3d1ca50104045d49f329925e`; Task 7 supervised local diagnostic is
next and has not started.

## Global Constraints

- Work only on `codex/xiaomi-camera-reply-lifecycle-review` in the existing linked
  worktree. Preserve the installed root's untracked `Interactive` and `test.sh`.
- Commands below use the conventional `.venv-alpha/bin/python`. If the isolated
  worktree has no venv, use the already-installed Python 3.11 environment with a local
  `PYTHONPATH=.`/Make `PYTHON` override; never commit its absolute deployment path.
- Do not modify or restart go2rtc, Dashboard, visual, gauge, environment or Guardian.
- Do not enable Camera Reply, full-care Voice, signing, outbox or Baby Care writes.
- Do not change wake grammar, action registry, correction table, VAD, Paraformer,
  transport, producer lifecycle or fixed TTS phrases.
- Tests use generated PCM and synthetic text only. No test, diff, normal log, status,
  documentation, commit or chat output may contain household audio/transcript.
- The only production transcript sink is the explicitly active ignored private session.
  Without a valid current marker, no PCM or transcript is retained.
- The session owns fixed limits: 1,800 seconds, 50 complete utterances, 16,777,216
  complete bytes, 256 transcript code points, queue capacity 2 and settlement 5 seconds.
- Runtime parents/directories/files require current-user ownership, no symlinks and
  exact `0700`/`0600` modes. Reject FIFO/socket/device/hard-link and traversal targets.
- Use bounded waits and fixed error/status codes. Never print paths, session IDs,
  transcripts, raw exceptions or configuration values.
- Every behavior task follows observed RED, minimal GREEN, same focused rerun, diff
  review and a focused commit. Do not weaken a failing test.

## File Structure

- Create `services/voice/diagnostic.py`: marker/session validation, ASR tap, immutable
  record, bounded writer and WAV/JSON publication.
- Modify `services/voice/listen_only_runtime.py`: build the optional tap/writer and offer
  one correlated record after each controller result.
- Modify `services/voice/worker.py`: add only fixed aggregate diagnostic status keys.
- Create `tools/voice_diagnostic.py`: fixed start/status/stop CLI and Voice-only service
  adapter.
- Modify `Makefile`: three fixed diagnostic commands.
- Add `tests/voice/test_diagnostic.py` and adjacent runtime/worker/tool/deploy tests.
- Modify `AGENTS.md` and `docs/runbooks/VOICE_LISTEN_ONLY.md`: record the narrow explicit
  diagnostic exception and operating procedure.
- Update the owning plan, review log and handoff docs only after fresh evidence.

---

### Task 1: Lock the private session and artifact RED contracts

**Files:**
- Create: `tests/voice/test_diagnostic.py`
- Create: `services/voice/diagnostic.py`

**Interfaces:**
- Produces immutable `DiagnosticSession`, `DiagnosticRecord`, `DiagnosticSnapshot` and
  fixed constants used by later tasks.
- Produces `load_active_session(project_root: Path, now_epoch: float) -> DiagnosticSession | None`.
- Produces `publish_diagnostic_record(session, record) -> int` where the return value is
  the complete pair byte count.

- [x] **Step 1: Write constructor and limit RED tests**

  Require exact constants and reject mutable/invalid fields:

  ```python
  assert DIAGNOSTIC_LIFETIME_SECONDS == 1_800
  assert DIAGNOSTIC_MAX_UTTERANCES == 50
  assert DIAGNOSTIC_MAX_BYTES == 16_777_216
  assert DIAGNOSTIC_MAX_TRANSCRIPT_CODEPOINTS == 256
  assert DIAGNOSTIC_QUEUE_CAPACITY == 2
  assert DIAGNOSTIC_SETTLEMENT_SECONDS == 5.0
  ```

  A session ID must match `[0-9a-f]{32}` and record fields must use existing closed
  phase, ASR state, action, match-kind and outcome allowlists.

- [x] **Step 2: Write marker/storage RED tests**

  Create synthetic private trees and require `None` before any artifact read for:

  - absent, malformed, expired, future-created or incoherent marker;
  - wrong owner/mode, symlink parent/leaf, FIFO, socket and directory where a file is
    required;
  - session ID/path mismatch and count/byte exhaustion.

  Require a valid marker and matching manifest to return one immutable session without
  exposing its path in `repr` or errors.

- [x] **Step 3: Write WAV/event publication RED tests**

  Use generated 16 kHz mono signed 16-bit PCM. Require:

  ```python
  with wave.open(str(wav_path), "rb") as wav:
      assert wav.getframerate() == 16_000
      assert wav.getnchannels() == 1
      assert wav.getsampwidth() == 2
      assert wav.readframes(wav.getnframes()) == pcm
  ```

  Require event correlation, JSON escaping/control-character stripping, 256-code-point
  text bound, exact `0600`, parent `0700`, no-replace behavior and event publication only
  after WAV publication.

- [x] **Step 4: Run valid RED**

  ```bash
  .venv-alpha/bin/python -m pytest -q tests/voice/test_diagnostic.py
  ```

  Expected: collection error because `services.voice.diagnostic` does not exist.

- [x] **Step 5: Implement minimal immutable contracts and safe publisher**

  Use frozen slotted dataclasses, `os.open` with no-follow/exclusive flags where
  available, descriptor-based validation, same-directory temporary publication and
  `fsync`. Publish a final with native no-replace rename so an existing name fails.
  After any ambiguous failure, retain the strict `0600` uncommitted temporary or
  quarantine under the `0700` private session instead of using a racy name-based
  unlink; report it as incomplete, consume its sequence and `fsync` the directory.
  Do not accept caller paths or limits.

- [x] **Step 6: Run GREEN and static checks**

  ```bash
  .venv-alpha/bin/python -m pytest -q tests/voice/test_diagnostic.py
  .venv-alpha/bin/python -m compileall -q services/voice/diagnostic.py
  git diff --check
  ```

- [x] **Step 7: Commit**

  ```bash
  git add services/voice/diagnostic.py tests/voice/test_diagnostic.py
  git commit -m "feat: add private Voice diagnostic artifacts"
  ```

**Acceptance:** a synthetic record can become exactly one private WAV/JSON pair; every
unsafe storage shape fails before publication and no existing final is overwritten.

---

### Task 2: Add bounded writer lifecycle and ASR correlation tap

**Files:**
- Modify: `services/voice/diagnostic.py`
- Modify: `tests/voice/test_diagnostic.py`

**Interfaces:**
- Produces `DiagnosticAsrTap`, wrapping the existing `transcribe(pcm: bytes)` interface.
- Produces `VoiceDiagnosticWriter.offer(record) -> bool`, `snapshot()` and
  `close(timeout_seconds=5.0)`.
- `take_observation()` consumes at most one observation from the latest transcribe call.

- [x] **Step 1: Write ASR tap RED tests**

  Prove one underlying ASR call, exact synthetic text capture, unavailable/invalid result
  mapping, one-shot `take_observation()`, no transcript in `repr`, and no stale result
  after exceptions or the next call.

- [x] **Step 2: Write bounded queue RED tests**

  With a blocked fake publisher, require two accepted records, the third rejected in
  bounded time, fixed queue-drop count and immediate release of the rejected PCM.

- [x] **Step 3: Write settlement/failure RED tests**

  Cover normal drain, expiry, capacity, writer exception, publication failure,
  cancellation and a publisher that ignores shutdown. `close(5.0)` returns in bound,
  publishes no fabricated complete count and discards remaining references.

- [x] **Step 4: Run RED**

  ```bash
  .venv-alpha/bin/python -m pytest -q \
    tests/voice/test_diagnostic.py -k 'tap or queue or settle or writer'
  ```

- [x] **Step 5: Implement minimal tap and single writer thread**

  Use `queue.Queue(maxsize=2)`, one daemon writer, immutable copied bytes and one lock for
  snapshot/close state. The worker thread is the only publisher. Store only fixed failure
  codes; never store an exception string.

- [x] **Step 6: Run GREEN and full diagnostic tests**

  ```bash
  .venv-alpha/bin/python -m pytest -q tests/voice/test_diagnostic.py
  .venv-alpha/bin/python -m compileall -q services/voice/diagnostic.py
  git diff --check
  ```

- [x] **Step 7: Commit**

  ```bash
  git add services/voice/diagnostic.py tests/voice/test_diagnostic.py
  git commit -m "feat: bound Voice diagnostic writing"
  ```

**Acceptance:** diagnostics cannot make a second ASR call or block the Voice loop, and
shutdown is bounded even when storage settlement fails.

---

### Task 3: Integrate diagnostics into the existing listen-only worker

**Files:**
- Modify: `services/voice/listen_only_runtime.py`
- Modify: `services/voice/worker.py`
- Modify: `tests/voice/test_listen_only_runtime.py`
- Modify: `tests/voice/test_worker.py`

**Interfaces:**
- `ListenOnlyVoiceWorker` accepts optional diagnostic tap/writer dependencies.
- `build_listen_only_worker()` loads a valid active session once and otherwise constructs
  the unchanged memory-only graph.
- Fixed status keys: `voice_diagnostic_records`, `voice_diagnostic_drops`,
  `voice_diagnostic_failures`.

- [x] **Step 1: Write disabled-path RED regression**

  Build and run without a marker. Prove the original ASR object is used directly, no
  diagnostic writer/thread/path exists, status diagnostic counters remain zero and PCM/
  text references are released after each controller call.

- [x] **Step 2: Write active correlation RED tests**

  For synthetic PCM/text, prove one record contains the same PCM, ASR observation,
  phase-before, replay flag, action/match outcome and bounded latency. Cover wake, armed
  exact, corrected, rejected, high-risk and ASR-unavailable outcomes without changing
  their existing results.

- [x] **Step 3: Write failure isolation RED tests**

  Queue full, writer closed, marker expiry and writer exception must only increment fixed
  diagnostic counters. Voice outcomes, processed counts, action counters and subsequent
  utterances remain unchanged.

- [x] **Step 4: Run RED**

  ```bash
  .venv-alpha/bin/python -m pytest -q \
    tests/voice/test_listen_only_runtime.py \
    tests/voice/test_worker.py
  ```

- [x] **Step 5: Implement minimal worker wiring**

  Keep controller semantics unchanged. Capture phase/replay before `handle`, consume the
  ASR observation once afterward, construct one record and call non-blocking `offer`.
  Close writer before closing the ASR/pump, bounded by the fixed settlement timeout.

- [x] **Step 6: Run GREEN and adjacent Voice gates**

  ```bash
  .venv-alpha/bin/python -m pytest -q \
    tests/voice/test_diagnostic.py \
    tests/voice/test_listen_only.py \
    tests/voice/test_listen_only_runtime.py \
    tests/voice/test_worker.py \
    tests/tools/test_voice_status.py
  git diff --check
  ```

- [x] **Step 7: Commit**

  ```bash
  git add services/voice/listen_only_runtime.py services/voice/worker.py \
    tests/voice/test_listen_only_runtime.py tests/voice/test_worker.py \
    tests/tools/test_voice_status.py
  git commit -m "feat: observe Voice utterances in private sessions"
  ```

**Acceptance:** an active session observes the existing utterance exactly once; an
inactive or broken session leaves the memory-only production path unchanged.

---

### Task 4: Add fixed diagnostic lifecycle commands

**Files:**
- Create: `tools/voice_diagnostic.py`
- Create: `tests/tools/test_voice_diagnostic.py`
- Modify: `Makefile`
- Modify: `tests/deploy/test_alpha_commands.py`
- Modify: `tests/deploy/test_voice_worker_deploy.py`

**Interfaces:**
- CLI operations: `start`, `status`, `stop` only.
- Make targets: `alpha-voice-diagnostic-start`, `alpha-voice-diagnostic-status`,
  `alpha-voice-diagnostic-stop`.

- [x] **Step 1: Write CLI RED tests**

  Require closed args, no caller paths/limits, fixed stdout, no transcript/path/session
  ID, proper exit codes and failure before marker creation when mode/private-root checks
  fail.

- [x] **Step 2: Write lifecycle ownership RED tests**

  Require start to create a secure random session/marker, reject an existing current
  session, perform Voice-only restart through a fixed adapter and invalidate its own
  marker if readiness fails. Require stop to prove marker identity, disable admission,
  settle via Voice-only restart and retain the session directory.

- [x] **Step 3: Write Make/deploy RED tests**

  Require all targets to call the tracked tool with fixed operation only. Prohibit
  go2rtc/full-Alpha commands, shell interpolation and private values.

- [x] **Step 4: Run RED**

  ```bash
  .venv-alpha/bin/python -m pytest -q \
    tests/tools/test_voice_diagnostic.py \
    tests/deploy/test_alpha_commands.py \
    tests/deploy/test_voice_worker_deploy.py
  ```

- [x] **Step 5: Implement the minimal CLI and Make entries**

  Use existing bounded subprocess/service patterns. `status` reads metadata and file
  counts without opening WAV payloads or transcript event contents. All output uses fixed
  codes and integers.

- [x] **Step 6: Run GREEN and command static gates**

  ```bash
  .venv-alpha/bin/python -m pytest -q \
    tests/tools/test_voice_diagnostic.py \
    tests/deploy/test_alpha_commands.py \
    tests/deploy/test_voice_worker_deploy.py
  .venv-alpha/bin/python -m compileall -q tools/voice_diagnostic.py
  make -n alpha-voice-diagnostic-start
  make -n alpha-voice-diagnostic-status
  make -n alpha-voice-diagnostic-stop
  git diff --check
  ```

- [x] **Step 7: Commit**

  ```bash
  git add Makefile tools/voice_diagnostic.py tests/tools/test_voice_diagnostic.py \
    tests/deploy/test_alpha_commands.py tests/deploy/test_voice_worker_deploy.py
  git commit -m "feat: control private Voice diagnostic sessions"
  ```

**Acceptance:** the operator can start, inspect aggregate status and stop one bounded
session without exposing private content or touching independent services.

---

### Task 5: Lock documentation, privacy and production defaults

**Files:**
- Modify: `AGENTS.md`
- Modify: `docs/runbooks/VOICE_LISTEN_ONLY.md`
- Modify: `tests/contracts/test_voice_settings.py`
- Modify: `tests/voice/test_diagnostic.py`
- Modify: this plan

**Interfaces:**
- Durable rule: household PCM/transcript remain memory-only except during an explicitly
  active, supervised, bounded, ignored local diagnostic session.
- No diagnostic boolean/path is added to tracked settings.

- [x] **Step 1: Write privacy RED tests**

  Prove default settings and absent marker persist nothing; normal status/log writers
  reject transcript/audio/path fields; `.gitignore` covers the private root; tracked
  examples cannot enable diagnostics; CLI output cannot echo event content.

- [x] **Step 2: Update durable rules and runbook**

  Document exact start/status/stop sequence, limits, permissions, artifact sensitivity,
  explicit retained-data deletion boundary and the independent CoreAudio recovery:

  ```bash
  /usr/bin/afplay -v 0.35 /System/Library/Sounds/Ping.aiff
  sudo killall coreaudiod
  ```

  Explicitly prohibit SIP changes and `launchctl kickstart` for protected CoreAudio.

- [x] **Step 3: Run privacy/document gates**

  ```bash
  .venv-alpha/bin/python -m pytest -q \
    tests/contracts/test_voice_settings.py \
    tests/voice/test_diagnostic.py \
    tests/tools/test_voice_diagnostic.py
  git diff --check
  ```

  Scan the tracked diff for household media/transcripts, credentials, private network
  literals, runtime paths, databases and generated settings. Synthetic fixed strings are
  allowed only in tests.

- [x] **Step 4: Commit**

  ```bash
  git add AGENTS.md docs/runbooks/VOICE_LISTEN_ONLY.md \
    tests/contracts/test_voice_settings.py tests/voice/test_diagnostic.py \
    docs/superpowers/plans/2026-08-28-voice-local-diagnostic-session.md
  git commit -m "docs: govern supervised Voice diagnostics"
  ```

**Acceptance:** future sessions cannot confuse the private diagnostic exception with
ordinary production logging or continuous recording.

---

### Task 6: Run complete software and review gates

**Files:**
- Modify: this plan and the existing multi-intent review log with aggregate evidence.

- [x] **Step 1: Run diagnostic focused tests**

  ```bash
  .venv-alpha/bin/python -m pytest -q \
    tests/voice/test_diagnostic.py \
    tests/voice/test_listen_only.py \
    tests/voice/test_listen_only_runtime.py \
    tests/voice/test_worker.py \
    tests/tools/test_voice_diagnostic.py \
    tests/tools/test_voice_status.py \
    tests/contracts/test_voice_settings.py \
    tests/deploy/test_alpha_commands.py \
    tests/deploy/test_voice_worker_deploy.py
  ```

- [x] **Step 2: Run authoritative gates**

  ```bash
  make alpha-voice-test
  .venv-alpha/bin/python -m pytest -q
  .venv-alpha/bin/python -m compileall -q services/voice tools
  git diff --check
  ```

- [x] **Step 3: Review final tracked scope**

  Confirm no go2rtc/Xiaomi patch, Camera Reply enablement, Baby Care, signing, outbox,
  model, threshold or unrelated worker change. Confirm no real runtime artifact is
  tracked and no normal log/status output contains transcript/PCM/path.

- [x] **Step 4: Record actual counts and commit**

  Append only aggregate RED/GREEN counts, exact business head, privacy result and
  unverified device scope. Never paste diagnostic content.

  ```bash
  git add docs/superpowers/plans/2026-08-28-voice-local-diagnostic-session.md \
    docs/reviews/2026-08-27-voice-care-multi-intent-asr-optimization-log.md
  git commit -m "docs: record Voice diagnostic software gate"
  ```

**Acceptance:** focused, Voice, full repository, compile, diff and privacy gates pass;
software evidence does not claim household diagnostic success.

**Fresh Task 6 evidence (2026-08-28):** business head
`fb7b17bd7ccae49f3d1ca50104045d49f329925e`; diagnostic focused
194/194, Voice 587/587, full repository 1892/1892, affected review set 88/88;
compileall, Make dry-runs, diff-check, tracked-scope and privacy scans passed. Independent
review found 0 Critical and 0 Important after the final lifecycle probes. No microphone,
camera playback, private runtime content, Baby Care write or Camera Reply enablement was
used by this software gate.

---

### Task 7: Install and perform one supervised local diagnostic session

**Files:**
- Runtime only under ignored private storage.
- Modify after execution: `SUMMARY.md`, `docs/STATUS.md`, `docs/CHECKPOINT.md`,
  `docs/NEXT.md`, this plan and a new resolution document.

- [ ] **Step 1: Install exact clean candidate**

  Preserve unrelated untracked files. Advance the installed detached checkout to the
  exact reviewed business head and run Voice-only stop/start. Do not restart go2rtc.

- [ ] **Step 2: Prove preflight**

  Require Camera Reply false, Voice healthy/idle, macOS media preflight PASS, source
  PASS, one launchd-owned go2rtc and no current diagnostic session.

- [ ] **Step 3: Start one diagnostic session**

  ```bash
  make alpha-voice-diagnostic-start
  make alpha-voice-diagnostic-status
  ```

  Require active, zero complete records and fixed limits. The adult then speaks only the
  agreed bounded low-risk test phrases. CoreAudio output may remain unavailable; it is
  not an ASR diagnostic blocker.

- [ ] **Step 4: Inspect private evidence locally**

  Verify complete WAV/event pairs, valid WAV format, bounded text and expected aggregate
  pipeline classifications. Do not print or paste transcript/path content. Diagnose the
  first fixed mismatch without relaxing classifier rules.

- [ ] **Step 5: Stop and prove memory-only restoration**

  ```bash
  make alpha-voice-diagnostic-stop
  make alpha-voice-diagnostic-status
  ```

  Require inactive status, retained complete bundle, healthy Voice and source PASS.
  With explicit adult speech after stop, prove complete artifact count no longer grows.

- [ ] **Step 6: Write resolution and handoff state**

  Create
  `docs/reviews/2026-08-28-voice-local-diagnostic-session-resolution.md`. Record only
  aggregate counts, fixed mismatch classes, CoreAudio state, private retention warning,
  tests, commits and remaining deletion decision.

- [ ] **Step 7: Run final bounded verification and commit**

  Run focused diagnostic/Voice tests, compile, diff/privacy scan and Git status. Commit
  only tracked documentation; retain the ignored private diagnostic bundle until the
  user separately approves deletion.

**Acceptance:** one supervised session proves the local diagnostic chain and a later
post-stop utterance proves production memory-only restoration. The retained private
bundle is reported but neither committed nor deleted.

---

## Execution Handoff

The approved execution preference is inline execution in the existing isolated
worktree. Start at Task 1 and stop before Task 7 adult speech if the user is unavailable.
Routine software failures are diagnosed and fixed without weakening privacy or safety
gates. Model installation, Camera Reply, Baby Care, deletion, PR, merge, protected
branches and force-push remain outside this plan.
