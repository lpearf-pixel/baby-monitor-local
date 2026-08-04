#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ENV_FILE="$ROOT/runtime/alpha.env"
GO2RTC_PID="$ROOT/runtime/pids/go2rtc.pid"
API_PID="$ROOT/runtime/pids/api.pid"

if [[ ! -f "$ENV_FILE" || ! -x "$ROOT/.local/bin/go2rtc" || ! -x "$ROOT/.venv-alpha/bin/uvicorn" ]]; then
  echo "Alpha is not installed. Run tools/install_alpha_macos.sh first." >&2
  exit 1
fi

mkdir -p "$ROOT/runtime/logs" "$ROOT/runtime/pids"
set -a
# shellcheck disable=SC1090
source "$ENV_FILE"
set +a

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

start_if_stopped "$API_PID" \
  nohup "$ROOT/.venv-alpha/bin/uvicorn" apps.api.main:app \
  --app-dir "$ROOT" --host 127.0.0.1 --port 8080 \
  >"$ROOT/runtime/logs/api.log" 2>&1

for _ in {1..30}; do
  if curl -fsS http://127.0.0.1:8080/healthz >/dev/null 2>&1; then
    break
  fi
  sleep 1
done

if ! curl -fsS http://127.0.0.1:8080/healthz >/dev/null 2>&1; then
  echo "Dashboard did not become ready. Check runtime/logs/api.log" >&2
  exit 1
fi

cat <<EOF
Baby Monitor Local Alpha is running.

Dashboard: http://127.0.0.1:8080
Xiaomi setup: http://127.0.0.1:1984

For private remote access after installing Tailscale on the Mac and both Android phones:
  tailscale serve --bg 8080

Never use tailscale funnel and never add router port forwarding.
EOF
