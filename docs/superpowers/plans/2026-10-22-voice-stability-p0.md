# Voice Stability P0 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Establish a repeatable local Voice P0 loop from bounded audio input through ASR, deterministic handling, TTS playback, settlement, cleanup, and the next interaction without enabling Camera Reply or Baby Care writes.

**Architecture:** Keep the existing `ExactFrameAudioPump`, Paraformer process, `ListenOnlyController`, and `VoiceOutput`/`AudioSink` boundaries. Add a small session lifecycle layer around the existing local output and deterministic test commands, with explicit phase transitions and fail-closed settlement. Add a private, opt-in encrypted corpus store and an offline runner using synthetic or licensed fixtures; real household capture remains a separate authorization gate.

**Tech Stack:** Python 3.11+, pytest, existing macOS `/usr/bin/say`/`afplay` adapters, existing Paraformer subprocess, existing Baby Care v2 contracts unchanged.

**Spec:** User-provided `Baby Care Voice Stability P0` task in the conversation.

## Global Constraints

- Camera Reply remains disabled and no Xiaomi hardware activation occurs in this slice.
- No Baby Care formal care-record write is added or claimed.
- Raw household audio and transcripts remain memory-only unless a separately authorized bounded diagnostic session is active.
- Existing M6 contracts, idempotency, leases, and historical data models remain unchanged.
- Existing user changes (`Interactive`, `test.sh`, and Baby Care `.pnpm-store/`) are preserved.
- All tests use synthetic, public, or explicitly licensed fixtures; CI never uploads household audio.

## Review Focus

- A TTS renderer succeeds but playback completion is unknown: the session must report `AMBIGUOUS`, clean resources, and avoid automatic replay. Covered by output lifecycle fault-injection tests.
- A second utterance arrives during `SPEAKING`: only one output flight may exist and the next accepted turn must start from `IDLE`. Covered by concurrency/one-flight tests.
- ASR or playback hangs: the bounded timeout must cancel/close the current child or sink and recover to `IDLE`/`FAILED` without an orphan. Covered by timeout tests.
- Echo or replayed tail audio contains the wake word: it must be ignored without consuming a new user turn. Covered by wake/ducker tests.
- Corpus consent is absent or revoked: recording must be refused and deletion must remove encrypted media and metadata. Covered by corpus policy tests.

---

### Task 1: Add explicit Voice P0 lifecycle and deterministic test responses

**Files:**
- Create: `services/voice/stability.py`
- Modify: `services/voice/tts.py`
- Test: `tests/voice/test_stability.py`
- Test: `tests/voice/test_tts.py`

**Interfaces:**
- `VoicePhase`: `IDLE`, `LISTENING`, `RECOGNIZING`, `PROCESSING`, `SPEAKING`, `FAILED`, `CANCELLED`, `TIMED_OUT`.
- `VoiceSessionState(session_id, phase, generation, response_code, error_code)`.
- `VoiceStabilitySession.handle_pcm(pcm, cancelled, *, push_to_talk=False) -> VoiceSessionState`.
- Add fixed local-only response codes for `我在`, `能听见`, `语音回复正常`, `停止`, and one bounded ASR failure response; keep Camera Reply’s accepted code set unchanged.

- [x] Step 1: Write failing phase-transition and deterministic-command tests.
- [x] Step 2: Run `pytest -q tests/voice/test_stability.py` and verify the new API/behavior fails.
- [x] Step 3: Implement the minimal lifecycle/session and local response-code mapping.
- [x] Step 4: Run the focused tests and the existing TTS/listen-only tests.
- [ ] Step 5: Commit the monitor slice when Git writes are available.

### Task 2: Make local output settlement one-flight and fail-closed

**Files:**
- Modify: `services/voice/tts.py`
- Modify: `services/voice/listen_only_runtime.py`
- Test: `tests/voice/test_tts.py`
- Test: `tests/voice/test_listen_only_runtime.py`

**Interfaces:**
- Preserve `AudioSink.play(RenderedReply, cancelled) -> bool`.
- Add bounded output settlement reporting so a sink can distinguish complete, failed, cancelled, and ambiguous completion without changing the M6 semantic response contract.

- [x] Step 1: Add failing tests for duplicate output, cancellation, missing completion, sink exception, cleanup, and recovery to the next turn.
- [x] Step 2: Run the focused tests and verify the failures are lifecycle failures.
- [x] Step 3: Implement the smallest serialized output guard and cleanup path around the existing `AudioSink`.
- [x] Step 4: Run TTS/runtime tests plus the existing Camera Reply synthetic tests; Camera Reply must remain disabled in all fixtures.
- [x] Step 5: Record the result in the report; commit remains pending Git write access.

### Task 3: Add Push-to-Talk and exact wake stability paths

**Files:**
- Modify: `services/voice/listen_only.py`
- Modify: `services/voice/listen_only_runtime.py`
- Modify: `services/voice/worker.py`
- Test: `tests/voice/test_listen_only.py`
- Test: `tests/voice/test_worker.py`

**Interfaces:**
- PTT uses the same ASR, deterministic command, TTS, and output lifecycle boundaries as wake mode.
- Wake phrase remains user-facing `嘿小小`, internally normalized to `小小`.
- PTT and wake test commands are local test interactions only and never enter Baby Care formal records.

- [x] Step 1: Add failing tests for the five required interactions, PTT mode, ASR failure, timeout, cancel, and repeated next-turn recovery.
- [x] Step 2: Run the focused tests and verify the expected RED failures.
- [x] Step 3: Implement deterministic routing without changing M6/M7 care intent parsing or Camera Reply.
- [x] Step 4: Run all affected Voice tests and compile checks.
- [ ] Step 5: Commit and update the report.

### Task 4: Add private opt-in Voice Test Corpus storage

**Files:**
- Create: `services/voice/test_corpus.py`
- Create: `tests/voice/test_test_corpus.py`
- Modify: `.gitignore` only if an existing ignored runtime path is insufficient

**Interfaces:**
- `VoiceTestCorpusStore(root, key_provider, clock)` with explicit consent state.
- `record(...)`, `list_records()`, `read_audio(test_id)`, `delete(test_id)`, `delete_all()`, `purge_expired()`.
- Default recording disabled; encrypted audio, 0600 files, 0700 directory, bounded metadata, 7-day expiry, and no raw content in logs.

- [x] Step 1: Add failing consent, encryption, permissions, deletion, expiry, and revoked-consent tests.
- [x] Step 2: Run the corpus tests and verify RED.
- [x] Step 3: Implement the smallest local encrypted store using an injected secret reference, never a repository key.
- [x] Step 4: Run corpus/privacy tests and tracked-media scans.
- [ ] Step 5: Commit and update the report.

### Task 5: Add deterministic Voice Regression Runner and report

**Files:**
- Create: `tools/voice_stability_runner.py`
- Create: `tests/tools/test_voice_stability_runner.py`
- Create: `docs/VOICE_STABILITY_P0_REPORT.md`
- Modify: `Makefile`

**Interfaces:**
- Runner executes synthetic/fixed-fixture software passes, fault injection, and bounded repetition; it reports counts, P50/P95/P99 latency, ambiguous playback separately, and resource-cleanup counters.
- No real microphone, camera speaker, Baby Care database, or raw household media is touched by the runner.

- [x] Step 1: Add failing runner contract tests for 1000 software repetitions and the required fault cases.
- [x] Step 2: Run the runner tests and verify RED.
- [x] Step 3: Implement bounded deterministic replay/fault injection with compact JSON/Markdown output.
- [x] Step 4: Run focused tests, runner, full Python suite, shell/Make/diff/privacy checks.
- [x] Step 5: Write the report with separate `SOFTWARE_TEST_PASS`, `LOCAL_AUDIO_HARDWARE_PASS`, `WAKE_WORD_PASS`, `CAMERA_REPLY_PASS`, and `FAMILY_DEPLOYMENT_READY` statuses.

### Task 6: Real-device gates, not autonomous implementation

- [ ] Stop before real recording or Camera Reply activation and request explicit local operator authorization.
- [ ] Run the user-specified 100 adult utterances, 60-minute false-wake observation, and sustained resource check only in the logged-in user context with the fixed readiness/countdown workflow.
- [ ] Keep Camera Reply false unless its independent Xiaomi V3E gate is separately approved and passes.
