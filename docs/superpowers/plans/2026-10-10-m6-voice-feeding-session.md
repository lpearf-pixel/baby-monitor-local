# M6 Voice Feeding Session Plan

## Task 1 — offline session contract and parser

Status: complete (offline software slice)

Implement a bounded post-wake parser and in-memory session coordinator. Reuse the
existing v1 intent vocabulary at the gateway boundary, but keep multi-component
aggregation behind a v2-capable interface.

Prerequisites: AudioSink P0 review and existing Voice Care v1 contract.

Codex work: deterministic parser, eight-second expiry, deduplication, closed result
codes, tests with synthetic text.

Human work: none.

Acceptance: mixed feeding, correction, duplicate, expiry and malformed input are
deterministic; direct breastfeeding never becomes ml.

Next: Task 4 v2 production adapter decision; Task 2/3 evidence is included in the
same offline slice because the typed gateway and synthetic loop are required to prove
the parser contract safely.

## Task 2 — gateway/output integration

Status: complete (synthetic only)

Add a typed gateway protocol and Mock implementation. Verify identity/version/confirm
boundaries and that audio sink failure is isolated.

## Task 3 — full synthetic care loop

Status: complete (synthetic only)

Run start → two components → end → confirm → query with failure and retry branches.

## Task 4 — production adapter decision

Status: blocked on Baby Care v2 contract

Compare the pinned M5 v1 branch with a future multi-component contract. Do not send
mixed components to v1 and do not deploy until the Baby Care v2 schema/source digest is
available.

## Task 5 — NetworkAudioSink interface

Status: pending

Document only a replaceable sink interface and bounded failure semantics. No hardware
purchase, firmware or household deployment.
