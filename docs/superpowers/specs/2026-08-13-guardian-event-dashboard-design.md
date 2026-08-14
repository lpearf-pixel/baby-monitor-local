# Guardian Event Dashboard Design

Date: 2026-08-13

## Scope

Add a read-only, authenticated Guardian event list to the existing Alpha Dashboard.
This slice does not add screenshot, clip or other media access; parent acknowledgement,
false-positive feedback and Baby Care integration remain out of scope.

## Query boundary

`GuardianEventQueryService` is a standalone read-only service injected by the
Dashboard runtime. It resolves the centralized `app.data_dir`, opens the existing
`events.sqlite3` in SQLite read-only and query-only modes, and joins event lifecycle
rows to evidence state. Routes receive only validated models and never know the
database path.

The query first selects the newest 20 events by update time and stable event ID. It
then places unresolved events first only within that fixed result set. Missing evidence
is represented as `unavailable`. Database absence, schema mismatch or invalid rows fail
closed as one stable unavailable response.

The public projection is limited to event ID, risk kind, event state, severity,
lifecycle timestamps, adult-intervention count and evidence state. It excludes model
confidence, rule version, evidence keys, filesystem paths and media.

## Dashboard behavior

The authenticated page loads immediately and refreshes every 15 seconds. It displays
collecting, ready, failed, interrupted and unavailable evidence states. Unresolved
events have explicit text and visual emphasis. If a later refresh fails, the existing
list remains visible and the page shows `数据可能已过期`; internal errors are not shown.

## Verification

Tests cover read-only failure, fixed newest-20 selection before unresolved pinning,
closed projection, all evidence states, authentication-before-service access, stable
redacted failure, centralized runtime wiring, protected assets, immediate loading,
15-second refresh and stale-data retention.
