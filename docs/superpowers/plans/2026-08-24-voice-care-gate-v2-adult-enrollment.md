# Voice Care Gate V2 Adult Enrollment Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Deliver a private, memory-only Intel i9 enrollment path for Dad and Mom with
one-time spoken challenges, isolated encrypted profiles and conservative ECAPA quality
gates, while Voice Care remains disabled.

**Architecture:** Extend the existing Task 7 Keychain/profile boundary rather than
creating another identity store. Each opaque profile owns a distinct Keychain secret;
an ignored mode-0600 registry maps only `dad`/`mom` to opaque IDs. A one-time in-memory
challenge must match local Whisper output before a bounded ECAPA observation may enter
enrollment. The operator command reads the fixed Xiaomi audio alias directly into
bounded memory, never a file, and closes every model/decoder on all exits.

**Tech Stack:** Python 3.11, macOS Security.framework, AES-GCM, NumPy, local
faster-whisper `base`, local SpeechBrain ECAPA, FFmpeg, pytest, Make.

**Spec:** `docs/superpowers/specs/2026-08-19-voice-care-v1-design.md`

## Global Constraints

- Run only on Darwin `x86_64`; Linux CI uses fakes and synthetic PCM.
- Keep `VoiceCareSettings.enabled=false` before, during and after enrollment.
- Never persist raw PCM, generated or household audio, transcript, challenge response,
  embedding plaintext, Keychain secret, model output or local address, except for the
  Task 5 operator-approved encrypted fixed-phrase calibration corpus defined below.
- Never write Baby Care, pair a device, create a care fact or start the Voice worker.
- Dad/Mom are the only local enrollment roles; role is not authorization.
- Every failure emits one stable code and leaves no new usable profile or false success.
- No anti-spoof or overlap model and no new training is introduced. One-time phrase
  freshness plus three whole-utterance ECAPA consistency checks are enrollment gates,
  not proof against arbitrary replay or automatic multi-speaker detection.
- Automatic overlap state remains fail-closed (`unknown`). Only the explicitly
  human-supervised Dad/Mom enrollment operator may assert one speaker; Voice stays
  disabled until the later overlap acceptance gate is separately satisfied.
- Do not lower identity or overlap standards when a synthetic or real test fails.

---

### Task 1: Isolate Dad And Mom Profile Secrets

**Files:**
- Modify: `services/voice/enrollment.py`
- Modify: `tests/voice/test_enrollment.py`

**Interfaces:**
- Consumes: `KeychainSecretStore` and canonical UUID profile IDs.
- Produces: `VoiceProfileStore(path, keychain, profile_id: str)` where the exact profile
  owns Keychain account `voice-profile-key.v1.<uuid>` and delete affects only that key.

- [x] **Step 1: Write multi-profile RED tests**

```python
dad = VoiceProfileStore(dad_path, secrets, boundary=root, profile_id=DAD_ID)
mom = VoiceProfileStore(mom_path, secrets, boundary=root, profile_id=MOM_ID)
dad.create(profile(DAD_ID))
mom.create(profile(MOM_ID))
dad.delete()
assert mom.read() == profile(MOM_ID)
assert dad_key not in backend.values
assert mom_key in backend.values
```

Also reject a noncanonical ID, a profile/path ID mismatch, a symlinked parent and
creation when either the profile or its exact Keychain item already exists.

- [x] **Step 2: Run RED tests**

Run:

```bash
.venv-alpha/bin/python -m pytest -q tests/voice/test_enrollment.py
```

Expected: FAIL because `VoiceProfileStore` still shares one fixed Keychain account and
does not bind a store to one opaque profile ID.

- [x] **Step 3: Implement per-profile ownership**

```python
def _profile_key_account(profile_id: str) -> str:
    canonical = str(UUID(profile_id))
    if canonical != profile_id:
        raise ValueError(PROFILE_UNAVAILABLE)
    return f"voice-profile-key.v1.{canonical}"
```

Validate the ID in the constructor, require `profile.profile_id == self._profile_id`,
derive the account for create/read/delete, and preserve exclusive 0600 publication.
Do not add fallback reads for the old shared account because no real profile was ever
accepted under it.

- [x] **Step 4: Run GREEN and adjacent privacy tests**

Run:

```bash
.venv-alpha/bin/python -m pytest -q tests/voice/test_enrollment.py tests/voice/test_keychain.py tests/voice/test_speaker.py
.venv-alpha/bin/python -m compileall -q services/voice/enrollment.py
git diff --check
```

- [x] **Step 5: Commit Task 1**

```bash
git add services/voice/enrollment.py tests/voice/test_enrollment.py
git commit -m "fix: isolate caregiver profile secrets"
```

### Task 2: One-Time Enrollment Phrase Challenge

**Files:**
- Create: `services/voice/challenge.py`
- Create: `tests/voice/test_challenge.py`

**Interfaces:**
- Produces: `EnrollmentChallenge`, `EnrollmentChallengeSession.issue()` and
  `EnrollmentChallengeSession.consume(challenge_id, transcript)`.
- Consumes: an injected monotonic clock, secure token generator and digit chooser.

- [x] **Step 1: Write challenge RED tests**

```python
challenge = session.issue()
assert challenge.phrase.startswith("小小，我要说口令")
assert session.consume(challenge.challenge_id, challenge.phrase) is True
assert session.consume(challenge.challenge_id, challenge.phrase) is False
```

Cover 60-second expiry, wrong phrase, old challenge after a newer issue, Unicode
normalization, punctuation-only tolerance, Arabic-to-Chinese digit normalization,
unknown IDs, and stable `voice_enrollment_challenge_failed` errors without transcript
or token in exceptions/repr.

- [x] **Step 2: Run RED tests**

Run:

```bash
.venv-alpha/bin/python -m pytest -q tests/voice/test_challenge.py
```

Expected: FAIL because the challenge module does not exist.

- [x] **Step 3: Implement the in-memory challenge**

```python
@dataclass(frozen=True)
class EnrollmentChallenge:
    challenge_id: str
    phrase: str

class EnrollmentChallengeSession:
    def issue(self) -> EnrollmentChallenge:
        digits = four_unique_digits(self._choose)
        challenge = EnrollmentChallenge(self._token(), f"小小，我要说口令{digits}")
        self._active = (challenge.challenge_id, _normalize(challenge.phrase),
                        self._clock() + 60.0)
        return challenge

    def consume(self, challenge_id: str, transcript: str) -> bool:
        active, self._active = self._active, None
        return bool(active and self._clock() <= active[2]
                    and challenge_id == active[0]
                    and _normalize(transcript) == active[1])
```

Generate four non-repeating digits from the fixed Chinese digit table, store only one
active expected normalized phrase plus expiry in memory, and consume it before checking
the transcript so every attempt is one-shot. Never log or persist the transcript.

- [x] **Step 4: Run GREEN and static checks**

Run:

```bash
.venv-alpha/bin/python -m pytest -q tests/voice/test_challenge.py
.venv-alpha/bin/python -m compileall -q services/voice/challenge.py
git diff --check
```

- [x] **Step 5: Commit Task 2**

```bash
git add services/voice/challenge.py tests/voice/test_challenge.py
git commit -m "feat: add one-time voice enrollment challenges"
```

### Task 3: Conservative ECAPA Speaker Observation Adapter

**Files:**
- Create: `services/voice/speaker_runtime.py`
- Create: `tests/voice/test_speaker_runtime.py`
- Verify: `services/voice/ecapa.py`
- Verify: `tests/voice/test_ecapa.py`

**Interfaces:**
- Consumes: one owned `EcapaProcess`, validated float32 mono samples and an explicit
  human-supervision flag used only by the private enrollment operator.
- Produces: `EcapaObservationRunner(samples) -> EmbeddingObservation` and `close()`.

- [x] **Step 1: Write observation RED tests**

```python
runner = EcapaObservationRunner(process=fake_process)
observed = runner(samples_with_quiet_edges_and_one_speaker())
assert len(observed.embedding) == 192
assert observed.speech_seconds >= 0.8
assert observed.snr_db >= 8.0
assert observed.overlap_probability <= 0.10
```

Require at least 1.6 seconds of detected active speech and one full-utterance embedding.
Without explicit human supervision the overlap state remains unknown and fails closed.
Short input, flat/quiet input, malformed embeddings, timeout and closed process must
fail closed; `close()` is idempotent. Tests use synthetic PCM and fixed fake embeddings
only.

- [x] **Step 2: Run RED tests**

Run:

```bash
.venv-alpha/bin/python -m pytest -q tests/voice/test_speaker_runtime.py tests/voice/test_ecapa.py
```

Expected: FAIL because the production `EmbeddingRunner` adapter does not exist.

- [x] **Step 3: Implement bounded temporal quality**

```python
class EcapaObservationRunner:
    def __call__(self, samples: np.ndarray) -> EmbeddingObservation:
        checked = _validated_samples(samples)
        full = self._process.embed(_pcm_bytes(checked)).embedding
        speech_seconds, snr_db = _signal_quality(checked)
        return EmbeddingObservation(full, speech_seconds, snr_db,
                                    0.0 if supervised else 1.0)

    def close(self) -> None:
        self._process.close()
```

Reject anything outside 1.6–8.0 seconds of active speech. Compute 20 ms RMS frames and
use bounded lower and upper percentiles for an SNR estimate. Embed only the full
utterance; `VoiceEnrollment` compares all three enrollment utterances. An installed-i9
synthetic diagnostic proved phonetic 0.8-second window variance is not a valid overlap
estimator because it falsely rejected one speaker, so unsupervised overlap remains
closed rather than fabricating a probability. Return no latency, segment vector or
private diagnostic in the observation.

- [x] **Step 4: Run GREEN and adjacent identity gates**

Run:

```bash
.venv-alpha/bin/python -m pytest -q tests/voice/test_speaker_runtime.py tests/voice/test_ecapa.py tests/voice/test_speaker.py tests/voice/test_enrollment.py
.venv-alpha/bin/python -m compileall -q services/voice/ecapa.py services/voice/speaker_runtime.py
git diff --check
```

- [x] **Step 5: Commit Task 3**

```bash
git add services/voice/speaker_runtime.py tests/voice/test_speaker_runtime.py
git commit -m "feat: derive bounded ECAPA speaker quality"
```

### Task 4: Memory-Only Live Enrollment Operator

**Files:**
- Create: `services/voice/live_enrollment.py`
- Create: `tools/voice_enroll.py`
- Create: `tests/voice/test_live_enrollment.py`
- Create: `tests/tools/test_voice_enroll.py`
- Modify: `services/audio/source.py`
- Modify: `services/voice/enrollment.py`
- Modify: `services/voice/speaker_runtime.py`
- Modify: `tests/audio/test_source.py`
- Modify: `Makefile`
- Modify: `tests/deploy/test_alpha_commands.py`

**Interfaces:**
- Produces: `make alpha-voice-enroll-dad`, `make alpha-voice-enroll-mom` and aggregate
  only `result=PASS|FAIL`, `role=dad|mom`, `sample_count`, `profile_state`,
  `raw_audio_persisted=false`; a failure may additionally expose only the fixed stage
  enum `preflight|capture|asr|challenge|speaker|storage`.
- Consumes: fixed Xiaomi `audio_analysis`, local Whisper base, Tasks 1–3, macOS
  Keychain and terminal confirmation before each prompted phrase.

- [x] **Step 1: Write operator RED tests**

```python
result = run_enrollment(role="dad", capture=fake_capture, asr=fake_asr,
                        challenges=fake_challenges, runner=fake_runner,
                        store=fake_store, confirm=fake_confirm)
assert result.sample_count == 3
assert fake_capture.persisted_paths == []
```

Cover Dad/Mom only, Voice enabled rejection, challenge mismatch/replay, capture timeout,
ASR/ECAPA/Keychain failure, SIGINT/SIGTERM cleanup, existing-role refusal, exclusive
profile/registry publication and redacted output. No test may use household media.

- [x] **Step 2: Run RED tests**

Run:

```bash
.venv-alpha/bin/python -m pytest -q tests/voice/test_live_enrollment.py tests/tools/test_voice_enroll.py tests/deploy/test_alpha_commands.py
```

Expected: FAIL because the live enrollment coordinator and Make commands do not exist.

- [x] **Step 3: Implement fixed memory-only capture and enrollment**

Expose the existing fixed FFmpeg command builder from `services/audio/source.py` so the
operator does not duplicate the loopback endpoint. Extend the decoder with an optional
selector-backed bounded read and collect exactly bounded 16 kHz mono s16le bytes with
a hard deadline, keeping all PCM in bytearrays and
zeroing them on every exit. For each of three one-time challenges: print the public
prompt, wait for explicit Enter, capture one utterance, require local Whisper to match,
then pass PCM to `VoiceEnrollment`. Publish the encrypted profile and a mode-0600
role-to-opaque-ID registry only after all three samples pass. On failure, publish neither.

- [x] **Step 4: Run software and installed dry gates**

Run:

```bash
.venv-alpha/bin/python -m pytest -q tests/voice/test_live_enrollment.py tests/tools/test_voice_enroll.py tests/audio/test_source.py tests/deploy/test_alpha_commands.py
.venv-alpha/bin/python -m compileall -q services/audio services/voice tools/voice_enroll.py
make -n alpha-voice-enroll-dad alpha-voice-enroll-mom
make alpha-voice-test
git diff --check
```

Do not run either real enrollment command in this step.

- [x] **Step 5: Commit Task 4**

```bash
git add services/audio/source.py services/voice/enrollment.py services/voice/live_enrollment.py services/voice/speaker_runtime.py tools/voice_enroll.py Makefile tests/audio/test_source.py tests/voice/test_enrollment.py tests/voice/test_live_enrollment.py tests/voice/test_speaker_runtime.py tests/tools/test_voice_enroll.py tests/deploy/test_alpha_commands.py docs/superpowers/plans/2026-08-24-voice-care-gate-v2-adult-enrollment.md
git commit -m "feat: add private adult voice enrollment"
```

### Task 5: Installed i9 ASR Accuracy Gate

**Status:** In progress. This gate now blocks enrollment and speaker verification.

**Goal:** Prove accurate camera-to-text behavior before any voice identity work. Capture
one bounded supervised corpus of fixed adult test phrases, encrypt it locally, and reuse
the same clips for fair Whisper candidate and preprocessing comparisons.

**Constraints:** Maximum 20 clips, eight seconds each; fixed displayed phrases only;
dedicated Keychain encryption; ignored mode-0600 files; no free-form transcript, raw
audio log, Baby Care write, Voice enablement or automatic deletion.

- [x] Implement and test the encrypted private ASR calibration corpus.
- [x] Implement the registry-validated Silero v6.2 segmentation runtime and bounded
  capture command with aggregate signal/VAD diagnostics.
- [x] Capture one supervised six-phrase corpus on the Xiaomi/i9 path. The ignored
  ciphertext contains six distinct fixed prompt IDs, uses a dedicated Keychain key and
  has mode 0600 under a mode-0700 parent.
- [x] Establish the first exact baseline: base 4/6 exact, wake 6/6, P95 1,138 ms;
  small 1/6 exact, wake 6/6, P95 3,818 ms. Both fail; Voice remains disabled.
- [ ] Complete Tasks 5A-5D below, then record aggregate evidence only. Keep enrollment
  blocked on any Keychain, ASR or Silero failure.

#### Task 5A: Stable Non-Interactive Keychain Identity

**Files:**
- Create: `tools/native/voice_keychain_helper.c`
- Create: `tools/voice_keychain_helper_build.py`
- Create: `tools/voice_keychain_probe.py`
- Create: `tools/voice_keychain_migrate.py`
- Create: `tools/authorize_voice_keychain.command`
- Create: `services/voice/helper_keychain.py`
- Create: `tests/voice/test_helper_keychain.py`
- Create: `tests/monitoring/test_voice_keychain_helper_build.py`
- Create: `tests/tools/test_voice_keychain_probe.py`
- Create: `tests/tools/test_voice_keychain_migrate.py`
- Create: `tests/deploy/test_voice_keychain_authorize.py`
- Modify: `services/voice/keychain.py`
- Modify: `tools/voice_asr_calibrate.py`
- Modify: `tools/voice_enroll.py`
- Modify: `tools/install_alpha_macos.sh`
- Modify: `tools/test_guardian.sh`
- Modify: `Makefile`
- Modify: `tests/deploy/test_alpha_commands.py`

**Interfaces:**
- Produces: ignored `.local/VoiceKeychainHelper.app`, fixed bundle identifier
  `com.babymonitor.voice-keychain-helper`, explicit stable designated requirement and
  `HelperKeychainBackend.read(service, account)`, `write(service, account, secret)` and
  `delete(service, account)`.
- Consumes: fixed service `com.baby-monitor-local.voice-care`, 32-byte secrets and only
  the existing fixed Voice account names/prefixes.

- [x] **Step 1: Write helper protocol and path RED tests**

Use a fake subprocess with a real anonymous stdin/stdout pipe. Assert a binary bounded
request/response, exact service rejection before spawn, fixed 32-byte secrets, unknown
account rejection, truncated/overlong response rejection, timeout termination and no
secret in argv, environment, exception or repr. Mutating the implementation to accept
an arbitrary service/account or print a secret must fail these tests.

```python
backend = HelperKeychainBackend(helper, opener=fake_opener)
backend.write(VOICE_KEYCHAIN_SERVICE, "voice-asr-calibration-key.v2", b"k" * 32)
assert fake.argv == (str(helper),)
assert b"k" * 32 in fake.stdin_payload
assert b"k" * 32 not in repr(fake.argv)
```

- [x] **Step 2: Run RED tests**

```bash
.venv-alpha/bin/python -m pytest -q tests/voice/test_helper_keychain.py tests/monitoring/test_voice_keychain_helper_build.py
```

Expected: FAIL because the signed helper builder/backend do not exist.

- [x] **Step 3: Implement the minimum native helper and Python backend**

The C helper must use Security.framework directly and a fixed binary protocol. It
refuses TTY stdin/stdout, fixes the service internally, accepts only
`voice-asr-calibration-key.v2`, `device-signing-key.v1`, `voice-outbox-key.v1` and
`voice-profile-key.v1.<canonical UUID>`, bounds all messages to 4 KiB and zeroes secret
buffers before exit. Python always starts it with `stdin=PIPE`, `stdout=PIPE`,
`stderr=DEVNULL`, an empty fixed environment and a five-second deadline. Build it with
the system clang, wrap it in the fixed app bundle and sign using an explicit designated
requirement derived from the bundle identifier, following the existing Go2RTC app
identity pattern.

```python
def keychain_for_runtime(root: Path) -> KeychainSecretStore:
    helper = root / ".local/VoiceKeychainHelper.app/Contents/MacOS/voice-keychain-helper"
    return KeychainSecretStore(HelperKeychainBackend(helper, boundary=root))
```

- [x] **Step 4: Run software, build and identity GREEN gates**

```bash
.venv-alpha/bin/python -m pytest -q tests/voice/test_helper_keychain.py tests/voice/test_keychain.py tests/monitoring/test_voice_keychain_helper_build.py tests/deploy/test_alpha_commands.py
.venv-alpha/bin/python -m compileall -q services/voice/helper_keychain.py tools/voice_keychain_helper_build.py
make alpha-voice-keychain-helper-build
codesign --verify --deep --strict .local/VoiceKeychainHelper.app
codesign -d -r- .local/VoiceKeychainHelper.app
git diff --check
```

- [x] **Step 5: Prove the existing corpus key is readable through the stable identity**

Run one aggregate-only helper probe from the logged-in i9 session. The operator may
approve the stable helper once. Then run the same probe through the installed user
launchd context and require both to return `key_state=available`, `key_bytes=32` without
printing the key, path or account. A second run must require no new approval. Do not
delete or replace the existing corpus/key.

Evidence on 2026-08-24: the fixed migration copied the identical 32-byte v1 value to
helper-owned v2 without rewriting the encrypted corpus or deleting v1. The signed
helper requirement verified as `com.babymonitor.voice-keychain-helper`. A one-shot
`gui/501` launchd probe ran twice with exit 0 and returned only
`key_state=available`, `key_bytes=32`; the probe job was then unloaded. The complete
Voice software gate passed 223 tests. Direct Codex execution remains unable to read the
login Keychain because its managed execution context is restricted; that is not used
as production evidence and does not override the successful launchd gate.

- [x] **Step 6: Commit Task 5A**

```bash
git add tools/native/voice_keychain_helper.c tools/voice_keychain_helper_build.py tools/voice_keychain_probe.py tools/voice_keychain_migrate.py tools/authorize_voice_keychain.command services/voice/helper_keychain.py services/voice/keychain.py tools/voice_asr_calibrate.py tools/voice_enroll.py tools/install_alpha_macos.sh tools/test_guardian.sh Makefile tests/voice/test_helper_keychain.py tests/monitoring/test_voice_keychain_helper_build.py tests/tools/test_voice_keychain_probe.py tests/tools/test_voice_keychain_migrate.py tests/deploy/test_voice_keychain_authorize.py tests/deploy/test_alpha_commands.py docs/superpowers/specs/2026-08-19-voice-care-v1-design.md docs/superpowers/plans/2026-08-24-voice-care-gate-v2-adult-enrollment.md
git commit -m "feat: add stable Voice Keychain identity"
```

#### Task 5B: One-Shot ASR Decode Bake-Off

**Files:**
- Modify: `services/voice/asr.py`
- Modify: `services/voice/asr_calibration.py`
- Modify: `tools/voice_asr_calibrate.py`
- Modify: `tests/voice/test_asr.py`
- Modify: `tests/voice/test_asr_calibration.py`
- Modify: `tests/tools/test_voice_asr_calibrate.py`

**Interfaces:**
- Produces: closed `AsrDecodeProfile` values `baseline`, `no_hotwords`,
  `care_hotwords` and `care_hotwords_beam10`, plus one aggregate bake-off report.
- Consumes: the same six decrypted clips in memory; no profile receives the current
  prompt text or expected transcript.

- [x] **Step 1: Write RED profile and privacy tests**

Assert exact runner options for all four closed profiles, reject arbitrary options and
ensure reports contain only model/profile, public prompt IDs, edit distance, exact/wake
counts and latency. Include a numeric-form classifier (`90` versus `九十`) that reports
the category but leaves `exact=False`.

```python
report = evaluator.evaluate_profiles((BASELINE, NO_HOTWORDS, CARE_HOTWORDS, CARE_BEAM10))
assert report.candidates[0].mismatch_prompt_ids == ("feeding_amount",)
assert report.candidates[0].numeric_form_only_count == 1
assert report.candidates[0].passed is False
assert "90" not in repr(report)
```

- [x] **Step 2: Run RED tests**

```bash
.venv-alpha/bin/python -m pytest -q tests/voice/test_asr.py tests/voice/test_asr_calibration.py tests/tools/test_voice_asr_calibrate.py
```

- [x] **Step 3: Implement the closed matrix**

Use the baseline exactly as recorded. `no_hotwords` removes only the global hotword
argument. `care_hotwords` uses one fixed vocabulary containing the wake word, caregiver,
feeding, quantity, cancellation and negative-control terms. `care_hotwords_beam10`
changes only `beam_size=10`. Do not add `initial_prompt`, `prefix`, per-clip hotwords,
post-ASR phrase replacement or fuzzy wake matching. Select only a candidate with 6/6
exact, 6/6 wake and P95 at most 3,000 ms.

- [x] **Step 4: Run GREEN and the real one-shot bake-off**

```bash
.venv-alpha/bin/python -m pytest -q tests/voice/test_asr.py tests/voice/test_asr_calibration.py tests/tools/test_voice_asr_calibrate.py
make alpha-voice-asr-bakeoff
```

If no candidate passes, keep Voice disabled and stop this task with an explicit
`asr_candidate_unavailable`; do not add another profile. A different model family then
requires a separate approved model/license amendment.

Evidence on 2026-08-24: the launchd one-shot matrix completed all eight candidates and
returned `asr_candidate_unavailable`. Baseline base remained 4/6 exact, 6/6 wake and
P95 1,260 ms. The best bounded candidates were base `care_hotwords` and
`care_hotwords_beam10`, both 5/6 exact and 6/6 wake with P95 2,246 ms and 2,145 ms;
both missed only public prompt ID `feeding_start_dad` with aggregate edit distance 2.
Every small candidate failed accuracy and exceeded the latency gate. Voice remains
disabled; no fifth profile or per-prompt correction was added.

- [x] **Step 5: Commit Task 5B**

```bash
git add services/voice/asr.py services/voice/asr_calibration.py tools/voice_asr_calibrate.py tests/voice/test_asr.py tests/voice/test_asr_calibration.py tests/tools/test_voice_asr_calibrate.py Makefile
git commit -m "feat: run bounded local ASR bakeoff"
```

#### Task 5C: Silero Runtime And Xiaomi Signal Gate

**Files:**
- Modify: `services/voice/silero_runtime.py`
- Create: `services/voice/vad_diagnostic.py`
- Create: `tools/voice_vad_diagnostic.py`
- Modify: `tests/voice/test_silero_runtime.py`
- Create: `tests/voice/test_vad_diagnostic.py`
- Create: `tests/tools/test_voice_vad_diagnostic.py`
- Modify: `Makefile`

**Interfaces:**
- Produces: aggregate-only `make alpha-voice-vad-diagnostic` with control/private
  signal level, probability and span counts; optional fixed `VadGainPreprocessor` capped
  at +12 dB for VAD input only.
- Consumes: one generated non-household Mandarin control and the six encrypted clips in
  memory through Task 5A.

- [x] **Step 1: Write RED control, signal and gain-bound tests**

Assert the official input/state/context shapes, state reset between clips, finite
probabilities, exact 0.50 speech threshold, aggregate-only output and deterministic
gain capped at +12 dB without clipping. ASR bytes and corpus ciphertext must remain
unchanged.

- [x] **Step 2: Run RED tests**

```bash
.venv-alpha/bin/python -m pytest -q tests/voice/test_silero_runtime.py tests/voice/test_vad_diagnostic.py tests/tools/test_voice_vad_diagnostic.py
```

- [x] **Step 3: Implement diagnostic-first decision logic**

First run unmodified Silero on both control and private clips. If the control returns no
span, correct only the ONNX state/context contract. If the control returns one span per
utterance while private clips return none and private RMS is at least 12 dB lower, run
the fixed +12 dB-or-less non-clipping preprocessor for VAD only. Never lower the 0.50
threshold, rewrite the stored corpus or pass gained PCM to ASR/ECAPA.

- [x] **Step 4: Run GREEN and real aggregate gate**

```bash
.venv-alpha/bin/python -m pytest -q tests/voice/test_silero_runtime.py tests/voice/test_vad_diagnostic.py tests/tools/test_voice_vad_diagnostic.py
make alpha-voice-vad-diagnostic
```

Require six private prompts with exactly one bounded span each plus a passing generated
control. Otherwise return `vad_candidate_unavailable` and keep Voice disabled.

Evidence on 2026-08-24: the generated Mandarin control passed with one span and peak
probability 1.000. Five private prompt IDs produced exactly one span; public prompt ID
`negative_weather` produced two. Private RMS ranged from -16.713 to -14.700 dBFS,
which was not 12 dB below the -18.053 dBFS control, so the bounded gain branch correctly
did not run. The gate returned `vad_candidate_unavailable`; threshold 0.50, corpus
ciphertext and ASR input bytes remained unchanged and Voice stayed disabled.

- [x] **Step 5: Commit Task 5C**

```bash
git add services/voice/silero_runtime.py services/voice/vad_diagnostic.py tools/voice_vad_diagnostic.py tests/voice/test_silero_runtime.py tests/voice/test_vad_diagnostic.py tests/tools/test_voice_vad_diagnostic.py Makefile
git commit -m "fix: validate Xiaomi speech segmentation"
```

#### Task 5E: Approved Paraformer Mandarin ASR Amendment

**Files:**
- Modify: `packages/contracts/settings.py`
- Modify: `services/voice/artifacts.py`
- Create: `services/voice/paraformer.py`
- Create: `tools/voice_asr_environment.py`
- Create: `tools/voice_asr_install.py`
- Create: `tools/voice_paraformer_runner.py`
- Create: `tools/voice_paraformer_source.py`
- Create: `config/voice-asr-requirements.txt`
- Modify: `services/voice/asr_calibration.py`
- Modify: `tools/voice_asr_calibrate.py`
- Modify: `Makefile`
- Modify: focused tests under `tests/contracts/`, `tests/voice/` and `tests/tools/`

**Interfaces:**
- Consumes: the manifest-validated Apache-2.0 Paraformer INT8 model at revision
  `def027084691107096b5ebba69785756d63de6c5`, ignored `runtime/voice-asr-venv`, and
  the unchanged six-clip encrypted corpus through the helper-owned Keychain v2 item.
- Produces: `ParaformerProcess.transcribe(pcm: bytes) -> AsrResult`, the fixed framed
  child protocol, and `make alpha-voice-asr-paraformer` aggregate-only acceptance.

- [x] **Step 1: Add registry, settings and isolated-environment RED tests**

Require artifact ID `sherpa-onnx-paraformer-zh-2023-09-14`, only
`model.int8.onnx`/`tokens.txt`, Apache-2.0, exact source revision, a canonical manifest
digest, Darwin x86_64 and `sherpa-onnx==1.13.6`. Reject parent/leaf symlinks, system site
packages, wrong versions and extra model files before any runtime process is started.

- [x] **Step 2: Run registry/environment RED, then implement minimal GREEN**

```bash
.venv-alpha/bin/python -m pytest -q tests/contracts/test_voice_settings.py tests/voice/test_artifacts.py tests/tools/test_voice_asr_environment.py
```

Add the fifth optional settings digest, closed artifact registry entry, pinned isolated
requirements and path/version validator. Keep Voice disabled and preserve the existing
Whisper artifact fields for historical validation and rollback evidence.

- [x] **Step 3: Add child-protocol and parent-process RED tests**

Exercise two sequential requests through one child, exact mono 16 kHz s16le bounds,
canonical UTF-8 JSON, Mandarin language, 3,000 ms request timeout, child settlement,
offline sanitized environment and absence of PCM/transcript persistence. Malformed or
extra response fields, timeout and child exit must destroy the child and fail closed.

- [x] **Step 4: Run protocol RED, then implement minimal GREEN**

```bash
.venv-alpha/bin/python -m pytest -q tests/voice/test_paraformer.py tests/tools/test_voice_paraformer_runner.py
```

Implement one fixed greedy-search CPU recognizer with two threads. Do not supply a
hotword file, expected phrase, punctuation model, ITN, network client or fallback
engine. The parent passes PCM only over anonymous stdin and receives text only over
stdout; stderr is discarded.

- [x] **Step 5: Add aggregate calibration/CLI RED tests, then implement GREEN**

Require a single candidate named `paraformer`, six evaluated public prompt IDs, 6/6
exact, 6/6 wake and P95 at most 3,000 ms. Output may contain only counts, public prompt
IDs and aggregate latency; it must not contain recognized text, PCM, local paths or
Keychain details.

```bash
.venv-alpha/bin/python -m pytest -q tests/voice/test_asr_calibration.py tests/tools/test_voice_asr_calibrate.py
```

- [x] **Step 6: Install public runtime/model and run the real encrypted-corpus gate**

```bash
make alpha-voice-asr-install
make alpha-voice-paraformer-install
make alpha-voice-asr-paraformer
```

The install command may download only the pinned public runtime/model during this
operator step. The installed worker never downloads. Accept only 6/6 exact, 6/6 wake,
P95 at most 3,000 ms and `VoiceCareSettings.enabled=false`; otherwise report
`asr_candidate_unavailable` and retain Voice disabled.

Exact-head i9 result on 2026-08-25: the pinned candidate was available for all six
encrypted clips at p50 509 ms / p95 529 ms, but reached only 5/6 exact and 1/6 wake;
the only exact mismatch was public prompt ID `negative_weather`, with aggregate edit
distance 2. The unchanged gate therefore failed closed as `asr_candidate_unavailable`.
No transcript, PCM, Keychain value or private path was emitted, and Voice remained
disabled.

- [x] **Step 7: Run full verification, update handoff state and commit Task 5E**

```bash
make alpha-voice-test
.venv-alpha/bin/python -m pytest -q
.venv-alpha/bin/python -m compileall -q services/voice tools tests/voice tests/tools
make -n alpha-voice-asr-install alpha-voice-paraformer-install alpha-voice-asr-paraformer
git diff --check
```

Record the exact real gate result without transcript/audio. Commit only tracked
implementation, tests, spec, plan and handoff documents; never stage runtime artifacts,
private corpus, settings, Keychain data or `uv.lock`.

Implementation checkpoint: `4677fec`. Fresh verification recorded 250/250 Voice tests,
1,302/1,302 full Python tests, Python compilation, the three Make dry-runs, diff/privacy
checks and an independent review with no remaining Critical or Important finding. This
completes the approved amendment implementation, not the ASR accuracy gate.

#### Task 5F: Approved Punctuation-Free Wake Boundary Amendment

**Files:**
- Modify: `services/voice/wake.py`
- Modify: `tests/voice/test_wake.py`
- Modify: `tests/voice/test_asr_calibration.py`
- Modify: this spec/plan and the authoritative handoff documents

**Interfaces:**
- Consumes: local ASR text held only in memory and the existing exact `小小` prefix.
- Produces: the existing `WakeResult`; no transcript, audio, setting or new runtime
  artifact is persisted.

- [x] **Step 1: Lock the lexical boundary with RED tests**

Accept punctuation-free text only when the exact leading `小小` is followed immediately
by one fixed care-vocabulary prefix needed by the closed feeding/cancellation grammar or
the fixed six-prompt calibration corpus. Continue to reject empty text, repeated wake
words, unknown continuations, sentence-internal wake words, `小小鸟` and `小小小心`.

- [x] **Step 2: Implement the minimal deterministic validator**

Do not modify ASR text, add punctuation, replace phrases, use fuzzy/edit-distance
matching or change the downstream parser. The fixed lexicon proves only that `小小` is
a standalone prefix; the full command must still pass the existing closed parser.

- [x] **Step 3: Run software and real encrypted-corpus gates**

Run wake/calibration focused tests, the complete Voice suite and the full Python suite.
Then rerun the exact-head aggregate Paraformer and Silero commands through the installed
user-launchd context. Keep the unchanged requirements of 6/6 exact, 6/6 wake, P95 at
most 3,000 ms and one Silero span per fixed prompt. If the existing `negative_weather`
clip still fails, leave Voice disabled and require one clean operator rerecord; never
rewrite, trim or replace encrypted household audio automatically.

Exact-head user-launchd evidence for implementation `6e933a6` on 2026-08-25 showed the
boundary change raised the Paraformer result from 1/6 to 6/6 wake while preserving 5/6 exact, edit distance 2 and
the sole public mismatch ID `negative_weather`; p50 was 506 ms and p95 540 ms. The same
clip still produced two Silero spans while the other five produced one each. Software
evidence was 27/27 wake tests, 267/267 Voice tests and 1,319/1,319 full Python tests.
Voice remains disabled; the next action is one clean operator rerecord of only the
fixed public `negative_weather` prompt, followed by both unchanged aggregate gates.

#### Task 5D: Installed Non-Interactive Voice Preflight

**Files:**
- Modify: `tools/run_voice_worker.py`
- Modify: `services/voice/worker.py`
- Modify: `deploy/launchd/com.babymonitor.voice.plist.example`
- Modify: `tests/voice/test_worker.py`
- Modify: `tests/deploy/test_voice_worker_deploy.py`
- Modify: `tools/test_guardian.sh`
- Modify: `SUMMARY.md`
- Modify: `docs/STATUS.md`
- Modify: `docs/CHECKPOINT.md`
- Modify: `docs/NEXT.md`

**Interfaces:**
- Produces: disabled-mode launchd preflight proving stable helper access, selected ASR
  artifact/profile and Silero artifact without capturing audio or writing Baby Care.
- Consumes: passing Tasks 5A-5C; it does not enable the Voice worker.

- [x] **Step 1: Write RED launchd preflight tests**

Require `voice_preflight=available` only when helper identity, fixed selected ASR profile
and Silero artifact all validate. Keychain/model failure must report one stable reason,
must not open the decoder and must not restart any sibling service.

- [x] **Step 2: Run RED tests**

```bash
.venv-alpha/bin/python -m pytest -q tests/voice/test_worker.py tests/deploy/test_voice_worker_deploy.py
```

- [x] **Step 3: Implement and run GREEN installed gate**

Keep `voice_care.enabled=false`. Add a bounded `--preflight` path to the installed Voice
launchd executable, invoked by `make alpha-voice-preflight`; it validates only artifacts
and one helper read, emits aggregate state and exits. Run focused tests, Voice full tests,
compile, plist lint, shell syntax, Make dry-run and `git diff --check`.

- [x] **Step 4: Record the exact evidence and commit Task 5D**

Check Task 5 complete only if Task 5A is non-interactive on its second run, one ASR
candidate is 6/6 exact and wake with P95 at most 3,000 ms, and Silero is one-span-per-
prompt with its public control. Otherwise record the blocking code and leave Task 6
unchecked.

```bash
git add tools/run_voice_worker.py services/voice/worker.py deploy/launchd/com.babymonitor.voice.plist.example tests/voice/test_worker.py tests/deploy/test_voice_worker_deploy.py tools/test_guardian.sh SUMMARY.md docs/STATUS.md docs/CHECKPOINT.md docs/NEXT.md docs/superpowers/plans/2026-08-24-voice-care-gate-v2-adult-enrollment.md
git commit -m "test: gate installed Voice runtime preflight"
```

**Next:** Only after this gate passes, continue Dad/Mom enrollment below.

Current installed evidence: Task 5A is complete and helper-owned v2 passes two fresh
non-interactive launchd reads. Task 5B and Task 5E are exhausted and blocked as
`asr_candidate_unavailable`: the best approved base profiles reached 5/6 exact and 6/6
wake within latency. Task 5F corrected the deterministic punctuation-free boundary, so
Paraformer now reaches 5/6 exact and 6/6 wake at p95 540 ms; only the fixed public
`negative_weather` clip remains an exact mismatch.
Task 5C is blocked as `vad_candidate_unavailable`; its generated control and 5/6 private
prompts pass. A later bounded rerecord replaced `negative_weather` with a clip too quiet
for Silero; the current aggregate is zero spans, and two subsequent human-timed capture
windows also detected zero spans without publishing a replacement. Task 5D is
implementation-complete at `41da786`; after approved removal of one stale legacy pending
request by `aacefd9`, the installed login-LaunchAgent gate passed with helper, fixed
Paraformer artifact and fixed Silero artifact all available. Task 6 remains unchecked.
These failures now require one correctly timed clean public negative-control rerecord and a
compliant Silero result, not weaker privacy, exact-match, wake, VAD or latency gates.

### Task 6: Installed i9 Human Enrollment Gate

**Files:**
- Modify: `SUMMARY.md`
- Modify: `docs/STATUS.md`
- Modify: `docs/CHECKPOINT.md`
- Modify: `docs/NEXT.md`
- Modify: `docs/superpowers/plans/2026-08-19-voice-care-v1.md`
- Modify: this plan

**Interfaces:**
- Consumes: actual i9, Xiaomi audio, Dad and Mom separately, Tasks 1–4.
- Produces: two encrypted local opaque profiles and aggregate-only acceptance evidence.

- [ ] **Step 1: Verify preconditions without mutation**

Run:

```bash
make alpha-source-check
make alpha-voice-speaker-check
make alpha-voice-ecapa-probe
```

Require Voice disabled, no existing Dad/Mom registry entry and Guardian services healthy.

- [ ] **Step 2: Enroll Dad privately**

Run:

```bash
make alpha-voice-enroll-dad
```

Human action: Dad alone reads the three displayed one-time phrases at normal volume.
Do not paste audio, transcript, profile ID or local path into chat or Git.

- [ ] **Step 3: Enroll Mom privately**

Run:

```bash
make alpha-voice-enroll-mom
```

Human action: Mom alone reads the three newly displayed one-time phrases. Reuse of any
Dad or previous challenge must fail closed.

- [ ] **Step 4: Run post-enrollment isolation gates**

Run:

```bash
make alpha-voice-test
make alpha-guardian-test
.venv-alpha/bin/python -m pytest -q
node --test tests/frontend/*.test.mjs
git diff --check
```

Record only aggregate counts and stable states. Software and two successful enrollments
still do not prove false-accept/false-reject, arbitrary replay resistance, Baby Care
pairing or production feeding writes.

- [ ] **Step 5: Update status, commit and publish**

```bash
git add SUMMARY.md docs/STATUS.md docs/CHECKPOINT.md docs/NEXT.md docs/superpowers/plans/2026-08-19-voice-care-v1.md docs/superpowers/plans/2026-08-24-voice-care-gate-v2-adult-enrollment.md
git commit -m "docs: record private adult voice enrollment"
git push origin codex/voice-care-v1-gate-v1
```

Monitor exact-head CI. Do not create a PR, merge, modify main, enable Voice or begin the
Baby Care pairing/private delivery slice.

**Completion boundary:** Stop after both profiles and exact-head CI pass. The next
separately supervised slice measures Dad/Mom false acceptance/rejection, challenge
replay, overlapping voices, normal/quiet and near/far scenarios before any Baby Care
profile binding or Voice worker enablement.
