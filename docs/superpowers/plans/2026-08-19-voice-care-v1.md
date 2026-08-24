# Voice Care v1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use
> `superpowers:subagent-driven-development` (recommended) or
> `superpowers:executing-plans` to implement this plan task-by-task. Steps use checkbox
> (`- [ ]`) syntax for tracking.

**Goal:** Deliver a fully local, fail-closed Voice Care v1 feeding loop from Xiaomi
audio through explicit caregiver identity and signed structured intent to an
authoritative Baby Care pending/confirm/commit transaction.

**Architecture:** Baby Local owns bounded audio, VAD, local Whisper ASR, exact wake
validation, local speaker verification, signed intent delivery and bounded spoken
responses. Baby Care owns device/profile binding, authorization, pending feeding state,
idempotent final writes, revision/undo and audit. The shared contract is published by
Baby Care and vendored into Baby Local at an exact source commit and SHA-256.

**Tech Stack:** Python 3.11, NumPy, OpenVINO/ONNX, faster-whisper 1.2.1,
CTranslate2 4.8.1, cryptography 48.0.1, FFmpeg, macOS Keychain and launchd on Baby
Local; Node.js 24, TypeScript 5.9, Zod, Fastify, PostgreSQL/Drizzle and Vitest on Baby
Care.

**Spec:** `docs/superpowers/specs/2026-08-19-voice-care-v1-design.md`

## Global Constraints

- Household audio and ordinary ASR transcripts are memory-only and are never written to
  Git, SQLite, logs, diagnostics, Baby Care or model services.
- Voice models live only under ignored runtime storage, require immutable provenance and
  SHA-256 validation, and are never downloaded by a running worker.
- The exact normalized wake prefix is `小小`; punctuation and surrounding whitespace
  may be removed, but fuzzy spellings and homophones are rejected.
- One utterance has at most 500 ms pre-roll, 800 ms terminal silence and eight seconds
  total duration inside the existing 15-second PCM memory ceiling.
- Only `speakerState=verified` plus an active Baby Care device/profile binding may
  create a final care record. Missing, uncertain, mismatched or unavailable identity is
  fail-closed.
- Baby Care resolves family, Baby and actor from the paired device/profile. It never
  trusts caller-supplied family, Baby or user identifiers.
- Voice is a distinct `care_source`; it is never disguised as manual, Guardian, device
  or AI input.
- No response says `saved` before the Baby Care transaction commits.
- Feeding is the only V1 care fact. Diaper, sleep and medication remain later gates.
- i9/macOS speech output is first. Xiaomi camera backchannel remains outside Gate V1.
- Both products remain independently deployable; one component failure cannot restart
  the other product or the full Guardian stack.
- No protected branch, merge, PR, tag or remote push is implied by this plan.

---

## Scope

This plan records completed **Gate V0** and defines the approved implementation sequence
for **Gate V1** on the confirmed Xiaomi + i9 topology.

The governing design remains:
`docs/superpowers/specs/2026-08-19-voice-care-v1-design.md`

Gate V0 is explicitly low-impact and non-invasive: no Baby Care writes, no household
audio persistence, no ASR/care logic enablement, and no production behavior changes
beyond the fixed decoder timeout/cleanup lifecycle required by the probe gate.

**Overall status:** Gate V0 completed on 2026-08-20. Gate V1 local model architecture was
approved on 2026-08-20. Baby Local Tasks 1–3 are complete and independently reviewed;
Task 3 selected Whisper `base` on the installed i9 synthetic gate on 2026-08-21. Task 4
must wait for the Baby Care M4 exact-head prerequisite. No production Voice Care path is
enabled.
Gate V0 proves only inbound audio and the bounded receive/decode boundary. It does not
approve household ASR/speaker accuracy or Baby Care writes.

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

**Next:** Execute Gate V1 Task 0 and the independent Baby Local Tasks 1–3. Guardian cry
A8 remains a separate disabled track.

## Gate V1 Baselines And Parallel Order

Baby Local baseline is `codex/voice-care-v1-design` at or after approved spec commit
`8dc8b4bf64f6d0d4b9471d9a04d1f1504e4282be`.

Baby Care's current cumulative product branch is
`codex/m4-birth-ready-operations`. At planning time its head was
`53997b9c24de75b4850b4e193ef89ff755be9913`, M0–M3 were verified complete and M4 Task 3
was next. Voice Care must not interrupt or bypass that M4 data-safety plan. The Voice
Care Baby Care branch is created only from an exact M4 head whose
`.agent/current-milestone.json` records M4 verified complete and whose exact-head CI
passes static, unit, PostgreSQL integration, build and production Compose gates.

The safe parallel schedule is:

```text
Baby Local: Tasks 1 -> 2 -> 3 -------------------> Task 6 -> 7 -> 9 -> 10
Baby Care:  finish existing M4 -> Task 4 -> Task 5 -> Task 8 -----------+
                                                                         |
Both exact heads ----------------------------------------------------> Task 11
```

Tasks 1–3 do not define the cross-product intent schema and may proceed while Baby Care
finishes M4. Task 4 is contract-first. Tasks 6 and 9 may consume only Task 4's committed
schema and golden fixtures.

### Task 0: Establish Exact Independent Feature Branches

**Files:**
- Verify only: Baby Local `SUMMARY.md`, `docs/STATUS.md`, `docs/NEXT.md`
- Verify only: Baby Care `agent.md`, `summary.md`, `.agent/current-milestone.json`

**Interfaces:**
- Consumes: approved Voice Care spec and the existing Baby Care M4 plan.
- Produces: one exact Baby Local head and, after M4 completion, one exact Baby Care
  head from which independent Voice Care feature branches are created.

- [x] **Step 1: Verify Baby Local baseline and preserve unrelated files**

Run:

```bash
git branch --show-current
git rev-parse HEAD
git status --short
```

Expected: feature branch `codex/voice-care-v1-design`; existing ignored/untracked local
runtime files remain unstaged.

- [x] **Step 2: Create the Baby Local Gate V1 feature branch**

Run after the Baby Local baseline check and this planning checkpoint commit:

```bash
git switch -c codex/voice-care-v1-gate-v1
```

Expected: Baby Local work starts from the approved spec/plan checkpoint without
modifying or merging `main`.

- [ ] **Step 3: Finish Baby Care M4 under its existing approved plan**

Run in the Baby Care checkout:

```bash
pnpm lint
pnpm typecheck
pnpm test
pnpm build
```

Expected: M4's own plan and exact-head CI close before any Voice Care Baby Care branch
is created. Do not merge or modify `main`.

- [ ] **Step 4: Create the Baby Care Voice Care feature branch**

Run in Baby Care only after M4 exact-head CI and status close:

```bash
git switch -c codex/voice-care-v1-contract
```

Expected: Baby Care starts from its own verified M4 product head; neither repository is
nested inside the other.

### Task 1: Baby Local Voice Settings And Artifact Registry

**Status:** Complete through `1cc1f51` (`fix: correct whisper conversion bundles`);
independent review approved after three bounded fix rounds. Real pinned source-manifest
recording and i9 model conversion remain explicit operator gates for Task 3.

**Files:**
- Create: `services/voice/__init__.py`
- Create: `services/voice/artifacts.py`
- Modify: `packages/contracts/settings.py`
- Modify: `pyproject.toml`
- Create: `tools/voice_models.py`
- Test: `tests/contracts/test_voice_settings.py`
- Test: `tests/voice/test_artifacts.py`

**Interfaces:**
- Produces: `VoiceCareSettings`, `VoiceArtifactSpec`,
  `validate_voice_artifact(spec, project_root) -> Path`.
- Consumes: existing strict Pydantic settings and the relative-path/SHA-256 pattern used
  by `AudioSettings` and `CryClassifier`.

- [x] **Step 1: Write strict settings and artifact RED tests**

```python
def test_voice_defaults_are_disabled_and_bounded() -> None:
    settings = VoiceCareSettings()
    assert settings.enabled is False
    assert settings.stream_name == "audio_analysis"
    assert settings.max_utterance_ms == 8_000
    assert settings.pre_roll_ms == 500
    assert settings.terminal_silence_ms == 800


def test_enabled_voice_rejects_missing_artifact_digests() -> None:
    with pytest.raises(ValueError, match="VOICE_ARTIFACT_DIGEST_REQUIRED"):
        VoiceCareSettings(enabled=True)
```

- [x] **Step 2: Run RED tests**

Run: `.venv-alpha/bin/python -m pytest -q tests/contracts/test_voice_settings.py tests/voice/test_artifacts.py`

Expected: FAIL because `VoiceCareSettings` and `services.voice.artifacts` do not exist.

- [x] **Step 3: Implement the minimum closed configuration**

Define literal artifact IDs `silero-vad-v6.2`, `openai-whisper-base`,
`openai-whisper-small` and `speechbrain-ecapa-voxceleb`; each spec contains a relative
runtime path, upstream project, immutable source revision, SPDX license and SHA-256.
Validation resolves the path strictly under the repository, rejects symlinks and hashes
before creating any runner. Keep all digest fields required only when `enabled=True`.
The explicit installer downloads/converts into ignored runtime storage, validates every
digest and license record before atomic placement and never runs from worker startup.
Pin `faster-whisper==1.2.1` and Intel macOS `ctranslate2==4.8.1` for local ASR, and
`cryptography==48.0.1` for later Ed25519/AES-GCM boundaries. Load only an absolute
validated local model directory into faster-whisper so its implicit Hub download path
cannot run. Set the structured outbox limit to 128 intents with a 1,800-second retention
ceiling.

- [x] **Step 4: Run GREEN tests and static checks**

Run:

```bash
.venv-alpha/bin/python -m pytest -q tests/contracts/test_voice_settings.py tests/voice/test_artifacts.py
.venv-alpha/bin/python -m compileall -q packages/contracts services/voice tools/voice_models.py
git diff --check
```

Expected: all focused tests pass; no model file is created or downloaded.

- [x] **Step 5: Commit Task 1**

```bash
git add packages/contracts/settings.py services/voice/__init__.py services/voice/artifacts.py tools/voice_models.py pyproject.toml tests/contracts/test_voice_settings.py tests/voice/test_artifacts.py
git commit -m "feat: add closed voice artifact registry"
```

### Task 2: Baby Local VAD And Eight-Second Utterance Collector

**Status:** Complete through `d750f05` (`test: prove voice buffer zeroization`);
independent review approved after one bounded fix round.

**Files:**
- Create: `services/voice/vad.py`
- Create: `services/voice/capture.py`
- Test: `tests/voice/test_vad.py`
- Test: `tests/voice/test_capture.py`

**Interfaces:**
- Produces: `VadResult(speech: bool, probability: float)`,
  `VoiceActivityDetector.observe(frame: bytes) -> VadResult`, and
  `UtteranceCollector.push(frame: bytes, vad: VadResult) -> UtteranceResult | None`.
- Consumes: 16 kHz mono s16le frames from the existing fixed audio decoder.

- [x] **Step 1: Write collector RED tests**

```python
def test_collector_closes_at_eight_seconds_and_discards_after_take() -> None:
    collector = UtteranceCollector(settings)
    for _ in range(80):
        result = collector.push(frame_100ms, VadResult(speech=True, probability=0.9))
    assert result is not None
    assert result.reason == "max_duration"
    assert len(result.pcm) == 8 * 16_000 * 2
    assert collector.buffered_bytes == 0
```

Also cover 500 ms pre-roll, 800 ms terminal silence, malformed frame rejection, VAD
non-finite output and close/reset zeroization.

- [x] **Step 2: Run RED tests**

Run: `.venv-alpha/bin/python -m pytest -q tests/voice/test_vad.py tests/voice/test_capture.py`

Expected: FAIL because the collector and VAD boundary do not exist.

- [x] **Step 3: Implement bounded memory-only capture**

Use `bytearray` buffers only. Reject non-frame-aligned PCM, cap memory before append,
copy one terminal utterance to the caller and overwrite/clear internal buffers in a
`finally` path. The VAD runner receives fixed 16 kHz float32 frames and maps every model
error to `voice_model_unavailable`.

- [x] **Step 4: Run GREEN tests**

Run:

```bash
.venv-alpha/bin/python -m pytest -q tests/voice/test_vad.py tests/voice/test_capture.py tests/audio/test_source.py
.venv-alpha/bin/python -m compileall -q services/voice
git diff --check
```

Expected: focused voice and existing audio-source tests pass; no persistence API exists.

- [x] **Step 5: Commit Task 2**

```bash
git add services/voice/vad.py services/voice/capture.py tests/voice/test_vad.py tests/voice/test_capture.py
git commit -m "feat: collect bounded voice utterances"
```

### Task 3: Local Whisper Adapter, Exact Wake Gate And Public Benchmark

**Status:** Complete through `99eb8f7` and independently reviewed. The installed-i9
synthetic bake-off selected Whisper `base`; production Voice Care remains disabled until
the later worker, identity, Baby Care integration and supervised household gates pass.

**Files:**
- Create: `services/voice/asr.py`
- Create: `services/voice/wake.py`
- Create: `tools/voice_model_benchmark.py`
- Test: `tests/voice/test_asr.py`
- Test: `tests/voice/test_wake.py`
- Test: `tests/tools/test_voice_model_benchmark.py`
- Modify: `Makefile`

**Interfaces:**
- Produces: `AsrResult(text: str, language: str, duration_ms: int)`,
  `AsrEngine.transcribe(pcm: bytes) -> AsrResult`, and
  `validate_wake_prefix(text: str) -> WakeResult`.
- Wake success returns only the post-prefix command text. Failure returns a stable code
  and does not expose the transcript.

- [x] **Step 1: Write exact wake RED tests**

```python
@pytest.mark.parametrize("text", ["小小，我是爸爸", "  小小 我要喂奶了。"])
def test_exact_xiaoxiao_prefix_is_accepted(text: str) -> None:
    assert validate_wake_prefix(text).accepted is True


@pytest.mark.parametrize("text", ["嘿，小小，我是爸爸", "晓晓，我是爸爸", "我叫小小"])
def test_non_exact_prefix_fails_closed(text: str) -> None:
    result = validate_wake_prefix(text)
    assert result.accepted is False
    assert result.reason == "wake_not_detected"
```

- [x] **Step 2: Run RED tests**

Run: `.venv-alpha/bin/python -m pytest -q tests/voice/test_asr.py tests/voice/test_wake.py tests/tools/test_voice_model_benchmark.py`

Expected: FAIL because the ASR/wake modules do not exist.

- [x] **Step 3: Implement runner isolation and benchmark contract**

The ASR adapter accepts only validated local `base` or `small` artifacts, language
`zh`, no translation and no network. The benchmark consumes an explicitly public or
generated manifest, reports aggregate wake/slot accuracy and p50/p95 latency, and never
prints transcript text or paths. `base` wins only if it meets the same gate as `small`;
otherwise `small` wins. If neither passes, Voice Care remains disabled.

- [x] **Step 4: Run GREEN tests**

Run:

```bash
.venv-alpha/bin/python -m pytest -q tests/voice/test_asr.py tests/voice/test_wake.py tests/tools/test_voice_model_benchmark.py
make -n alpha-voice-model-benchmark
.venv-alpha/bin/python -m compileall -q services/voice tools/voice_model_benchmark.py
git diff --check
```

Expected: fake-runner and generated-signal tests pass without downloading models.

- [x] **Step 5: Run the installed-i9 model bake-off**

Before committing, explicitly install the ignored local artifacts and run the i9
bake-off:

```bash
make alpha-voice-models-install
make alpha-voice-model-benchmark
```

The benchmark generates and immediately discards 24 Mandarin positive commands and 48
negative utterances with the local macOS speech synthesizer at bounded rates. Required
software-gate results are 24/24 exact wake decisions, 0/48 false wakes, 24/24 typed slot
results and p95 ASR latency no greater than 3,000 ms for an utterance no longer than
eight seconds. `base` is selected only if it passes all four gates; otherwise `small`
must pass them. Neither passing leaves Voice Care disabled. This synthetic gate does not
prove household adult accuracy.

Fresh installed-i9 evidence: both pinned local sources converted in the isolated
NumPy/PyTorch conversion environment, the exact runtime bundles installed, and a clean
Torch-free runtime evaluated all 72 generated samples. `base` passed with 24/24 wake,
0/48 false wakes, 24/24 typed slots and p95 2,196 ms. `small` was rejected with one
false wake and p95 5,772 ms. Generated WAV files were held only in a temporary directory
and discarded; no household audio was used or persisted.

- [x] **Step 6: Commit Task 3 software slice**

```bash
git add services/voice/asr.py services/voice/wake.py tools/voice_model_benchmark.py tests/voice/test_asr.py tests/voice/test_wake.py tests/tools/test_voice_model_benchmark.py Makefile
git commit -m "feat: add exact local voice wake gate"
```

### Task 4: Baby Care-Owned VoiceCareIntentV1 Contract And Golden Corpus

**Files (Baby Care):**
- Create: `packages/contracts/src/voice-care/common.ts`
- Create: `packages/contracts/src/voice-care/intent.ts`
- Create: `packages/contracts/src/voice-care/responses.ts`
- Create: `packages/contracts/src/voice-care/index.ts`
- Create: `packages/contracts/voice-care-intent.v1.schema.json`
- Create: `packages/contracts/fixtures/voice-care/v1/valid.json`
- Create: `packages/contracts/fixtures/voice-care/v1/invalid.json`
- Modify: `packages/contracts/src/index.ts`
- Test: `packages/contracts/test/voice-care-contracts.test.ts`
- Modify: `agent.md`
- Modify: `summary.md`

**Interfaces:**
- Produces: Zod schemas and JSON Schema for `VoiceCareIntentV1`, the six V1 intent
  types, four closed `speakerState` values and eight semantic responses.
- Consumes: existing feeding component semantics and UUID/offset-time conventions.

- [ ] **Step 1: Write contract RED tests**

```typescript
it('rejects caller-owned family, baby, actor and transcript fields', () => {
  for (const forbidden of ['familyId', 'babyId', 'actorId', 'transcript', 'audio']) {
    expect(VoiceCareIntentV1Schema.safeParse({ ...validIntent, [forbidden]: 'x' }).success)
      .toBe(false);
  }
});
```

The valid corpus must cover takeover, feeding start/update/end, confirm and cancel. The
invalid corpus must cover unknown fields, malformed UUID/time/signature, wrong payload
shape, unsupported intent and non-verified final confirmation.

- [ ] **Step 2: Run RED tests**

Run: `pnpm --filter @baby-care/contracts test -- voice-care-contracts.test.ts`

Expected: FAIL because Voice Care schemas do not exist.

- [ ] **Step 3: Implement strict Zod and JSON Schema contracts**

Use discriminated unions. `feeding_end` requires either bottle liquid type plus actual
consumed integer ml, or direct-breastfeeding integer minutes; it never accepts inferred
ml or bottle capacity as intake. Export the exact generated JSON Schema and keep fixture
parity in one test.

- [ ] **Step 4: Reconcile Baby Care voice prose**

Replace `嘿，小小` examples with exact-prefix `小小`. Replace lease-only identity prose
with the approved hybrid rule: explicit claim + local speaker verification + paired
profile binding + Baby Care permission/session state. Keep Voice Care outside M4.

- [ ] **Step 5: Run GREEN gates**

Run:

```bash
pnpm --filter @baby-care/contracts test
pnpm --filter @baby-care/contracts typecheck
pnpm lint
git diff --check
```

- [ ] **Step 6: Commit Task 4 and record its immutable source SHA**

```bash
git add agent.md summary.md packages/contracts/src/index.ts packages/contracts/src/voice-care packages/contracts/voice-care-intent.v1.schema.json packages/contracts/fixtures/voice-care packages/contracts/test/voice-care-contracts.test.ts
git commit -m "feat: publish voice care v1 contract"
```

### Task 5: Baby Care Device Pairing And Profile Binding

**Files (Baby Care):**
- Create: `migrations/0004_voice_care.sql`
- Modify: `apps/api/src/schema.ts`
- Create: `apps/api/src/voice-care/device-repository.ts`
- Create: `apps/api/src/voice-care/device-service.ts`
- Create: `apps/api/src/voice-care/device-auth.ts`
- Create: `apps/api/src/routes/voice-care-devices.ts`
- Modify: `apps/api/src/app.ts`
- Test: `apps/api/test/voice-care-device.integration.test.ts`

**Interfaces:**
- Produces: one-time pairing challenge, Ed25519 device binding, revocable
  `voiceProfileId -> family membership` binding and verified device request context.
- Consumes: M1 family/session authorization and Task 4 signing payload.

- [ ] **Step 1: Write RED integration tests**

Test Dad/Mom-only challenge creation, five-minute expiry, one-time consumption, invalid
signature, replay, revoked device/profile, cross-family profile and Nanny denial for
administrative pairing. Assert that no private key or embedding enters PostgreSQL.

- [ ] **Step 2: Run RED tests**

Run: `pnpm --filter @baby-care/api test -- voice-care-device.integration.test.ts`

Expected: FAIL because the migration and routes do not exist.

- [ ] **Step 3: Implement transactional pairing**

Store only device UUID, Ed25519 public key, family scope, capabilities, status and
timestamps. Store only opaque voice profile ID, membership binding and revocation state.
Challenges are random, hashed at rest, expire after five minutes and are consumed in the
same transaction that creates the binding. Use Node `crypto.verify` over the Task 4
canonical UTF-8 signing payload.

- [ ] **Step 4: Run GREEN gates and migration checks**

Run:

```bash
pnpm --filter @baby-care/api test -- voice-care-device.integration.test.ts migrations.integration.test.ts
pnpm typecheck
pnpm lint
git diff --check
```

- [ ] **Step 5: Commit Task 5**

```bash
git add migrations/0004_voice_care.sql migrations/meta apps/api/src/schema.ts apps/api/src/voice-care apps/api/src/routes/voice-care-devices.ts apps/api/src/app.ts apps/api/test/voice-care-device.integration.test.ts
git commit -m "feat: pair voice care devices"
```

### Task 6: Baby Local Vendored Contract And Deterministic Feeding Parser

**Files:**
- Create: `packages/contracts/vendor/voice-care-intent.v1.schema.json`
- Create: `packages/contracts/vendor/voice-care-v1-valid.json`
- Create: `packages/contracts/vendor/voice-care-v1-invalid.json`
- Create: `packages/contracts/voice_care.py`
- Create: `services/voice/intent.py`
- Test: `tests/contracts/test_voice_care.py`
- Test: `tests/voice/test_intent.py`

**Interfaces:**
- Produces: Python `VoiceCareIntentV1`, closed payload types and
  `parse_feeding_command(command: str, state: DialogueState) -> ParsedIntent`.
- Consumes: exact Task 4 Baby Care commit and SHA-256 recorded beside the vendored files.

- [x] **Step 1: Vendor exact contract files**

Copy only the committed JSON Schema and golden corpora from Task 4. Record repository,
full source commit and SHA-256 in module constants. Do not dynamically import another
checkout or download at runtime.

- [x] **Step 2: Write RED parity/parser tests**

```python
def test_formula_finish_requires_actual_consumed_ml() -> None:
    result = parse_feeding_command("喂完了，喝了六十毫升配方奶", feeding_state)
    assert result.intent_type == "feeding_end"
    assert result.payload == {"feedingKind": "bottle", "liquidType": "formula", "amountMl": 60}


def test_ambiguous_amount_fails_closed() -> None:
    assert parse_feeding_command("喂完了，喝了一些", feeding_state).reason == "intent_uncertain"
```

- [x] **Step 3: Implement a closed deterministic grammar**

Support only the approved feeding phrases and Chinese integers in a bounded range.
Reject free-form notes, medication, unknown units, inferred values and command/state
conflicts. The parser receives only the post-wake command and returns no model prose.

- [x] **Step 4: Run GREEN gates**

Run:

```bash
.venv-alpha/bin/python -m pytest -q tests/contracts/test_voice_care.py tests/voice/test_intent.py
.venv-alpha/bin/python -m compileall -q packages/contracts services/voice
git diff --check
```

- [x] **Step 5: Commit Task 6**

```bash
git add packages/contracts/vendor packages/contracts/voice_care.py services/voice/intent.py tests/contracts/test_voice_care.py tests/voice/test_intent.py
git commit -m "feat: parse closed voice feeding intents"
```

Completed 2026-08-23 at `84e9a17`. The authoritative Baby Care M5 corpus now combines
valid and invalid examples in `packages/contracts/voice-care/voice-care-v1.json`; that
newer committed layout supersedes this task's earlier split-corpus path examples. Exact
source bytes and SHA-256 match Baby Care commit `bb1337226c1948695159d14199c9bb73cdaf115a`.
Fresh evidence: 19 focused tests and 103 adjacent Voice Care tests passed, compilation
and diff checks passed, and the Baby Care read-only verifier returned `CONTRACT_OK`.

### Task 7: Local Speaker Enrollment, Keychain Storage And Hybrid Identity

**Files:**
- Create: `services/voice/keychain.py`
- Create: `services/voice/speaker.py`
- Create: `services/voice/enrollment.py`
- Test: `tests/voice/test_keychain.py`
- Test: `tests/voice/test_speaker.py`
- Test: `tests/voice/test_enrollment.py`

**Interfaces:**
- Produces: `SpeakerState`, `VoiceProfile`, `SpeakerVerifier.verify(pcm)`, and encrypted
  profile create/read/delete operations.
- Consumes: validated ECAPA artifact, explicit identity claim and an injected Keychain
  backend.

- [x] **Step 1: Write RED privacy and identity tests**

Cover verified, uncertain, mismatch and not-enrolled states; short/noisy/overlapping
audio; claim/profile conflict; encrypted local profile file mode 0600; deletion; and
absence of samples/transcripts from stored payloads and status.

- [x] **Step 2: Run RED tests**

Run: `.venv-alpha/bin/python -m pytest -q tests/voice/test_keychain.py tests/voice/test_speaker.py tests/voice/test_enrollment.py`

- [x] **Step 3: Implement the fail-closed boundary**

Use macOS Security.framework through a narrow adapter so secrets never appear in argv.
Protect the local embedding with an AES-GCM key stored in Keychain. Store ciphertext,
nonce, opaque profile ID, model version and bounded calibration only. Enrollment PCM is
discarded after embedding creation. No pickle is loaded by the production worker; the
installed speaker artifact must be converted and validated before enablement.

- [x] **Step 4: Run GREEN gates**

Run:

```bash
.venv-alpha/bin/python -m pytest -q tests/voice/test_keychain.py tests/voice/test_speaker.py tests/voice/test_enrollment.py
.venv-alpha/bin/python -m compileall -q services/voice
git diff --check
```

- [x] **Step 5: Commit Task 7**

```bash
git add services/voice/keychain.py services/voice/speaker.py services/voice/enrollment.py tests/voice/test_keychain.py tests/voice/test_speaker.py tests/voice/test_enrollment.py
git commit -m "feat: verify local caregiver voice profiles"
```

Software boundary completed 2026-08-23 at `e850b8d`. Fresh evidence: 18 focused,
121 adjacent Voice Care and 1,061 full Python tests passed; compile and diff checks
passed. The Intel macOS Security.framework adapter completed a read-only missing-item
probe without a CLI or Keychain mutation. The profile store uses AES-GCM, canonical
0600 files and closed tamper/symlink handling. Voice Care remains disabled: a converted,
validated ECAPA runtime, real Keychain create/delete, adult enrollment and household
accuracy are later installed/human gates. The originally planned `cryptography==50.0.0`
did not exist on official PyPI and was corrected to the available pinned `48.0.1`.

### Task 8: Baby Care Pending Feeding State And Final Voice Write

**Files (Baby Care):**
- Create: `migrations/0005_voice_care_sessions.sql`
- Modify: `apps/api/src/schema.ts`
- Modify: `packages/contracts/src/care/common.ts`
- Create: `apps/api/src/voice-care/session-repository.ts`
- Create: `apps/api/src/voice-care/session-service.ts`
- Create: `apps/api/src/routes/voice-care-intents.ts`
- Modify: `apps/api/src/care/care-event-repository.ts`
- Modify: `apps/api/src/care/feeding-write-service.ts`
- Modify: `apps/api/src/app.ts`
- Test: `apps/api/test/voice-care-feeding.integration.test.ts`

**Interfaces:**
- Produces: `/api/voice-care/intents` with closed semantic results
  `accepted_pending`, `saved`, `needs_identity`, `needs_confirmation`,
  `identity_mismatch`, `state_conflict`, `temporarily_unavailable`, `rejected`.
- Consumes: Task 4 contract and Task 5 verified device/profile context.

- [ ] **Step 1: Write RED transactional tests**

Cover takeover, start, update, bottle/direct end, explicit confirmation, cancel,
abandonment, duplicate request ID, out-of-order request, concurrent confirmation, profile
revocation and database rollback. Assert that only one confirmation creates a feeding
event and that it has `source=voice` with the server-derived actor.

- [ ] **Step 2: Run RED tests**

Run: `pnpm --filter @baby-care/api test -- voice-care-feeding.integration.test.ts`

- [ ] **Step 3: Implement pending state and source semantics**

Add `voice` to the PostgreSQL and Zod care-source enums. Extend care-event creation with
an explicit allow-listed source while preserving the existing manual default for PWA
routes. Require actor fields for both manual and voice. Pending Voice Care sessions are
separate rows; only `care_confirm` calls the existing feeding persistence transaction.
Request IDs are unique per paired device and duplicate delivery returns the winning
semantic result.

- [ ] **Step 4: Run GREEN and regression gates**

Run:

```bash
pnpm --filter @baby-care/api test -- voice-care-feeding.integration.test.ts feeding-bottle.integration.test.ts feeding-direct.integration.test.ts care-concurrency.integration.test.ts
pnpm test
pnpm typecheck
pnpm lint
git diff --check
```

- [ ] **Step 5: Commit Task 8**

```bash
git add migrations/0005_voice_care_sessions.sql migrations/meta apps/api/src/schema.ts packages/contracts/src/care/common.ts apps/api/src/voice-care apps/api/src/routes/voice-care-intents.ts apps/api/src/care/care-event-repository.ts apps/api/src/care/feeding-write-service.ts apps/api/src/app.ts apps/api/test/voice-care-feeding.integration.test.ts
git commit -m "feat: commit confirmed voice feeding sessions"
```

### Task 9: Baby Local Device Key, Signed Client And Restart-Safe Outbox

**Files:**
- Create: `services/voice/signing.py`
- Create: `services/voice/client.py`
- Create: `services/voice/outbox.py`
- Test: `tests/voice/test_signing.py`
- Test: `tests/voice/test_client.py`
- Test: `tests/voice/test_outbox.py`

**Interfaces:**
- Produces: Ed25519 device identity, canonical Task 4 signing bytes,
  `VoiceCareClient.send(intent) -> VoiceSemanticResponse`, and a bounded idempotent
  structured-intent queue.
- Consumes: Task 5 pairing endpoints and Task 8 intent endpoint.

- [x] **Step 1: Write RED signature/outbox tests**

Use the same fixed Ed25519 golden vector in Python and TypeScript. Test retry, duplicate,
expired intent, Baby Care outage, stale ambiguous intent and process restart. Assert the
SQLite queue contains only signed structured fields and never PCM, transcript, embedding
or endpoint credentials.

- [x] **Step 2: Run RED tests**

Run: `.venv-alpha/bin/python -m pytest -q tests/voice/test_signing.py tests/voice/test_client.py tests/voice/test_outbox.py`

- [x] **Step 3: Implement closed delivery**

Store the Ed25519 private key through Task 7 Keychain support. Canonicalize only the
closed contract fields and exclude `signature`. Use request ID idempotency, bounded
timeouts and a short structured queue retention. Never say saved while queued; stale or
ambiguous pending confirmations require reconciliation rather than auto-commit.

- [x] **Step 4: Run GREEN gates**

Run:

```bash
.venv-alpha/bin/python -m pytest -q tests/voice/test_signing.py tests/voice/test_client.py tests/voice/test_outbox.py
.venv-alpha/bin/python -m compileall -q services/voice
git diff --check
```

- [x] **Step 5: Commit Task 9**

```bash
git add services/voice/signing.py services/voice/client.py services/voice/outbox.py tests/voice/test_signing.py tests/voice/test_client.py tests/voice/test_outbox.py
git commit -m "feat: deliver signed voice care intents"
```

Completed 2026-08-24 at `b8f0002`. The i9 device seed remains behind the Task 7
Keychain boundary; canonical Ed25519 intent and pairing signatures match the fixed
Baby Care vector recorded at Baby Care commit `9b4f150`. The mode-0600 SQLite outbox
stores only AES-GCM ciphertext plus bounded delivery metadata, retries the exact signed
request ID across restart, and moves expired or unresolved delivery to reconciliation
without claiming a save. Fresh evidence: 27 focused, 108 adjacent Voice Care and 1,088
full Python tests passed; compile and diff checks passed. No real Keychain mutation,
Baby Care write, endpoint credential, household audio or production worker was used.

### Task 10: Fixed TTS, Independent Voice Worker And Deployment Gate

**Files:**
- Create: `services/voice/tts.py`
- Create: `services/voice/worker.py`
- Create: `tools/run_voice_worker.py`
- Create: `tools/voice_status.py`
- Create: `deploy/launchd/com.babymonitor.voice.plist.example`
- Modify: `tools/install_alpha_macos.sh`
- Modify: `tools/start_alpha.sh`
- Modify: `tools/stop_alpha.sh`
- Modify: `tools/test_guardian.sh`
- Modify: `Makefile`
- Test: `tests/voice/test_tts.py`
- Test: `tests/voice/test_worker.py`
- Test: `tests/deploy/test_voice_worker_deploy.py`

**Interfaces:**
- Produces: independent disabled-by-default Voice worker, bounded status and Make
  commands `alpha-voice-status`, `alpha-voice-test`, `alpha-voice-start` and
  `alpha-voice-stop`.
- Consumes: Tasks 1–3 and 6–9.

- [x] **Step 1: Write RED worker/TTS tests**

Assert exact response mapping, including `saved -> 好的，已经记录。` and
`temporarily_unavailable -> 我听到了，但还没有保存，请稍后确认。`. Feed text to the
macOS synthesizer through stdin, never argv. Test capture ducking before speech,
post-playback guard, bounded volume, cancellation and unavailable output. Worker/model
failure must not restart go2rtc, Dashboard, visual, gauge, environment or cry workers.

- [x] **Step 2: Run RED tests**

Run: `.venv-alpha/bin/python -m pytest -q tests/voice/test_tts.py tests/voice/test_worker.py tests/deploy/test_voice_worker_deploy.py`

- [x] **Step 3: Implement minimum worker and launchd ownership**

Compose the fixed audio decoder, VAD/capture, ASR/wake, parser, speaker verifier, signed
client and TTS. Keep `voice.enabled=false` by default. Status contains only stable state,
reason, timestamps and bounded aggregate latency; it excludes text, scores tied to a
person, paths and configuration. launchd owns only the Voice worker.

- [ ] **Step 4: Run focused and full Baby Local gates**

Run:

```bash
make alpha-voice-test
.venv-alpha/bin/python -m pytest -q
node --test tests/frontend/*.test.mjs
bash -n tools/install_alpha_macos.sh tools/start_alpha.sh tools/stop_alpha.sh tools/test_guardian.sh
make -n alpha-voice-status alpha-voice-test alpha-voice-start alpha-voice-stop
make alpha-guardian-test
git diff --check
```

Expected: software gates pass with Voice disabled, no real notification/care write and
no household audio access.

- [x] **Step 5: Commit Task 10**

```bash
git add services/voice/tts.py services/voice/worker.py tools/run_voice_worker.py tools/voice_status.py deploy/launchd/com.babymonitor.voice.plist.example tools/install_alpha_macos.sh tools/start_alpha.sh tools/stop_alpha.sh tools/test_guardian.sh Makefile tests/voice/test_tts.py tests/voice/test_worker.py tests/deploy/test_voice_worker_deploy.py
git commit -m "feat: run independent local voice care worker"
```

Software boundary committed 2026-08-24 at `31e8332`. Fixed semantic phrases, stdin-only
macOS synthesis, 0.35 playback volume, capture ducking/guard, cancellation, the in-memory
ASR/wake/claim/speaker/parser/sign/outbox composition, bounded status and one independent
interactive launchd job are implemented. Fresh evidence: Voice 140 passed, frontend 73
passed, deployment/Guardian focused 133 passed and full Python 1,106 passed; shell syntax,
plist lint, Make dry-run, compile and diff checks passed. The exact installed
`make alpha-guardian-test` was also run and reported 13 PASS / 6 FAIL because this
isolated worktree intentionally has no `.local` go2rtc app, private runtime settings,
installed launchd definitions or realtime-model bundle. Source and sibling services
passed. Step 4 remains open until this exact head is deployed to the actual i9 checkout
and that installed gate is rerun; Voice remains disabled and no real TTS/care write ran.

### Task 11: Cross-Repository Synthetic Gate V1

**Files:**
- Modify: Baby Local `SUMMARY.md`, `docs/STATUS.md`, `docs/CHECKPOINT.md`, `docs/NEXT.md`
- Modify: Baby Care `summary.md`, `.agent/current-milestone.json`, `docs/PLAN.md`
- Create: Baby Care `apps/api/test/voice-care-cross-product.integration.test.ts`
- Create: Baby Local `tests/integration/test_voice_care_cross_product.py`

**Interfaces:**
- Consumes: exact heads from Tasks 4–10 and the same schema/golden corpus.
- Produces: Gate V1 evidence for synthetic wake through committed feeding, correction,
  cancellation, failure and privacy paths.

- [x] **Step 1: Run contract digest parity**

Verify Baby Local's vendored schema and fixtures byte-for-byte against the recorded Baby
Care source commit and SHA-256. Any mismatch is a closed gate failure.

- [x] **Step 2: Run the synthetic closed loop**

Exercise generated/fake audio through VAD, exact wake, ASR result, explicit claim,
speaker verification, signed takeover, feeding start/end, readback confirmation and one
authoritative Baby Care write. Repeat for direct breastfeeding, correction, cancel,
identity mismatch, duplicate delivery and Baby Care outage. No infant or household audio
is required. The correction case uses Baby Care's existing authenticated revision route
after a Voice-created record; it does not invent a seventh V1 voice intent.

- [x] **Step 3: Run both full software gates**

Baby Local:

```bash
.venv-alpha/bin/python -m pytest -q
node --test tests/frontend/*.test.mjs
make alpha-guardian-test
git diff --check
```

Baby Care:

```bash
pnpm lint
pnpm typecheck
pnpm test
pnpm build
git diff --check
```

- [x] **Step 4: Inspect privacy and side effects**

Scan both tracked diffs and test databases for audio/media files, transcripts,
embeddings, credentials, private addresses and raw model output. Confirm manual Baby
Care recording and all independent Baby Local workers remain available when Voice is
disabled or failed.

- [ ] **Step 5: Update authoritative status and commit separately**

Commit each repository's own status changes on its own feature branch. Record both full
local HEADs and exact CI run IDs. Do not claim V2 household accuracy, merge, tag or
release.

**Gate V1 completion:** software evidence proves contract, security, privacy,
idempotency and the synthetic end-to-end loop. It does not prove Dad/Mom household
speaker accuracy, quiet-night accuracy, camera backchannel, cry detection or unattended
care. Those remain Gate V2 or later human-supervised gates.

Local Gate V1 implementation is committed at Baby Local `e4cd5d5` and Baby Care
`bca9b9e`. Fresh local evidence is contract digest 5/5, cross-product 2/2 in each
repository, Baby Local full Python 1,108 and frontend 73, and Baby Care Node 24 full 458
passed / 115 opt-in skipped with lint/typecheck/build plus real PostgreSQL 16 2/2. The
installed Baby Local gate remains 13 PASS / 6 FAIL in the isolated worktree because
private installation/model assets are absent. Step 5 stays open until both branches are
pushed, exact CI run IDs are recorded and the accepted Baby Local head is deployed to
the actual i9 checkout for installed readiness. Voice remains disabled.
