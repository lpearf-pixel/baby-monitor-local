# Voice Contextual/Hotword Isolated A/B Implementation Plan

> Execute inline on `codex/xiaomi-camera-reply-lifecycle-review`. Do not switch or
> restart the production Voice model during Tasks 1-6.

**Goal:** Build and run a privacy-safe, reproducible A/B between the current pinned
Paraformer and one immutable ContextualParaformer hotword candidate, then decide whether
a separate deployment slice is justified.

**Architecture:** A candidate-only environment and digest-addressed model bundle feed a
bounded framed subprocess. The existing closed action benchmark supplies identical PCM
to baseline and candidate and serializes aggregate results only. No production worker,
settings or launchd interface imports the candidate.

**Tech stack:** Python 3.11, FunASR ONNX runtime 0.4.2 at fixed source revision,
ONNX Runtime CPU, ModelScope ContextualParaformer at fixed revision, pytest and Make.

---

### Task 1: Lock the candidate contract and source manifest

**Files:**
- Create: `config/voice-contextual-requirements.txt`
- Create: `services/voice/contextual_artifacts.py`
- Create: `tests/voice/test_contextual_artifacts.py`

- [ ] Write RED tests for exact candidate/runtime revisions, required files, sizes,
      digests, license labels, unsafe paths, symlinks, hardlinks, owner/mode and extras.
- [ ] Implement immutable dataclasses and validation with stable errors.
- [ ] Pin the isolated dependency closure after an Intel install probe; no floating
      requirements and no edits to the production ASR environment.
- [ ] Run focused tests and `git diff --check`.

**Acceptance:** only the approved source/runtime/model identity can pass; no artifact is
downloaded or installed by importing the module.

### Task 2: Build the isolated installer and acquisition boundary

**Files:**
- Create: `tools/voice_contextual_install.py`
- Modify: `Makefile`
- Create: `tests/tools/test_voice_contextual_install.py`
- Modify: `.gitignore` only if the existing runtime rule is insufficient.

- [ ] Write RED tests for pre-write path checks, fixed revision URLs, streaming
      size/digest checks, staging publication, interrupted retention, isolated venv,
      offline import check and redacted errors.
- [ ] Implement `alpha-voice-contextual-install` and
      `alpha-voice-contextual-check`; caller-supplied URL/model/path is forbidden.
- [ ] Verify Make dry-runs, changed Python compile and privacy checks.

**Acceptance:** a complete validated candidate can be installed beneath ignored runtime
state without touching production settings, venvs, plists or services.

### Task 3: Implement the bounded ContextualParaformer runner

**Files:**
- Create: `services/voice/contextual_paraformer.py`
- Create: `tools/voice_contextual_runner.py`
- Create: `tests/voice/test_contextual_paraformer.py`

- [ ] Write RED tests for fixed hotword digest/order, 16 kHz PCM framing, canonical
      response, startup/request/output bounds, crash/timeout settlement and no network.
- [ ] Implement one candidate-only child using `ContextualParaformer(...,
      quantize=True)` and the fixed hotword string.
- [ ] Prove child termination and no production module/config import.

**Acceptance:** the candidate returns an `AsrResult` or one fixed unavailable failure;
no timeout or malformed response leaves a child alive.

### Task 4: Extend the benchmark into a true baseline/candidate A/B

**Files:**
- Modify: `tools/voice_action_benchmark.py`
- Modify: `tests/tools/test_voice_action_benchmark.py`
- Create: `tools/voice_contextual_ab.py`
- Create: `tests/tools/test_voice_contextual_ab.py`
- Modify: `Makefile`

- [ ] Write RED tests proving identical sample order/PCM, candidate isolation,
      transcript disposal, aggregate-only JSON, 24/48 cardinality, zero false accepts,
      per-action coverage, latency/RSS bounds and independent failures.
- [ ] Add closed candidate IDs and `alpha-voice-contextual-ab`; do not make engine,
      hotwords, corpus or thresholds caller-configurable.
- [ ] Preserve the current benchmark behavior and exact classifier.

**Acceptance:** generated/public A/B reports both engines independently and passes only
when all candidate gates from the spec pass.

### Task 5: Add the private-local aggregate evaluator

**Files:**
- Modify: `tools/voice_contextual_ab.py`
- Modify: `tests/tools/test_voice_contextual_ab.py`
- Modify: `Makefile`

- [ ] Write RED tests for inventory identity/mode/session bounds, no transcript/path in
      output, candidate-after-public-gate ordering and memory disposal.
- [ ] Reuse the existing retained diagnostic inventory read-only; do not copy, rename,
      delete or rewrite private artifacts.
- [ ] Emit only fixed aggregate classifications and timing.

**Acceptance:** the known local sample can be compared without exposing or mutating it;
invalid/incomplete private state fails closed.

### Task 6: Run the isolated Intel A/B and decide keep/reject

**Files:**
- Create: `docs/reviews/2026-08-28-voice-contextual-hotword-ab-result.md`
- Modify: this plan

- [ ] Run the isolated installer/check and record exact package/model digests.
- [ ] Run generated/public A/B; require 24/24 positives, 48/48 negatives, zero false
      accepts, p95 <= 3,000 ms and RSS <= 2 GiB.
- [ ] Only if public passes, run the private-local aggregate gate.
- [ ] Record keep/reject with exact aggregate evidence; do not switch production.

**Acceptance:** the report makes no production claim. A failed gate leaves the current
model unchanged; a passed gate authorizes only Task 7 planning.

### Task 7: Production deployment amendment (conditional, not yet executable)

**Files:**
- Create only after Task 6 PASS:
  `docs/superpowers/specs/2026-08-28-voice-contextual-production-amendment.md`

- [ ] Define worker ownership, lifecycle/recovery, installed checks, supervised device
      matrix and exact rollback to the sherpa Paraformer.
- [ ] Obtain explicit approval before any settings/plist/service/model switch.

**Acceptance:** separate written approval exists. This plan never auto-deploys.

### Task 8: Verification and documentation checkpoint

**Files:**
- Modify: `SUMMARY.md`
- Modify: `docs/STATUS.md`
- Modify: `docs/CHECKPOINT.md`
- Modify: `docs/NEXT.md`

- [ ] Run all affected focused tests and `make alpha-voice-test`.
- [ ] Run changed Python compile, Make dry-runs, `git diff --check` and final credential,
      media, transcript, path, private-network and generated-artifact scans.
- [ ] Update authoritative docs with the exact A/B result and ordered next step.
- [ ] Commit focused slices locally; do not push/merge/main.

**Acceptance:** documentation distinguishes software/public/private/device/deployment
evidence, the tracked tree contains no runtime artifact and production remains unchanged.
