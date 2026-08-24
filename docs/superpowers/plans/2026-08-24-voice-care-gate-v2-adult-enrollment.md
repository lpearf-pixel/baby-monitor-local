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
- [ ] Capture the supervised fixed-phrase corpus once on the Xiaomi/i9 path.
- [ ] Run base and small against identical clips; require exact normalized text,
  exact `小小` prefix and bounded aggregate latency before selecting a candidate.
- [ ] Record aggregate evidence only. Keep enrollment blocked on any accuracy failure.

**Next:** Only after this gate passes, continue Dad/Mom enrollment below.

Current installed evidence: the pinned official Silero artifact validates and rejects
real silence, while the supervised Xiaomi batch returned zero speech spans and therefore
did not publish a corpus. A fixed eight-second calibration-only capture now isolates ASR
from VAD, but the current automation context cannot create its dedicated Keychain item:
macOS returns OSStatus `-25308` (`User interaction is not allowed`). Run the fixed capture
once from the logged-in user's Terminal; do not substitute a plaintext key or weaken VAD.

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
