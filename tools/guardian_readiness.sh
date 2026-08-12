#!/usr/bin/env bash
set -u

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ENV_FILE="$ROOT/runtime/alpha.env"
PYTHON="$ROOT/.venv-alpha/bin/python"
FAIL_COUNT=0

if [[ -f "$ENV_FILE" ]]; then
  set -a
  # shellcheck disable=SC1090
  source "$ENV_FILE" >/dev/null 2>&1
  set +a
fi

BABY_MONITOR_PORT="${BABY_MONITOR_PORT:-8080}"
BABY_MONITOR_SETTINGS_PATH="${BABY_MONITOR_SETTINGS_PATH:-$ROOT/runtime/settings.yaml}"

run_probe() {
  local name="$1"
  shift
  if [[ "${BABY_MONITOR_GUARDIAN_TEST_MODE:-0}" == "1" ]]; then
    local hook_dir="${BABY_MONITOR_GUARDIAN_HOOK_DIR:-}"
    if [[ -z "$hook_dir" || ! -x "$hook_dir/$name" ]]; then
      return 1
    fi
    "$hook_dir/$name" >/dev/null 2>&1
    return $?
  fi
  "$@" >/dev/null 2>&1
}

report_probe() {
  local name="$1"
  shift
  if run_probe "$name" "$@"; then
    echo "PASS start $name"
  else
    echo "FAIL start $name unavailable"
    FAIL_COUNT=$((FAIL_COUNT + 1))
  fi
}

probe_go2rtc() {
  curl -fsS --noproxy '*' --max-time 2 http://127.0.0.1:1984/api
}

probe_dashboard() {
  case "$BABY_MONITOR_PORT" in
    ''|*[!0-9]*) return 1 ;;
  esac
  curl -fsS --noproxy '*' --max-time 2 \
    "http://127.0.0.1:${BABY_MONITOR_PORT}/healthz"
}

probe_service() {
  local label="$1"
  local pid_file="$2"
  if [[ "$(uname -s)" == "Darwin" ]] && command -v launchctl >/dev/null 2>&1; then
    launchctl print "gui/$(id -u)/$label"
    return $?
  fi
  if [[ ! -f "$pid_file" ]]; then
    return 1
  fi
  local pid
  pid="$(cat "$pid_file" 2>/dev/null)" || return 1
  case "$pid" in
    ''|*[!0-9]*) return 1 ;;
  esac
  kill -0 "$pid" 2>/dev/null
}

probe_visual_worker() {
  probe_service "com.babymonitor.visual" "$ROOT/runtime/pids/visual.pid"
}

probe_environment_watchdog() {
  probe_service \
    "com.babymonitor.environment-watchdog" \
    "$ROOT/runtime/pids/environment-watchdog.pid"
}

probe_gauge_worker() {
  probe_service "com.babymonitor.gauge" "$ROOT/runtime/pids/gauge.pid"
}

probe_realtime_models() {
  "$PYTHON" "$ROOT/tools/realtime_models.py" check
}

probe_visual_metrics() {
  "$PYTHON" "$ROOT/tools/realtime_visual_status.py"
}

semantic_review_required() {
  if [[ ! -x "$PYTHON" || ! -f "$BABY_MONITOR_SETTINGS_PATH" ]]; then
    return 1
  fi
  "$PYTHON" -c \
    'import sys,yaml; data=yaml.safe_load(open(sys.argv[1], encoding="utf-8")) or {}; sys.exit(0 if bool((data.get("visual") or {}).get("enabled")) else 1)' \
    "$BABY_MONITOR_SETTINGS_PATH"
}

probe_ollama_bridge() {
  curl -fsS --noproxy '*' --max-time 2 http://127.0.0.1:11435/api/version
}

report_probe "go2rtc" probe_go2rtc
report_probe "dashboard" probe_dashboard
report_probe "visual_worker" probe_visual_worker
report_probe "environment_watchdog" probe_environment_watchdog
report_probe "gauge_worker" probe_gauge_worker
report_probe "realtime_models" probe_realtime_models
report_probe "visual_metrics" probe_visual_metrics

if run_probe "semantic_review_required" semantic_review_required; then
  report_probe "ollama_bridge" probe_ollama_bridge
else
  echo "PASS start ollama_bridge"
fi

if [[ "$FAIL_COUNT" -eq 0 ]]; then
  exit 0
fi
exit 1
