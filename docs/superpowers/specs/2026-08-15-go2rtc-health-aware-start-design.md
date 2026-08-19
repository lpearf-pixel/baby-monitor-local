# go2rtc Health-Aware Start Design

## Context

The installed i9 Alpha stopped go2rtc by the PID recorded in
`runtime/pids/go2rtc.pid`. During recovery, an older go2rtc process still held
the loopback API and RTSP ports while a replacement process started. The
replacement could not bind either listener but remained alive, and its PID was
written to the PID file. After the older listener stopped, the replacement was
still alive without a working API. Later starts treated `kill -0` success as
proof of readiness, skipped replacement, and eventually reported that go2rtc
did not become ready.

The failure is a mismatch between process liveness and service readiness. A
live PID alone does not prove that the expected project process owns a healthy
go2rtc API.

## Scope

Change only go2rtc startup recovery in `tools/start_alpha.sh` and its deployment
tests. Preserve the existing startup behavior for the Dashboard and independent
workers. Do not change camera configuration, stream quality, ports, credentials,
launchd ownership, stop behavior, or the visual Guardian pipeline.

## Startup Design

Before deciding that go2rtc is already running, evaluate its loopback API with
a bounded request and reconcile a positive response with the recorded process:

1. If the API is healthy, require a PID file, a live PID, the exact repository
   go2rtc command, and proof that this PID owns the loopback API listener before
   continuing. A healthy listener alone is insufficient; missing, dead,
   unrelated, or non-listening PIDs fail closed. Listener inspection may verify
   only the already validated PID and must never select a process to terminate.
2. If the API is unhealthy and no PID file exists, start go2rtc normally.
3. If the API is unhealthy and the PID file names a dead process, remove the
   stale PID file and start go2rtc normally.
4. If the API is unhealthy and the PID is alive, verify through BSD
   `ps -ww -p PID -o command=` that the
   process command is the repository's configured go2rtc executable with the
   repository's runtime configuration.
5. Only when that identity matches, terminate the unhealthy process using the
   existing bounded graceful-wait and forced-stop pattern, remove the PID file,
   and start one replacement.
6. If the live PID does not match the expected command, fail closed with a fixed
   error and leave the process untouched.

The existing bounded API readiness wait remains the final authority after a
new process starts. The script must never select or kill a process by port
alone.

## Error and Privacy Contract

Failures use fixed ASCII status text and do not print PIDs, commands, paths,
configuration, URLs, private addresses, or underlying process output. A live
PID whose identity cannot be verified returns:

`go2rtc pid identity mismatch`

Failure of the replacement to expose the API retains the existing bounded
message:

`go2rtc did not become ready. Check runtime/logs/go2rtc.log`

## Test Design

Deployment tests run the startup script with controlled fake `kill`, `ps`,
`curl`, `sleep`, and go2rtc commands. Regression coverage must prove:

- a healthy API causes no restart only with a live exact go2rtc PID;
- a healthy API with a missing, dead, or unrelated PID fails closed;
- a healthy API whose verified go2rtc PID does not own the API listener fails
  closed without terminating that process;
- a dead PID is replaced;
- a live expected go2rtc PID with an unhealthy API is stopped and replaced;
- a live unrelated PID with an unhealthy API is not stopped and startup fails
  with the fixed identity error;
- a long exact go2rtc command is not truncated during BSD `ps` identity
  verification;
- the readiness wait remains bounded when a replacement never becomes healthy;
- Dashboard and independent-worker startup behavior remains unchanged.

The key regression test must fail against the current script because it skips
the live-but-unhealthy PID rather than replacing it.

## Acceptance and Delivery

Use test-driven development: add the live-but-unhealthy regression test, verify
the expected RED result, implement the minimum shell change, and verify GREEN.
Run the focused deployment tests, `bash -n tools/start_alpha.sh`, the repository
shell ASCII/LF check, `make -n alpha-start`, `git diff --check`, and a final
tracked-diff sensitive-data scan. Do not use a software test to claim camera
availability or Guardian accuracy.

Deliver the design and implementation as separate focused local commits on the
current feature branch. Do not push, merge, create a PR, modify protected
branches, or stage the unrelated `.local/`, `Interactive`, or `test.sh` files.
