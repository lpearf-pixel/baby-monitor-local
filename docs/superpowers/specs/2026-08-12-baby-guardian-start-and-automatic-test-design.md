# Baby Guardian Start and Automatic Test Design

## Scope

This slice delivers option A: one idempotent guardian start command and one
complete automatic test command for the current local Baby Guardian chain. It
does not send a real ntfy test message, ask either Android phone to acknowledge
receipt, simulate a live baby risk, modify production risk data, or add the
Dashboard event workflow.

The existing `alpha-start`, `alpha-source-check`, `alpha-visual-status`, Python
tests, and deployment checks remain the lower-level authorities. The new
commands orchestrate them and provide one stable result instead of duplicating
their implementation.

## Commands

`make alpha-guardian-start` starts the installed Alpha services through the
existing start path and then runs bounded guardian readiness checks. Repeating
the command while services are healthy must not create duplicate processes or
restart healthy launchd jobs.

`make alpha-guardian-test` runs the automatic acceptance workflow. It never
sends ntfy traffic and never writes a synthetic event to the production
database. The command is suitable for the Intel i9 installation. Its offline
software phase must also be independently testable in development and CI.

The existing commands retain their behavior and compatibility.

## Start readiness

The guardian start command verifies these required components after
`tools/start_alpha.sh` returns:

- go2rtc API is reachable on its loopback endpoint;
- Dashboard `/healthz` is reachable on its configured local port;
- visual worker is registered with launchd on macOS or has a live pid file on
  the portable fallback;
- environment watchdog is registered or has a live pid file;
- gauge worker is registered or has a live pid file;
- pinned realtime model files pass the existing model checker;
- the visual metrics snapshot is current and valid;
- the configured Ollama bridge is reachable when semantic review is enabled.

Every poll has a fixed timeout. A missing optional notification configuration
does not fail startup because risk persistence and evidence remain available.
A required component failure returns nonzero and prints only a fixed component
name plus its fixed diagnostic command or log category. It does not print
environment values, network addresses, paths, exception text, or log content.

## Automatic acceptance phases

The test command executes ordered phases and stops only after collecting every
safe result that can still run:

1. **Repository safety** checks Bash 3.2 syntax, ASCII/LF shell policy,
   Makefile wiring, tracked runtime/media/database files, and credential or
   private-address literals in the changed production surface.
2. **Software regression** runs the repository Python test suite with the
   installed Alpha virtual environment. Tests use temporary directories and
   isolated databases.
3. **Installation** checks required binaries, settings, launchd definitions,
   pinned realtime models, and readable non-secret configuration structure.
4. **Service readiness** checks go2rtc, Dashboard, visual worker, gauge worker,
   watchdog, visual metrics, and the conditional Ollama bridge.
5. **Live media** delegates to `alpha-source-check` for protocol, received
   bytes, source dimensions, MJPEG continuity, and Dashboard preview health.
6. **Guardian isolation** runs focused deterministic tests for risk state,
   event persistence, evidence JPEG/WebP, notification outbox ordering and
   retry, dispatcher failure isolation, production runtime wiring, and privacy
   rejection.

Repository safety, software regression, and guardian isolation can run without
the camera. Installation, service readiness, and live media are required for a
complete i9 acceptance result. Missing installed runtime or camera access is a
`FAIL`, not a false `PASS`. Unit-test fixtures may represent an unavailable
live environment as `SKIP`, but the user-facing i9 command does not silently
skip required hardware checks.

## Reporting and exit status

Each check emits one ASCII line in this shape:

```text
PASS <phase> <check>
FAIL <phase> <check> <fixed_reason>
```

The final summary includes pass and fail counts and a single
`guardian_test=PASS` or `guardian_test=FAIL`. Exit status is zero only when all
required checks pass. Command output must remain copy-safe on macOS and must
not contain credentials, ntfy topics, camera identifiers, household paths,
private addresses, payloads, media, database contents, or raw exception text.

The script stores no report file by default. The caller may redirect stdout to
a local file when needed.

## Shell and process constraints

Repository shell remains compatible with macOS system Bash 3.2 and BSD tools.
Scripts are ASCII-only UTF-8 with LF endings, use no GNU-only flags, and pass
`bash -n`. Long logic lives under `tools/`; Makefile targets remain thin.

The workflow may read runtime state but must not edit `runtime/alpha.env`,
`runtime/settings.yaml`, go2rtc configuration, launchd plists, evidence, or
SQLite data. The only mutations allowed by `alpha-guardian-start` are the same
service-start and pid-file effects already authorized by `alpha-start`.

## Test strategy

Shell orchestration is tested through injected command paths and temporary
runtime fixtures so failure aggregation, timeouts, idempotency, redaction, and
exit status are deterministic. Tests first demonstrate missing command and
reporting behavior, then the minimum production scripts are added.

Fresh completion evidence must include:

- focused script tests;
- the existing guardian notification, evidence, risk, runtime, deployment, and
  visual status regressions;
- `bash -n` for every changed shell script;
- ASCII and CRLF checks for every changed shell script;
- `git diff --check`;
- tracked runtime/media/database and credential/private-literal scans.

## Deferred work

Real ntfy delivery and confirmation by both Android phones remain a separate
`alpha-guardian-test-live` slice. Safe live risk rehearsal, authenticated event
queries, parent acknowledgement, false-positive feedback, and Dashboard event
listing also remain deferred.
