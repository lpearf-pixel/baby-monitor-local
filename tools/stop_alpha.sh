#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
GO2RTC_LABEL="com.babymonitor.go2rtc"
GAUGE_LABEL="com.babymonitor.gauge"
WATCHDOG_LABEL="com.babymonitor.environment-watchdog"
VISUAL_LABEL="com.babymonitor.visual"
AUDIO_LABEL="com.babymonitor.audio"
VOICE_LABEL="com.babymonitor.voice"
VOICE_ASR_OPERATOR_LABEL="com.babymonitor.voice-asr-operator"
TUNNEL_LABEL="com.babymonitor.ollama-tunnel"
VOICE_ONLY_STOP=0

wait_voice_jobs_unloaded() {
  local domain="$1"
  local voice_target="${domain}/${VOICE_LABEL}"
  local operator_target="${domain}/${VOICE_ASR_OPERATOR_LABEL}"
  local voice_loaded
  local operator_loaded
  local attempt

  for attempt in {1..20}; do
    voice_loaded=0
    operator_loaded=0
    if launchctl print "$voice_target" >/dev/null 2>&1; then
      voice_loaded=1
    fi
    if launchctl print "$operator_target" >/dev/null 2>&1; then
      operator_loaded=1
    fi
    if [[ "$voice_loaded" -eq 0 && "$operator_loaded" -eq 0 ]]; then
      return 0
    fi
    sleep 0.1
  done
  return 1
}

if [[ "$#" -eq 1 && "$1" == "--voice-only" ]]; then
  VOICE_ONLY_STOP=1
elif [[ "$#" -ne 0 ]]; then
  echo "Usage: bash tools/stop_alpha.sh [--voice-only]" >&2
  exit 2
fi

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

if [[ "$VOICE_ONLY_STOP" -eq 1 ]]; then
  if [[ "$(uname -s)" == "Darwin" ]] && command -v launchctl >/dev/null 2>&1; then
    VOICE_DOMAIN="gui/$(id -u)"
    if launchctl print "${VOICE_DOMAIN}/${VOICE_LABEL}" >/dev/null 2>&1; then
      launchctl bootout "${VOICE_DOMAIN}/${VOICE_LABEL}" >/dev/null
    fi
    if launchctl print "${VOICE_DOMAIN}/${VOICE_ASR_OPERATOR_LABEL}" >/dev/null 2>&1; then
      launchctl bootout "${VOICE_DOMAIN}/${VOICE_ASR_OPERATOR_LABEL}" >/dev/null
    fi
    if ! wait_voice_jobs_unloaded "$VOICE_DOMAIN"; then
      echo "voice_stop=FAIL reason=service_stop_timeout" >&2
      exit 1
    fi
  else
    stop_pidfile "$ROOT/runtime/pids/voice.pid"
  fi
  echo "voice_stop=PASS"
  exit 0
fi

stop_pidfile "$ROOT/runtime/pids/api.pid"
if [[ "$(uname -s)" == "Darwin" ]] && command -v launchctl >/dev/null 2>&1; then
  GAUGE_DOMAIN="gui/$(id -u)"
  if launchctl print "${GAUGE_DOMAIN}/${GO2RTC_LABEL}" >/dev/null 2>&1; then
    launchctl bootout "${GAUGE_DOMAIN}/${GO2RTC_LABEL}"
  fi
  if launchctl print "${GAUGE_DOMAIN}/${VISUAL_LABEL}" >/dev/null 2>&1; then
    launchctl bootout "${GAUGE_DOMAIN}/${VISUAL_LABEL}"
  fi
  if launchctl print "${GAUGE_DOMAIN}/${AUDIO_LABEL}" >/dev/null 2>&1; then
    launchctl bootout "${GAUGE_DOMAIN}/${AUDIO_LABEL}"
  fi
  if launchctl print "${GAUGE_DOMAIN}/${VOICE_LABEL}" >/dev/null 2>&1; then
    launchctl bootout "${GAUGE_DOMAIN}/${VOICE_LABEL}"
  fi
  if launchctl print "${GAUGE_DOMAIN}/${VOICE_ASR_OPERATOR_LABEL}" >/dev/null 2>&1; then
    launchctl bootout "${GAUGE_DOMAIN}/${VOICE_ASR_OPERATOR_LABEL}"
  fi
  if launchctl print "${GAUGE_DOMAIN}/${TUNNEL_LABEL}" >/dev/null 2>&1; then
    launchctl bootout "${GAUGE_DOMAIN}/${TUNNEL_LABEL}"
  fi
  if launchctl print "${GAUGE_DOMAIN}/${GAUGE_LABEL}" >/dev/null 2>&1; then
    launchctl bootout "${GAUGE_DOMAIN}/${GAUGE_LABEL}"
  fi
  if launchctl print "${GAUGE_DOMAIN}/${WATCHDOG_LABEL}" >/dev/null 2>&1; then
    launchctl bootout "${GAUGE_DOMAIN}/${WATCHDOG_LABEL}"
  fi
fi
stop_pidfile "$ROOT/runtime/pids/visual.pid"
stop_pidfile "$ROOT/runtime/pids/audio.pid"
stop_pidfile "$ROOT/runtime/pids/voice.pid"
stop_pidfile "$ROOT/runtime/pids/gauge.pid"
stop_pidfile "$ROOT/runtime/pids/environment-watchdog.pid"
if [[ "$(uname -s)" != "Darwin" ]] || ! command -v launchctl >/dev/null 2>&1; then
  stop_pidfile "$ROOT/runtime/pids/go2rtc.pid"
fi

echo "Baby Monitor Local Alpha stopped."
