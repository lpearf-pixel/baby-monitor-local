#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ENV_FILE="$ROOT/runtime/alpha.env"
GO2RTC_PID="$ROOT/runtime/pids/go2rtc.pid"
API_PID="$ROOT/runtime/pids/api.pid"
GAUGE_PID="$ROOT/runtime/pids/gauge.pid"

if [[ ! -f "$ENV_FILE" || ! -x "$ROOT/.local/bin/go2rtc" || ! -x "$ROOT/.venv-alpha/bin/uvicorn" ]]; then
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

find_lan_ipv4() {
  local interface
  interface="$(route -n get default 2>/dev/null | awk '/interface:/{print $2; exit}')"
  if [[ -n "$interface" ]]; then
    ipconfig getifaddr "$interface" 2>/dev/null || true
  fi
}

start_if_stopped "$GO2RTC_PID" \
  nohup "$ROOT/.local/bin/go2rtc" -config "$ROOT/runtime/go2rtc.yaml" \
  >"$ROOT/runtime/logs/go2rtc.log" 2>&1

for _ in {1..30}; do
  if curl -fsS http://127.0.0.1:1984/api >/dev/null 2>&1; then
    break
  fi
  sleep 1
done

if ! curl -fsS http://127.0.0.1:1984/api >/dev/null 2>&1; then
  echo "go2rtc did not become ready. Check runtime/logs/go2rtc.log" >&2
  exit 1
fi

start_if_stopped "$GAUGE_PID" \
  nohup "$ROOT/.venv-alpha/bin/python" "$ROOT/tools/run_gauge_worker.py" \
  --settings "$BABY_MONITOR_SETTINGS_PATH" --env-file "$ENV_FILE" \
  >"$ROOT/runtime/logs/gauge.log" 2>&1

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
