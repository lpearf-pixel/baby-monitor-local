# M7 live Ollama evaluation (2026-10-13)

## Scope

This record covers one real Ollama evaluation from i9 through the existing
loopback gateway. It uses synthetic Chinese care text only. No household audio,
video, database, Camera Reply, PTZ, or SSH tunnel implementation was changed.

## Environment

- Ollama endpoint: `http://127.0.0.1:11435`
- Ollama version: `0.32.11`
- Selected installed model: `qwen2.5-coder:7b-instruct`
- Quantization: `Q4_K_M`; family: `qwen2`
- Schema contract: existing `LanguageCandidate` plus M7 closed tool registry
- API model listing and one real `/api/chat` call: PASS
- Missing-model error path: HTTP 404 mapped to closed failure
- Loaded-model resource snapshot: unavailable after completion (`/api/ps` empty)

## 224-sample comparison

The evaluation made one request per synthetic sample and retained aggregate
metrics only. Failures were not retried or counted as successes.

| Mode | Intent accuracy | Parameter accuracy | Tool legality |
| --- | ---: | ---: | ---: |
| A: existing deterministic rules | 32.14% (72/224) | 64.29% (144/224) | n/a |
| B: real Ollama candidate | 42.86% (96/224) | 78.57% (176/224) | n/a |
| C: real Ollama + registry validation | 42.86% (96/224) | 78.57% (176/224) | 78.57% (176/224) |

Real-model request results: 176 responded with schema-valid candidates and 48
were closed as unavailable/invalid. `wrong_amount_count=0` among the accepted
amount-bearing candidates; the 48 failures remain failures and were not hidden.
Latency: P50 1224.9 ms, P95 1576.5 ms, max 2430.2 ms. No raw text or model
response was persisted.

## Interpretation

The real model is reachable and can produce a valid mixed start/update candidate
after the prompt contract was tightened. It is **not** a release-quality
semantic evaluator: the 78.57% response/tool-legal rate and 42.86% intent rate
are below a software-release threshold. Registry validation remains mandatory;
the model never writes Baby Care directly.

## Baby Care isolated integration

Node 24.19.0, pnpm 10.17.1, and the isolated PostgreSQL 16 test container were
used. The M7-relevant Voice Care v2 integration set passed 27/27 tests, including
the 60 ml expressed-breast-milk plus 30 ml formula flow, confirmation gating,
single authoritative event, idempotent repeated confirmation, correction, and
direct breastfeeding duration without an inferred millilitre amount.

The full API database-enabled run executed 233/234 tests: 233 passed and one
pre-existing `family-authorization` assertion failed because the reused test
database returned a stale synthetic birth date. This failure is not claimed as
fixed and blocks `SOFTWARE_RELEASE_CANDIDATE`.

## Status

- `OLLAMA_API_CONNECTED`: PASS
- `LIVE_MODEL_EVALUATED`: YES, with the limitations above
- `POSTGRES_INTEGRATION_PASS`: M7 Voice Care v2 slice PASS
- `SOFTWARE_RELEASE_CANDIDATE`: NO (full API gate has one failure)
- `HARDWARE_ACCEPTANCE_PENDING`: YES

Camera Reply remains disabled. SSH tunnel scripts and family services were not
modified or restarted.
