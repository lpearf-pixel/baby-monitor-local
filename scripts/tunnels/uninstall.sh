#!/bin/bash
set -eu
LABEL="com.babymonitor.ssh-tunnels"
DOMAIN="gui/$(id -u)"
AGENTS_DIR="${LAUNCH_AGENTS_DIR:-$HOME/Library/LaunchAgents}"
LAUNCHCTL="${LAUNCHCTL:-/bin/launchctl}"
PLIST="$AGENTS_DIR/$LABEL.plist"
if [ ! -f "$PLIST" ]; then echo 'ssh_tunnels_uninstall=PASS state=not_installed'; exit 0; fi
plutil -extract BabymonitorManaged raw -o - "$PLIST" 2>/dev/null | grep -qx true || { echo 'ssh_tunnels_uninstall=FAIL reason=not_owned' >&2; exit 1; }
"$LAUNCHCTL" bootout "$DOMAIN/$LABEL" >/dev/null 2>&1 || true
rm -f "$PLIST"
echo "ssh_tunnels_uninstall=PASS label=$LABEL"
