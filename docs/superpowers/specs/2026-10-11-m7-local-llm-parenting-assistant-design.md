# M7 Local LLM Parenting Assistant Design

## Goal

Connect natural-language Voice Care on the i9 to the existing M6/Baby Care v2
feeding workflow through the restricted M2 Ollama bridge, without allowing model
output to write data or bypass identity, lease, confirmation, version, or
idempotency checks.

## Scope and non-goals

M7 initially supports feeding only: mixed bottle feeding, direct breastfeeding
duration, correction, resume, confirmation, cancellation, and authoritative
queries. Camera Reply remains disabled. There is no PTZ, household media access,
production database access, new Ollama service, new database, or new long-lived
care state machine. Diaper, medication, and other care domains remain outside
the first tool registry.

## Architecture

The existing ASR and wake-word path remains the input boundary. After wake-word
handling, ordinary natural-language utterances go to a bounded language
orchestrator. Stop/cancel and other explicitly registered low-latency commands
remain deterministic. The orchestrator calls the existing Ollama `/api/chat`
origin through the fixed i9 loopback gateway (`127.0.0.1:11435`) and accepts
only a strict JSON candidate. It never receives video, continuous audio, or
private history.

The candidate is validated by a feeding-only tool registry and then translated
to the existing signed Voice Care v2 Gateway contract. Baby Care remains the
authority for caregiver lease, device signature, session version, idempotency,
transaction, confirmation, correction, audit, and saved state. The LLM may
request clarification but cannot assert identity, permission, or persistence.

The existing M6 coordinator owns the long-lived care session. Its short language
context window may expire, but an active server-side feeding session remains
recoverable by query/resume. TTS and AudioSink receive bounded response codes or
safe templates after authoritative gateway results; a playback failure cannot
roll back or duplicate a committed care record.

## LLM contract

The language client uses a fixed model selected by configuration, bounded request
and response sizes, a bounded timeout, `temperature=0`, `stream=false`, and a
strict schema. Unknown fields, duplicate JSON keys, invalid numbers, unsupported
tools, guessed identity, direct database verbs, and prose-only responses fail
closed. Model failure returns a deterministic `llm_unavailable` result and the
existing M6 rule parser may be used as a fallback.

Each candidate contains only:

* `intent`: one registered feeding intent;
* `tool_calls`: a bounded ordered list of typed calls;
* `clarification`: a bounded user-facing question or null;
* `confidence`: a bounded number used for routing, never authorization;
* `context_key`: an opaque conversation key, never a database identifier.

The first registry contains `get_active_feeding`, `start_feeding`,
`add_feeding_component`, `correct_feeding_component`, `end_feeding`,
`request_feeding_confirmation`, `confirm_feeding`, `cancel_feeding`,
`get_recent_feedings`, and `get_feeding_summary`. Writes that change or save a
care session require explicit confirmation according to the existing M6/v2
contract. Direct breastfeeding stores duration only; it is never converted to
millilitres. Bottle breast milk and formula remain separate components.

## Required interactions

The software path must represent:

1. mixed feeding: expressed breast milk 60 ml plus formula 30 ml, then explicit
   confirmation and one authoritative saved session;
2. correction: “奶粉是二十” targets the unique uncommitted formula component or
   asks for clarification when the target is not unique;
3. resume after a language-context gap without deleting the Baby Care session;
4. authoritative query for today/yesterday totals, with direct breastfeeding
   duration kept separate;
5. ambiguous quantity or “补一点” producing clarification rather than a write;
6. Ollama timeout, invalid JSON, TTS failure, AudioSink failure, database
   failure, retry, and process restart without duplicate accounting or a false
   “saved” response.

## Evaluation and safety gates

At least 200 synthetic Chinese utterances cover standard speech, colloquial
speech, ASR noise, Chinese numerals, mixed feeding, multi-intent, correction,
negation, queries, resume, ambiguity, refusal, malicious tool candidates, and
model/runtime faults. Results compare rule-only, pure LLM, and LLM plus
deterministic validation. Report intent, parameter, tool legality, quantity and
confirmation errors separately, plus P50/P95 latency and resource observations.

Real M2 model results are required for an M7 software candidate. If the bridge or
model is unavailable, the implementation and synthetic tests may proceed but the
status is `LIVE_MODEL_PENDING`; Mock results must never be reported as live-model
evidence. No software result is a family-device or production readiness claim.

## Compatibility

Voice Care v1 remains accepted unchanged. M7 emits the existing versioned v2
intent envelope for multi-component feeding and refuses to downgrade a v2
proposal to a lossy v1 single-component record. Camera Reply stays false and
Guardian continues independently if the model, bridge, TTS, or Baby Care API is
unavailable.
