# Baby Guardian Risk ntfy Design

## Scope

This slice delivers text-only ntfy notifications for persisted Baby Guardian
risk events. It builds on the existing visual risk event and safe evidence
stores. It does not add Dashboard queries, authenticated links, parent
acknowledgement, media upload, audio, performance work, or device control.

## Delivery model

Risk handling must not wait for network I/O. Each notifiable state change is
first inserted into a SQLite outbox in the same local `events.sqlite3`
database. A single background dispatcher claims pending rows and calls the
existing bounded ntfy HTTP adapter. The dispatcher starts after the visual
runtime is built and stops with the worker.

Both Android phones subscribe to the same private ntfy topic. One successful
publish therefore represents delivery to the shared household channel; phone
receipt remains part of the later physical acceptance script.

## Notification stages

- A newly created `alert_opened` event queues `risk_opened` once.
- A successfully persisted recovery queues `risk_recovered` once.
- An adult intervention queues `adult_intervention` for each currently linked
  open event once. An intervention with no linked open event is audit-only.
- Watch transitions and duplicate open callbacks never queue notifications.
- The current risk state machine has one severity (`high`), so this slice does
  not invent a severity-upgrade transition. The schema leaves upgrade work to
  a future deterministic state-machine version.

The stable idempotency key is derived from the event ID, stage, and optional
intervention ID. A unique SQLite constraint prevents duplicate sends across
callbacks and restarts.

## Outbox lifecycle

Rows use `pending`, `delivered`, or `rejected` state. Temporary ntfy
unavailability leaves a row pending with a bounded attempt count and a future
retry time. A permanent payload or 4xx rejection terminates as `rejected`.
Successful delivery terminates as `delivered`. Delivered and rejected rows are
immutable.

Within one event, a later pending stage cannot overtake an earlier pending
stage, even while the earlier stage waits for retry. Other events remain
independently dispatchable.

The dispatcher processes one row at a time, uses the existing notifier's
three-attempt bounded HTTP policy, and applies local retry delays of 5, 30, and
300 seconds after successive unavailable dispatches. After three dispatcher
runs, an unavailable row becomes `rejected` with the fixed code
`retry_exhausted`. This bounds traffic and storage churn.

## Payload allowlist

The JSON payload contains only:

- private topic;
- fixed Chinese title;
- event ID;
- allowlisted Chinese risk label;
- allowlisted notification stage;
- severity `high` or recovered state;
- event timestamp;
- evidence state from `collecting`, `ready`, `failed`, `interrupted`, or
  `unavailable`.

It contains no image, clip, local or relative path, IP address, camera URI,
model output, exception text, token, or credential-bearing URL. No `click`
field is sent until an authenticated risk event endpoint exists.

## Failure isolation and logs

Outbox insertion, dispatch, and log failures cannot terminate the visual
worker or roll back an already persisted risk event. Logs are one-line JSON
and use fixed codes, notification ID, event ID, stage, state, attempt count,
and safe result code only. They never include payload bodies, URLs, topics,
tokens, paths, response bodies, or exception text.

## Configuration

Risk delivery reuses `notifications.ntfy_topic`,
`notifications.ntfy_token_env`, and `NTFY_BASE_URL`. Invalid or missing runtime
notification configuration disables the dispatcher and emits one fixed
startup code; event and evidence persistence continue.

## Acceptance

- Opening, recovery, and linked adult intervention queue exactly once.
- Duplicate callbacks and worker restarts do not redeliver terminal rows.
- Temporary errors retry within the documented bounds; permanent rejection
  does not retry.
- The visual worker never performs ntfy HTTP work on its analysis callback.
- Payload and logs pass tests that inject private addresses, paths, tokens,
  response bodies, and exception text.
- Existing source-health ntfy behavior remains unchanged.
