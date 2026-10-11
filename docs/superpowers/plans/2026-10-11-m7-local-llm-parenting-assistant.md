# M7 Local LLM Parenting Assistant Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Deliver a feeding-only local LLM orchestration path that uses M2 Ollama to create validated candidates and the existing M6/Baby Care v2 Gateway to perform authoritative care operations.

**Architecture:** Reuse the existing Voice ASR/wake path, extract a bounded Ollama transport client from the visual transport constraints without importing visual business logic, and route strict candidates through a feeding-only registry into the existing signed v2 gateway. Keep the M6 long-lived session independent from the short language context and retain deterministic fallback.

**Tech Stack:** Python 3.11+, Pydantic contracts, existing urllib transport, existing Voice Care client/outbox, Baby Care Node 24/pnpm v2 gateway, pytest, synthetic JSON fixtures.

**Spec:** `docs/superpowers/specs/2026-10-11-m7-local-llm-parenting-assistant-design.md`

## Global Constraints

- Camera Reply remains disabled; no PTZ, household audio/video, production database, or home deployment.
- Use the fixed `127.0.0.1:11435` Ollama bridge; do not create another service.
- LLM output is a candidate only; identity, lease, signature, version, idempotency, confirmation, transaction and audit remain authoritative outside the model.
- Direct breastfeeding records duration only; bottle expressed milk and formula remain distinct actual consumed millilitres.
- v1 remains compatible; v2 multi-component proposals are never lossy-downgraded to v1.
- Preserve untracked `Interactive`, `test.sh`, and baby-care `.pnpm-store/`.

## Review Focus

- Invalid/hostile model JSON, duplicate keys, unknown tools, guessed identity: contract tests must reject without a Gateway call (Task 2).
- “帮我保存” and ambiguous quantities: orchestration tests must ask for explicit confirmation/clarification (Task 4).
- Context expiry with an active server session: recovery tests must query/resume rather than delete the session (Task 3).
- Database/TTS/AudioSink failure after or before commit: integration tests must never duplicate or say saved before authoritative success (Task 5).
- Ollama timeout/unavailable model and v1/v2 mismatch: fallback tests must preserve deterministic M6 and refuse lossy downgrade (Task 1/6).

---

### Task 1: M7 transport and strict language candidate contract

**Files:**
- Create: `services/voice/m7_llm.py`
- Test: `tests/voice/test_m7_llm.py`
- Modify: `packages/contracts/voice.py` only if an existing shared contract export is required

**Interfaces:**
- Consumes: fixed Ollama origin and model configuration; text plus bounded structured context.
- Produces: `OllamaLanguageClient.complete(text, context) -> LanguageCandidate | LlmUnavailable`.

- [ ] Write RED tests for valid candidate, duplicate-key rejection, unknown field/tool rejection, response-size limit and timeout mapping.
- [ ] Run the focused tests and record the expected RED failures.
- [ ] Implement independent bounded HTTP transport and strict Pydantic candidate models; do not import visual reviewer classes.
- [ ] Run focused tests to GREEN and add a no-image/no-audio payload assertion.
- [ ] Commit `feat: add bounded M7 language client`.

### Task 2: Feeding-only tool registry and deterministic validation

**Files:**
- Create: `services/voice/m7_tools.py`
- Test: `tests/voice/test_m7_tools.py`

**Interfaces:**
- Consumes: `LanguageCandidate`, existing `M6FeedingCoordinator` result types, profile/lease context.
- Produces: `ValidatedToolCall` with explicit confirmation requirement or `Clarification`.

- [ ] Write RED tests for mixed components, direct breastfeeding duration, correction targeting, ambiguity, negation, malicious tool names and identity/permission spoofing.
- [ ] Run focused RED tests.
- [ ] Implement whitelist schemas for the ten feeding tools and deterministic range/type/value-origin checks.
- [ ] Run focused GREEN tests and verify no Gateway invocation occurs for rejected candidates.
- [ ] Commit `feat: add M7 feeding tool registry`.

### Task 3: Durable M6 session bridge and context recovery

**Files:**
- Modify: `services/voice/m6_feeding.py`
- Create: `services/voice/m7_session.py`
- Test: `tests/voice/test_m7_session_recovery.py`

**Interfaces:**
- Consumes: validated tool calls and the existing `M6SessionGateway` boundary.
- Produces: `M7SessionResult` with phase, authoritative response code, clarification and safe reply data.

- [ ] Write RED tests proving an 8-second language context expiry does not delete a pending gateway session; query/resume, cancel, duplicate request and retry remain idempotent.
- [ ] Run focused RED tests.
- [ ] Implement session state as a thin coordinator over the existing gateway, never a second database/state machine.
- [ ] Run focused GREEN tests, including process-restart reload through gateway query.
- [ ] Commit `feat: preserve M7 feeding sessions across context expiry`.

### Task 4: Voice Worker model-first orchestration with rule fallback

**Files:**
- Modify: `services/voice/worker.py`
- Create: `services/voice/m7_orchestrator.py`
- Test: `tests/voice/test_m7_orchestrator.py`

**Interfaces:**
- Consumes: ASR text, wake handling, `OllamaLanguageClient`, tool registry, M7 session bridge, existing synthesizer.
- Produces: bounded `VoiceSemanticResponse`/reply template and stable diagnostics; no raw transcript persistence.

- [ ] Write RED tests for ordinary natural language reaching LLM first, stop/cancel fast paths, LLM timeout fallback, clarification, explicit save confirmation and no false saved reply.
- [ ] Run focused RED tests.
- [ ] Implement the feature-flagged M7 path while preserving existing M6 deterministic mode and Camera Reply=false.
- [ ] Run focused GREEN tests plus existing Voice regression tests.
- [ ] Commit `feat: connect M7 orchestration to Voice Worker`.

### Task 5: Cross-repository v2 Gateway adapter and synthetic integration

**Files:**
- baby-monitor-local: `services/voice/m7_gateway.py`, `tests/integration/test_m7_baby_care_gateway.py`
- baby-care: focused adapter/contract test files under `apps/api/test` or existing voice-care test location
- Create: a versioned synthetic integration fixture, never a production credential or family identity

**Interfaces:**
- Consumes: existing device signature, lease, v2 schemas and HTTP response contract.
- Produces: one authoritative mixed-feeding saved session or explicit non-saved outcome.

- [ ] Write RED integration tests for 60 ml expressed milk + 30 ml formula, direct breastfeeding duration, confirmation, duplicate retry, DB failure, network interruption, TTS failure and concurrent confirmation.
- [ ] Run isolated synthetic RED tests against disposable PostgreSQL 16 where available.
- [ ] Implement only the adapter needed to construct existing v2 intents and parse existing semantic results.
- [ ] Run GREEN integration tests and verify one care session, two components, actual total 90 ml, no direct-breastfeeding ml conversion, and no pre-commit saved reply.
- [ ] Commit adapter changes independently in each repository.

### Task 6: 200-sample evaluation, live-model probe and release gate

**Files:**
- Create: `tests/fixtures/m7_zh_feeding_eval.v1.json` (200+ synthetic utterances)
- Create: `tools/m7_eval.py`
- Create: `docs/reviews/2026-10-11-m7-evaluation.md`
- Modify: `docs/STATUS.md`, `docs/NEXT.md`, and baby-care handoff docs

**Interfaces:**
- Consumes: rule parser, pure LLM adapter, hybrid orchestrator and optional live Ollama endpoint.
- Produces: bounded aggregate metrics without transcripts in logs or reports.

- [ ] Write RED evaluator tests for sample count, categories, deterministic IDs, A/B/C output schema and no private-text persistence.
- [ ] Implement fixture generation/evaluation and bounded latency/resource sampling.
- [ ] Run the 200+ synthetic evaluation and report intent, parameters, tool legality, quantity/confirmation errors, P50/P95 latency and fault outcomes.
- [ ] Probe the fixed M2 Ollama bridge and record exact model/version; if unavailable mark `LIVE_MODEL_PENDING`.
- [ ] Run affected full software gates and independent review; update status only with fresh evidence.
- [ ] Commit docs/evaluation and ordinary-push approved feature branches; do not deploy or merge protected branches.
