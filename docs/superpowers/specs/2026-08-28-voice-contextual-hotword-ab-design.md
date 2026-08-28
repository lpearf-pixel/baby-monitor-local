# Voice Contextual/Hotword Isolated A/B Design

**Status:** Approved on 2026-08-28 for isolated design, implementation and evaluation.
Production model selection and deployment remain unapproved until every gate in this
document passes and a separate deployment checkpoint is recorded.

## 1. Goal

Determine whether an offline ContextualParaformer with a fixed care-domain hotword list
can improve the known two-stage Mandarin follow-up miss without weakening negatives or
changing the installed Voice service. The current pinned sherpa-onnx Paraformer remains
the production baseline throughout this slice.

This is an evaluation boundary, not a new production fallback. A missing, invalid,
slow, crashed or inaccurate candidate produces an unavailable/failed A/B result and has
no effect on Voice, go2rtc, the Xiaomi producer, Camera Reply or Baby Care.

## 2. Evidence and candidate selection

The current `sherpa-onnx 1.13.6` Paraformer uses greedy decoding and has no contextual
hotword input. Adding a config value cannot enable model-level biasing. Sherpa transducer
hotwords and Chinese KWS remain excluded because they require different models and the
currently reviewed Chinese KWS weights do not have a closed redistribution-license
decision.

The sole candidate is the official ModelScope ONNX ContextualParaformer repository:

- model: `iic/speech_paraformer-large-contextual_asr_nat-zh-cn-16k-common-vocab8404-onnx`;
- immutable Git revision: `8f0881c891ceba7360e215b04e54cad564a68c41`;
- model card license: Apache License 2.0;
- `model_quant.onnx`: 871,251,660 bytes,
  SHA-256 `f404e6eb532b54fd95761e2b4be4ed1998e8cff3cb3b930a9bee1f2d556e5035`;
- `model_eb.onnx`: 25,618,359 bytes,
  SHA-256 `d31446a5af664291a2922cca253a4200a523f347d6fc3cb1bff356bf60a116b6`;
- required small assets: `am.mvn`, `config.yaml`, `seg_dict`, `tokens.json`;
- fixed source URL base uses the immutable revision, never `master` or `latest`.

The isolated Python runtime uses FunASR's official ONNX package source at Git revision
`67d6d880841e0c8f3a33e0f98d3bfc2122e34eff`, whose package metadata declares
`funasr_onnx==0.4.2`, MIT, `numpy<=1.26.4` and CPU ONNX Runtime. The installer must pin
the complete resolved dependency set with hashes after proving Intel macOS compatibility;
it must not install into `.venv-alpha` or `runtime/voice-asr-venv`.

Official references:

- https://www.modelscope.cn/models/iic/speech_paraformer-large-contextual_asr_nat-zh-cn-16k-common-vocab8404-onnx
- https://github.com/modelscope/FunASR/blob/main/runtime/python/onnxruntime/README.md
- https://github.com/modelscope/FunASR/blob/main/runtime/python/onnxruntime/funasr_onnx/paraformer_bin.py
- https://github.com/modelscope/FunASR/blob/main/MODEL_LICENSE
- https://k2-fsa.github.io/sherpa/onnx/hotwords/index.html

## 3. Isolation architecture

Tracked code may add only an installer/validator, one bounded candidate runner, one A/B
evaluator, fixed manifests/templates, Make entry points and tests. Runtime state is:

```text
runtime/voice-contextual-venv/                 ignored candidate-only environment
runtime/models/voice-contextual-sources/...   ignored immutable download/source
runtime/models/voice-contextual/...           ignored validated published artifact
runtime/voice-contextual-ab/                   ignored aggregate/private local state
```

Every path is resolved beneath the repository runtime root, rejects symlinks and unsafe
ownership/modes, and is published only after file count, size and digest validation.
The candidate runner is a separate bounded subprocess with stdin/stdout framing, no
network, stderr discarded, a fixed Intel-CPU thread count, a 60-second startup bound and
a 3-second per-utterance bound. It receives completed memory-only 16 kHz mono PCM, returns
one bounded canonical JSON response and is destroyed on timeout, protocol error or
invalid output.

The evaluator imports no worker builder and never edits settings, plist files, Keychain,
launchd or installed model manifests. It does not open go2rtc or create a Xiaomi
producer. It runs only when explicitly invoked from the repository.

## 4. Fixed hotword policy

The candidate receives one source-controlled, space-separated hotword string built from
the existing approved low-risk wake/care command registry. It contains only the wake
word and exact feeding, diaper-change and burping phrases already accepted by the closed
parser. It excludes names, household vocabulary, free text, medication names/doses,
identities and any input derived from the current clip or private transcript.

The hotword set, order and digest are fixed. CLI callers cannot add, remove or weight a
word. The candidate's transcript still passes through the unchanged normalization,
closed action classifier and negative/question/cancellation protections. A hotword hit
alone never creates an action.

## 5. A/B corpus and privacy

Both engines receive identical PCM in a fixed order:

1. the existing generated/public action corpus: exactly 24 positives and 48 adversarial
   negatives;
2. an optional locally retained diagnostic sample set, admitted only through the
   existing private diagnostic inventory and identity/mode checks.

Generated audio lives in a private temporary directory and is not committed. Private
audio never leaves the i9, is never copied into the candidate model area, never becomes
training data and is never serialized by the evaluator. Each transcript is scoped to
one comparison, classified in memory and immediately discarded.

Persisted or printed results contain only fixed candidate IDs, availability, artifact
digests, sample counts, exact/correct/rejected/false-accept integer aggregates,
latency p50/p95, peak RSS, fixed reason codes and pass/fail. They contain no transcript,
character difference, PCM, filename, local absolute path, family identity or private
network value.

## 6. Gates

### 6.1 Artifact and runtime gate

- exact model/runtime revisions, license labels, required file set, byte counts and
  SHA-256 values pass;
- no extra model files, symlink, hardlink, unsafe owner/mode or repository escape;
- candidate environment is isolated and `pip check` passes;
- imports and warm-up pass on Intel x86_64 macOS with network disabled;
- startup, request, output and shutdown bounds fail closed without child leakage.

### 6.2 Generated/public A/B gate

- both baseline and candidate evaluate all 72 samples;
- candidate accepts all 24 approved positives through the unchanged classifier;
- all 48 negatives are rejected and false accepts equal zero;
- each low-risk action has complete coverage; high-risk medication candidates remain
  non-actionable and cannot be promoted by hotwords;
- candidate p95 inference is at most 3,000 ms and peak RSS is at most 2 GiB;
- baseline metrics are reported honestly; candidate failure never changes them.

### 6.3 Private-local diagnostic gate

The known retained two-stage failure may be evaluated locally only after the public gate
passes. The candidate must convert the fixed failed classification into the exact
approved low-risk action while the baseline remains an independently measured control.
Only aggregate classification and timing may be retained. Failure is a rejected
candidate, not authority to add a transcript-specific rewrite.

### 6.4 Production switch gate

Passing the prior gates proves only an isolated offline candidate. It does not switch
production. Deployment requires a separate checkpoint that records exact artifacts,
installed Intel evidence, worker lifecycle/recovery tests, one-at-a-time process
ownership, supervised real-device positives/negatives and a rollback to the current
sherpa Paraformer. No automatic fallback or shadow inference is allowed in production.

## 7. Error and cleanup semantics

Every error maps to a fixed reason such as `voice_contextual_unavailable`,
`voice_contextual_artifact_invalid`, `voice_contextual_protocol_invalid`,
`voice_contextual_timeout` or `voice_contextual_gate_failed`. Raw dependency errors and
paths are not emitted.

An interrupted download or build remains in an ignored private staging/quarantine state
and is never treated as published. No material retained artifact is deleted without
explicit user approval. A completed published candidate is immutable; replacement uses
a new digest-addressed directory rather than overwriting it.

## 8. Non-goals

- no production model/config/plist/launchd change;
- no Voice worker restart or supervised camera playback;
- no new Xiaomi connection, go2rtc consumer, PTZ or Camera Reply work;
- no Baby Care write, identity, medication action or free-form assistant;
- no training/fine-tuning and no persistence of household audio or transcripts;
- no push, merge, PR or protected-branch change under this slice.

## 9. Completion and handoff

The implementation is complete only when focused tests, the full Voice gate, Python
compile, Make dry-runs, diff/privacy checks and an actual isolated Intel A/B run all pass.
Documentation must state separately whether the public corpus, private-local diagnostic
and production deployment gates passed. If the candidate fails any mandatory gate, keep
the current production model and record the rejection without weakening thresholds.
