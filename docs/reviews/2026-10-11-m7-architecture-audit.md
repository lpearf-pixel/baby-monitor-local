# M7 architecture audit and implementation checkpoint

## Baseline

- baby-monitor-local M6 baseline: `03fae3830733dfb1bccb0524d9385f9ead41ff40`
- baby-care M6 baseline: `4f14ecc254740e9405f2e9b40e7b3217c4a5cb49`
- Voice Care v2 schema SHA-256: `a0fe59a4c30c7f053a13677ab472e343c95a8794def7ee8ac5303a46d4d47954`
- M7 branch: `codex/m7-local-llm-parenting-assistant`

## Reuse findings

The i9 reaches M2 through the existing fixed loopback SSH-forwarded Ollama
origin at `127.0.0.1:11435`; the repository already uses `/api/chat` for Visual
Review. `services/vision/ollama_client.py` supplies bounded no-proxy HTTP,
timeout, response-size and strict JSON patterns. M7 copies those constraints
into an independent language module and does not import visual business logic.

The ASR/wake entry is `VoiceCommandProcessor.process`. M7 has an optional
processor hook after wake and speaker verification; stop/cancel remain
deterministic fast paths and a missing M7 result can fall back to the existing
parser.

`M6FeedingCoordinator` already keeps the server-side session separate from its
eight-second language context. `M7SessionBridge` exposes resume/query/cancel
without adding a database or a second long-lived state machine. Baby Care v2
already owns signatures, caregiver Lease, versions, idempotency, transaction
commit, confirmation, correction and audit; M7 constructs v2 candidates and
does not write its database.

## Implemented software slices

- `f4067db`: bounded strict Ollama language client and fail-closed candidate parser.
- `674d633`: feeding-only whitelist validator for ten tools and ambiguity/identity gates.
- `31f9b18`: M6 session bridge preserving recovery after language-context expiry.
- `22fc464`: optional model-first Voice Worker hook with deterministic fallback.
- `9833b82`: v2 multi-component intent construction and non-downgrading response adapter.
- `1472c4c`: deterministic 224-sample synthetic evaluation generator.
- `382e7d6`: Voice Worker response adapter and synthetic authoritative mixed-feeding closure.
- `60f48be`: M6 lifecycle adapter to the signed Baby Care v2 device route.
- `7e73f8e`: explicit approved Voice Care v2 schema digest pin.

Focused M7 and existing M6/Worker paths pass in targeted suites. The v2 adapter is
transport-injected and has not been enabled in the installed worker; the authoritative
read/query route still needs a Baby Care read adapter. Full cross-repository PG16
integration and live A/B/C evaluation remain open.

## Live model status

One bounded health probe to `http://127.0.0.1:11435/api/tags` returned connection
failure. No retries, model downloads, or service restarts were performed. Status is
`LIVE_MODEL_PENDING`; no Mock result is represented as live-model evidence.

## Safety status

Camera Reply=false, PTZ disabled, Guardian and AudioSink behavior unchanged, no
household media or production database accessed. Untracked `Interactive` and
`test.sh` remain untouched.
