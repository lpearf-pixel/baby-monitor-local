# M2 to i9 SSH tunnel operations

This runbook describes the repository-owned, combined tunnel. The code-development
machine, SSH/LaunchAgent installation machine and Ollama inference machine are
separate roles. Never infer those roles from the machine running Codex.

- code machine: the checkout used for development (currently the Intel i9)
- tunnel machine: the logged-in M2, M3 or another explicitly selected host
- inference machine: the host that serves Ollama on port 11434

The SSH target is the i9 at `192.168.2.141`. A checkout on the i9 does not make it
the tunnel machine or the inference machine.

## Scope and safety

The LaunchAgent is `com.babymonitor.ssh-tunnels`. It owns one SSH process with
two loopback-only forwards:

- M2 `127.0.0.1:1984` to i9 `127.0.0.1:1984` (go2rtc)
- i9 `127.0.0.1:11435` to an explicit Ollama host reachable from the i9 on port 11434

The `-L` destination is resolved from the tunnel machine. The `-R` destination is
resolved from the i9 SSH server. If Ollama is on M2 or M3, use an address that the
i9 can reach; do not silently use the tunnel machine's loopback. A local
`127.0.0.1:11434` check on M3 proves only M3-local availability.

The forwards are not exposed to the LAN. The scripts never restart Guardian,
go2rtc, Ollama or Baby Care and never enable Camera Reply. Install, start and
uninstall are not run automatically by this repository task.

## M2 installation

Use a dedicated pre-existing SSH key whose file is mode 0600. Do not put the
key, passphrase or host-specific paths in Git. First run this read-only preflight
on the actual tunnel machine, for example M3:

```text
bash scripts/tunnels/preflight.sh --install-host m3 --target kandysmith@192.168.2.141 --identity "$HOME/.ssh/baby-monitor-i9" --ollama-host 192.168.2.144
```

Replace `192.168.2.144` only with an address the i9 can reach for Ollama. The
preflight does not infer roles from `uname -m` and never stops old services. After
`MIGRATION_PREFLIGHT_PASS`, install from that same tunnel machine:

```text
bash scripts/tunnels/install.sh --initiator-host m3 --target kandysmith@192.168.2.141 --identity "$HOME/.ssh/baby-monitor-i9" --ollama-host 192.168.2.144 --log-dir "$HOME/Library/Logs/BabyMonitor"
bash scripts/tunnels/control.sh status
bash scripts/tunnels/control.sh check --target kandysmith@192.168.2.141 --identity "$HOME/.ssh/baby-monitor-i9"
```

`install.sh` validates the target, key permissions, initiator role, Ollama
destination, local port and remote port
before writing the private plist. It refuses occupied ports and does not kill
unknown processes. The LaunchAgent uses non-interactive authentication,
`ExitOnForwardFailure`, keepalives and a 30-second launchd throttle.

## Status interpretation

`check.sh` reports independent facts: `launchd_registration`, `ssh_process`,
`m2_port_1984`, `go2rtc_api`, `i9_port_11435` and `ollama_api`. A listening port is not proof
that its HTTP service is healthy. A remote port or Ollama result of `unknown` or
`unreachable` can mean the SSH connection is unavailable; it must not trigger a
stack restart. The M7 client continues to use i9 loopback `127.0.0.1:11435`.

## Existing tunnel migration

Before installation, inspect any existing `com.babymonitor.ollama-tunnel`
LaunchAgent and current listeners. This repository never disables that legacy
service and never replaces a process it does not own. If it occupies i9 port
11435, installation fails closed. A human operator may later schedule a
separate migration: stop the old service using its own documented owner,
confirm the port is free, install the combined label, and retain the old plist
as rollback evidence. Do not stop both services at once.

## Control and rollback

```text
bash scripts/tunnels/control.sh start
bash scripts/tunnels/control.sh stop
bash scripts/tunnels/control.sh restart
bash scripts/tunnels/control.sh status
bash scripts/tunnels/uninstall.sh
```

`control.sh` and `uninstall.sh` verify the repository ownership marker and only
operate on `com.babymonitor.ssh-tunnels`. Uninstall is idempotent and leaves all
other LaunchAgents untouched. Rollback is `uninstall.sh` for this label only;
restore or restart the prior operator-owned service manually if that migration
was separately approved.

## Verification boundary

The checked-in tests use fake launchctl, SSH, lsof and curl commands. They prove
argument construction, ownership, conflict handling, restart safety and layered
status reporting only. They do not install a LaunchAgent, access the household
camera, or prove M2/i9 network availability. Hardware activation remains a
separate approved operation.
