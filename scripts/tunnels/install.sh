#!/bin/bash
set -eu

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
LABEL="com.babymonitor.ssh-tunnels"
DOMAIN="gui/$(id -u)"
AGENTS_DIR="${LAUNCH_AGENTS_DIR:-$HOME/Library/LaunchAgents}"
LAUNCHCTL="${LAUNCHCTL:-/bin/launchctl}"
LSOF="${LSOF:-/usr/sbin/lsof}"
SSH="${SSH:-/usr/bin/ssh}"
TARGET=""
IDENTITY=""
LOG_DIR="${ROOT}/runtime/logs"

fail() { echo "ssh_tunnels_install=FAIL reason=$1" >&2; exit 1; }
usage() { echo "usage: install.sh --target USER@192.168.2.141 --identity PATH [--log-dir PATH]" >&2; exit 64; }
while [ "$#" -gt 0 ]; do
  case "$1" in
    --target) [ "$#" -ge 2 ] || usage; TARGET="$2"; shift 2 ;;
    --identity) [ "$#" -ge 2 ] || usage; IDENTITY="$2"; shift 2 ;;
    --log-dir) [ "$#" -ge 2 ] || usage; LOG_DIR="$2"; shift 2 ;;
    *) usage ;;
  esac
done
[ "$(uname -s)" = "Darwin" ] || fail macos_required
[ -n "$TARGET" ] && [ -n "$IDENTITY" ] || usage
case "$TARGET" in *'@192.168.2.141') ;; *) fail target_must_be_i9_192_168_2_141 ;; esac
[ -f "$IDENTITY" ] || fail identity_missing
[ "$(stat -f '%Lp' "$IDENTITY" 2>/dev/null || true)" = 600 ] || fail identity_not_0600

PLIST="$AGENTS_DIR/$LABEL.plist"
mkdir -p "$AGENTS_DIR" "$LOG_DIR"
chmod 700 "$LOG_DIR"
if [ -e "$PLIST" ]; then
  plutil -extract BabymonitorManaged raw -o - "$PLIST" 2>/dev/null | grep -qx true || fail existing_plist_not_owned
fi

local_listener="$($LSOF -nP -iTCP:1984 -sTCP:LISTEN 2>/dev/null || true)"
[ -z "$local_listener" ] || fail m2_port_1984_occupied
remote_listener="$($SSH -o BatchMode=yes -o ConnectTimeout=8 -o IdentitiesOnly=yes -i "$IDENTITY" "$TARGET" /usr/sbin/lsof -nP -iTCP:11435 -sTCP:LISTEN 2>/dev/null || true)"
if [ -z "$remote_listener" ]; then
  "$SSH" -o BatchMode=yes -o ConnectTimeout=8 -o IdentitiesOnly=yes -i "$IDENTITY" "$TARGET" /usr/bin/true >/dev/null 2>&1 || fail remote_i9_unreachable
else
  fail i9_port_11435_occupied
fi

TMP="$AGENTS_DIR/.$LABEL.$$.plist"
trap 'rm -f "$TMP"' EXIT HUP INT TERM
bash "$ROOT/scripts/tunnels/render.sh" \
  --template "$ROOT/config/launchd/$LABEL.plist.template" --output "$TMP" \
  --target "$TARGET" --identity "$IDENTITY" --log-dir "$LOG_DIR"
plutil -lint "$TMP" >/dev/null 2>&1 || fail rendered_plist_invalid
chmod 600 "$TMP"
mv "$TMP" "$PLIST"
if "$LAUNCHCTL" print "$DOMAIN/$LABEL" >/dev/null 2>&1; then
  "$LAUNCHCTL" bootout "$DOMAIN/$LABEL" >/dev/null 2>&1 || fail owned_bootout_failed
fi
"$LAUNCHCTL" bootstrap "$DOMAIN" "$PLIST" >/dev/null 2>&1 || fail bootstrap_failed
"$LAUNCHCTL" kickstart -k "$DOMAIN/$LABEL" >/dev/null 2>&1 || fail kickstart_failed
echo "ssh_tunnels_install=PASS label=$LABEL"
