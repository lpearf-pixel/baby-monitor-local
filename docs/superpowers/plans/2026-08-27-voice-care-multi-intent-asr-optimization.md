# Voice Care Multi-Intent ASR Optimization Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use
> `superpowers:subagent-driven-development` (recommended) or
> `superpowers:executing-plans` to implement this plan task-by-task. Steps use checkbox
> (`- [ ]`) syntax for tracking.
>
> **Status:** Software implementation authorized on 2026-08-27. Task 1 RED corpus is
> complete; Task 2 is next. Model installation, household audio, Camera Reply activation,
> Baby Care writes, PRs and protected-branch changes remain unauthorized.

**Goal:** Make the existing armed listen-only Voice flow safely recognize a closed set
of feeding, diaper-change and burping commands, classify medication utterances only as
high-risk candidates, and retain enough aggregate evidence to optimize and retrospect
without persisting household audio or transcripts.

**Architecture:** Keep the pinned Paraformer, exact wake path and Feeding V1 parser.
Add a listen-only-only closed action registry, then an armed/action-scoped explicit
correction table that always returns through exact classification. Risk policy allows
only low-risk listen-only acknowledgement; medication stays a silent high-risk
candidate and no new action reaches Baby Care.

**Tech Stack:** Python 3.11 on Intel macOS, sherpa-onnx 1.13.6 Paraformer, Silero VAD,
pytest, fixed JSON/status schemas and generated/public 16 kHz mono PCM fixtures.

**Spec:**
`docs/superpowers/specs/2026-08-27-voice-care-multi-intent-asr-optimization-design.md`

## Global Constraints

- Start from `codex/xiaomi-camera-reply-lifecycle-review` at or after exact published
  head `4f599225f908d8052006353a9dafec03eed40fdf`; record any newer head and review its
  intervening diff before editing.
- Preserve all user changes. Never reset, clean, overwrite, rebase, force-push, merge,
  modify `main/stable`, create a PR or perform remote operations without separate
  explicit approval.
- Current authority is documentation only. Code execution requires a later explicit
  user instruction. A local commit also requires explicit authority; otherwise record
  `commit=not_authorized` in the review log.
- Keep `voice_care.camera_reply_enabled=false` during software and initial i9 ASR gates.
  Do not operate PTZ, change camera settings, force UDP/TCP, change `transport=auto`,
  add a second Xiaomi producer or restart the full Alpha stack.
- Keep the pinned go2rtc source/patch and the long-lived single-producer architecture.
  This plan does not modify Xiaomi video, microphone transport or speaker lifecycle.
- Keep household PCM and transcript memory-only. Tests use generated, synthetic or
  explicitly public media. Never add a household utterance, drug name/dose, private
  path, address, token, key, URI or device identifier to Git, logs, fixtures or status.
- Keep full-care Voice, speaker identity, signing, outbox and Baby Care writes isolated.
  `VoiceCareIntentV1` remains Feeding-only.
- Exact parse runs before correction. Correction is armed-only, action-scoped and based
  on reviewed explicit mappings. Generic edit distance, prefix/suffix shape acceptance,
  open-vocabulary NLU and KWS-only decisions are prohibited.
- Medication receives no approximate correction, no positive save acknowledgement and
  no external intent.
- Every behavior change follows observed RED, minimal GREEN, focused rerun and review-log
  update. Any false accept blocks the next gate.

## File Structure

- Create `services/voice/care_action.py`: memory-only closed listen-only action registry
  and risk policy. It must not import signing, outbox or Baby Care clients.
- Create `services/voice/asr_correction.py`: explicit armed follow-up correction table
  and pre/post safety guards. It must not use edit distance for acceptance.
- Modify `services/voice/listen_only.py`: exact action classification, optional guarded
  correction and one-shot response policy.
- Modify `services/voice/listen_only_runtime.py`: fixed aggregate action/correction
  counters only.
- Modify `services/voice/worker.py` and `tools/voice_status.py`: closed counter/reason
  allowlists; no transcript fields.
- Create `tools/voice_action_benchmark.py`: generated/public aggregate-only action
  benchmark for the current Paraformer and approved future offline candidates.
- Add adjacent tests under `tests/voice/` and `tests/tools/`.
- Update the spec, this plan, review log, `SUMMARY.md`, `docs/STATUS.md`,
  `docs/CHECKPOINT.md` and `docs/NEXT.md` only with fresh evidence.

---

### Task 1: Lock the multi-action RED corpus

**Files:**
- Create: `tests/voice/test_care_action.py`
- Create: `tests/voice/test_asr_correction.py`
- Modify: `tests/voice/test_listen_only.py`
- Modify: `docs/reviews/2026-08-27-voice-care-multi-intent-asr-optimization-log.md`

**Interfaces:**
- Consumes: existing `DialogueState`, `parse_feeding_command()` and
  `ListenOnlyController.handle()` behavior.
- Produces: failing tests for `classify_exact_action(command: str)`,
  `correct_armed_followup(command: str)` and the controller policy implemented by Tasks
  2–4.

- [x] **Step 1: Confirm the execution baseline**

  ```bash
  git status --short --branch
  git rev-parse HEAD
  git log -5 --oneline
  git diff --check
  ```

  Expected: the exact approved branch/head is known; unrelated changes are listed and
  preserved. If the checkout is detached, do not create a branch or commit without user
  authority.

- [x] **Step 2: Add exact-action RED tests**

  Define table-driven expectations equivalent to:

  ```python
  @pytest.mark.parametrize(
      ("command", "code", "risk", "allow_ack"),
      [
          ("开始喂奶", "feeding_command", "low", True),
          ("开始换尿布", "diaper_change_start", "low", True),
          ("换好尿布了", "diaper_change_complete", "low", True),
          ("开始拍嗝", "burping_start", "low", True),
          ("拍嗝结束", "burping_complete", "low", True),
          ("开始喂药", "medication_start_candidate", "high", False),
          ("喂药完成", "medication_complete_candidate", "high", False),
      ],
  )
  def test_exact_closed_actions(command, code, risk, allow_ack):
      result = classify_exact_action(command)
      assert (result.action_code, result.risk, result.allow_ack) == (
          code, risk, allow_ack
      )
  ```

  Also require punctuation/space normalization only, one action per utterance and
  rejection of unsupported ordinary statements.

- [x] **Step 3: Add guarded-correction RED tests**

  Require only the explicit synthetic confusion to correct:

  ```python
  def test_reviewed_synthetic_feeding_confusion_is_correctable():
      result = correct_armed_followup("开始为奶")
      assert result is not None
      assert result.canonical_command == "开始喂奶"
      assert result.action_family == "feeding"
  ```

  Require `None` for negation, stop, cancellation, questions, semantic neighbors,
  cross-action phrases and medication near matches. Include at least:

  ```python
  REJECTED = (
      "不要开始喂奶", "还没开始喂奶", "停止喂奶", "结束喂奶",
      "取消开始喂奶", "开始喂奶吗", "要不要开始喂奶",
      "开始断奶", "开始泡奶", "开始热奶", "开始喂药",
      "开始换尿布", "开始拍嗝", "宝宝刚才喝了奶",
  )
  ```

- [x] **Step 4: Add controller RED tests**

  Prove exact/corrected low-risk actions acknowledge exactly once only while armed;
  medication returns a fixed high-risk candidate reason with no spoken response; idle,
  timeout, reply echo and replay behavior remain unchanged.

- [x] **Step 5: Run the RED and capture the first actionable failure**

  ```bash
  .venv-alpha/bin/python -m pytest -q \
    tests/voice/test_care_action.py \
    tests/voice/test_asr_correction.py \
    tests/voice/test_listen_only.py
  ```

  Expected: RED because the two new modules/interfaces do not exist, not because pytest,
  dependencies or fixtures are unavailable. If the environment is unavailable, record
  the blocker and do not call the RED proven.

- [x] **Step 6: Append the exact RED evidence to the review log**

  Record command, head, test count, first failure and that no camera/model/private data
  was used. Do not paste raw exception payloads if they contain paths or text.

**Acceptance:** the corpus demonstrates every desired exact action and every safety
rejection before implementation exists.

**Commit boundary:** if and only if the user authorizes a local commit, commit the RED
tests as `test: define closed voice care action corpus`; otherwise leave the reviewed
diff uncommitted and record `commit=not_authorized`.

---

### Task 2: Implement the internal closed action registry

**Files:**
- Create: `services/voice/care_action.py`
- Modify: `tests/voice/test_care_action.py`
- Modify: `docs/reviews/2026-08-27-voice-care-multi-intent-asr-optimization-log.md`

**Interfaces:**
- Consumes: `services.voice.intent.DialogueState` and `parse_feeding_command()`.
- Produces:
  `classify_exact_action(command: str) -> CareActionMatch | None`, where
  `CareActionMatch` contains fixed `action_code`, `risk` and `allow_ack` fields.

- [x] **Step 1: Add the smallest immutable types**

  Implement the equivalent interface:

  ```python
  ActionCode = Literal[
      "feeding_command",
      "diaper_change_start", "diaper_change_complete",
      "burping_start", "burping_complete",
      "medication_start_candidate", "medication_complete_candidate",
  ]
  Risk = Literal["low", "high"]

  @dataclass(frozen=True, slots=True)
  class CareActionMatch:
      action_code: ActionCode
      risk: Risk
      allow_ack: bool
  ```

  Reject invalid constructor combinations so a high-risk medication candidate cannot
  accidentally set `allow_ack=True`.

- [x] **Step 2: Preserve Feeding V1 through delegation**

  Recreate the existing listen-only synthetic-state check inside the new module and
  return `feeding_command` only when the unchanged `parse_feeding_command()` accepts an
  exact command in one of the existing closed states. Do not add diaper, burping or
  medication to `services/voice/intent.py` or the vendored VoiceCareIntentV1 corpus.

- [x] **Step 3: Add the exact non-Feeding registry**

  Use an immutable mapping with only the four low-risk phrases and two medication
  phrases defined in the spec. Normalization removes whitespace and Unicode punctuation
  only; it does not replace words, homophones or characters.

- [x] **Step 4: Enforce one-domain and bounded-input failure**

  Reject non-string, empty, over-64-character, multiple-action and unknown statements.
  Return `None`; never return raw input in an exception or reason.

- [x] **Step 5: Run focused GREEN**

  ```bash
  .venv-alpha/bin/python -m pytest -q \
    tests/voice/test_care_action.py \
    tests/voice/test_intent.py
  ```

  Expected: all exact-action and unchanged Feeding tests pass.

- [x] **Step 6: Review and log**

  Confirm the module imports no Baby Care client, signing, outbox, model or camera code.
  Append fresh results and diff scope to the review log.

**Acceptance:** exact diaper/burping/medication candidates are internally classifiable,
while Feeding V1 and unsupported commands remain unchanged and fail closed.

**Commit boundary:** when authorized, `feat: classify closed listen-only care actions`.

---

### Task 3: Implement armed action-scoped correction

**Files:**
- Create: `services/voice/asr_correction.py`
- Modify: `tests/voice/test_asr_correction.py`
- Modify: `docs/reviews/2026-08-27-voice-care-multi-intent-asr-optimization-log.md`

**Interfaces:**
- Consumes: normalized follow-up text only after exact classification failed in an armed
  controller.
- Produces:
  `correct_armed_followup(command: str) -> CorrectionResult | None`, with fixed
  `canonical_command` and `action_family`; no distance/probability field.

- [x] **Step 1: Add a source-controlled correction result**

  ```python
  @dataclass(frozen=True, slots=True)
  class CorrectionResult:
      canonical_command: str
      action_family: Literal["feeding"]
  ```

  Keep the initial reviewed mapping exactly:

  ```python
  _CORRECTIONS = {"开始为奶": CorrectionResult("开始喂奶", "feeding")}
  ```

  Do not infer additional entries from edit distance. Each later entry requires its own
  positive and adversarial tests plus review-log rationale.

- [x] **Step 2: Add pre-correction guards**

  Reject bounded marker families for negation, no-action-yet, stop, cancel and question.
  Reject known neighboring Feeding semantics and every non-Feeding action-domain token.
  Run these guards before mapping lookup.

- [x] **Step 3: Add post-correction validation**

  Require `classify_exact_action(canonical_command)` to return a low-risk Feeding result.
  A stale mapping or a mapping to medication/non-Feeding fails closed.

- [x] **Step 4: Prove no fuzzy algorithm exists**

  Add a structural test or source assertion that this module does not import/call the
  diagnostic `_edit_distance` function and does not use RapidFuzz, Levenshtein,
  embeddings or an ASR model.

- [x] **Step 5: Run focused GREEN**

  ```bash
  .venv-alpha/bin/python -m pytest -q \
    tests/voice/test_asr_correction.py \
    tests/voice/test_care_action.py
  ```

- [x] **Step 6: Append the correction decision to the review log**

  Record the exact number of approved mappings, false accepts and test counts. Do not
  claim the synthetic `开始为奶` is one of the four private live transcripts.

**Acceptance:** one reviewed synthetic Feeding confusion can become an exact command;
every safety family and every other action remains rejected.

**Commit boundary:** when authorized, `fix: add guarded feeding follow-up correction`.

---

### Task 4: Wire recognition into listen-only without opening care writes

**Files:**
- Modify: `services/voice/listen_only.py`
- Modify: `tests/voice/test_listen_only.py`
- Modify: `tests/voice/test_listen_only_runtime.py`
- Modify: `docs/reviews/2026-08-27-voice-care-multi-intent-asr-optimization-log.md`

**Interfaces:**
- Consumes: `classify_exact_action()` and `correct_armed_followup()`.
- Produces: existing `ListenOnlyOutcome` with fixed reasons; low-risk actions may use
  existing `listen_only_received`, medication uses a no-audio high-risk candidate reason.

- [x] **Step 1: Preserve exact-first ordering**

  In an armed follow-up:

  ```text
  strip fixed reply echo -> exact action -> guarded correction if exact missed
  -> exact action again -> risk policy -> one response or silent high-risk candidate
  ```

  For one-utterance `wake_with_command`, run exact action classification only: low-risk
  exact actions may acknowledge and exact medication may become the silent high-risk
  candidate. In idle without an exact wake, keep the existing ignore behavior. Do not
  call correction for idle input, `wake_with_command`, wake classification, reply echo
  or replay-only invalid speech.

- [x] **Step 2: Acknowledge low-risk actions once**

  Exact Feeding, diaper and burping results call the existing `_acknowledge()` once and
  reset to idle. A corrected Feeding result follows the same one-shot path. Do not add a
  second TTS code or modify Camera Reply accepted-code sets in this slice.

- [x] **Step 3: Fail closed for medication**

  Exact medication candidates reset to idle and return fixed reason
  `listen_only_high_risk_candidate` with `response_code=None`. They do not call TTS,
  `parse_feeding_command()`, worker signing, outbox or Baby Care.

- [x] **Step 4: Preserve existing echo, timeout and zeroization behavior**

  Rerun all reply-echo, delayed echo, replay, tail-buffer, deadline, cancellation and
  output-failure tests. An invalid corrected candidate must consume the one armed
  utterance and return idle without a response.

- [x] **Step 5: Run focused GREEN**

  ```bash
  .venv-alpha/bin/python -m pytest -q \
    tests/voice/test_listen_only.py \
    tests/voice/test_listen_only_runtime.py \
    tests/voice/test_tts.py \
    tests/voice/test_camera_reply.py
  ```

  Expected: no Camera Reply vocabulary/lifecycle regression and no Baby Care call.

- [x] **Step 6: Append behavior and regression results to the review log**

**Acceptance:** armed low-risk multi-actions receive one syntactic acknowledgement;
medication is recognized only as a silent high-risk candidate; every path returns idle
and retains no transcript.

**Commit boundary:** when authorized, `feat: recognize guarded listen-only care actions`.

---

### Task 5: Add aggregate-only action evidence

**Files:**
- Modify: `services/voice/worker.py`
- Modify: `services/voice/listen_only_runtime.py`
- Modify: `tools/voice_status.py`
- Modify: `tests/voice/test_worker.py`
- Modify: `tests/voice/test_listen_only_runtime.py`
- Modify: `tests/tools/test_voice_status.py`
- Modify: `docs/reviews/2026-08-27-voice-care-multi-intent-asr-optimization-log.md`

**Interfaces:**
- Consumes: fixed action/match outcomes from Task 4.
- Produces: bounded integer counters and fixed status reasons only.

- [x] **Step 1: Add closed integer counters**

  Add counters equivalent to:

  ```text
  listen_only_feeding_exact
  listen_only_feeding_corrected
  listen_only_diaper_exact
  listen_only_burping_exact
  listen_only_medication_candidate
  listen_only_action_rejected
  ```

  Every value must be a non-negative bounded integer. Do not add command text, corrected
  text, character differences, edit distance, confidence or medication slots.

- [x] **Step 2: Count exactly one terminal classification per armed utterance**

  Reply echo/replay bookkeeping remains independent. Do not double-count a corrected
  Feeding result as both exact and corrected. Timeout and model/output failure use their
  existing counters.

- [x] **Step 3: Keep the status schema closed**

  Extend writer and CLI allowlists together; reject unknown/non-integer fields and avoid
  changing private runtime settings.

- [x] **Step 4: Run focused GREEN**

  ```bash
  .venv-alpha/bin/python -m pytest -q \
    tests/voice/test_worker.py \
    tests/voice/test_listen_only_runtime.py \
    tests/tools/test_voice_status.py
  ```

- [x] **Step 5: Run privacy scans and update the review log**

  ```bash
  git diff --check
  git diff -- services/voice tools/voice_status.py tests/voice tests/tools | \
    rg -n 'V1:|token|password|BEGIN .*PRIVATE|rtsp://|家庭音频|完整转写'
  ```

  Expected: `git diff --check` passes and the sensitive scan has no true positive.

**Acceptance:** a later supervised run can distinguish action families and corrected
Feeding without retaining what the caregiver said.

**Commit boundary:** when authorized, `feat: expose bounded voice action counters`.

---

### Task 6: Build the generated/public action benchmark

**Files:**
- Create: `tools/voice_action_benchmark.py`
- Create: `tests/tools/test_voice_action_benchmark.py`
- Modify: `tests/deploy/test_alpha_commands.py` only if a Make target is added
- Modify: `Makefile` only if the existing command pattern requires it
- Modify: `docs/reviews/2026-08-27-voice-care-multi-intent-asr-optimization-log.md`

**Interfaces:**
- Consumes: a manifest containing only generated/public 16 kHz mono PCM, source kind,
  license, fixture ID and expected fixed action code.
- Produces: aggregate candidate metrics: evaluated, correct, false accepts, rejected,
  p50/p95 latency, RSS if available and gate pass/fail. It emits no transcript.

- [ ] **Step 1: Write manifest-validation RED tests**

  Reject symlinks, traversal, missing license, household/private source kinds, duplicate
  files, invalid PCM, unknown action codes and free-form expected text.

- [ ] **Step 2: Write evaluation RED tests**

  Use injected fake ASR engines. Require exact/corrected distinction, high-risk
  medication classification, false-accept count and no transcript field in JSON output.

- [ ] **Step 3: Implement the minimal aggregate evaluator**

  Run the current classifier over engine results in memory, immediately discard text,
  and serialize only fixed metrics. When `--manifest` is omitted on macOS, mirror the
  existing bounded benchmark pattern: create a private temporary directory, synthesize
  the fixed corpus with the installed `Tingting` voice at four fixed rates, validate it,
  evaluate it and delete the directory on every exit path. Do not reuse the historical
  Whisper benchmark's candidate list or change its evidence.

- [ ] **Step 4: Build the first generated corpus**

  Generate exactly 24 positive samples covering all approved exact actions and 48
  adversarial negatives covering no wake, negation, stop/cancel, question, semantic
  neighbors, cross-action and ordinary statements. Generate them only in the validated
  temporary directory and mark the manifest `source_kind=generated`,
  `license=GENERATED`; do not track the WAV files.

- [ ] **Step 5: Run the current Paraformer candidate**

  ```bash
  .venv-alpha/bin/python -m pytest -q tests/tools/test_voice_action_benchmark.py
  .venv-alpha/bin/python tools/voice_action_benchmark.py \
    --candidate current-paraformer \
    --json
  ```

  The CLI owns and removes its temporary generated corpus. Never paste its private
  temporary path into Git or the review log. Record only aggregate output.

- [ ] **Step 6: Apply the upstream decision gate**

  - If restricted correction reaches the positive target with zero false accepts, keep
    the current Paraformer and do not install another model.
  - If observed synthetic/public errors are proven homophone-only, request separate
    approval for an isolated HomophoneReplacer FST A/B; do not change production runner.
  - If recall remains insufficient, resolve KWS model licensing before requesting a
    KWS+ASR A/B.
  - ContextualParaformer requires a separate model-migration spec and is not executable
    under this plan.

- [ ] **Step 7: Append exact metrics and the keep/reject decision to the review log**

**Acceptance:** the same fixed corpus compares current behavior without leaking text;
zero false accepts is mandatory, and model alternatives remain behind license/approval
gates.

**Commit boundary:** when authorized, `test: benchmark closed voice care actions`.

---

### Task 7: Run the complete software and documentation gate

**Files:**
- Modify: `SUMMARY.md`
- Modify: `docs/STATUS.md`
- Modify: `docs/CHECKPOINT.md`
- Modify: `docs/NEXT.md`
- Modify: this plan and the review log

**Interfaces:**
- Consumes: Tasks 1–6.
- Produces: one reproducible software checkpoint, not a household/device acceptance.

- [ ] **Step 1: Run focused Voice tests**

  ```bash
  .venv-alpha/bin/python -m pytest -q \
    tests/voice/test_care_action.py \
    tests/voice/test_asr_correction.py \
    tests/voice/test_intent.py \
    tests/voice/test_listen_only.py \
    tests/voice/test_listen_only_runtime.py \
    tests/voice/test_worker.py \
    tests/voice/test_tts.py \
    tests/voice/test_camera_reply.py \
    tests/tools/test_voice_action_benchmark.py \
    tests/tools/test_voice_status.py
  ```

- [ ] **Step 2: Run authoritative Voice and repository gates**

  ```bash
  make alpha-voice-test
  .venv-alpha/bin/python -m pytest -q
  .venv-alpha/bin/python -m compileall -q services/voice tools
  git diff --check
  ```

  Record every real count. Missing tools/dependencies are blockers, not PASS. A historical
  test count is never copied as fresh evidence.

- [ ] **Step 3: Review the final tracked diff**

  Confirm no changes to go2rtc patch, Xiaomi transport, camera settings, PTZ, Baby Care
  vendored contract, signing, outbox or unrelated Guardian workers. Scan for credentials,
  private endpoints, runtime media/database/settings and generated household artifacts.

- [ ] **Step 4: Update authoritative docs consistently**

  Mark only software-proven gates complete. Keep Camera Reply false, full-care closed and
  all household/action accuracy statuses unverified until Task 8.

- [ ] **Step 5: Self-review the plan and review log**

  Search for contradictory status, unfilled placeholders, stale head, copied historical
  counts and claims unsupported by commands. Correct them before handoff.

**Acceptance:** focused, full, compile, diff and privacy gates pass with real evidence;
docs distinguish software from device proof.

**Commit boundary:** when the user authorizes local commits, use one focused commit per
completed task or one explicitly approved docs/test squash; do not push.

---

### Task 8: Perform separately approved adult-supervised i9 acceptance and resolution

**Files:**
- Create after execution:
  `docs/reviews/2026-08-27-voice-care-multi-intent-asr-optimization-resolution.md`
- Modify: `docs/reviews/2026-08-27-voice-care-multi-intent-asr-optimization-log.md`
- Modify: `SUMMARY.md`
- Modify: `docs/STATUS.md`
- Modify: `docs/CHECKPOINT.md`
- Modify: `docs/NEXT.md`

**Interfaces:**
- Consumes: Task 7 software PASS, installed exact candidate and explicit human approval.
- Produces: aggregate adult-supervised recognition evidence and final keep/rollback
  decision; no raw audio/transcript and no Baby Care write.

- [ ] **Step 1: Establish the human/device preflight**

  Require logged-in interactive i9 context, explicit visible/audible readiness,
  `camera_reply_enabled=false`, healthy Voice idle, healthy single Xiaomi producer,
  no baby required and no care write. Record only fixed preflight results.

- [ ] **Step 2: Run Feeding isolation**

  From fresh counters, run at least 10 approved positive follow-ups and 20 negative
  controls spanning no wake, negation, cancellation, question, semantic neighbor and
  cross-action. Any false accept stops the gate and rolls back correction.

- [ ] **Step 3: Run diaper and burping independently**

  Clear/record counter baselines between action families. Validate each exact approved
  phrase and its negative/cross-action controls. Do not infer diaper contents or burp
  success from command recognition.

- [ ] **Step 4: Run medication candidate isolation**

  Validate only exact high-risk candidate counters. Require no spoken save confirmation,
  no external intent, no outbox and no Baby Care data. Do not speak or record a real
  household medication name or dose for this gate.

- [ ] **Step 5: Decide whether Camera Reply V3E may resume**

  Only if every ASR action gate is clean may a separately approved Camera Reply V3E
  matrix resume. Its movement, truncation, duplicate, lifecycle, producer, timeout and
  EOF rules remain independent and cannot be marked passed by ASR results.

- [ ] **Step 6: Write the resolution**

  Compare baseline and final recall, false accepts, p50/p95/RSS, action coverage,
  software/device evidence, privacy, model decisions, rollback and remaining Baby Care
  contract work. State exactly which upstream alternatives were evaluated, deferred or
  rejected and why.

- [ ] **Step 7: Request remote-operation authority separately**

  Report local branch/head, commits and dirty state. Push, PR, merge, stable integration
  and release remain separate user decisions.

**Acceptance:** Feeding, diaper, burping and medication-candidate behavior each have
independent aggregate evidence, zero observed false accepts and an auditable resolution.
This still does not prove unattended care, medication correctness, child speech,
night/far-field accuracy or Baby Care writes.

---

## Execution Handoff

After explicit implementation approval, continue from the first unchecked task. Use
TDD and update the review log after every slice. Do not dispatch overlapping workers to
the same files. The implementation session must stop for human authority before any
model installation, household capture/playback, Camera Reply enablement, commit, push,
PR, protected-branch change or Baby Care contract expansion.
