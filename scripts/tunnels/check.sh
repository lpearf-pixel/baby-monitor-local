#!/bin/bash
set -eu

LABEL="com.babymonitor.ssh-tunnels"
DOMAIN="gui/$(id -u)"
AGENTS_DIR="${LAUNCH_AGENTS_DIR:-$HOME/Library/LaunchAgents}"
LAUNCHCTL="${LAUNCHCTL:-/bin/launchctl}"
LSOF="${LSOF:-/usr/sbin/lsof}"
CURL="${CURL:-/usr/bin/curl}"
SSH="${SSH:-/usr/bin/ssh}"
TARGET=""
IDENTITY=""
fail() { echo "ssh_tunnels_check=FAIL reason=$1" >&2; exit 64; }
usage() { echo "usage: check.sh --target USER@HOST --identity PATH" >&2; exit 64; }
while [ "$#" -gt 0 ]; do
  case "$1" in
    --target) [ "$#" -ge 2 ] || usage; TARGET="$2"; shift 2 ;;
    --identity) [ "$#" -ge 2 ] || usage; IDENTITY="$2"; shift 2 ;;
    *) usage ;;
  esac
done
[ -n "$TARGET" ] && [ -n "$IDENTITY" ] || usage
[ -f "$IDENTITY" ] || fail identity_missing

PLIST="$AGENTS_DIR/$LABEL.plist"
if [ ! -f "$PLIST" ]; then
  echo 'ssh_process=not_installed'
else
  if "$LAUNCHCTL" print "$DOMAIN/$LABEL" >/dev/null 2>&1; then echo 'ssh_process=present'; else echo 'ssh_process=absent'; fi
fi

local_listener="$($LSOF -nP -iTCP:1984 -sTCP:LISTEN 2>/dev/null || true)"
if [ -n "$local_listener" ]; then echo 'm2_port_1984=listening'; else echo 'm2_port_1984=not_listening'; fi
if "$CURL" -fsS --noproxy '*' --max-time 2 http://127.0.0.1:1984/api/streams >/dev/null 2>&1; then
  echo 'go2rtc_api=reachable'
else
  echo 'go2rtc_api=unreachable'
fi

remote_port=""
remote_port_status=0
set +e
remote_port="$($SSH -o BatchMode=yes -o ConnectTimeout=8 -o IdentitiesOnly=yes -o StrictHostKeyChecking=yes -i "$IDENTITY" "$TARGET" /usr/sbin/lsof -nP -iTCP:11435 -sTCP:LISTEN 2>/dev/null)"
remote_port_status=$?
set -e
if [ "$remote_port_status" -ne 0 ]; then
  echo 'i9_port_11435=unknown'
elif [ -n "$remote_port" ]; then
  echo 'i9_port_11435=listening'
else
  echo 'i9_port_11435=not_listening'
fi

if "$SSH" -o BatchMode=yes -o ConnectTimeout=8 -o IdentitiesOnly=yes -o StrictHostKeyChecking=yes -i "$IDENTITY" "$TARGET" /usr/bin/curl -fsS --noproxy '*' --max-time 2 http://127.0.0.1:11435/api/tags >/dev/null 2>&1; then
  echo 'ollama_api=reachable'
else
  echo 'ollama_api=unreachable'
fi
