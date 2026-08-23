#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ENV_FILE="$ROOT/runtime/alpha.env"
GO2RTC_PID="$ROOT/runtime/pids/go2rtc.pid"
API_PID="$ROOT/runtime/pids/api.pid"
GAUGE_PID="$ROOT/runtime/pids/gauge.pid"
WATCHDOG_PID="$ROOT/runtime/pids/environment-watchdog.pid"
VISUAL_PID="$ROOT/runtime/pids/visual.pid"
AUDIO_PID="$ROOT/runtime/pids/audio.pid"
VOICE_PID="$ROOT/runtime/pids/voice.pid"
GO2RTC_ONLY_RESTART=0
VOICE_ONLY_START=0
GO2RTC_LABEL="com.babymonitor.go2rtc"
GO2RTC_PLIST="$HOME/Library/LaunchAgents/${GO2RTC_LABEL}.plist"
GO2RTC_EXECUTABLE="$ROOT/.local/bin/go2rtc"
if [[ "$(uname -s)" == "Darwin" ]] && command -v launchctl >/dev/null 2>&1; then
  GO2RTC_EXECUTABLE="$ROOT/.local/Go2RTC.app/Contents/MacOS/go2rtc"
fi
GAUGE_LABEL="com.babymonitor.gauge"
GAUGE_PLIST="$HOME/Library/LaunchAgents/${GAUGE_LABEL}.plist"
WATCHDOG_LABEL="com.babymonitor.environment-watchdog"
WATCHDOG_PLIST="$HOME/Library/LaunchAgents/${WATCHDOG_LABEL}.plist"
VISUAL_LABEL="com.babymonitor.visual"
VISUAL_PLIST="$HOME/Library/LaunchAgents/${VISUAL_LABEL}.plist"
AUDIO_LABEL="com.babymonitor.audio"
AUDIO_PLIST="$HOME/Library/LaunchAgents/${AUDIO_LABEL}.plist"
VOICE_LABEL="com.babymonitor.voice"
VOICE_PLIST="$HOME/Library/LaunchAgents/${VOICE_LABEL}.plist"
TUNNEL_LABEL="com.babymonitor.ollama-tunnel"
TUNNEL_PLIST="$HOME/Library/LaunchAgents/${TUNNEL_LABEL}.plist"

if [[ "$#" -eq 1 && "$1" == "--go2rtc-only-restart" ]]; then
  GO2RTC_ONLY_RESTART=1
elif [[ "$#" -eq 1 && "$1" == "--voice-only" ]]; then
  VOICE_ONLY_START=1
elif [[ "$#" -ne 0 ]]; then
  echo "Usage: bash tools/start_alpha.sh [--go2rtc-only-restart|--voice-only]" >&2
  exit 2
fi

if [[ "$VOICE_ONLY_START" -eq 1 ]]; then
  if [[ "$(uname -s)" != "Darwin" ]] || ! command -v launchctl >/dev/null 2>&1 || [[ ! -f "$VOICE_PLIST" ]]; then
    echo "voice_start=FAIL reason=service_unavailable" >&2
    exit 1
  fi
  VOICE_DOMAIN="gui/$(id -u)"
  if ! launchctl print "${VOICE_DOMAIN}/${VOICE_LABEL}" >/dev/null 2>&1; then
    launchctl bootstrap "$VOICE_DOMAIN" "$VOICE_PLIST" >/dev/null
  else
    launchctl kickstart -k "${VOICE_DOMAIN}/${VOICE_LABEL}" >/dev/null
  fi
  echo "voice_start=PASS"
  exit 0
fi

if [[ ! -f "$ENV_FILE" || ! -x "$GO2RTC_EXECUTABLE" || ! -x "$ROOT/.venv-alpha/bin/uvicorn" ]]; then
  echo "Alpha is not installed. Run tools/install_alpha_macos.sh first." >&2
  exit 1
fi

mkdir -p "$ROOT/runtime/logs" "$ROOT/runtime/pids"
set -a
# shellcheck disable=SC1090
source "$ENV_FILE"
set +a

BABY_MONITOR_BIND_HOST="${BABY_MONITOR_BIND_HOST:-0.0.0.0}"
BABY_MONITOR_PORT="${BABY_MONITOR_PORT:-8080}"
BABY_MONITOR_SETTINGS_PATH="${BABY_MONITOR_SETTINGS_PATH:-$ROOT/runtime/settings.yaml}"
export BABY_MONITOR_SETTINGS_PATH

if [[ ! -f "$BABY_MONITOR_SETTINGS_PATH" ]]; then
  echo "Environment settings are missing. Run tools/install_alpha_macos.sh first." >&2
  exit 1
fi

if [[ ! "$BABY_MONITOR_PORT" =~ ^[0-9]+$ ]] || (( BABY_MONITOR_PORT < 1 || BABY_MONITOR_PORT > 65535 )); then
  echo "BABY_MONITOR_PORT must be an integer between 1 and 65535." >&2
  exit 1
fi

start_if_stopped() {
  local pidfile="$1"
  shift
  if [[ -f "$pidfile" ]]; then
    local old_pid
    old_pid="$(cat "$pidfile")"
    if kill -0 "$old_pid" 2>/dev/null; then
      return 0
    fi
    rm -f "$pidfile"
  fi
  "$@" &
  echo $! >"$pidfile"
}

go2rtc_api_ready() {
  curl -fsS --max-time 2 http://127.0.0.1:1984/api >/dev/null 2>&1
}

go2rtc_pid_matches() {
  local pid="$1"
  local command
  command="$(ps -ww -p "$pid" -o command= 2>/dev/null || true)"
  [[ "$command" == "$GO2RTC_EXECUTABLE -config $ROOT/runtime/go2rtc.yaml" ]]
}

go2rtc_pid_owns_api_listener() {
  local pid="$1"
  lsof -nP -a -p "$pid" -iTCP:1984 -sTCP:LISTEN >/dev/null 2>&1
}

go2rtc_pid_is_verified() {
  local pid
  [[ -f "$GO2RTC_PID" ]] || return 1
  pid="$(cat "$GO2RTC_PID")"
  kill -0 "$pid" 2>/dev/null && \
    go2rtc_pid_matches "$pid" && \
    go2rtc_pid_owns_api_listener "$pid"
}

ensure_direct_go2rtc_started() {
  if go2rtc_api_ready; then
    if go2rtc_pid_is_verified; then
      return 0
    fi
    echo "go2rtc pid identity mismatch" >&2
    return 1
  fi

  if [[ -f "$GO2RTC_PID" ]]; then
    local old_pid
    old_pid="$(cat "$GO2RTC_PID")"
    if kill -0 "$old_pid" 2>/dev/null; then
      if ! go2rtc_pid_matches "$old_pid"; then
        echo "go2rtc pid identity mismatch" >&2
        return 1
      fi
      kill "$old_pid" 2>/dev/null || true
      for _ in {1..20}; do
        kill -0 "$old_pid" 2>/dev/null || break
        sleep 0.25
      done
      kill -9 "$old_pid" 2>/dev/null || true
    fi
    rm -f "$GO2RTC_PID"
  fi

  start_if_stopped "$GO2RTC_PID" \
    nohup "$ROOT/.local/bin/go2rtc" -config "$ROOT/runtime/go2rtc.yaml" \
    >"$ROOT/runtime/logs/go2rtc.log" 2>&1
}

ensure_launchd_go2rtc_started() {
  local domain="gui/$(id -u)"
  local pid=""

  if launchctl print "${domain}/${GO2RTC_LABEL}" >/dev/null 2>&1; then
    pid="$(launchctl print "${domain}/${GO2RTC_LABEL}" 2>/dev/null | \
      awk '/^[[:space:]]*pid = [0-9]+/{print $3; exit}')"
    if [[ -n "$pid" ]] && ! go2rtc_pid_matches "$pid"; then
      echo "go2rtc launchd identity mismatch" >&2
      return 1
    fi
    if go2rtc_api_ready; then
      if [[ -n "$pid" ]] && go2rtc_pid_owns_api_listener "$pid"; then
        return 0
      fi
      echo "go2rtc launchd identity mismatch" >&2
      return 1
    fi
    if ! launchctl kickstart -k "${domain}/${GO2RTC_LABEL}" >/dev/null 2>&1; then
      echo "go2rtc launchd start failed" >&2
      return 1
    fi
    return 0
  fi

  if [[ ! -f "$GO2RTC_PLIST" ]]; then
    echo "go2rtc launchd service missing. Run make alpha-install." >&2
    return 1
  fi
  if ! launchctl bootstrap "$domain" "$GO2RTC_PLIST" >/dev/null 2>&1; then
    echo "go2rtc launchd start failed" >&2
    return 1
  fi
}

restart_launchd_go2rtc() {
  local domain="gui/$(id -u)"

  if launchctl print "${domain}/${GO2RTC_LABEL}" >/dev/null 2>&1; then
    if ! launchctl kickstart -k "${domain}/${GO2RTC_LABEL}" >/dev/null 2>&1; then
      echo "go2rtc launchd start failed" >&2
      return 1
    fi
    return 0
  fi

  if [[ ! -f "$GO2RTC_PLIST" ]]; then
    echo "go2rtc launchd service missing. Run make alpha-install." >&2
    return 1
  fi
  if ! launchctl bootstrap "$domain" "$GO2RTC_PLIST" >/dev/null 2>&1; then
    echo "go2rtc launchd start failed" >&2
    return 1
  fi
}

ensure_go2rtc_started() {
  if [[ "$(uname -s)" == "Darwin" ]] && command -v launchctl >/dev/null 2>&1; then
    ensure_launchd_go2rtc_started
  else
    ensure_direct_go2rtc_started
  fi
}

find_lan_ipv4() {
  local interface
  interface="$(route -n get default 2>/dev/null | awk '/interface:/{print $2; exit}')"
  if [[ -n "$interface" ]]; then
    ipconfig getifaddr "$interface" 2>/dev/null || true
  fi
}

if [[ "$GO2RTC_ONLY_RESTART" -eq 1 ]]; then
  if [[ "$(uname -s)" != "Darwin" ]] || ! command -v launchctl >/dev/null 2>&1; then
    echo "go2rtc-only restart requires macOS launchd" >&2
    exit 1
  fi
  restart_launchd_go2rtc
else
  ensure_go2rtc_started
fi

for _ in {1..30}; do
  if go2rtc_api_ready; then
    break
  fi
  sleep 1
done

if ! go2rtc_api_ready; then
  echo "go2rtc did not become ready. Check runtime/logs/go2rtc.log" >&2
  exit 1
fi

if [[ "$(uname -s)" == "Darwin" ]] && command -v launchctl >/dev/null 2>&1; then
  GO2RTC_DOMAIN="gui/$(id -u)"
  GO2RTC_LAUNCHD_PID="$(launchctl print "${GO2RTC_DOMAIN}/${GO2RTC_LABEL}" 2>/dev/null | \
    awk '/^[[:space:]]*pid = [0-9]+/{print $3; exit}')"
  if [[ -z "$GO2RTC_LAUNCHD_PID" ]] || \
    ! go2rtc_pid_matches "$GO2RTC_LAUNCHD_PID" || \
    ! go2rtc_pid_owns_api_listener "$GO2RTC_LAUNCHD_PID"; then
    echo "go2rtc launchd identity mismatch" >&2
    exit 1
  fi
fi

if [[ "$GO2RTC_ONLY_RESTART" -eq 1 ]]; then
  echo "go2rtc_restart=PASS"
  exit 0
fi

if [[ "$(uname -s)" == "Darwin" ]] && command -v launchctl >/dev/null 2>&1; then
  GAUGE_DOMAIN="gui/$(id -u)"
  if [[ -f "$TUNNEL_PLIST" ]]; then
    if ! launchctl print "${GAUGE_DOMAIN}/${TUNNEL_LABEL}" >/dev/null 2>&1; then
      launchctl bootstrap "$GAUGE_DOMAIN" "$TUNNEL_PLIST"
    fi
  fi
  if [[ -f "$VISUAL_PLIST" ]]; then
    if ! launchctl print "${GAUGE_DOMAIN}/${VISUAL_LABEL}" >/dev/null 2>&1; then
      launchctl bootstrap "$GAUGE_DOMAIN" "$VISUAL_PLIST"
    fi
  fi
  if [[ -f "$AUDIO_PLIST" ]]; then
    if ! launchctl print "${GAUGE_DOMAIN}/${AUDIO_LABEL}" >/dev/null 2>&1; then
      launchctl bootstrap "$GAUGE_DOMAIN" "$AUDIO_PLIST"
    fi
  fi
  if [[ -f "$VOICE_PLIST" ]]; then
    if ! launchctl print "${GAUGE_DOMAIN}/${VOICE_LABEL}" >/dev/null 2>&1; then
      launchctl bootstrap "$GAUGE_DOMAIN" "$VOICE_PLIST"
    fi
  fi
  if ! launchctl print "${GAUGE_DOMAIN}/${WATCHDOG_LABEL}" >/dev/null 2>&1; then
    launchctl bootstrap "$GAUGE_DOMAIN" "$WATCHDOG_PLIST"
  fi
  if ! launchctl print "${GAUGE_DOMAIN}/${GAUGE_LABEL}" >/dev/null 2>&1; then
    launchctl bootstrap "$GAUGE_DOMAIN" "$GAUGE_PLIST"
  fi
else
  start_if_stopped "$VISUAL_PID" \
    nohup "$ROOT/.venv-alpha/bin/python" "$ROOT/tools/run_visual_worker.py" \
    --settings "$BABY_MONITOR_SETTINGS_PATH" --env-file "$ENV_FILE" \
    >"$ROOT/runtime/logs/visual.log" 2>&1
  start_if_stopped "$AUDIO_PID" \
    nohup "$ROOT/.venv-alpha/bin/python" "$ROOT/tools/run_audio_worker.py" \
    --settings "$BABY_MONITOR_SETTINGS_PATH" \
    >"$ROOT/runtime/logs/audio.log" 2>&1
  start_if_stopped "$VOICE_PID" \
    nohup "$ROOT/.venv-alpha/bin/python" "$ROOT/tools/run_voice_worker.py" \
    --settings "$BABY_MONITOR_SETTINGS_PATH" \
    >"$ROOT/runtime/logs/voice.log" 2>&1
  start_if_stopped "$WATCHDOG_PID" \
    nohup "$ROOT/.venv-alpha/bin/python" "$ROOT/tools/run_environment_watchdog.py" \
    --settings "$BABY_MONITOR_SETTINGS_PATH" --env-file "$ENV_FILE" \
    >"$ROOT/runtime/logs/environment-watchdog.log" 2>&1
  start_if_stopped "$GAUGE_PID" \
    nohup "$ROOT/.venv-alpha/bin/python" "$ROOT/tools/run_gauge_worker.py" \
    --settings "$BABY_MONITOR_SETTINGS_PATH" --env-file "$ENV_FILE" \
    >"$ROOT/runtime/logs/gauge.log" 2>&1
fi

start_if_stopped "$API_PID" \
  nohup "$ROOT/.venv-alpha/bin/uvicorn" apps.api.main:app \
  --app-dir "$ROOT" --host "${BABY_MONITOR_BIND_HOST}" --port "${BABY_MONITOR_PORT}" \
  --no-proxy-headers \
  >"$ROOT/runtime/logs/api.log" 2>&1

for _ in {1..30}; do
  if curl -fsS "http://127.0.0.1:${BABY_MONITOR_PORT}/healthz" >/dev/null 2>&1; then
    break
  fi
  sleep 1
done

if ! curl -fsS "http://127.0.0.1:${BABY_MONITOR_PORT}/healthz" >/dev/null 2>&1; then
  echo "Dashboard did not become ready. Check runtime/logs/api.log" >&2
  exit 1
fi

LAN_IP="$(find_lan_ipv4)"

cat <<EOF
Baby Monitor Local Alpha is running.

Local Dashboard: http://127.0.0.1:${BABY_MONITOR_PORT}
EOF

if [[ -n "$LAN_IP" ]]; then
  cat <<EOF
LAN Dashboard: http://${LAN_IP}:${BABY_MONITOR_PORT}

From the M2 Mac, open the LAN Dashboard URL directly.
For Xiaomi setup from the M2 Mac, keep go2rtc private and create an SSH tunnel:
  ssh -L 1984:127.0.0.1:1984 <i9-user>@${LAN_IP}
Then open http://127.0.0.1:1984 on the M2 Mac.
EOF
else
  cat <<EOF
LAN Dashboard: unable to detect automatically. Run on the i9 Mac:
  ipconfig getifaddr en0
  ipconfig getifaddr en1
Then open http://<detected-ip>:${BABY_MONITOR_PORT} from the M2 Mac.
EOF
fi

cat <<EOF

Xiaomi setup remains private on the i9 Mac: http://127.0.0.1:1984

Future private external access with Tailscale:
  tailscale serve --bg http://127.0.0.1:${BABY_MONITOR_PORT}
  tailscale serve status

Never use tailscale funnel and never add router port forwarding.
EOF
