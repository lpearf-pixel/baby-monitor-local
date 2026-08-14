# Guardian Evidence Retention Design

**Date:** 2026-08-13

**Status:** Approved for implementation by the user's long-task continuation

**Parent design:** `2026-08-11-baby-guardian-safe-evidence-design.md`

## 1. Goal and scope

Bound Guardian evidence storage to the existing configured age and quota limits while
preserving the event lifecycle, notification causality, privacy boundary and independent
worker failure behavior.

This slice implements automatic cleanup for privacy-processed Guardian screenshots and
animated WebP clips. It does not delete risk events, interventions, notifications or
diagnostic history. It does not add media access, parent identities, Baby Care writes,
false-positive feedback, audio, PTZ or public networking.

## 2. Existing configuration

Use the centralized settings that already exist:

- `retention.event_retention_days`, default `30`;
- `retention.event_quota_gb`, default `30`.

The runtime converts the quota to bytes using binary GiB (`1024 ** 3`). No second
configuration surface or environment variable is introduced. Cleanup runs immediately
when the independent retention worker starts and then at most once every 24 hours.

## 3. Eligibility and ordering

An evidence record is deletable only when all of these are true:

1. its risk event is `recovered`;
2. its evidence state is terminal: `ready`, `failed`, or `interrupted`;
3. its recovery notification exists and is terminal (`delivered` or `rejected`);
4. the event has no `pending` Guardian notification;
5. the evidence state and effective retention timestamp still match the exact record
   selected for cleanup.

Open events and `collecting` evidence are always protected. Age expiration uses the
later of the event's `updated_at` and evidence `updated_at`, so a long event or delayed
evidence completion receives the full configured retention window.

Cleanup first removes every eligible record at or beyond the age cutoff. It then
removes the oldest remaining eligible records until total evidence-root usage is at or
below the quota. All current visual risks have the same `high` severity, so quota
ordering is oldest-first with `event_id` as the deterministic tie-breaker.

If protected or unmanaged files alone keep usage above quota, cleanup reports
`quota_unmet` and does not weaken the protection rules.

## 4. Persistence and filesystem behavior

`VisualRiskEventStore` exposes a closed retention projection and a guarded evidence-row
delete. The guarded delete starts `BEGIN IMMEDIATE`, repeats the exact-record and
eligibility checks, executes the bounded file callback while holding the SQLite writer
lock, and removes the evidence row before commit. This closes the recovery/outbox and
selection/deletion races: no writer can add a pending notification between the final
eligibility check and file removal. A recovered event with no terminal recovery
notification is never eligible, so the separate production recovery/outbox commits do
not create an unprotected window.

`GuardianEvidenceFiles` calculates usage without following symbolic links and deletes
only the fixed digest directory derived from the selected `event_id`. Root,
`visual-risk`, event-directory traversal and unlink/rmdir operations are anchored by
directory descriptors with `O_NOFOLLOW`; a symlink at any ancestor or entry fails
closed. Stored relative keys are never used as arbitrary filesystem paths. Known
snapshot and clip files are removed idempotently; an unexpected or unsafe filesystem
entry fails that record closed.

For each selected record the service deletes controlled files first, then removes the
evidence row. If the database delete fails after file deletion, the row remains and the
next run retries; the authenticated Dashboard may temporarily retain the terminal status
but still has no media route. If the database row is deleted, the event remains and the
existing left join returns `unavailable`, displayed as `无证据`.

## 5. Runtime and failure isolation

A dedicated daemon retention worker shares the configured evidence-file component and
uses separate short-lived SQLite connections. It runs independently of the visual worker
and notification dispatcher.

Filesystem, SQLite, logging, clock, scheduler or thread-start failures:

- never terminate or restart the visual worker;
- never delete an open, collecting or notification-pending record;
- never fabricate a successful cleanup;
- never expose paths, digests, evidence keys or exception text.

Shutdown uses the existing stop event and a bounded thread join. An interrupted cleanup
is safe to repeat because file and database deletion are idempotent and guarded.

## 6. Diagnostics

Retention diagnostics use the existing JSON-line `baby_guardian` component and only
aggregate fields:

- `guardian.evidence_retention_completed`;
- `guardian.evidence_retention_failed`.

Allowed result values are `within_quota`, `deleted`, `quota_unmet`, and
`retention_unavailable`. Allowed numeric fields are `deleted_count`,
`reclaimed_bytes`, `usage_bytes`, and `quota_bytes`. Logs contain no event IDs, file
names, paths, stored keys, digests, media, credentials, network values or exceptions.

## 7. Verification

Synthetic tests must prove:

- age cleanup uses the later terminal timestamp and preserves boundary-young evidence;
- quota cleanup is deterministic and oldest-first;
- open, collecting and pending-notification evidence is protected;
- a recovered event remains protected until its recovery notification exists and is
  terminal;
- successful cleanup removes controlled files and only the evidence row;
- the event remains queryable and the Dashboard projection becomes `unavailable`;
- file or database failure is retryable and isolated;
- unsafe filesystem entries fail closed;
- symlinked root or `visual-risk` ancestors cannot redirect deletion outside the
  configured evidence root;
- total usage includes managed and unmanaged regular files without following symlinks;
- the worker runs immediately, repeats after 24 hours and stops through a bounded event;
- production wiring uses centralized settings and does not make visual startup depend on
  cleanup success;
- diagnostics obey the aggregate allowlist.

Only generated files and temporary SQLite databases may be used. The final milestone
gate includes the complete Python and Node suites, compilation, shell syntax, Make
dry-runs, diff checks and sensitive/runtime artifact scans.

## 8. Cross-project boundary

Retention remains entirely inside `baby-monitor-local`. Baby Care may later consume the
media-free Guardian event API, but it neither controls nor writes this local evidence
store. Per-parent acknowledgement remains outside this slice and must use Baby Care's
identity and authorization model when that integration is designed.
