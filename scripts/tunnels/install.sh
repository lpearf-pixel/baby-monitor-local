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
owns_plist() {
  [ -f "$PLIST" ] || return 1
  plutil -extract BabymonitorManaged raw -o - "$PLIST" 2>/dev/null | grep -qx true || return 1
  plutil -extract Label raw -o - "$PLIST" 2>/dev/null | grep -qx "$LABEL" || return 1
  [ "$(plutil -extract ProgramArguments.0 raw -o - "$PLIST" 2>/dev/null || true)" = /usr/bin/ssh ] || return 1
  plutil -extract ProgramArguments.1 raw -o - "$PLIST" 2>/dev/null | grep -qx -- -N || return 1
  plutil -extract ProgramArguments.22 raw -o - "$PLIST" 2>/dev/null | grep -qx '127.0.0.1:1984:127.0.0.1:1984' || return 1
  plutil -extract ProgramArguments.24 raw -o - "$PLIST" 2>/dev/null | grep -qx '127.0.0.1:11435:127.0.0.1:11434' || return 1
}
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
  owns_plist || fail existing_plist_not_owned
fi

if "$LAUNCHCTL" print "$DOMAIN/com.babymonitor.ollama-tunnel" >/dev/null 2>&1; then
  fail legacy_tunnel_loaded
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
BACKUP="$AGENTS_DIR/.$LABEL.$$.backup"
HAD_OLD=0
WAS_LOADED=0
trap 'rm -f "$TMP" "$BACKUP"' EXIT HUP INT TERM
bash "$ROOT/scripts/tunnels/render.sh" \
  --template "$ROOT/config/launchd/$LABEL.plist.template" --output "$TMP" \
  --target "$TARGET" --identity "$IDENTITY" --log-dir "$LOG_DIR"
plutil -lint "$TMP" >/dev/null 2>&1 || fail rendered_plist_invalid
chmod 600 "$TMP"
if [ -f "$PLIST" ]; then
  cp "$PLIST" "$BACKUP" || fail backup_failed
  chmod 600 "$BACKUP"
  HAD_OLD=1
fi
if "$LAUNCHCTL" print "$DOMAIN/$LABEL" >/dev/null 2>&1; then
  WAS_LOADED=1
  "$LAUNCHCTL" bootout "$DOMAIN/$LABEL" >/dev/null 2>&1 || fail owned_bootout_failed
fi
rollback() {
  rm -f "$PLIST"
  if [ "$HAD_OLD" -eq 1 ]; then
    mv "$BACKUP" "$PLIST" || return 1
    "$LAUNCHCTL" bootstrap "$DOMAIN" "$PLIST" >/dev/null 2>&1 || return 1
    [ "$WAS_LOADED" -eq 1 ] && "$LAUNCHCTL" kickstart -k "$DOMAIN/$LABEL" >/dev/null 2>&1 || true
  fi
}
if ! mv "$TMP" "$PLIST"; then
  rollback || fail replace_failed_rollback_failed
  fail replace_failed_rolled_back
fi
if ! "$LAUNCHCTL" bootstrap "$DOMAIN" "$PLIST" >/dev/null 2>&1; then
  rollback || fail bootstrap_failed_rollback_failed
  fail bootstrap_failed_rolled_back
fi
if ! "$LAUNCHCTL" kickstart -k "$DOMAIN/$LABEL" >/dev/null 2>&1; then
  rollback || fail kickstart_failed_rollback_failed
  fail kickstart_failed_rolled_back
fi
echo "ssh_tunnels_install=PASS label=$LABEL"
