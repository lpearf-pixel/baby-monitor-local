# Voice Listen-Only Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Deliver a continuously prewarmed, memory-only Xiaomi audio listener that responds to exact `小小`, accepts one bounded follow-up command, and never writes Baby Care.

**Architecture:** A separate `listen_only_enabled` mode composes one fixed audio decoder, exact-frame pump, stateful Silero VAD, bounded utterance collector, local Paraformer ASR, a pure wake/dialogue controller, and fixed macOS TTS. The listen-only builder has no dependency on speaker identity, signing, outbox, Baby Care client, family IDs, or private calibration corpus; its status and lifecycle remain isolated from Guardian siblings.

**Tech Stack:** Python 3.11+, Pydantic settings, FFmpeg PCM pipe, ONNX Runtime Silero VAD, pinned sherpa-onnx Paraformer subprocess, macOS `say`/`afplay`, launchd, pytest.

**Spec:** `docs/superpowers/specs/2026-08-25-voice-listen-only-design.md`

## Global Constraints

- Household PCM and ASR text remain memory-only and are never logged, persisted, or transmitted.
- `enabled` and `listen_only_enabled` are mutually exclusive and both default to `false`.
- Listen-only must not construct or import the Baby Care client, outbox, signer, speaker verifier, Keychain corpus, identity, or family configuration.
- Exact normalized `小小` is the only wake keyword; fuzzy matching and transcript repair are prohibited.
- Standalone wake says only `我在，请说。`; an accepted closed command says only `我听到了。`.
- The armed wait is eight monotonic seconds after TTS playback guard; timeout returns silently to idle.
- Decoder, VAD/ASR, TTS, launchd, status, and retries are bounded and independently supervised.
- Full-care Voice remains disabled; Guardian video, gauge, environment, and other workers are never restarted by this slice.
- User-facing shell remains ASCII-only and macOS Bash 3.2 compatible.
- Run the full repository suite only once at the final software milestone; during implementation use focused Voice gates.

---

### Task 1: Closed Runtime Mode And Status Schema V2

**Files:**
- Modify: `packages/contracts/settings.py`
- Modify: `services/voice/worker.py`
- Modify: `tools/voice_status.py`
- Modify: `config/settings.example.yaml`
- Test: `tests/contracts/test_voice_settings.py`
- Test: `tests/voice/test_worker.py`
- Test: `tests/tools/test_voice_status.py`

**Interfaces:**
- Produces: `VoiceCareSettings.listen_only_enabled: bool`; `VoiceStatusWriter.write(mode: Literal["disabled", "listen_only", "care"], ...)`; status schema version 2.
- Preserves: the existing full-care `enabled` artifact requirements and preflight behavior.

- [x] **Step 1: Write failing settings and status tests**

```python
def test_listen_only_is_disabled_by_default_and_exclusive() -> None:
    assert VoiceCareSettings().listen_only_enabled is False
    with pytest.raises(ValueError, match="VOICE_MODE_CONFLICT"):
        VoiceCareSettings(enabled=True, listen_only_enabled=True, **all_digests())

def test_status_v2_has_only_closed_mode_and_aggregate_fields(tmp_path: Path) -> None:
    writer = VoiceStatusWriter(tmp_path / "voice.json", clock=lambda: NOW)
    writer.write(mode="listen_only", worker_state="healthy", reason="listen_only_idle",
                 processed_count=0, last_latency_ms=None)
    assert json.loads((tmp_path / "voice.json").read_text()) == {
        "schema_version": 2, "checked_at": NOW.isoformat(), "mode": "listen_only",
        "worker_state": "healthy", "reason": "listen_only_idle",
        "processed_count": 0, "last_latency_ms": None,
    }
```

- [x] **Step 2: Run the RED tests**

Run: `.venv-alpha/bin/python -m pytest -q tests/contracts/test_voice_settings.py tests/voice/test_worker.py tests/tools/test_voice_status.py`

Expected: failures for missing `listen_only_enabled`, `mode`, and schema v2.

- [x] **Step 3: Add the minimal closed fields and validators**

```python
class VoiceCareSettings(StrictSettingsModel):
    enabled: bool = False
    listen_only_enabled: bool = False

    @model_validator(mode="after")
    def require_one_voice_mode(self) -> "VoiceCareSettings":
        if self.enabled and self.listen_only_enabled:
            raise ValueError("VOICE_MODE_CONFLICT")
        return self
```

Extend `_STATUS_REASONS` with the exact spec reasons, require a closed `mode`, emit schema 2, and update every current writer call explicitly.

- [x] **Step 4: Run the same focused tests GREEN**

Run the Step 2 command. Expected: all pass.

- [x] **Step 5: Commit Task 1**

```bash
git add packages/contracts/settings.py services/voice/worker.py tools/voice_status.py config/settings.example.yaml tests/contracts/test_voice_settings.py tests/voice/test_worker.py tests/tools/test_voice_status.py
git commit -m "feat: add closed Voice listen-only mode"
```

### Task 2: Exact-Frame Continuous Audio Pump

**Files:**
- Create: `services/voice/audio_pump.py`
- Test: `tests/voice/test_audio_pump.py`

**Interfaces:**
- Consumes: `Decoder.read(max_bytes) -> DecoderRead`, `Decoder.close()`.
- Produces: `ExactFrameAudioPump.read_frame() -> PumpFrame`; `warm_up(cancelled) -> bool`; `begin_duck()`, `end_duck()`, `close()`.
- Fixed values: 3,200-byte/100-ms frames, bounded 500-ms warm-up, no more than 14 frames buffered, no disk path.

- [x] **Step 1: Write RED tests for partial reads, warm-up, ducking, close, and bounds**

```python
def test_partial_reads_form_one_exact_frame_without_loss() -> None:
    pump = ExactFrameAudioPump(FakeDecoder([b"a" * 1000, b"b" * 2200]))
    assert pump.read_frame().pcm == b"a" * 1000 + b"b" * 2200

def test_warmup_and_duck_drop_frames_and_resume_empty() -> None:
    pump = ExactFrameAudioPump(FakeDecoder([FRAME] * 12), warmup_frames=5)
    assert pump.warm_up(threading.Event()) is True
    pump.begin_duck(); assert pump.read_frame().dropped is True
    pump.end_duck(); assert pump.buffered_bytes == 0
```

Add cases for EOF/failure, oversized partial input, cancellation, idempotent close, and zeroizing the mutable assembler.

- [x] **Step 2: Run RED**

Run: `.venv-alpha/bin/python -m pytest -q tests/voice/test_audio_pump.py`

Expected: import failure for `services.voice.audio_pump`.

- [x] **Step 3: Implement the bounded pump**

Use a `bytearray` assembler, pull only the remaining bytes, return only immutable exact frames, clear/overwrite the assembler on reset, and never create files or background unbounded queues. Duck mode continues consuming and dropping decoder data.

- [x] **Step 4: Run GREEN and compile**

Run: `.venv-alpha/bin/python -m pytest -q tests/voice/test_audio_pump.py && .venv-alpha/bin/python -m py_compile services/voice/audio_pump.py`

- [x] **Step 5: Commit Task 2**

```bash
git add services/voice/audio_pump.py tests/voice/test_audio_pump.py
git commit -m "feat: add bounded Voice audio pump"
```

### Task 3: Stateful Streaming Silero Adapter

**Files:**
- Modify: `services/voice/silero_runtime.py`
- Modify: `services/voice/vad.py`
- Test: `tests/voice/test_silero_runtime.py`
- Test: `tests/voice/test_vad.py`

**Interfaces:**
- Produces: `StreamingSileroVad.observe(frame: bytes) -> VadResult`; `reset() -> None`; `close() -> None`.
- Preserves: `SileroOnnxSegmenter` whole-clip diagnostic API.

- [x] **Step 1: Write RED streaming-state tests**

```python
def test_streaming_vad_carries_state_and_resets_on_boundary() -> None:
    vad = StreamingSileroVad(fake_artifact(), project_root=tmp_path, session_factory=factory)
    assert vad.observe(FRAME).speech is True
    assert vad.observe(FRAME).speech is False
    vad.reset()
    assert session_inputs[-1]["state"].sum() == 0
```

Cover fixed frame length, 512-sample chunking within a 1,600-sample frame, context/state continuity, invalid ONNX output, close, and no probability/status persistence.

- [x] **Step 2: Run RED**

Run: `.venv-alpha/bin/python -m pytest -q tests/voice/test_silero_runtime.py tests/voice/test_vad.py`

- [x] **Step 3: Implement a dedicated streaming adapter**

Reuse the pinned artifact/session validation, keep model state only in instance memory, aggregate the fixed subchunks conservatively to one `VadResult`, and reset after utterance, duck, source discontinuity, or close.

- [x] **Step 4: Run GREEN**

Run the Step 2 command. Expected: all pass.

- [x] **Step 5: Commit Task 3**

```bash
git add services/voice/silero_runtime.py services/voice/vad.py tests/voice/test_silero_runtime.py tests/voice/test_vad.py
git commit -m "feat: add streaming Silero voice activity"
```

### Task 4: Exact Wake And Bounded Two-Stage Dialogue

**Files:**
- Modify: `services/voice/wake.py`
- Create: `services/voice/listen_only.py`
- Modify: `services/voice/tts.py`
- Test: `tests/voice/test_wake.py`
- Create: `tests/voice/test_listen_only.py`
- Test: `tests/voice/test_tts.py`

**Interfaces:**
- Produces: `classify_wake(text: str) -> WakeClassification`; `ListenOnlyController.handle(pcm, now_ns, cancelled) -> ListenOnlyOutcome`; `expire(now_ns) -> ListenOnlyOutcome`.
- `WakeClassification.kind` is one of `standalone_wake|wake_with_command|not_wake`.
- `ListenOnlyOutcome.reason` and `response_code` are closed strings only; transcript never escapes.

- [x] **Step 1: Write the complete dialogue RED matrix**

```python
@pytest.mark.parametrize("text,kind", [("小小", "standalone_wake"),
    (" 小小。", "standalone_wake"), ("小小今天天气", "not_wake"),
    ("你好小小", "not_wake")])
def test_exact_wake_classification(text: str, kind: str) -> None:
    assert classify_wake(text).kind == kind

def test_standalone_wake_acks_then_accepts_at_most_one_closed_command() -> None:
    controller = controller_with_texts("小小", "我是爸爸，开始喂奶", "喝了90毫升")
    assert controller.handle(PCM, 1, STOP).response_code == "listen_only_ready"
    assert controller.handle(PCM, 2, STOP).response_code == "listen_only_received"
    assert controller.handle(PCM, 3, STOP).response_code is None
```

Add one-utterance wake+closed command, unknown/malformed silence, armed eight-second expiry, deadline starting after TTS returns, speech-start-before-deadline completion, TTS/model error reset, and no identity/outbox/client calls.

- [x] **Step 2: Run RED**

Run: `.venv-alpha/bin/python -m pytest -q tests/voice/test_wake.py tests/voice/test_listen_only.py tests/voice/test_tts.py`

- [x] **Step 3: Implement pure classification and memory-only state**

Keep `validate_wake_prefix` unchanged. Add fixed TTS codes:

```python
RESPONSE_PHRASES.update({
    "listen_only_ready": "我在，请说。",
    "listen_only_received": "我听到了。",
})
```

Use the existing deterministic care parser only for closed syntax, discard its result, and reset dialogue state in every success/failure/timeout path.

- [x] **Step 4: Run GREEN**

Run the Step 2 command. Expected: all pass.

- [x] **Step 5: Commit Task 4**

```bash
git add services/voice/wake.py services/voice/listen_only.py services/voice/tts.py tests/voice/test_wake.py tests/voice/test_listen_only.py tests/voice/test_tts.py
git commit -m "feat: add bounded Voice wake dialogue"
```

### Task 5: Production Listen-Only Composition

**Files:**
- Create: `services/voice/listen_only_runtime.py`
- Modify: `services/voice/worker.py`
- Modify: `tools/run_voice_worker.py`
- Test: `tests/voice/test_listen_only_runtime.py`
- Test: `tests/voice/test_worker.py`
- Test: `tests/deploy/test_voice_worker_deploy.py`

**Interfaces:**
- Produces: `build_listen_only_worker(settings: AppSettings, project_root: Path) -> VoiceWorker`.
- The builder validates only fixed Paraformer/Silero artifacts, opens the fixed loopback `audio_analysis` decoder, and constructs the pump/controller/TTS stack.

- [x] **Step 1: Write RED composition and privacy-boundary tests**

```python
def test_builder_constructs_only_listen_only_dependencies(monkeypatch, tmp_path: Path) -> None:
    built = build_listen_only_worker(listen_only_settings(), tmp_path, dependencies=fakes())
    assert isinstance(built, VoiceWorker)
    assert not any(name in imported_modules() for name in (
        "services.voice.client", "services.voice.outbox", "services.voice.signing",
        "services.voice.speaker", "services.voice.helper_keychain"))

def test_runner_builds_default_listen_only_worker_but_not_full_care(tmp_path: Path) -> None:
    assert main(["--settings", listen_only_yaml, "--voice-models", fixed_models],
                project_root=tmp_path, runtime_builder=fake_builder) == 0
    assert main(["--settings", full_care_yaml], project_root=tmp_path) == 2
```

Also prove startup warm-up precedes ready, exact frames are used, duck/reset happens around TTS, stop closes decoder/VAD/ASR/TTS, and no transcript enters status/stdout/stderr.

- [x] **Step 2: Run RED**

Run: `.venv-alpha/bin/python -m pytest -q tests/voice/test_listen_only_runtime.py tests/voice/test_worker.py tests/deploy/test_voice_worker_deploy.py`

- [x] **Step 3: Implement the default builder and listen-only worker loop**

Move full-care-only imports out of the base worker module into their full-care boundary so importing listen-only does not load them. Validate `_VOICE_MODELS_RELATIVE`, require only pinned Paraformer and Silero digests for listen-only, run a bounded warm-up, process frames continuously, and use only closed status reasons.

- [x] **Step 4: Run GREEN and the full Voice gate**

Run: `.venv-alpha/bin/python -m pytest -q tests/voice/test_listen_only_runtime.py tests/voice/test_worker.py tests/deploy/test_voice_worker_deploy.py && make alpha-voice-test`

- [x] **Step 5: Commit Task 5**

```bash
git add services/voice/listen_only_runtime.py services/voice/worker.py tools/run_voice_worker.py tests/voice/test_listen_only_runtime.py tests/voice/test_worker.py tests/deploy/test_voice_worker_deploy.py
git commit -m "feat: compose Voice listen-only runtime"
```

### Task 6: Independent Operator Lifecycle And Installed Acceptance

**Files:**
- Modify: `Makefile`
- Modify: `tools/start_alpha.sh`
- Modify: `tools/stop_alpha.sh`
- Modify: `tools/voice_status.py`
- Modify: `deploy/launchd/com.babymonitor.voice.plist.example`
- Modify: `tests/deploy/test_voice_worker_deploy.py`
- Modify: `docs/runbooks/VOICE_CARE_V1.md`

**Interfaces:**
- Produces: `make alpha-voice-listen-start`, `alpha-voice-listen-status`, `alpha-voice-listen-stop`.
- Preserves: Guardian and ASR operator launchd ownership and ordinary `alpha-voice-*` compatibility.

- [x] **Step 1: Write RED lifecycle tests**

Assert Make dry-runs are short, use only Voice labels, status prints only schema/mode/state/reason/count/latency, start requires `listen_only_enabled=true`, and stop settles the Voice worker without touching go2rtc/Guardian/audio siblings.

- [x] **Step 2: Run RED**

Run: `.venv-alpha/bin/python -m pytest -q tests/deploy/test_voice_worker_deploy.py`

- [x] **Step 3: Add minimal lifecycle targets and runbook**

Use existing Voice-only launchd scripts; do not add an Alpha restart path. Document fixed i9 commands and that TTS uses the i9 speaker, not the camera.

- [x] **Step 4: Run software GREEN gates**

Run:

```bash
.venv-alpha/bin/python -m pytest -q tests/voice tests/contracts/test_voice_care.py tests/contracts/test_voice_settings.py tests/deploy/test_voice_worker_deploy.py
.venv-alpha/bin/python -m py_compile services/voice/*.py tools/run_voice_worker.py tools/voice_status.py
bash -n tools/start_alpha.sh tools/stop_alpha.sh
plutil -lint deploy/launchd/com.babymonitor.voice.plist.example
make -n alpha-voice-listen-start alpha-voice-listen-status alpha-voice-listen-stop
git diff --check
```

- [ ] **Step 5: Install and run supervised i9 acceptance**

Run `make alpha-install`, enable only the ignored `listen_only_enabled: true`, then run the three listen-only Make targets. Record the spec's 5 standalone wakes, 3 two-stage commands, 3 silent timeouts, 5 non-wake controls, no self-trigger, bounded fault/restart, privacy file scan, no Baby Care write, clean stop, and Guardian health. Any missed wake remains a failed real-device gate; do not lower exact matching or VAD thresholds.

Automated installed-i9 readiness is complete at implementation head `aa28cf3`: the
Voice-only launchd job runs with the fixed Intel Homebrew `PATH`, owns a live FFmpeg
audio child, reports `healthy / listen_only_idle`, and leaves the Xiaomi source gate
passing. The exact Voice-only stop/start lifecycle also returns `voice_stop=PASS` and
`voice_start=PASS`, then returns to healthy without restarting any sibling. The first
status check during decoder warm-up transiently reported
`voice_audio_unavailable` and then recovered without restarting Guardian. The human
5/3/3/5 wake/dialogue/timeout/non-wake matrix and acoustic self-trigger check remain
pending and are not replaced by synthetic TTS.

- [x] **Step 6: Commit Task 6 and handoff checkpoint**

Update `SUMMARY.md`, `docs/STATUS.md`, `docs/CHECKPOINT.md`, `docs/NEXT.md`, and this plan's checkboxes with exact evidence. Commit lifecycle/code separately from evidence docs. Do not push or merge.
