# M6 Voice Feeding Session Design

Status: implementation slice approved for offline software validation

## Scope

M6 adds a deterministic, local conversation layer for feeding only. It accepts
post-wake synthetic text, keeps an eight-second inactivity window in memory, and
delegates every care transition through a typed gateway. The default audio output
remains disabled in production and tests use a mock sink.

The first validation flow is:

```text
start feeding -> expressed breast milk 60 ml -> formula 30 ml
-> end -> confirm save -> query records
```

Direct breastfeeding is represented as a duration component and is never converted
to millilitres.

## Contract boundary

The existing Baby Care Voice Care v1 envelope and its
`feeding_start/update/end/confirm/cancel` semantics remain unchanged. M5 v1 stores a
single proposal, so it cannot safely represent multiple feeding components. M6 uses a
separate in-memory gateway interface with an explicit version-2 adapter boundary for
production multi-component delivery. Until Baby Care publishes and pins that v2
contract, the M6 implementation is software-only and must not send a mixed proposal to
the v1 endpoint.

The gateway remains responsible for identity, lease, request-id deduplication,
expected-version checks, confirmation, transaction commit and database errors. The
conversation layer never writes Baby Care storage directly.

## Safety and lifecycle

- Context is bounded to eight seconds of inactivity and a bounded number of turns.
- Expired context is rejected and cleared; it is not silently resumed.
- Duplicate request IDs return the prior result without another gateway call.
- Gateway failure returns a closed temporary-unavailable result and does not mutate the
  committed care state.
- Audio acknowledgement is best effort through `VoiceOutput`; sink failure cannot
  affect Guardian, go2rtc or Baby Care state.
- Camera Reply stays disabled. NetworkAudioSink is an interface-only follow-up.

## Validation

Tests use synthetic text, a mock gateway and a mock audio sink. They cover the mixed
feeding flow, correction, expiry, duplicate commands, gateway/database failure,
audio-output failure, direct breastfeeding separation and malformed/ambiguous input.
No household audio, camera, transcript, model output or production event is used.
