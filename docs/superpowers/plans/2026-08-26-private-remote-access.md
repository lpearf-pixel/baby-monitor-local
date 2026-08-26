# P4 Authenticated Private Remote Access Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (- [ ]) syntax for tracking.

**Goal:** Publish only the Basic-authenticated Baby Monitor Dashboard to two approved parent iPhones over private Tailscale Serve HTTPS, with redacted local audits and no public or direct camera-service exposure.

**Architecture:** Add a pure parser for bounded Tailscale and listener evidence, then a macOS-only operator adapter with fixed CLI paths, fixed argv and stable status codes. A separately approved configure action creates exactly one HTTPS 443 Serve proxy to http://127.0.0.1:8080; a minimum Tailscale grant and two-phone cellular gate remain human-controlled.

**Tech Stack:** Python 3.11 standard library, pytest, GNU Make, macOS Tailscale Standalone CLI, Tailscale Serve HTTPS and grants.

**Spec:** docs/superpowers/specs/2026-08-26-private-remote-access-design.md

## Global Constraints

- Tailscale Serve HTTPS is private tailnet access only. Never invoke or enable Funnel, router forwarding, a subnet router, an exit node, Tailscale SSH or device sharing.
- The only Serve listener is HTTPS TCP 443; the only proxy target is the literal http://127.0.0.1:8080.
- Dashboard Basic Auth remains mandatory. Tailscale identity headers never replace application authentication.
- go2rtc TCP 1984, 8554 and 8555 remain loopback-only and are never published.
- Existing trusted-LAN Dashboard access on TCP 8080 remains unchanged in P4.
- Real tailnet names, MagicDNS names, user identities, device names, addresses, credentials, policy exports and auth keys never enter Git or command output.
- Operator subprocesses use fixed argument arrays, no shell, bounded output, bounded timeouts and stable redacted errors.
- A Tailscale or Serve failure never restarts the Dashboard, go2rtc, Guardian, Voice, environment monitoring or the full Alpha stack.
- alpha-remote-test is side-effect-free. Real installation, login, policy merge, Serve mutation and phone checks remain separately controlled gates.
- No implementation task may run tailscale serve reset, tailscale serve off, tailscale logout, or delete a policy/runtime file.

---

### Task 1: Pure Tailscale evidence contract

**Files:**
- Create: packages/monitoring/private_remote_access.py
- Create: tests/monitoring/test_private_remote_access.py

**Interfaces:**
- Produces: RemoteCode, TailnetEvidence, ServeEvidence, ListenerEvidence, DashboardEvidence and RemoteAccessReport immutable dataclasses.
- Produces: parse_tailnet_status(payload: bytes) -> TailnetEvidence.
- Produces: parse_serve_status(payload: bytes) -> ServeEvidence.
- Produces: evaluate_remote_access(*, installed, tailnet, serve, listeners, dashboard, policy_reviewed) -> RemoteAccessReport.
- Consumes: bounded bytes and already-derived listener/Dashboard facts; it performs no filesystem, process or network I/O.

- [x] **Step 1: Write failing tailnet and Serve parser tests**

Use exact synthetic fixtures:

~~~python
RUNNING = b'{"BackendState":"Running","Self":{"Online":true}}'
FIXED_SERVE = b'''{
  "TCP":{"443":{"HTTPS":true}},
  "Web":{"node.example.invalid:443":{"Handlers":{"/":{"Proxy":"http://127.0.0.1:8080"}}}}
}'''
FUNNEL_SERVE = b'''{
  "TCP":{"443":{"HTTPS":true}},
  "Web":{"node.example.invalid:443":{"Handlers":{"/":{"Proxy":"http://127.0.0.1:8080"}}}},
  "AllowFunnel":{"node.example.invalid:443":true}
}'''
~~~

Assert logged-out, offline, malformed, non-object, oversized, multiple-host,
multiple-handler, non-root-handler, non-HTTPS, unexpected-port, unexpected-target and
Funnel-enabled documents all return closed evidence without preserving a raw hostname,
address or payload. The maximum accepted size for each JSON document is 1,048,576 bytes.

- [x] **Step 2: Run parser RED**

~~~bash
.venv-alpha/bin/python -m pytest -q tests/monitoring/test_private_remote_access.py
~~~

Expected: collection fails because packages.monitoring.private_remote_access does not exist.

- [x] **Step 3: Implement immutable types and strict parsing**

Define these public values:

~~~python
class RemoteCode(StrEnum):
    NOT_INSTALLED = "REMOTE_NOT_INSTALLED"
    NOT_AUTHENTICATED = "REMOTE_NOT_AUTHENTICATED"
    DASHBOARD_UNHEALTHY = "REMOTE_DASHBOARD_UNHEALTHY"
    POLICY_UNVERIFIED = "REMOTE_POLICY_UNVERIFIED"
    SERVE_UNCONFIGURED = "REMOTE_SERVE_UNCONFIGURED"
    SERVE_CONFLICT = "REMOTE_SERVE_CONFLICT"
    READY_SOFTWARE = "REMOTE_READY_SOFTWARE"
    READY_DEVICE_GATE = "REMOTE_READY_DEVICE_GATE"

@dataclass(frozen=True)
class TailnetEvidence:
    authenticated: bool

@dataclass(frozen=True)
class ServeEvidence:
    configured: bool
    fixed_https_proxy: bool
    funnel_present: bool
    conflict: bool

@dataclass(frozen=True)
class ListenerEvidence:
    dashboard_available: bool
    go2rtc_loopback_only: bool

@dataclass(frozen=True)
class DashboardEvidence:
    health_ok: bool
    basic_auth_required: bool

@dataclass(frozen=True)
class RemoteAccessReport:
    code: RemoteCode
    tailnet_authenticated: bool
    serve_fixed: bool
    funnel_absent: bool
    dashboard_healthy: bool
    basic_auth_required: bool
    go2rtc_private: bool
    policy_reviewed: bool
~~~

Parse only required fields. Accept exactly one Web host entry on port 443, one root
handler containing one Proxy string equal to the fixed target, and an HTTPS TCP entry
for 443. Any truthy AllowFunnel, extra handler, extra Web host, extra TCP port,
malformed structure or unknown target sets conflict. Never copy source strings into
exceptions or reports.

- [x] **Step 4: Add public-state precedence tests**

Lock this order: missing CLI -> not installed; backend not running/online -> not
authenticated; unhealthy Dashboard or missing Basic challenge -> Dashboard unhealthy;
non-loopback go2rtc or malformed/Funnel/unexpected Serve route -> Serve conflict;
missing policy acknowledgement -> policy unverified; empty Serve -> Serve unconfigured;
otherwise ready software. READY_DEVICE_GATE is never synthesized by software
evaluation. A missing acknowledgement must never mask a Funnel or exposed-port conflict.

- [x] **Step 5: Run GREEN and commit**

~~~bash
.venv-alpha/bin/python -m pytest -q tests/monitoring/test_private_remote_access.py
.venv-alpha/bin/python -m compileall -q packages/monitoring/private_remote_access.py
git diff --check
git add packages/monitoring/private_remote_access.py tests/monitoring/test_private_remote_access.py
git commit -m "feat: validate private remote access evidence"
~~~

---

### Task 2: Read-only macOS preflight and status adapter

**Files:**
- Create: tools/private_remote_access.py
- Create: tests/tools/test_private_remote_access.py
- Create: tests/__init__.py
- Create: tests/monitoring/__init__.py
- Create: tests/tools/__init__.py

**Interfaces:**
- Consumes: Task 1 parsers and evaluator.
- Produces: run_bounded(argv: tuple[str, ...], timeout_seconds: float) -> CommandResult with a hard 1,048,576-byte combined-output cap and complete child settlement.
- Produces: collect_preflight() -> RemoteAccessReport using only /usr/local/bin/tailscale, /usr/sbin/lsof and fixed loopback HTTP requests.
- Produces CLI subcommands preflight and status; both print the same fixed eight-line allowlist and never mutate state.

- [x] **Step 1: Write fixed-command and privacy RED tests**

Inject a recording command runner and HTTP opener. Assert exact argv:

~~~python
("/usr/local/bin/tailscale", "status", "--json")
("/usr/local/bin/tailscale", "serve", "status", "--json")
("/usr/sbin/lsof", "-nP", "-iTCP:8080", "-sTCP:LISTEN")
("/usr/sbin/lsof", "-nP", "-iTCP:1984", "-sTCP:LISTEN")
("/usr/sbin/lsof", "-nP", "-iTCP:8554", "-sTCP:LISTEN")
("/usr/sbin/lsof", "-nP", "-iTCP:8555", "-sTCP:LISTEN")
~~~

Assert fixed HTTP probes request only http://127.0.0.1:8080/healthz and
http://127.0.0.1:8080/, both with two-second timeouts. The root accepts only HTTP 401
with WWW-Authenticate Basic; health accepts only HTTP 200 with exact bounded JSON
{"status":"ok"}.

Feed canary hostnames, addresses, email identities, tokens, stderr and absolute paths
into every failure path. Stdout must be exactly:

~~~text
remote_code=<allowlisted code>
tailnet_authenticated=<true|false>
serve_fixed=<true|false>
funnel_absent=<true|false>
dashboard_healthy=<true|false>
basic_auth_required=<true|false>
go2rtc_private=<true|false>
policy_reviewed=<true|false>
~~~

- [x] **Step 2: Run adapter RED**

~~~bash
.venv-alpha/bin/python -m pytest -q tests/tools/test_private_remote_access.py
~~~

Expected: collection fails because tools.private_remote_access does not exist.

- [x] **Step 3: Implement bounded collection**

Use subprocess.Popen without shell=True. Read at most 1,048,577 bytes; terminate then
kill on timeout/overflow; wait for child settlement before return. Discard raw stderr
after deriving a stable code.

Parse lsof only into closed, loopback, all_interfaces, specific_interface or invalid.
Require 8080 listening and all go2rtc ports loopback or closed. Never print PID, process
name or address.

Read policy acknowledgement only from runtime/status/private-remote-policy.json. Accept
this exact schema:

~~~json
{"schema_version":1,"policy_reviewed":true,"serve_applied":true}
~~~

Require a regular current-user-owned mode-0600 file and no symlink in any component
from repository root to leaf. Unknown fields or values mean policy_reviewed=false.

- [x] **Step 4: Add settlement and filesystem tests**

Use synthetic children and temporary directories. Prove timeout and cap paths reap the
child and prevent late writes after return. Prove symlink parent/leaf, FIFO/socket,
non-regular file, wrong owner simulation, wrong mode and malformed state fail closed
without deletion or chmod repair.

- [x] **Step 5: Run GREEN and commit**

~~~bash
.venv-alpha/bin/python -m pytest -q tests/monitoring/test_private_remote_access.py tests/tools/test_private_remote_access.py
.venv-alpha/bin/python -m compileall -q packages/monitoring/private_remote_access.py tools/private_remote_access.py
git diff --check
git add tools/private_remote_access.py tests/tools/test_private_remote_access.py
git commit -m "feat: audit private remote access locally"
~~~

---

### Task 3: Explicit fixed Serve configuration

**Files:**
- Modify: tools/private_remote_access.py
- Modify: tests/tools/test_private_remote_access.py

**Interfaces:**
- Produces CLI subcommand configure.
- Consumes: successful Task 2 preflight, a controlling TTY and exact literal YES.
- Executes only ("/usr/local/bin/tailscale", "serve", "--bg", "http://127.0.0.1:8080").
- Produces the fixed mode-0600 policy acknowledgement only after the Serve command and fresh post-apply validation succeed.

- [x] **Step 1: Write configure RED tests**

Cover missing TTY, wrong confirmation, missing CLI, unauthenticated backend, unhealthy
Dashboard, missing Basic challenge, non-loopback go2rtc, Funnel, conflicting Serve,
timeout, command failure, invalid post-apply status and state-write failure. Each case
must invoke either zero Serve mutations or one exact fixed mutation, and never invoke
reset, off, logout or a full-stack command.

Add success and idempotency tests. Success invokes fixed Serve argv once, re-reads
Serve status, atomically publishes exact policy JSON with mode 0600, fsyncs file and
parent directory, and emits a redacted ready report. An already-correct route performs
no mutation and refreshes the acknowledgement only after policy reconfirmation.

- [x] **Step 2: Run configure RED**

~~~bash
.venv-alpha/bin/python -m pytest -q tests/tools/test_private_remote_access.py -k configure
~~~

Expected: tests fail because configure is not a recognized subcommand.

- [x] **Step 3: Implement the minimum mutation**

Read confirmation from /dev/tty; piped stdin and environment variables cannot authorize
the change. Print only:

~~~text
policy_review_confirmation=required
type_yes_to_apply_fixed_private_serve=
~~~

On failure, preserve Serve state and return a stable code. Do not auto-rollback. Accept
no target, port, hostname, policy, identity or executable option. Before confirmation,
configure requires installed/authenticated Tailscale, healthy Basic-authenticated
Dashboard, private go2rtc listeners, no Funnel and no Serve conflict. The only
admissible pre-apply public states are REMOTE_POLICY_UNVERIFIED,
REMOTE_SERVE_UNCONFIGURED and REMOTE_READY_SOFTWARE; Serve may be empty or already the
fixed route. The exact YES supplies the human policy-review assertion, so there is no
circular requirement for the acknowledgement file to exist before its first creation.

- [x] **Step 4: Run GREEN and commit**

~~~bash
.venv-alpha/bin/python -m pytest -q tests/tools/test_private_remote_access.py
.venv-alpha/bin/python -m compileall -q tools/private_remote_access.py
git diff --check
git add tools/private_remote_access.py tests/tools/test_private_remote_access.py
git commit -m "feat: configure fixed private Tailscale Serve"
~~~

---

### Task 4: Make targets, grant example and runbook

**Files:**
- Modify: Makefile
- Modify: tools/start_alpha.sh
- Modify: tools/install_alpha_macos.sh
- Modify: tests/deploy/test_network_access.py
- Create: tests/deploy/test_private_remote_access.py
- Create: config/tailscale.grants.example.hujson
- Create: docs/runbooks/PRIVATE_REMOTE_ACCESS.md
- Modify: docs/runbooks/ALPHA_QUICKSTART.md

**Interfaces:**
- Produces: make alpha-remote-preflight, alpha-remote-status, alpha-remote-configure and alpha-remote-test.
- Produces: valid synthetic grant example with group:baby-parents, tag:baby-monitor and only tcp:443.
- Replaces: raw Serve mutation instructions in generic startup output with bounded repository commands.

- [ ] **Step 1: Write deployment/documentation RED tests**

Assert Make targets invoke only:

~~~make
$(PYTHON) tools/private_remote_access.py preflight
$(PYTHON) tools/private_remote_access.py status
$(PYTHON) tools/private_remote_access.py configure
$(PYTHON) -m pytest -q tests/monitoring/test_private_remote_access.py tests/tools/test_private_remote_access.py tests/deploy/test_private_remote_access.py tests/deploy/test_network_access.py
~~~

Parse the valid-JSON subset of the HuJSON example. Assert one tag owner, one parent
group and one grant to tag:baby-monitor whose only permission is tcp:443; all identities
must end in .invalid.

Scan changed operator files for executable Funnel/router/reset/logout instructions,
grants for 8080/1984/8554/8555, auth keys, private IPv4 literals and real identities.
Prohibitions in prose and fixed loopback literals are the only allowed matches.

- [ ] **Step 2: Run deployment RED**

~~~bash
.venv-alpha/bin/python -m pytest -q tests/deploy/test_private_remote_access.py tests/deploy/test_network_access.py
~~~

Expected: assertions fail because P4 commands, example and runbook do not exist.

- [ ] **Step 3: Add Make and safe generic output**

Add targets to .PHONY and help. Generic Alpha startup may print
make alpha-remote-preflight and the runbook path, but not a direct Serve mutation or
a detected network address.

- [ ] **Step 4: Add grant and operating procedure**

The runbook uses the official Standalone client and Settings CLI integration, requires
interactive login on i9 and both iPhones, tells the admin to merge rather than replace
policy, and requires validation plus review of broader grants. Distinguish read-only
commands from configure. Rollback is explicit-approval only and gets no Make target.

- [ ] **Step 5: Run GREEN/static gates and commit**

~~~bash
make alpha-remote-test
make -n alpha-remote-preflight
make -n alpha-remote-status
make -n alpha-remote-configure
bash -n tools/start_alpha.sh tools/install_alpha_macos.sh
.venv-alpha/bin/python -m compileall -q packages/monitoring/private_remote_access.py tools/private_remote_access.py
git diff --check
git add Makefile tools/start_alpha.sh tools/install_alpha_macos.sh tests/deploy/test_network_access.py tests/deploy/test_private_remote_access.py config/tailscale.grants.example.hujson docs/runbooks/PRIVATE_REMOTE_ACCESS.md docs/runbooks/ALPHA_QUICKSTART.md
git commit -m "docs: add private remote access workflow"
~~~

---

### Task 5: Software checkpoint

**Files:**
- Modify: SUMMARY.md
- Modify: docs/STATUS.md
- Modify: docs/CHECKPOINT.md
- Modify: docs/NEXT.md
- Modify: docs/superpowers/plans/2026-08-26-private-remote-access.md

**Interfaces:**
- Records the P4 software head and exact fresh gate counts.
- Does not claim installation, policy, Serve or phone PASS unless observed.

- [ ] **Step 1: Run focused and adjacent software gates**

~~~bash
make alpha-remote-test
.venv-alpha/bin/python -m pytest -q tests/api/test_alpha_app.py tests/api/test_hd_stream.py tests/deploy/test_alpha_commands.py
node --test tests/frontend/*.test.mjs
.venv-alpha/bin/python -m pytest -q
~~~

Expected: all pass. This proves parser, CLI, redaction, application-auth and same-origin
contracts only, not Tailscale account policy or off-home access.

- [ ] **Step 2: Run static/privacy gates**

~~~bash
.venv-alpha/bin/python -m compileall -q packages/monitoring/private_remote_access.py tools/private_remote_access.py
bash -n tools/start_alpha.sh tools/install_alpha_macos.sh
make -n alpha-remote-preflight alpha-remote-status alpha-remote-configure alpha-remote-test
git diff --check
git grep -n -E 'tailscale[[:space:]]+funnel|serve[[:space:]]+reset|tailscale[[:space:]]+logout'
git grep -n -E '([0-9]{1,3}\\.){3}[0-9]{1,3}|auth[_ -]?key|BEGIN (RSA|OPENSSH|PRIVATE) KEY'
~~~

Review every match. Loopback literals, explicit prohibitions and synthetic canaries are
allowed; executable prohibited actions, private network literals, credentials, real
identities or keys fail.

- [ ] **Step 3: Update documents and commit**

Set P4 to Software complete; installed/device gates pending. Record that Dashboard-health
recovery, Tailscale install/login, private grant merge, Serve apply and two-iPhone
cellular acceptance remain pending. Set Voice Gate V3 as the next independent software
slice; do not make P5 ready.

~~~bash
git add SUMMARY.md docs/STATUS.md docs/CHECKPOINT.md docs/NEXT.md docs/superpowers/plans/2026-08-26-private-remote-access.md
git commit -m "docs: record P4 software checkpoint"
~~~

---

### Task 6: Installed i9 and two-iPhone acceptance

**Files:**
- Modify after evidence: SUMMARY.md
- Modify after evidence: docs/STATUS.md
- Modify after evidence: docs/CHECKPOINT.md
- Modify after evidence: docs/NEXT.md
- Modify after evidence: docs/superpowers/plans/2026-08-26-private-remote-access.md

**Interfaces:**
- Consumes: approved software head, healthy Dashboard, installed/authenticated Tailscale on i9 and both phones, and privately merged grants.
- Produces: redacted P4 PASS or first stable blocker.

- [ ] **Step 1: Recover Dashboard health independently**

~~~bash
make alpha-status
~~~

If health is unavailable, inspect only Dashboard process and a bounded API log window.
Restart only Dashboard through the existing lifecycle; do not restart go2rtc, Guardian,
Voice or the full stack as a Tailscale repair. Continue only when health is exact
{"status":"ok"} and unauthenticated root returns a Basic challenge.

- [ ] **Step 2: Human installs/authenticates Tailscale**

The human installs official Tailscale Standalone, enables CLI integration in Settings,
and performs interactive login on i9 and both iPhones. No auth key or SSO value is given
to Codex or stored in Git.

- [ ] **Step 3: Human merges/validates minimum grant**

Privately replace .invalid identities, merge the tag owner/group/grant into existing
policy, tag the i9, validate it, and confirm no broader rule grants extra i9 ports. Do
not paste policy, identities, node name or addresses into chat or Git.

- [ ] **Step 4: Apply fixed Serve after separate approval**

~~~bash
make alpha-remote-preflight
make alpha-remote-configure
make alpha-remote-status
~~~

The configure command requires exact controlling-terminal YES. Expected final code is
REMOTE_READY_SOFTWARE with all booleans true and no private output. A failure stops at
that component; never widen grants or publish another port.

- [ ] **Step 5: Run two independent cellular checks**

For each phone: disable Wi-Fi, connect Tailscale, open private HTTPS, confirm wrong
Basic credentials fail, then view current normal stream and one bounded 2x/3x attempt.
Confirm direct tailnet TCP 8080/1984/8554/8555 is unavailable. Disable Tailscale and
confirm private URL stops while Mi Home and local i9 workers continue.

Record only:

~~~text
phone_1_https=true|false
phone_1_basic_auth=true|false
phone_1_normal_stream=true|false
phone_1_hd_bounded=true|false
phone_1_direct_ports_blocked=true|false
phone_2_https=true|false
phone_2_basic_auth=true|false
phone_2_normal_stream=true|false
phone_2_hd_bounded=true|false
phone_2_direct_ports_blocked=true|false
local_workers_independent=true|false
~~~

- [ ] **Step 6: Verify independence and record checkpoint**

If authenticated environment-notification links are enabled, place the private HTTPS
MagicDNS URL only in the ignored deployed runtime/alpha.env as
BABY_MONITOR_DASHBOARD_URL. Reject credentials, query parameters, fragments, numeric
addresses and non-HTTPS values. Restart only the notification component that consumes
the value; skip this conditional step when notification links remain disabled.

~~~bash
make alpha-remote-status
make alpha-source-check
make alpha-voice-listen-status
git status --short --branch
git diff --check
~~~

If both phones pass, mark P4 complete. Keep Voice Gate V3 next when it is incomplete;
only make P5 next after V3 and every other release prerequisite pass. Otherwise keep P4
pending with only the first stable code. Commit only the five documentation files:

~~~bash
git add SUMMARY.md docs/STATUS.md docs/CHECKPOINT.md docs/NEXT.md docs/superpowers/plans/2026-08-26-private-remote-access.md
git commit -m "docs: record private remote access acceptance"
~~~

Do not push, merge, tag, create a PR or modify main without separate explicit approval.
