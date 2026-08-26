# Voice Care v1 Cross-Product Design

Status: approved for staged implementation on 2026-08-19; local V1 model architecture
approved on 2026-08-20
Date: 2026-08-19
Products: `baby-monitor-local` and `baby-care`

## 1. Mission And Non-Goals

Voice Care v1 lets an enrolled caregiver record ordinary baby-care facts through local
speech without turning Baby Guardian into a second care database or identity system.
The minimum useful loop is:

```text
caregiver speaks
-> local wake, speech and speaker verification
-> Baby Care validates identity and opens a pending care session
-> local bounded acknowledgement
-> caregiver completes and confirms the fact by voice
-> Baby Care writes the authoritative record
-> the caregiver can review, correct or undo it through existing Baby Care behavior
```

The first production fact is feeding. The design must later support diaper, sleep,
bathing and factual medication records through the same intent contract without
changing the ownership boundary.

Success means that a correctly enrolled caregiver can start and finish a feeding by
voice, the resulting Baby Care record has the correct family, baby, caregiver, time and
typed feeding facts, retries do not duplicate it, and no response says that a record was
saved before Baby Care committed it.

Voice Care v1 is not:

- continuous household audio recording or cloud speech processing;
- background speaker surveillance or identification without a wake and explicit claim;
- a medical monitor, diagnosis service, medication recommendation or dose calculator;
- authority for family administration, export, deletion, permissions or security
  configuration;
- a direct Baby Guardian write into the Baby Care database;
- evidence that Xiaomi camera backchannel audio is safe or usable before a real-device
  gate;
- cry detection, emotion detection or a replacement for direct adult supervision.

## 2. Stakeholders And System Boundary

### 2.1 People

- Dad and Mom are family administrators and caregivers.
- Nanny is a caregiver with care-write permission but no family-admin permission.
- The baby is the subject of the record, never an actor or identity source.
- A supervising adult performs enrollment, device pairing, uncertain-identity review
  and real-device acceptance.

### 2.2 Product ownership

`baby-monitor-local` owns device-edge behavior:

- Xiaomi audio ingest and health;
- a short in-memory audio ring;
- voice activity detection, wake phrase, ASR and bounded TTS;
- local speaker-profile enrollment and verification;
- optional randomized phrase challenges;
- night response volume and camera/i9 output selection;
- delivery of versioned structured intents to Baby Care;
- a bounded local pending-delivery queue when Baby Care is unavailable.

`baby-care` owns care truth and authorization:

- family, baby, membership and permission identity;
- local device pairing and the binding from a voice profile ID to a membership;
- explicit caregiver takeover checkpoints;
- pending Voice Care sessions and their state transitions;
- default bottle amount settings and other care defaults;
- typed feeding validation, warnings, final writes, revisions, undo and audit;
- Dashboard review, correction and later analysis.

Neither product owns raw truth alone. Baby Local owns observations and verification
evidence; Baby Care owns the accepted care fact and its history.

### 2.3 Deployment boundary

- The Xiaomi MJSXJ17CM and Intel i9 are the first audio path.
- Raw audio remains on the i9 by default and is never sent to Baby Care.
- Baby Care and Baby Local remain independently deployable.
- A Baby Local outage must not break manual Baby Care recording.
- A Baby Care outage must not break camera viewing, Guardian alerts, environment
  monitoring or microSD recording.
- Temperature/humidity recognition and Voice Care run as independent workers and may be
  developed and tested in parallel.

## 3. Context And Feedback Loop

The system separates observations, identity hypotheses, decisions and outcomes:

| Layer | Example | Owner |
|---|---|---|
| Observation | wake detected, recognized words, local speaker embedding match | Baby Local |
| Hypothesis | the speaker claims Dad and resembles Dad's enrolled profile | Baby Local |
| Decision | the paired profile is allowed to act as Dad for this care session | Baby Care |
| Outcome | feeding session committed, corrected, voided or left pending | Baby Care |

The closed loop is:

1. Observe speech locally.
2. Estimate intent and claimed speaker with explicit confidence state.
3. Ask Baby Care to accept, challenge or reject the identity/session transition.
4. Speak only the semantic response returned by Baby Care.
5. Collect the final typed fact and read it back.
6. Commit the record through Baby Care.
7. Expose the result for review, correction and undo.
8. Measure false activation, identity conflict, correction and abandonment outcomes.

Model output and speaker similarity never become a care fact by themselves.

## 4. Subsystems And Interface Contracts

### 4.1 Xiaomi audio probe

Before production ASR work, an i9-only probe must establish:

- the active `source` advertises a receive-only audio medium;
- codec, sample rate and channels are supported by the local decoder;
- a 60-second receive run contains advancing audio packets without exposing the source
  URL, account data or room audio;
- 10-minute receive behavior does not accumulate unbounded timestamp drift or memory;
- video, Guardian and gauge workers remain healthy while the probe runs;
- stopping the probe releases all consumers and files.

The probe records only stable status codes and bounded metrics. It does not save or
commit household audio. Synthetic OPUS fixtures cover software behavior; a real adult
speaking with no infant present covers the physical gate.

Incoming camera audio and camera backchannel are separate gates. v1 may use the i9 Mac
or a dedicated local speaker for TTS even when camera backchannel is unavailable.

### 4.2 Voice capture worker

The Voice Capture Adapter is a new independent Baby Local worker. It consumes a
dedicated audio stream rather than adding audio to `analysis` or
`analysis_realtime`. It has bounded CPU, memory, concurrency, restart and health
contracts and cannot restart the full Guardian stack.

The worker performs:

```text
audio frames
-> voice activity detection
-> bounded utterance capture
-> ASR
-> exact wake-prefix validation
-> explicit identity-claim extraction
-> local speaker verification
-> structured intent
```

V1 does not add a separately trained keyword model. Silero VAD may open one bounded
utterance window only after speech is observed. The window includes at most 500 ms of
pre-roll, closes after 800 ms of terminal silence and never exceeds eight seconds. The
local Mandarin ASR result must begin with the exact normalized wake entry `小小`, or
with the single fixed optional lead `嘿` before `小小`. The optional lead may be
separated by a punctuation/whitespace boundary or directly concatenated when the local
ASR omits punctuation; both lexical tokens remain exact. Normalization removes only
surrounding whitespace and punctuation and does not accept homophones, fuzzy matches,
repeated wake words, sentence-internal wake words or any other lead. Because an approved
local recognizer may omit Chinese punctuation, the prefix boundary may also be proven
by one fixed, source-controlled post-wake care-vocabulary prefix. This is a lexical
boundary only: an empty remainder,
an unknown or repeated prefix, incidental words such as `小小鸟` and sentence-internal
`小小` remain rejected, and the downstream closed intent parser must still accept the
entire command independently. A missing prefix returns `wake_not_detected`, produces
no intent and cannot establish a caregiver session.

Normal audio stays in the existing 15-second memory ring. Raw samples for an utterance
are discarded as soon as it reaches a terminal result. ASR text is held only long enough
to derive one closed intent and is then discarded; it is not written to status, logs,
SQLite, Baby Care or diagnostics. Debug audio or transcript persistence is disabled in
production and cannot be enabled through a public API.

One supervised, operator-approved ASR calibration workflow is the only persistence
exception. It may retain at most 20 clips of fixed, pre-displayed adult test phrases,
each no longer than eight seconds, solely in ignored private storage encrypted with a
dedicated i9 Keychain key. It never records continuously, starts only from an explicit
local operator command, stores no free-form transcript, is never read by the production
worker and exposes only aggregate exact-match and latency results. The corpus remains
local until the operator separately approves deletion; Git, logs, status, Baby Care,
Ollama and network APIs never receive its audio or encryption key.

The calibration operator has two separate modes. The Silero mode proves real utterance
segmentation and remains fail-closed when zero or multiple spans are observed. A fixed-
window fallback may store one explicitly prompted eight-second clip without treating
VAD as passed; it exists only to isolate camera-to-Whisper accuracy from VAD accuracy.
Production Voice Care still requires the Silero path and never reads either calibration
mode's private corpus.

The i9 Keychain boundary must also work from the installed non-interactive Voice
launchd job. A secret created from Terminal is not considered deployable evidence:
macOS can bind generic-password access to the responsible interactive application and
return `errSecInteractionNotAllowed` to Codex or launchd even when both run as the same
user. Voice Care therefore uses one repository-built native helper with a fixed app
bundle identifier and explicit stable designated requirement. The helper alone calls
Security.framework. It accepts only the fixed Voice Care service, an allow-list of
Voice Care account names and fixed read/create/delete operations; delete is reachable
only through an explicit profile revocation or a failed-publication rollback and never
through calibration evaluation. It rejects a terminal stdout, caller-supplied service,
arbitrary size and unknown account.
Secret bytes travel only through an anonymous parent-owned pipe and remain in memory.
They never enter argv, environment, logs, status, files or network traffic. The
operator may need to approve this stable helper once in the logged-in macOS session;
after that, both calibration and the installed launchd worker must pass the same
non-interactive read probe before Voice can be enabled.

The already-captured calibration corpus predates the helper and uses the legacy
`voice-asr-calibration-key.v1` item owned by the interactive Terminal/Python identity.
One fixed local migration may read that 32-byte value in the logged-in Terminal and
write the identical bytes through the helper under
`voice-asr-calibration-key.v2`. The bytes stay in memory and cross only the helper's
anonymous stdin pipe; the corpus ciphertext is not rewritten. The migration refuses a
missing legacy key or a different existing v2 key. It does not delete v1; removal of the
orphaned legacy item requires a separate explicit deletion approval after every v2 gate
passes. All normal calibration, Codex and launchd reads use v2 only.

ASR tuning is one bounded bake-off, not an open-ended sequence of per-phrase patches.
Every profile runs against the identical encrypted corpus and may use only one global
decoder policy: the current baseline, no hotwords, a fixed care-domain vocabulary, or
that same vocabulary with a larger fixed beam. It must never receive the expected text
for the current clip as a prompt, prefix, hotword or correction. Diagnostics may expose
only the public prompt ID, edit distance, exact/wake counts and aggregate latency; they
must not expose recognized text. The selected profile still requires every phrase to
match after the approved whitespace/punctuation normalization, every wake decision to
match and P95 latency to stay at or below three seconds. A number-format classifier may
describe an Arabic/Chinese numeral-only mismatch, but it does not turn that mismatch
into a pass. If no approved Whisper candidate/profile passes, Voice remains disabled
and a different ASR family requires a separate model, license and runtime amendment.

Silero acceptance is separate from ASR acceptance. The same private clips may be
decrypted in memory to report bounded signal energy and VAD probability aggregates,
and a generated non-household Mandarin speech sample provides an independent runtime
control. If the control fails, fix the ONNX state/context implementation. If the
control passes but Xiaomi clips fail and their signal is at least 12 dB below the
control, a VAD-only preprocessor may apply at most 12 dB of deterministic gain without
clipping; ASR and persisted calibration ciphertext remain unchanged. The speech
threshold stays at 0.50. If this still does not produce exactly one bounded span per
prompt, production Voice remains disabled rather than lowering the gate.

### 4.2.1 Approved local model and runtime boundary

The first V1 implementation uses this fixed local stack:

- Silero VAD ONNX at 16 kHz mono for speech activity. The artifact and MIT license are
  installed locally, pinned by source revision and SHA-256 and never downloaded by a
  running worker.
- Official OpenAI multilingual Whisper `base` and `small` were the first closed ASR
  bake-off candidates. Both code and weights use the upstream MIT license. Their
  installed-i9 matrix is retained as historical evidence; neither passed the private
  exact-match gate. The approved replacement candidate and runtime are defined in
  section 4.2.2. Any selected artifact, conversion metadata and SHA-256 become fixed
  runtime configuration before V1 can be enabled.
- SpeechBrain `spkrec-ecapa-voxceleb` is the first speaker-embedding candidate. Its
  upstream model card declares Apache-2.0. It is used only for local adult enrollment
  and verification; the exact source revision, files and digests are pinned before use.
- macOS `AVSpeechSynthesizer` is the first response engine. It speaks only allow-listed
  semantic templates and typed confirmed values. It does not receive raw model prose,
  credentials, internal identifiers, private diagnostics or a Baby name.

Every model is optional at runtime and fail-closed. Missing files, digest mismatch,
unsupported tensor shape, non-finite output, timeout or runner failure returns a stable
unavailable reason and creates no wake, identity, intent, care record or success phrase.
No model artifact is committed to Git, fetched at worker startup or sent to Ollama or a
cloud API.

### 4.2.2 Approved Mandarin ASR family amendment

The installed-i9 Whisper matrix is exhausted: no approved base/small profile reached
6/6 exact matches, while adding another prompt, hotword profile or phrase correction
would violate the bounded bake-off contract. The approved next candidate is
`csukuangfj/sherpa-onnx-paraformer-zh-2023-09-14` at source revision
`def027084691107096b5ebba69785756d63de6c5`, using only `model.int8.onnx` and
`tokens.txt`. Its model card declares Apache-2.0. The runtime is `sherpa-onnx==1.13.6`,
also Apache-2.0, installed only in ignored `runtime/voice-asr-venv` on Darwin x86_64.

Paraformer runs in one separately supervised offline child process. The parent validates
the canonical artifact manifest and isolated environment before spawn, sends only one
length-prefixed mono 16 kHz s16le utterance through anonymous stdin, and accepts only one
bounded canonical JSON response containing schema version, Mandarin text and inference
latency. The child receives a minimal offline environment with no proxy, token or model-
hub credentials; it cannot download at startup. Timeout, malformed PCM, extra response
fields, non-UTF-8 text, child exit or digest mismatch destroys the child and returns
`voice_model_unavailable`. Raw audio and transcripts are never written by this adapter.

The Paraformer evaluation receives the identical six encrypted fixed-prompt clips in
memory and no expected phrase, hotword file, language-model correction, punctuation
model or inverse-text-normalization layer. Only the existing whitespace/punctuation
normalization may be used for scoring. It must reach 6/6 exact, 6/6 wake decisions and
P95 at most 3,000 ms. The older Whisper results remain historical evidence and cannot
be combined with Paraformer per phrase. A failing Paraformer gate leaves Voice disabled
and requires another separately approved model/runtime/license amendment.

The sherpa-onnx Chinese keyword-spotting models remain unapproved for V1. Approval of
the Paraformer ASR artifact above does not approve a KWS artifact: the selected KWS
weights do not currently carry an explicit model-specific redistribution license. A
later wake-model replacement requires a new recorded model/license review and the same
acceptance gates; it is not a silent runtime configuration change.

Guardian cry classification remains a separate A8 gate. Voice Care V1 neither enables
cry analysis nor treats speech, ASR or speaker output as evidence of crying.

### 4.3 Device pairing

Baby Local never receives a reusable caregiver password or browser session cookie.
Pairing is initiated by an already authenticated family administrator in Baby Care:

1. Baby Local generates an Ed25519 device key in the i9 Keychain-backed local store.
2. Baby Care displays a short-lived, one-time pairing challenge.
3. Baby Local signs the challenge.
4. Baby Care stores the public key, device ID, family scope, allowed Voice Care
   capabilities and revocation state.
5. Baby Local stores only the scoped device credential and endpoint configuration in
   the Keychain-backed store.

Every intent contains a unique request ID, timestamp and signature. Baby Care rejects
expired, replayed, revoked, cross-family or capability-exceeding requests. Pairing never
grants family-admin, export or destructive permissions.

### 4.4 Speaker enrollment and profile ownership

Enrollment begins in an authenticated Baby Care membership session. The member confirms
their own profile, and a family administrator approves the profile-to-family binding.
The member then reads several prompted phrases at normal and quiet volume. Enrollment
uses adult speech only.

Baby Local stores:

- the speaker embedding and bounded calibration statistics encrypted with a
  Keychain-protected local key;
- an opaque `voiceProfileId`;
- model/version and enrollment quality state;
- no family password, Baby Care session cookie or raw long-term enrollment recording.

Baby Care stores:

- `voiceProfileId` -> family membership binding;
- paired device ID, enrollment/revocation state and timestamps;
- no embedding, raw audio or transcript.

Profiles are revocable and deletable. Deleting or revoking a membership disables the
binding without requiring access to raw audio. Re-enrollment creates a new profile ID.

### 4.5 Hybrid caregiver identity

An identity claim is not identity proof, and a speaker match is not authorization. The
accepted identity combines:

```text
explicit claim
+ local speaker-verification state
+ paired profile-to-membership binding
+ Baby Care permission and caregiver-session state
```

The first command in a care period is an explicit takeover, for example:

```text
"小小，我是爸爸，现在我来照顾香香。"
```

Baby Local verifies that the claim and enrolled profile agree. Baby Care then creates
the existing explicit caregiver handoff/checkpoint. Later care commands do not repeat
the spoken identity claim, but every utterance still requires a `verified` match to the
active profile. The active voice session ends on an explicit handoff, device/profile
revocation, identity conflict, Voice worker restart or manual termination. Fixed
schedules and silent time-based actor changes never select a caregiver.

Speaker-verification states are closed:

- `verified`: claim and enrolled profile agree within the accepted calibration band;
- `uncertain`: audio is too quiet, short, noisy, overlapping or outside calibration;
- `mismatch`: claim and best allowed profile disagree;
- `not_enrolled`: no usable profile is bound on this device.

Only `verified` may establish a new voice caregiver session. `uncertain` may request a
randomized short phrase or authenticated Baby Care confirmation. `mismatch` and
`not_enrolled` cannot write a final care record.

Voice verification is never accepted for family administration, export, membership,
credential, device-pairing or destructive actions.

### 4.6 Versioned Voice Care intent

Baby Local sends structured data, not raw transcripts or audio. The v1 envelope is:

```text
VoiceCareIntentV1
  schemaVersion: 1
  requestId: UUID
  deviceId: opaque ID
  voiceProfileId: opaque ID or null
  occurredAt: offset timestamp
  intentType: closed enum
  careSessionId: UUID or null
  speakerState: verified | uncertain | mismatch | not_enrolled
  payload: strict intent-specific object
  source: voice
  modelVersion: bounded non-secret label
  signature: detached device signature
```

The first closed intent set is:

- `caregiver_takeover`
- `feeding_start`
- `feeding_update`
- `feeding_end`
- `care_confirm`
- `care_cancel`

The payload contains only typed facts required by the intent. It never contains raw
audio, embeddings, free-form model reasoning, household paths, camera/account details,
credentials or unrestricted transcripts.

Baby Care adds `voice` as a distinct care source value rather than disguising a voice
write as `manual`, `device`, `guardian` or `ai`. Existing source meanings remain
unchanged.

Baby Care resolves family, baby and membership from the paired device and profile. It
must not trust caller-supplied family, baby or actor IDs.

### 4.7 Semantic response contract

Baby Care returns a closed semantic result:

- `accepted_pending`
- `saved`
- `needs_identity`
- `needs_confirmation`
- `identity_mismatch`
- `state_conflict`
- `temporarily_unavailable`
- `rejected`

Baby Local maps these codes to short local phrases. It does not improvise a success
claim. In particular:

```text
saved -> "好的，已经记录。"
accepted_pending -> "好的，已经开始记录，结束后我会再确认。"
temporarily_unavailable -> "我听到了，但还没有保存，请稍后确认。"
```

TTS output contains no private diagnostic, credential, internal identifier, model
score or database detail.

## 5. Feeding Session Behavior

### 5.1 Start

`feeding_start` creates a durable pending Voice Care session in Baby Care, not a final
feeding event. It records server-derived family, baby and caregiver identity, the
accepted start time, source, request ID and device/profile references.

Baby Care may attach the family-admin-configured default bottle amount for the current
baby and liquid type as a proposal. If liquid type is still unknown, no default amount
is selected. A default is never silently committed as consumed milk.

Example:

```text
Caregiver: "小小，我要喂奶了。"
System: "爸爸，好的，已经开始记录，结束后我会再确认。"
```

### 5.2 During feeding

Baby Local may attach bounded, non-authoritative candidate observations such as speech
updates or a feeding-like time interval. Visual Guardian observations never infer milk
amount and never overwrite a human statement.

The caregiver may say:

```text
"这是配方奶。"
"先按默认奶量。"
"刚才有拍嗝。"
```

These update the pending session only. They are not final care facts.

### 5.3 Finish and confirmation

For bottle feeding, the final record requires liquid type and actual consumed
milliliters. Bottle capacity remains optional metadata and never contributes to intake.

For direct breastfeeding, the final record contains total minutes only. The system does
not infer milliliters or left/right values. It may calculate an elapsed-time proposal
from accepted session timestamps, but must read it back for confirmation.

Examples:

```text
"喂完了，喝了六十毫升配方奶。"
-> "确认记录：配方奶六十毫升，是否正确？"

"亲喂结束。"
-> "本次亲喂十八分钟，是否按十八分钟记录？"
```

Only an affirmative `care_confirm` produces the existing typed Baby Care feeding
record. The same final request ID is idempotent. Warnings such as possible duplicate or
unusual value remain Baby Care decisions and require explicit confirmation.

### 5.4 Correction, cancellation and timeout

- Before final commit, voice updates change only the pending session.
- After commit, changes use the existing versioned Baby Care edit/revision path.
- `care_cancel` closes the pending session without creating a feeding event.
- An abandoned session becomes `needs_review`; it does not silently use the default.
- Restart recovery must distinguish pending, confirmed, committed, cancelled and
  needs-review states.

## 6. Other Care Facts And Risk Levels

The v1 pilot implements feeding only. Later facts reuse the same identity and intent
envelope behind separate stage gates.

Low-risk ordinary care facts may use the verified caregiver session and explicit
readback:

- diaper;
- sleep start/wake;
- bathing;
- burping and spit-up observations.

Medication remains factual recording only. It requires exact medication name, dose,
unit and administered time read back in full, followed by explicit confirmation. Voice
Care never recommends medication, calculates dose or interprets medical safety. An
uncertain field prevents the write.

## 7. Night Behavior

Night mode changes response presentation, not authorization or safety:

- wake and ASR thresholds are calibrated for quiet adult speech without increasing
  false acceptance;
- TTS uses a lower local volume and shorter phrases;
- the user may select i9 speaker or an independently accepted camera backchannel;
- Guardian safety notification volume, delivery and policy remain unchanged;
- low volume never lowers the identity threshold or converts `uncertain` to
  `verified`;
- if a second spoken challenge would cause excessive disturbance, the system offers
  authenticated Baby Care confirmation rather than guessing.

## 8. Failure Handling And Reversibility

### 8.1 Baby Care unavailable

Baby Local may keep a bounded encrypted structured-intent queue with a short retention
limit. It says that the fact is not saved. Reconnection may deliver the pending intent,
but a stale or ambiguous care fact requires caregiver reconciliation before final
commit. Medication intents are never auto-committed after an outage.

### 8.2 Audio or model unavailable

Voice Care becomes unavailable without affecting viewing, Guardian, environment
monitoring or manual Baby Care entry. It does not substitute visual inference or a
language-model guess for missing speech.

### 8.3 Conflicting caregivers

If two enrolled caregivers claim the same session or the active handoff conflicts with
the verified profile, Baby Care returns `needs_identity` or `state_conflict`. It does
not silently transfer ownership.

### 8.4 Duplicate and delayed intents

Baby Care applies request-id idempotency, timestamp bounds, device-signature checks and
closed session transitions. Duplicate delivery returns the winning result. A delayed
intent cannot reopen a committed or cancelled session.

### 8.5 Privacy and deletion

Raw audio is memory-only by default. Voice embeddings are sensitive local biometric
material, use private modes and Keychain-backed encryption, and can be deleted or
re-enrolled. Baby Care never stores embeddings. Logs and diagnostics use stable codes
and bounded aggregate metrics only.

## 9. Minimum Closed-Loop Pilot

The first pilot is deliberately narrow:

- one household;
- one MJSXJ17CM camera and Intel i9;
- Dad and Mom enrolled locally;
- one Baby Care family and baby;
- explicit caregiver takeover;
- feeding start, bottle finish, direct-breastfeeding finish, confirm and cancel;
- i9 speaker response first;
- no camera backchannel dependency;
- no diaper, medication, cry or Guardian visual automation.

Use generated audio for software tests and adult-only supervised household tests. No
real infant is required for acceptance.

The pilot completes only when the system proves the entire loop, including a corrected
or cancelled record, rather than only wake-word or ASR accuracy.

## 10. Metrics And Validation

### 10.1 Software evidence

- closed-schema parsing rejects unknown fields and overlong payloads;
- cross-family, revoked, replayed and unsigned intents fail closed;
- identity claim/profile mismatch cannot create a caregiver checkpoint or care fact;
- retries are idempotent and concurrent finalization has one winner;
- no response says `saved` before the Baby Care transaction commits;
- raw audio, transcript, embedding, credentials and private addresses do not enter
  Baby Care, logs, diagnostics or Git;
- Baby Care outage and Voice worker crash preserve manual care behavior;
- default bottle amount never becomes intake without explicit confirmation;
- direct breastfeeding never produces inferred milliliters;
- night mode cannot change Guardian alert policy or identity acceptance.

### 10.2 Real-device evidence

- inbound OPUS audio health and bounded 10-minute stability;
- wake and ASR results at normal and quiet night volume, near/far positions and with
  typical room noise;
- Dad/Mom speaker false acceptance and false rejection under normal, quiet and mildly
  changed voice conditions;
- replayed enrollment phrases and overlapping voices are rejected or challenged;
- end-to-end acknowledgement latency and Baby Care commit latency;
- no degradation of video, Guardian, gauge or Dashboard workers;
- successful recovery after audio, Baby Care and network interruption.

Report false acceptance, false rejection, ambiguous rate, correction rate, abandoned
session rate, duplicate-prevention result and caregiver workload. A single successful
demo is not acceptance evidence.

## 11. Human Review And Escalation

Human action is mandatory for:

- device pairing and voice-profile enrollment;
- real Xiaomi audio and optional backchannel acceptance;
- identity mismatch, ambiguous overlapping speech or unrecognized caregiver;
- stale pending sessions after an outage;
- medication field uncertainty;
- deletion, revocation and re-enrollment;
- any family-admin or destructive action.

The system always exposes the final record in Baby Care for review, correction and
undo. Corrections preserve the existing revision history rather than rewriting the
original fact invisibly.

## 12. Risks, Unknowns And Reversible Decisions

Known unknowns:

- sustained MJSXJ17CM audio timestamp behavior beyond the completed bounded V0 gate;
- camera backchannel quality and model-specific noise behavior;
- acceptable night false-reject rate without lowering false-accept protection;
- speaker verification under illness, whispering and microphone distance;
- whether Whisper `base` or `small` is the smallest model that passes the installed-i9
  Mandarin command and latency gate;
- LAN/TLS deployment details between the two independently deployable products.

Reversible choices:

- i9 speaker is the v1 response output; camera backchannel is a later adapter;
- ASR, VAD, wake, speaker and TTS engines sit behind replaceable interfaces;
- numeric speaker thresholds are calibrated evidence, not part of the cross-product
  contract;
- the intent schema uses closed versioning so v2 can add care facts without changing
  v1 semantics;
- Voice Care remains a separate worker and can be disabled without migrating existing
  care data.

## 13. Stage Gates And Entry Criteria

### Gate V0: audio feasibility

Entry: current Xiaomi Alpha source works on i9.
Exit: inbound audio media, decoder compatibility, bounded 10-minute stability and
worker isolation pass. No ASR or care write is required.

### Gate V1: synthetic Voice Care contract

Entry: V0 evidence and approved cross-product contracts.
Exit: pinned local artifacts and licenses pass validation; public/synthetic audio drives
VAD, exact `小小`/`嘿，小小` wake validation, ASR, explicit identity, signed intent,
pending feeding, confirmation and final Baby Care write with complete security and
privacy tests. Missing or failing models, fuzzy wake text and uncertain identity create
no care write or success phrase.

### Gate V2: supervised Dad/Mom feeding pilot

Entry: V1 exact-head CI, paired i9 and two enrolled adults.
Exit: day/night bottle and direct-breastfeeding simulations, explicit handoff,
identity conflict, correction, cancellation and outage recovery pass with no infant
present.

### Gate V3: optional camera backchannel

Entry: stable receive-only voice path and separate backchannel probe.
Exit: bounded output volume, no static/noise hazard, clean shutdown and independent
failure behavior pass. Failure keeps the i9 speaker path.

### Gate V4: additional care facts

Entry: V2 family acceptance and measured correction/identity workload.
Exit: diaper and sleep first; factual medication only after its exact readback and
uncertainty gates pass. Each fact gets an independent RED-GREEN slice.

## 14. Repository And Delivery Ownership

- This specification is tracked with the Baby Local hardware-edge work, while the
  business schema and final-write implementation remain Baby Care-owned.
- Baby Care remains authoritative for the Voice Care API schema, device/profile
  bindings, caregiver session and final care writes.
- Baby Care publishes `voice-care-intent.v1.schema.json` from its contract package.
  Baby Local vendors that exact schema with its Baby Care source commit and SHA-256;
  both repositories run the same golden valid/invalid fixture corpus. A schema change
  requires a new contract version or an explicit vendored-digest update, never an
  unpinned cross-repository import.
- The implementation plan must split work into independently testable Baby Local and
  Baby Care tasks. Baby Care contract tests precede Baby Local integration work.
- No implementation begins until this written specification is approved.
- No push, PR, merge, protected-branch change or real-device mutation is implied by
  specification approval.

## 15. External Technical Evidence

- NIST Speaker Recognition Evaluation material documents the need to evaluate speaker
  verification across channel, noise, duration and operating conditions rather than
  treating voice as an absolute credential:
  <https://www.nist.gov/programs-projects/speaker-and-language-recognition>.
- NIST research on speaker de-identification shows that voice identity information can
  remain recoverable, supporting local-only, revocable and encrypted biometric
  handling:
  <https://www.nist.gov/publications/evaluating-identity-leakage-speaker-de-identification-systems>.
- go2rtc's Xiaomi support evidence lists the Xiaomi Smart Camera 2 PTZ family with
  CS2, HEVC and OPUS, while upstream reports also show model-specific backchannel and
  timestamp risks. These are feasibility evidence, not a substitute for the V0 i9
  gate: <https://github.com/AlexxIT/go2rtc/issues/1982> and
  <https://github.com/AlexxIT/go2rtc/releases/>.
- Silero VAD documents its MIT license, local ONNX runtime and 8/16 kHz support:
  <https://github.com/snakers4/silero-vad>.
- OpenAI documents Whisper's multilingual model sizes, limitations and MIT license for
  code and model weights: <https://github.com/openai/whisper/blob/main/model-card.md>
  and <https://github.com/openai/whisper/blob/main/LICENSE>.
- The pinned Paraformer model card declares Apache-2.0 and publishes immutable INT8
  model and token assets at revision `def027084691107096b5ebba69785756d63de6c5`:
  <https://huggingface.co/csukuangfj/sherpa-onnx-paraformer-zh-2023-09-14>.
- sherpa-onnx documents macOS x86_64 support, local Python inference and the exact
  Paraformer model invocation; its runtime is Apache-2.0:
  <https://pypi.org/project/sherpa-onnx/> and
  <https://k2-fsa.github.io/sherpa/onnx/pretrained_models/offline-paraformer/paraformer-models.html>.
- SpeechBrain publishes the selected ECAPA-TDNN model card under Apache-2.0:
  <https://huggingface.co/speechbrain/spkrec-ecapa-voxceleb>.
- Apple documents bounded speech synthesis and explicit stop/control through
  `AVSpeechSynthesizer`:
  <https://developer.apple.com/documentation/avfaudio/avspeechsynthesizer>.
- The unresolved model-specific licensing question for official sherpa-onnx keyword
  weights is recorded upstream and is why that KWS artifact is excluded from V1:
  <https://github.com/k2-fsa/sherpa-onnx/issues/3760>.
