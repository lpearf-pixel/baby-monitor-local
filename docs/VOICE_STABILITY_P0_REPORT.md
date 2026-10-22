# Baby Care Voice Stability P0 Report

Date: 2026-10-22

## Gate summary

```text
SOFTWARE_TEST_PASS=PARTIAL
LOCAL_AUDIO_HARDWARE_PASS=NOT_RUN
WAKE_WORD_PASS=NOT_RUN
CAMERA_REPLY_PASS=FAIL_CLOSED_NOT_ACCEPTED
FAMILY_DEPLOYMENT_READY=NO
```

`SOFTWARE_TEST_PASS` is partial because the repeatable software and fault-boundary
checks pass, but the required 1000-repeat offline replay through the real Paraformer
with an authorized fixed audio manifest was not run in this session. No synthetic
test is promoted to real-ASR or hardware evidence.

## Delivered software slice

- Added `VoiceStabilitySession` and `VoiceStabilityController` with explicit
  `IDLE`, `LISTENING`, `RECOGNIZING`, `PROCESSING`, `SPEAKING`, `FAILED`,
  `CANCELLED` and `TIMED_OUT` states.
- Added Push-to-Talk opt-in and exact wake handling for `嘿，小小` / internal
  `小小`, with fixed local-only replies: `我在`, `能听见`, `语音回复正常`,
  `已停止`, and one bounded ASR failure reply.
- Serialized TTS output with one active playback flight, explicit completion,
  failure, cancellation, busy and ambiguous settlement, and cleanup before the
  next turn. Ambiguous playback is never auto-replayed or counted as delivered.
- Added opt-in encrypted Voice Test Corpus storage. Recording is disabled by
  default, revoked consent blocks new recordings, files are bounded and private,
  and retention is seven days. The corpus stores no continuous household audio.
- Added a manifest-bound regression runner. It rejects private/path-traversal or
  symlinked WAV input and accepts only bounded 16 kHz mono 16-bit PCM. With an
  explicit manifest it can invoke the pinned local Paraformer; without one it
  fails closed with `audio_manifest_required`.
- Camera Reply remains disabled. No Baby Care formal care-record write or schema
  change was made.

## Verification evidence

Fresh commands and results:

- `.venv-alpha/bin/python -m pytest -q --tb=short --disable-warnings tests/voice/test_stability.py tests/voice/test_tts.py tests/voice/test_test_corpus.py tests/tools/test_voice_stability_runner.py tests/deploy/test_voice_worker_deploy.py`
  — **55 passed**.
- `.venv-alpha/bin/python -m pytest -q --disable-warnings` — **2647 passed, 1
  expected visual-corpus skip** in 264.41 seconds.
- `.venv-alpha/bin/python -m compileall -q` on all changed Python modules — **pass**.
- `make -n alpha-voice-stability-test MANIFEST=...` — **pass**; command is
  bounded and requires an explicit manifest.
- `make alpha-voice-status` — runtime reported
  `degraded / listen_only / voice_audio_unavailable`; this is not microphone
  acceptance evidence.
- `python -m tools.voice_stability_runner --json` without a manifest — correctly
  failed closed with `audio_manifest_required`.
- `camera_reply_enabled: false` remains in runtime settings.

The unit runner repeated one synthetic PTT case 1000 times and reported P50/P95/P99
latencies with zero residuals. This proves state-machine repeatability only; its
ASR is synthetic and its TTS output is a no-device semantic boundary. It does not
prove adult speech recall, speaker audibility, or real Paraformer performance.

## Hardware and deployment gates

No real microphone recording, wake-word acceptance, 100-adult-utterance matrix,
60-minute false-wake observation, sustained CPU/memory check, Xiaomi speaker
activation, Camera Reply playback, or family deployment was performed. These gates
remain explicitly unverified. Camera Reply's historical V3E failure remains closed
and disabled; a ready/status marker is not acceptance.

## Cross-repository boundary

The Baby Care worktree remains unchanged at its existing M6 head. No formal care
record API was called, extended, or claimed by this slice. The monitor remains the
owner of local capture, ASR, deterministic test intent, TTS and playback lifecycle.

## Git and delivery state

- Monitor repository: branch `codex/m7-local-llm-parenting-assistant`, local HEAD
  `f8dcc54` at inspection time; changes are uncommitted and not pushed.
- Baby Care worktree: branch `codex/voice-stability-p0`, HEAD `33a31ac`; no code
  changes and no commit or push.
- Preserved unrelated untracked files: `Interactive`, `test.sh`, and Baby Care's
  `.pnpm-store/`.

## Next authorized slice

Obtain explicit authorization for a fixed, generated/public, non-household WAV
manifest and run the real Paraformer 1000-repeat offline gate. Separately request
the logged-in local operator's bounded hardware session for PTT, wake-word,
latency, resource and false-wake measurements. Do not enable Camera Reply or write
Baby Care records as part of that gate.
