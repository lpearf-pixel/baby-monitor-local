#!/bin/bash
set -eu

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
LABEL="com.babymonitor.ssh-tunnels"
DOMAIN="gui/$(id -u)"
AGENTS_DIR="${LAUNCH_AGENTS_DIR:-$HOME/Library/LaunchAgents}"
LAUNCHCTL="${LAUNCHCTL:-/bin/launchctl}"
PLIST="$AGENTS_DIR/$LABEL.plist"
fail() { echo "ssh_tunnels_control=FAIL reason=$1" >&2; exit 1; }
owned() { [ -f "$PLIST" ] && plutil -extract BabymonitorManaged raw -o - "$PLIST" 2>/dev/null | grep -qx true; }
start() { owned || fail not_installed; "$LAUNCHCTL" bootstrap "$DOMAIN" "$PLIST" >/dev/null 2>&1 || true; "$LAUNCHCTL" kickstart -k "$DOMAIN/$LABEL" >/dev/null 2>&1 || fail kickstart_failed; echo 'ssh_tunnels_start=PASS'; }
stop() { owned || { echo 'ssh_tunnels_stop=PASS state=not_installed'; return; }; "$LAUNCHCTL" bootout "$DOMAIN/$LABEL" >/dev/null 2>&1 || true; echo 'ssh_tunnels_stop=PASS'; }
status() { owned || { echo 'ssh_process=not_installed'; return; }; if "$LAUNCHCTL" print "$DOMAIN/$LABEL" >/dev/null 2>&1; then echo 'ssh_process=present'; else echo 'ssh_process=absent'; fi; }
check() { shift; bash "$ROOT/scripts/tunnels/check.sh" "$@"; }
case "${1:-}" in start) start ;; stop) stop ;; restart) stop; start ;; status) status ;; check) check "$@" ;; *) fail 'usage_start_stop_restart_status_check' ;; esac
