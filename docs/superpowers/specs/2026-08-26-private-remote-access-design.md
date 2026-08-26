# P4 Authenticated Private Remote Access Design

**Date:** 2026-08-26
**Status:** Approved
**Owning stage:** `docs/NEXT.md` P4 and Baby Monitor Local V1 Task 7

## Goal

Let the two approved parent iPhones open the authenticated Baby Monitor Dashboard
while away from the home network without exposing the camera, go2rtc, SQLite,
Ollama, Voice internals or any other local service to the public internet.

P4 is an access-control and deployment stage. It does not add a second Dashboard,
change Guardian decisions, change Voice behavior, alter the Xiaomi stream, or make
the system suitable for unattended or medical care.

## Current deployment facts

- The Intel i9 owns the Dashboard and currently permits trusted-LAN access on TCP
  `8080` for the M2 Mac.
- Dashboard pages, assets, API routes, MJPEG, snapshots and HD-session issuance use
  HTTP Basic authentication. The bounded `/healthz` response is intentionally free
  of secrets and remains unauthenticated for local supervision.
- go2rtc administration and media listeners remain bound to loopback on TCP `1984`,
  `8554` and `8555`.
- The Dashboard relays approved media from loopback go2rtc; browsers never receive
  a selectable upstream URL or direct go2rtc access.
- No Tailscale application or CLI was detected on the i9 during the 2026-08-26 P4
  design probe. No Tailscale Serve configuration is currently present or claimed.
- A process was listening on Dashboard port `8080` during the probe, but the bounded
  local health request did not complete. Dashboard health must be recovered and
  verified independently before any Serve change.

## Security invariants

1. Remote access is private tailnet access only. Tailscale Funnel and router port
   forwarding are prohibited.
2. Tailscale Serve publishes only HTTPS TCP `443` and proxies only to the fixed local
   target `http://127.0.0.1:8080`.
3. The Dashboard keeps its existing Basic authentication. Tailscale identity headers
   are not trusted as a replacement for application authentication.
4. Tailnet policy grants only the approved parent identities access to TCP `443` on
   the dedicated i9 node. It grants no access to `8080`, `1984`, `8554`, `8555`,
   SQLite, SSH, Ollama or Voice ports as part of P4.
5. The i9 node uses a dedicated `tag:baby-monitor` identity owned by tailnet admins.
   The tag and grant are applied through the Tailscale admin boundary only after
   policy validation. No reusable auth key is placed in a command, file or report.
6. Actual tailnet names, MagicDNS names, user email addresses, device names, node
   addresses, credentials and policy exports remain outside Git and diagnostic output.
7. Existing trusted-LAN Dashboard access remains unchanged in P4. Moving Dashboard
   port `8080` to loopback is a separate migration because it would interrupt the
   current M2 workflow.
8. Tailscale, Serve or policy failure does not restart or disable go2rtc, Guardian,
   Voice, environment monitoring, Dashboard, Mi Home or camera microSD recording.
9. Remote status and logs expose stable allowlisted codes and booleans only. Raw CLI
   JSON, URLs, hostnames, addresses, identities and exceptions are never printed.
10. Software checks do not prove real off-home access. Both iPhones require a separate
    supervised cellular-network acceptance.

## Chosen architecture

### Client and server membership

Install the official Tailscale Standalone macOS client on the i9 and enable its CLI
integration. Install Tailscale on both iPhones. A parent performs the interactive
login and admin-console operations; the repository never handles an auth key or SSO
credential.

The i9 joins as a dedicated tagged service node. The two phones join as the approved
parent users' devices. Personal device names and identities are supplied only in the
private Tailscale admin console.

### Network policy

New policy uses Tailscale `grants`, the current recommended policy form, rather than
creating a new legacy ACL. The tracked example uses documentation-only identities:

```hujson
{
  "tagOwners": {
    "tag:baby-monitor": ["autogroup:admin"],
  },
  "groups": {
    "group:baby-parents": [
      "parent-one@example.invalid",
      "parent-two@example.invalid",
    ],
  },
  "grants": [
    {
      "src": ["group:baby-parents"],
      "dst": ["tag:baby-monitor"],
      "ip": ["tcp:443"],
    },
  ],
}
```

The operator must merge the rule into the existing private policy rather than replace
unrelated policy. Policy validation must pass before saving. Existing broad grants are
not overridden by a narrower grant; if another rule already permits access to the i9,
that broader rule must be reviewed and narrowed before P4 can pass.

### Serve boundary

After Dashboard health, client login, tag ownership and policy validation pass, the i9
configures one persistent Serve route equivalent to:

```text
HTTPS 443 -> http://127.0.0.1:8080
```

Implementation invokes the installed Tailscale CLI through a fixed executable and
fixed argument vector. It does not accept a caller-supplied target, port, hostname,
path, service name, Funnel option or additional CLI flag.

The browser URL is the HTTPS MagicDNS URL emitted privately by Tailscale. The URL may
be stored only in the ignored local runtime configuration when needed for notification
links. Repository commands and reports state only whether the URL is configured and
valid; they do not print it.

### Application boundary

Serve terminates tailnet HTTPS and forwards to the existing loopback Dashboard target.
The Dashboard continues to challenge with Basic authentication. Uvicorn keeps
`--no-proxy-headers`, so forwarded identity or address headers cannot change the
application's authorization or origin policy.

The existing HD relay remains the only browser-to-go2rtc bridge. P4 publishes neither
go2rtc nor a generic TCP proxy. WebSocket and HTTP requests remain same-origin under
the Serve HTTPS hostname.

## Repository interfaces

P4 adds these bounded operator interfaces:

- `make alpha-remote-preflight`: read-only verification of platform support,
  Tailscale CLI availability, backend login state, Dashboard local health, existing
  Serve/Funnel conflict state, fixed listener scopes and application authentication.
- `make alpha-remote-status`: read-only, redacted verification that one HTTPS Serve
  route points to the fixed loopback Dashboard target and no Funnel route exists.
- `make alpha-remote-configure`: an explicit operator action that applies only the
  fixed Serve route after all preflight gates pass. It never changes tailnet policy,
  installs software, logs in or edits runtime credentials.
- `make alpha-remote-test`: software/security checks only. It performs no real Serve,
  Funnel, policy, notification or household-media operation.

The implementation also adds:

- a pure parser/validator for bounded Tailscale status and Serve configuration;
- a macOS operator adapter with fixed argv, timeouts and redacted errors;
- a tracked example grant and a P4 runbook section for installation, policy merge,
  configuration, verification and rollback;
- deployment tests that prove prohibited ports and Funnel instructions are absent.

`alpha-remote-configure` may change only Tailscale Serve state. Disabling or resetting
an existing Serve configuration is a separate destructive rollback action and requires
explicit user approval after a read-only status check identifies the exact owned route.

## State model and fail-closed behavior

The public P4 state is one of:

- `REMOTE_NOT_INSTALLED`
- `REMOTE_NOT_AUTHENTICATED`
- `REMOTE_DASHBOARD_UNHEALTHY`
- `REMOTE_POLICY_UNVERIFIED`
- `REMOTE_SERVE_UNCONFIGURED`
- `REMOTE_SERVE_CONFLICT`
- `REMOTE_READY_SOFTWARE`
- `REMOTE_READY_DEVICE_GATE`

`REMOTE_READY_SOFTWARE` requires all local and policy evidence but does not claim that
either phone worked away from Wi-Fi. Only the supervised two-phone gate may record
`REMOTE_READY_DEVICE_GATE`.

Missing CLI output, timeout, malformed JSON, multiple Serve routes, any Funnel route,
an unexpected target, an unexpected exposed port, a non-loopback go2rtc listener,
missing Basic-auth challenge, unhealthy Dashboard or unknown policy state fails closed.
The implementation returns a stable code and does not automatically reset, repair or
broaden policy.

## Operator sequence

1. Recover and verify local Dashboard health without changing Tailscale state.
2. Install the official Tailscale Standalone client on the i9 and enable CLI
   integration; install Tailscale on both iPhones.
3. Interactively authenticate all three devices.
4. In the admin console, add the dedicated i9 tag and merge the minimum parent grant;
   validate that no broader existing rule exposes the i9.
5. Run the repository preflight. It must report only stable redacted fields.
6. Apply the fixed Serve route with the repository command.
7. Run local status/security checks and record only aggregate PASS/FAIL evidence.
8. On each iPhone, disable Wi-Fi, connect Tailscale, open the private HTTPS URL, enter
   Dashboard Basic credentials and verify normal and HD viewing.
9. Verify from the phones that direct access to Dashboard `8080` and go2rtc ports is
   unavailable. Do not probe unrelated tailnet devices.
10. Store the private HTTPS hostname only in ignored runtime configuration if approved
    notification links need it, then restart only the affected notification component.

## Verification

### Automated software gates

- Pure parser tests cover logged-out, malformed, timeout, missing, multiple-route,
  unexpected-target, unexpected-port and Funnel-present states.
- Adapter tests assert fixed argv, bounded timeouts, no shell, no caller-controlled
  target and redacted output.
- Deployment tests prove go2rtc remains loopback-only and no tracked command enables
  Funnel or router forwarding.
- API tests prove the Dashboard root and media/API surfaces still require Basic Auth,
  `/healthz` remains bounded, and HTTPS-origin WebSockets stay same-origin.
- Shell, Make, Python compilation, focused pytest, `git diff --check` and final privacy
  scans pass.

### Real-device gate

Both iPhones must independently pass while Wi-Fi is disabled:

- Tailscale is connected and the private HTTPS Dashboard URL loads.
- Missing or wrong Basic credentials are rejected.
- Correct credentials open the Dashboard and a current normal stream.
- One bounded 2x/3x HD session opens or safely falls back according to the existing HD
  contract.
- TCP `8080`, `1984`, `8554` and `8555` are not directly reachable through the
  tailnet policy.
- Turning off Tailscale makes the private URL unavailable without affecting Mi Home,
  camera microSD recording or the i9's local workers.

P4 passes only after both phone results and the redacted local audit are recorded in
`docs/CHECKPOINT.md`. No screenshot, hostname, address, identity, URL or credential is
stored as evidence.

## Rollback and recovery

If Serve configuration or phone acceptance fails, leave Guardian and Dashboard running,
remove only the exact P4-owned Serve HTTPS route after explicit approval, and re-run the
redacted status check. Do not run a global Tailscale reset, log out devices, remove
unrelated grants, stop the Alpha stack or alter router settings as an automatic repair.

If Dashboard health is the blocker, diagnose it through the existing component-specific
runbook and restart only the Dashboard process. Tailscale failure must never trigger a
go2rtc, Guardian, Voice, environment-worker or full-stack restart.

## Explicitly deferred

- Making Dashboard `8080` loopback-only and moving the M2 to Tailscale-only access.
- Tailscale Services, subnet routers, exit nodes, SSH exposure or device sharing.
- Replacing Dashboard Basic Auth with Tailscale identity headers or application
  capabilities.
- Public sharing, Funnel, router forwarding or unauthenticated notification links.
- Automatic policy API writes, auth-key provisioning or MDM deployment.
- Any camera, go2rtc, database, Ollama, Voice or Baby Care remote endpoint.
