# Voice Care Gate V2 ECAPA Runtime Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use
> `superpowers:subagent-driven-development` (recommended) or
> `superpowers:executing-plans` to implement this plan task-by-task. Steps use checkbox
> (`- [ ]`) syntax for tracking.

**Goal:** Install and validate the pinned SpeechBrain ECAPA speaker-embedding candidate
on the Intel i9 without enabling Voice Care or collecting household enrollment audio.

**Architecture:** Keep Torch, torchaudio and SpeechBrain in a dedicated ignored Python
environment. An explicit operator command acquires the five registry-fixed model files
at the approved immutable revision, writes a canonical source manifest and installs the
validated bundle. The main Voice runtime launches a bounded persistent subprocess that
accepts only framed 16 kHz mono PCM on stdin and returns one canonical, normalized
192-dimensional embedding on stdout. This slice does not connect the runner to speaker
authorization, enrollment, Baby Care or the production worker.

**Tech Stack:** Intel macOS x86_64, Python 3.11, SpeechBrain 1.0.3, PyTorch 2.2.2,
torchaudio 2.2.2, NumPy 1.26.4, huggingface-hub 0.36.0, existing Voice artifact
registry and macOS `say`/FFmpeg for generated-speech smoke evidence.

**Spec:** `docs/superpowers/specs/2026-08-19-voice-care-v1-design.md`

## Global Constraints

- Voice remains disabled in `runtime/settings.yaml` throughout this plan.
- Do not enroll Dad, Mom or any other real adult in this slice.
- Do not persist raw PCM, WAV, transcript, embedding or generated speech outside a
  bounded temporary directory; the temporary directory is removed on every exit path.
- Model download is an explicit operator action only. A worker may never download,
  update or select a model.
- The exact artifact remains `speechbrain-ecapa-voxceleb` at revision
  `0f99f2d0ebe89ac095bcc5903c4dd8f72b367286` with Apache-2.0 metadata and the five
  files already fixed in `services/voice/artifacts.py`.
- The main `.venv-alpha` remains Torch-free by contract. SpeechBrain dependencies live
  only under ignored `runtime/voice-speaker-venv`.
- Missing files, symlinks, digest drift, incompatible tensors, non-finite values,
  protocol violations, timeout, subprocess exit or cleanup failure fail closed as
  `voice_model_unavailable` and never create an identity result.
- No Baby Care endpoint, database, device key, lease, Keychain item, launchd setting or
  production Voice state is changed by this plan.

---

### Task 1: Isolated Speaker Runtime Environment

**Files:**
- Create: `config/voice-speaker-requirements.txt`
- Create: `tools/voice_speaker_environment.py`
- Modify: `Makefile`
- Create: `tests/tools/test_voice_speaker_environment.py`
- Modify: `tests/deploy/test_alpha_commands.py`

**Interfaces:**
- Produces: `validate_speaker_environment(project_root: Path, expected_prefix: Path) -> Path`.
- Produces: `make alpha-voice-speaker-install` and `make alpha-voice-speaker-check`.
- Consumes: Homebrew Python 3.11 already required by the Alpha installer.

- [x] **Step 1: Write environment RED tests**

Test that the checker accepts only the exact prefix
`runtime/voice-speaker-venv`, rejects a symlink in either `runtime` or the environment,
requires `include-system-site-packages = false`, and checks these exact imported
versions without printing the prefix:

```text
numpy==1.26.4
huggingface-hub==0.36.0
speechbrain==1.0.3
torch==2.2.2
torchaudio==2.2.2
```

Also require both Make targets to reject non-Darwin/non-x86_64 hosts before any venv or
pip write, invoke the checker before and after installation, suppress pip internals and
emit only `voice_speaker_install=ready|failed|unavailable` or
`voice_speaker_check=ready|unavailable`.

- [x] **Step 2: Run RED tests**

Run:

```bash
.venv-alpha/bin/python -m pytest -q tests/tools/test_voice_speaker_environment.py tests/deploy/test_alpha_commands.py
```

Expected: FAIL because the checker, requirements file and Make targets do not exist.

- [x] **Step 3: Implement the isolated environment gate**

Use the same canonical-parent and `pyvenv.cfg` protections as
`tools/voice_converter_environment.py`, but require the speaker prefix and import each
dependency in one isolated child check. Never modify `sys.modules` in the main runtime.
The install target creates or upgrades the ignored venv and performs only the pinned
requirements install; startup and `alpha-install` must not invoke it.

- [x] **Step 4: Run GREEN and static checks**

Run:

```bash
.venv-alpha/bin/python -m pytest -q tests/tools/test_voice_speaker_environment.py tests/deploy/test_alpha_commands.py
.venv-alpha/bin/python -m compileall -q tools/voice_speaker_environment.py
make -n alpha-voice-speaker-install alpha-voice-speaker-check
git diff --check
```

- [x] **Step 5: Commit Task 1**

```bash
git add config/voice-speaker-requirements.txt tools/voice_speaker_environment.py Makefile tests/tools/test_voice_speaker_environment.py tests/deploy/test_alpha_commands.py
git commit -m "feat: isolate the ECAPA speaker runtime"
```

### Task 2: Explicit Pinned ECAPA Source And Bundle Installation

**Files:**
- Create: `tools/voice_ecapa_source.py`
- Modify: `tools/voice_models.py`
- Modify: `Makefile`
- Create: `tests/tools/test_voice_ecapa_source.py`
- Modify: `tests/voice/test_artifacts.py`
- Modify: `tests/deploy/test_alpha_commands.py`

**Interfaces:**
- Produces: `materialize_ecapa_source(destination: Path, fetch: Fetch) -> Path`.
- Produces: `make alpha-voice-ecapa-source` and `make alpha-voice-ecapa-install`.
- Consumes: the existing registry definition and canonical
  `validate_voice_source`/`acquire_voice_artifact` path.

- [x] **Step 1: Write source/install RED tests**

Use an injected fake fetcher and assert that the source materializer requests exactly
the approved repository, revision and five file names. It must reject a returned cache
path that is not a regular file, duplicate names, files over 500 MiB, zero-length
payloads, symlinks in the private publication boundary and a destination under
Git-tracked paths. It copies the returned cache file into private staging while hashing
it, writes a canonical ASCII source manifest with SHA-256 for every file, mode-0600
files and a mode-0700 parent, then atomically publishes only a complete source.

The Make install target must derive the source-manifest digest locally, call
`tools/voice_models.py --operation acquire` for only
`speechbrain-ecapa-voxceleb`, and expose no URL, path or digest in output.

- [x] **Step 2: Run RED tests**

Run:

```bash
.venv-alpha/bin/python -m pytest -q tests/tools/test_voice_ecapa_source.py tests/voice/test_artifacts.py tests/deploy/test_alpha_commands.py
```

Expected: FAIL because the explicit ECAPA materializer and Make targets do not exist.

- [x] **Step 3: Implement immutable acquisition**

Use `huggingface_hub.hf_hub_download` only in the explicit source command, with the
repository, immutable revision and file list supplied by the closed registry rather
than caller input. The library may follow its official immutable-file delivery path;
the materializer must not trust or publish the returned cache path directly. Copy it
into a private temporary file while hashing and enforcing the size cap. Publish the
source directory only after all five files and the canonical manifest validate. Reuse
`collect_voice_artifact`; do not create a second bundle validator or accept caller-
provided artifact IDs, revisions or file lists. All worker paths set offline flags and
never import the download client.

- [x] **Step 4: Run GREEN, privacy and static checks**

Run:

```bash
.venv-alpha/bin/python -m pytest -q tests/tools/test_voice_ecapa_source.py tests/voice/test_artifacts.py tests/deploy/test_alpha_commands.py
.venv-alpha/bin/python -m compileall -q tools/voice_ecapa_source.py tools/voice_models.py
make -n alpha-voice-ecapa-source alpha-voice-ecapa-install
git diff --check
```

Verify no model, manifest, runtime path, URL response or generated setting is tracked.

- [x] **Step 5: Commit Task 2**

```bash
git add tools/voice_ecapa_source.py tools/voice_models.py Makefile tests/tools/test_voice_ecapa_source.py tests/voice/test_artifacts.py tests/deploy/test_alpha_commands.py
git commit -m "feat: acquire the pinned ECAPA artifact"
```

### Task 3: Bounded Persistent ECAPA Embedding Process

**Files:**
- Create: `tools/voice_ecapa_runner.py`
- Create: `services/voice/ecapa.py`
- Create: `tests/tools/test_voice_ecapa_runner.py`
- Create: `tests/voice/test_ecapa.py`

**Interfaces:**
- Produces: `EcapaEmbedding(embedding: tuple[float, ...], latency_ms: int)`.
- Produces: `EcapaProcess.embed(pcm: bytes) -> EcapaEmbedding` and
  `EcapaProcess.close() -> None`.
- Consumes: a previously validated local artifact bundle and the checked isolated
  speaker Python.
- Does not yet produce `EmbeddingObservation`; SNR and overlap quality remain a later
  supervised-enrollment slice and are never fabricated as zero or healthy.

- [ ] **Step 1: Write framed-protocol RED tests**

Cover one 0.8–8.0 second 16 kHz mono s16le request, two sequential requests in the same
process, exact 192-value finite normalized output, 8,192-byte response cap, five-second
request timeout, startup timeout, malformed length, short/oversize PCM, noncanonical
JSON, wrong shape, non-finite output, child exit and `close()` settlement. Assert the
parent sends PCM only through stdin and never uses argv, filesystem or environment
variables for audio.

- [ ] **Step 2: Run RED tests**

Run:

```bash
.venv-alpha/bin/python -m pytest -q tests/tools/test_voice_ecapa_runner.py tests/voice/test_ecapa.py
```

Expected: FAIL because the runner and parent adapter do not exist.

- [ ] **Step 3: Implement the fail-closed process boundary**

The parent validates the artifact before process creation, sets
`HF_HUB_OFFLINE=1`, `TRANSFORMERS_OFFLINE=1` and `NO_PROXY=*`, then launches the fixed
runner from the checked speaker venv. The child loads only the supplied already-
validated local bundle, accepts a four-byte unsigned big-endian PCM length followed by
the bytes, and emits one canonical ASCII JSON line containing only `schemaVersion`,
`embedding` and `latencyMs`. It must never echo text, paths, exceptions or tensor data
other than the bounded normalized embedding. Parent failure closes/destroys the child
and raises `voice_model_unavailable`.

- [ ] **Step 4: Run GREEN and regression checks**

Run:

```bash
.venv-alpha/bin/python -m pytest -q tests/tools/test_voice_ecapa_runner.py tests/voice/test_ecapa.py tests/voice/test_speaker.py tests/voice/test_enrollment.py
.venv-alpha/bin/python -m compileall -q services/voice/ecapa.py tools/voice_ecapa_runner.py
git diff --check
```

- [ ] **Step 5: Commit Task 3**

```bash
git add services/voice/ecapa.py tools/voice_ecapa_runner.py tests/voice/test_ecapa.py tests/tools/test_voice_ecapa_runner.py
git commit -m "feat: run bounded local ECAPA embeddings"
```

### Task 4: Installed-i9 Generated-Speech ECAPA Smoke Gate

**Files:**
- Create: `tools/voice_ecapa_probe.py`
- Modify: `Makefile`
- Create: `tests/tools/test_voice_ecapa_probe.py`
- Modify: `tests/deploy/test_alpha_commands.py`
- Modify: `SUMMARY.md`
- Modify: `docs/STATUS.md`
- Modify: `docs/CHECKPOINT.md`
- Modify: `docs/NEXT.md`
- Modify: `docs/superpowers/plans/2026-08-19-voice-care-v1.md`
- Modify: this plan

**Interfaces:**
- Produces: `make alpha-voice-ecapa-probe` with aggregate-only PASS/FAIL output.
- Consumes: Tasks 1–3 and macOS local speech synthesis plus FFmpeg normalization.

- [ ] **Step 1: Write probe RED tests**

Use fake synthesizer/decoder/runner boundaries to assert five generated utterances are
processed, temporary WAV/PCM files are removed on success/failure/signal, the same
persistent runner is reused, and output contains only fixed fields: result, sample
count, dimensions, normalized count, p50/p95 latency and raw-audio-persisted=false.
Reject any transcript, voice name, path, embedding, similarity threshold or exception
text in stdout/stderr.

- [ ] **Step 2: Run RED tests**

Run:

```bash
.venv-alpha/bin/python -m pytest -q tests/tools/test_voice_ecapa_probe.py tests/deploy/test_alpha_commands.py
```

Expected: FAIL because the probe and Make target do not exist.

- [ ] **Step 3: Implement the generated-only smoke gate**

Generate five fixed Mandarin care phrases with the local macOS synthesizer into a
private temporary directory, normalize to 16 kHz mono s16le through the fixed FFmpeg
boundary, and discard every sample immediately after embedding. PASS requires 5/5
finite normalized 192-dimensional results, one persistent child process, p95 embedding
latency no greater than 3,000 ms and complete cleanup. Do not set speaker accept/
uncertain thresholds from synthetic voices and do not call `SpeakerVerifier`.

- [ ] **Step 4: Run installed operator gates**

Run on the actual i9, with Voice disabled before and after:

```bash
make alpha-voice-speaker-install
make alpha-voice-ecapa-source
make alpha-voice-ecapa-install
make alpha-voice-speaker-check
make alpha-voice-ecapa-probe
make alpha-voice-test
make alpha-guardian-test
git diff --check
```

Passing proves only local artifact/runtime compatibility and generated-speech embedding
shape/latency. It does not prove Dad/Mom identity accuracy, replay/overlap rejection,
enrollment quality, Baby Care pairing or a production Voice write.

- [ ] **Step 5: Update status and commit Task 4**

Record exact installed counts, stable reason codes and privacy evidence without model
paths, local addresses, voice names, embeddings or household content.

```bash
git add tools/voice_ecapa_probe.py Makefile tests/tools/test_voice_ecapa_probe.py tests/deploy/test_alpha_commands.py SUMMARY.md docs/STATUS.md docs/CHECKPOINT.md docs/NEXT.md docs/superpowers/plans/2026-08-19-voice-care-v1.md docs/superpowers/plans/2026-08-24-voice-care-gate-v2-ecapa-runtime.md
git commit -m "test: validate the i9 ECAPA runtime"
```

**Completion boundary:** Stop after Task 4. Do not enroll a real adult or enable Voice.
The next separately approved slice owns replay/overlap quality, encrypted Dad/Mom
enrollment, Baby Care profile binding, the private API transport and production worker
factory.
