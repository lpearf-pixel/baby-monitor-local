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

The evaluation now contains 224 unique synthetic texts: 56 development samples
and 168 independent test samples. It made one request per sample and retained
aggregate metrics only. Failures were not retried or counted as successes.

| Mode | Intent accuracy | Parameter accuracy | Tool legality |
| --- | ---: | ---: | ---: |
| A: existing deterministic rules | 22.32% (50/224) | 0% (0/80 applicable) | n/a |
| B: real Ollama candidate | 57.14% (128/224) | 77.5% (62/80 applicable) | n/a |
| C: real Ollama + registry validation | 57.14% (128/224) | 77.5% (62/80 applicable) | 67.86% (152/224) |

Real-model request results: 154 responded with schema-valid candidates and 70
were closed as `schema_mismatch` (no timeout in this full run). There were 18
wrong or missing amounts among the 80 applicable amount samples. Latency: P50
1205.5 ms, P95 1630.5 ms, max 1910.1 ms. The independent test split was 93/168
intent-correct, 45/60 applicable-parameter-correct, and 111/168 tool-legal.
No raw text or model response was persisted.

Development-only model screening used the same prompt, schema and 56 samples:

| Model | Intent | Applicable parameters | Tool legal | Failures | P95 ms |
| --- | ---: | ---: | ---: | ---: | ---: |
| qwen2.5-coder:7b-instruct | 62.5% | 85% | 73.21% | 14 | 1580.4 |
| qwen3-vl:8b-instruct-q4_K_M | 37.5% | 50% | 51.79% | 27 | 1824.8 |
| llama3.2:3b | 30.36% | 45% | 39.29% | 3 | 947.1 |

The Qwen2.5-Coder model remains the baseline candidate; no model was promoted.

## Interpretation

The real model is reachable and can produce a valid mixed start/update candidate
after the prompt contract was tightened. It is **not** a release-quality
semantic evaluator: the 67.86% tool-legal rate and 57.14% intent rate are below
the 95%/99% development targets. Registry validation remains mandatory;
the model never writes Baby Care directly.

## Baby Care isolated integration

Node 24.19.0, pnpm 10.17.1, and the isolated PostgreSQL 16 test container were
used. The M7-relevant Voice Care v2 integration set passed 27/27 tests, including
the 60 ml expressed-breast-milk plus 30 ml formula flow, confirmation gating,
single authoritative event, idempotent repeated confirmation, correction, and
direct breastfeeding duration without an inferred millilitre amount.

The full API database-enabled run on a new PostgreSQL 16 container executed
234/234 tests successfully. The prior `family-authorization` failure was a real
date-only serialization bug: PostgreSQL `date` values were converted through
`toISOString()` and shifted one day in Asia/Shanghai. Baby Care commit `cb9a86f`
fixes the conversion using local date components; the focused regression passed
2/2 and the full API gate passed 234/234.

## Status

- `OLLAMA_API_CONNECTED`: PASS
- `LIVE_MODEL_EVALUATED`: YES, with the limitations above
- `POSTGRES_INTEGRATION_PASS`: M7 Voice Care v2 slice and full API gate PASS
- `SOFTWARE_RELEASE_CANDIDATE`: NO (semantic targets are not met; CI still pending)
- `HARDWARE_ACCEPTANCE_PENDING`: YES

Camera Reply remains disabled. SSH tunnel scripts and family services were not
modified or restarted.

## 2026-10-14 M7.1 Stage 1/2 diagnostic update

The evaluator was audited before changing prompts. The 224-sample aggregate was
rerun once after adding bounded failure categories and amount-error categories:

| Failure category | Count | Applicable interpretation |
| --- | ---: | --- |
| JSON syntax error | 0 | No malformed JSON observed in the full run |
| Envelope response error | 0 | No missing model/done/message envelope observed |
| Schema mismatch | 70 | Closed responses failed the strict candidate contract |
| Unknown tool | 0 | No full-run response reached this branch |
| Amount missing/invalid candidate | 18 | Every amount error had no usable candidate |
| Wrong numeric amount | 0 | No wrong numeric amount was accepted |

The amount denominator remains 80 explicitly amount-bearing samples. Full results
remain 128/224 intent-correct, 62/80 applicable-parameter-correct and 152/224
tool-legal. Latency was P50 1363.7 ms, P95 2001.8 ms and max 2111.9 ms. No input
text or model response was persisted.

The client now exposes four bounded modes: A raw JSON, B current prompt plus native
schema, C optimized prompt plus native schema, and D optimized prompt plus one
JSON-fence-only repair. A 4-sample live smoke (not a development score) produced
A=4 schema mismatches, B=1 unknown-tool failure, C=0 failures and D=0 failures.
The prior complete 56-sample B/C baseline remains the only full development
comparison; a full A-D run was not claimed after repeated live calls became slow.
Stage 1 therefore points to strict schema rejection, not safe numeric repair, and
the release targets remain unmet.

## Development A/B/C/D comparison

All four modes used the same 56 development samples, model, temperature, timeout
and tool validator. No test-split sample was used for selection.

| Mode | Intent | Applicable amount | Tool-legal | Failures | Failure reasons | P95 ms |
| --- | ---: | ---: | ---: | ---: | --- | ---: |
| A raw JSON + current prompt | 0/56 | 0/20 | 0/56 | 56 | schema_mismatch | 1742.0 |
| B native Schema + current prompt | 2/56 | 0/20 | 4/56 | 48 | schema_mismatch 34, unknown_tool 14 | 1405.0 |
| C native Schema + optimized prompt | 35/56 | 17/20 | 41/56 | 14 | schema_mismatch 14 | 1580.4* |
| D C + one JSON-fence repair | 35/56 | 17/20 | 41/56 | 14 | schema_mismatch 14 | 1864.7 |

*C is the previously completed full development run with identical settings; its
P95 is retained as prior evidence, not mixed with a new prompt or corpus. D's
repair changed no business fields and did not improve the development scores.
The optimized prompt plus native Schema is therefore retained as the baseline
candidate for the next diagnostic slice, not as a release decision.

## Independent closed set

The 24-item closed synthetic set was authored after development comparison,
stored as code-only metadata, and verified disjoint from the 224-item corpus.
With the frozen C configuration it produced 13/24 intent-correct, 5/7
applicable-amount-correct, 19/24 tool-legal, 4 schema mismatches and 2
missing/invalid amount candidates. P50/P95/max latency was 1238.4/1558.1/2289.4
ms. This is an independent software measurement, not household acceptance.
