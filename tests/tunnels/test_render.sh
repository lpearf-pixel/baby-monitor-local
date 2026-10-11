#!/bin/bash
set -eu

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
TMP="$(mktemp -d "${TMPDIR:-/tmp}/ssh-tunnel-render.XXXXXX")"
trap 'rm -rf "$TMP"' EXIT HUP INT TERM
IDENTITY="$TMP/key"
LOG_DIR="$TMP/logs"
printf 'synthetic-key' >"$IDENTITY"
chmod 600 "$IDENTITY"
mkdir -p "$LOG_DIR"

bash "$ROOT/scripts/tunnels/render.sh" \
  --template "$ROOT/config/launchd/com.babymonitor.ssh-tunnels.plist.template" \
  --output "$TMP/rendered.plist" \
  --target "kandysmith@192.168.2.141" \
  --identity "$IDENTITY" \
  --log-dir "$LOG_DIR"

grep -q 'com.babymonitor.ssh-tunnels' "$TMP/rendered.plist"
grep -q '127.0.0.1:1984:127.0.0.1:1984' "$TMP/rendered.plist"
grep -q '127.0.0.1:11435:127.0.0.1:11434' "$TMP/rendered.plist"
grep -q 'BatchMode=yes' "$TMP/rendered.plist"
grep -q 'ExitOnForwardFailure=yes' "$TMP/rendered.plist"
grep -q 'ConnectTimeout=8' "$TMP/rendered.plist"
grep -q 'ServerAliveInterval=15' "$TMP/rendered.plist"
grep -q 'ServerAliveCountMax=3' "$TMP/rendered.plist"
grep -q 'ThrottleInterval' "$TMP/rendered.plist"
if bash "$ROOT/scripts/tunnels/render.sh" \
  --template "$ROOT/config/launchd/com.babymonitor.ssh-tunnels.plist.template" \
  --output "$TMP/bad.plist" --target '' --identity "$IDENTITY" --log-dir "$LOG_DIR"; then
  echo 'expected empty target rejection' >&2
  exit 1
fi
if bash "$ROOT/scripts/tunnels/render.sh" \
  --template "$ROOT/config/launchd/com.babymonitor.ssh-tunnels.plist.template" \
  --output "$TMP/bad2.plist" --target 'kandysmith@192.168.2.141' \
  --identity "$TMP/missing-key" --log-dir "$LOG_DIR"; then
  echo 'expected missing identity rejection' >&2
  exit 1
fi

echo 'test_render=PASS'
