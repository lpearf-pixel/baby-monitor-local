#!/bin/bash
set -Eeuo pipefail

ROOT="$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)"
PYTHON="${PYTHON:-$ROOT/.venv-alpha/bin/python}"
DOMAIN="gui/$(id -u)"
LABEL="com.babymonitor.visual"
SERVICE="$DOMAIN/$LABEL"
PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"
WORKER_STOPPED=0

restore_worker() {
  status=$?
  trap - EXIT HUP INT TERM
  if [[ "$WORKER_STOPPED" -eq 1 ]]; then
    if ! launchctl print "$SERVICE" >/dev/null 2>&1; then
      if ! launchctl bootstrap "$DOMAIN" "$PLIST"; then
        printf '%s\n' "diagnostic=FAIL reason=visual_worker_restore_failed"
        exit 3
      fi
    fi
    if ! launchctl kickstart -k "$SERVICE"; then
      printf '%s\n' "diagnostic=FAIL reason=visual_worker_restore_failed"
      exit 3
    fi
  fi
  exit "$status"
}

trap restore_worker EXIT
trap 'exit 129' HUP
trap 'exit 130' INT
trap 'exit 143' TERM

if [[ "$(uname -s)" != "Darwin" ]]; then
  printf '%s\n' "diagnostic=FAIL reason=macos_required"
  exit 2
fi
if [[ ! -x "$PYTHON" || ! -f "$PLIST" ]]; then
  printf '%s\n' "diagnostic=FAIL reason=diagnostic_unavailable"
  exit 2
fi
if ! launchctl print "$SERVICE" >/dev/null 2>&1; then
  printf '%s\n' "diagnostic=FAIL reason=visual_worker_offline"
  exit 2
fi

launchctl bootout "$SERVICE"
WORKER_STOPPED=1

"$PYTHON" "$ROOT/tools/realtime_visual_diagnostic.py" \
  --settings "$ROOT/runtime/settings.yaml"
