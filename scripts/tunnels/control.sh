#!/bin/bash
set -eu

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
LABEL="com.babymonitor.ssh-tunnels"
DOMAIN="gui/$(id -u)"
AGENTS_DIR="${LAUNCH_AGENTS_DIR:-$HOME/Library/LaunchAgents}"
LAUNCHCTL="${LAUNCHCTL:-/bin/launchctl}"
PS="${PS:-/bin/ps}"
PLIST="$AGENTS_DIR/$LABEL.plist"
fail() { echo "ssh_tunnels_control=FAIL reason=$1" >&2; exit 1; }
owned() {
  [ -f "$PLIST" ] || return 1
  plutil -extract BabymonitorManaged raw -o - "$PLIST" 2>/dev/null | grep -qx true || return 1
  plutil -extract Label raw -o - "$PLIST" 2>/dev/null | grep -qx "$LABEL" || return 1
  [ "$(plutil -extract ProgramArguments.0 raw -o - "$PLIST" 2>/dev/null || true)" = /usr/bin/ssh ] || return 1
  plutil -extract ProgramArguments.22 raw -o - "$PLIST" 2>/dev/null | grep -qx '127.0.0.1:1984:127.0.0.1:1984' || return 1
  plutil -extract ProgramArguments.24 raw -o - "$PLIST" 2>/dev/null | grep -Eq '^127\.0\.0\.1:11435:[A-Za-z0-9._:-]+:11434$' || return 1
}
start() { owned || fail not_installed; "$LAUNCHCTL" bootstrap "$DOMAIN" "$PLIST" >/dev/null 2>&1 || true; "$LAUNCHCTL" kickstart -k "$DOMAIN/$LABEL" >/dev/null 2>&1 || fail kickstart_failed; echo 'ssh_tunnels_start=PASS'; }
stop() {
  owned || { echo 'ssh_tunnels_stop=PASS state=not_installed'; return; }
  if ! "$LAUNCHCTL" print "$DOMAIN/$LABEL" >/dev/null 2>&1; then echo 'ssh_tunnels_stop=PASS state=not_loaded'; return; fi
  "$LAUNCHCTL" bootout "$DOMAIN/$LABEL" >/dev/null 2>&1 || fail bootout_failed
  "$LAUNCHCTL" print "$DOMAIN/$LABEL" >/dev/null 2>&1 && fail still_loaded
  echo 'ssh_tunnels_stop=PASS'
}
status() {
  owned || { echo 'launchd_registration=not_installed'; echo 'ssh_process=not_installed'; return; }
  if "$LAUNCHCTL" print "$DOMAIN/$LABEL" >/dev/null 2>&1; then echo 'launchd_registration=registered'; else echo 'launchd_registration=not_registered'; fi
  processes="$($PS -axo command= 2>/dev/null || true)"
  if printf '%s\n' "$processes" | grep -E '/usr/bin/ssh.*127\.0\.0\.1:1984:127\.0\.0\.1:1984.*127\.0\.0\.1:11435:127\.0\.0\.1:11434' >/dev/null 2>&1; then echo 'ssh_process=present'; else echo 'ssh_process=absent'; fi
}
check() { shift; bash "$ROOT/scripts/tunnels/check.sh" "$@"; }
case "${1:-}" in start) start ;; stop) stop ;; restart) stop; start ;; status) status ;; check) check "$@" ;; *) fail 'usage_start_stop_restart_status_check' ;; esac
