#!/bin/bash
set -eu
LABEL="com.babymonitor.ssh-tunnels"
DOMAIN="gui/$(id -u)"
AGENTS_DIR="${LAUNCH_AGENTS_DIR:-$HOME/Library/LaunchAgents}"
LAUNCHCTL="${LAUNCHCTL:-/bin/launchctl}"
PLIST="$AGENTS_DIR/$LABEL.plist"
if [ ! -f "$PLIST" ]; then echo 'ssh_tunnels_uninstall=PASS state=not_installed'; exit 0; fi
owns_plist() {
  plutil -extract BabymonitorManaged raw -o - "$PLIST" 2>/dev/null | grep -qx true || return 1
  plutil -extract Label raw -o - "$PLIST" 2>/dev/null | grep -qx "$LABEL" || return 1
  [ "$(plutil -extract ProgramArguments.0 raw -o - "$PLIST" 2>/dev/null || true)" = /usr/bin/ssh ] || return 1
  plutil -extract ProgramArguments.22 raw -o - "$PLIST" 2>/dev/null | grep -qx '127.0.0.1:1984:127.0.0.1:1984' || return 1
  plutil -extract ProgramArguments.24 raw -o - "$PLIST" 2>/dev/null | grep -Eq '^127\.0\.0\.1:11435:[A-Za-z0-9._:-]+:11434$' || return 1
}
owns_plist || { echo 'ssh_tunnels_uninstall=FAIL reason=not_owned' >&2; exit 1; }
if "$LAUNCHCTL" print "$DOMAIN/$LABEL" >/dev/null 2>&1; then
  "$LAUNCHCTL" bootout "$DOMAIN/$LABEL" >/dev/null 2>&1 || { echo 'ssh_tunnels_uninstall=FAIL reason=bootout_failed' >&2; exit 1; }
  "$LAUNCHCTL" print "$DOMAIN/$LABEL" >/dev/null 2>&1 && { echo 'ssh_tunnels_uninstall=FAIL reason=still_loaded' >&2; exit 1; }
fi
rm -f "$PLIST"
echo "ssh_tunnels_uninstall=PASS label=$LABEL"
