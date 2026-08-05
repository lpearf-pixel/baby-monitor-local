#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
GAUGE_LABEL="com.babymonitor.gauge"
WATCHDOG_LABEL="com.babymonitor.environment-watchdog"

stop_pidfile() {
  local pidfile="$1"
  if [[ ! -f "$pidfile" ]]; then
    return 0
  fi
  local pid
  pid="$(cat "$pidfile")"
  if kill -0 "$pid" 2>/dev/null; then
    kill "$pid"
    for _ in {1..20}; do
      kill -0 "$pid" 2>/dev/null || break
      sleep 0.25
    done
    kill -9 "$pid" 2>/dev/null || true
  fi
  rm -f "$pidfile"
}

stop_pidfile "$ROOT/runtime/pids/api.pid"
if [[ "$(uname -s)" == "Darwin" ]] && command -v launchctl >/dev/null 2>&1; then
  GAUGE_DOMAIN="gui/$(id -u)"
  if launchctl print "${GAUGE_DOMAIN}/${GAUGE_LABEL}" >/dev/null 2>&1; then
    launchctl bootout "${GAUGE_DOMAIN}/${GAUGE_LABEL}"
  fi
  if launchctl print "${GAUGE_DOMAIN}/${WATCHDOG_LABEL}" >/dev/null 2>&1; then
    launchctl bootout "${GAUGE_DOMAIN}/${WATCHDOG_LABEL}"
  fi
fi
stop_pidfile "$ROOT/runtime/pids/gauge.pid"
stop_pidfile "$ROOT/runtime/pids/environment-watchdog.pid"
stop_pidfile "$ROOT/runtime/pids/go2rtc.pid"

echo "Baby Monitor Local Alpha stopped."
