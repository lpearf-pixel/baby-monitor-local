#!/bin/bash
set -eu

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
PYTHON="$ROOT/.venv-alpha/bin/python"
STATUS="$ROOT/runtime/status/voice.json"
ACTION="${1:-}"

case "$ACTION" in
  start)
    not_before_epoch="$(date -u +%s)"
    start_attempt=0
    while ! bash "$ROOT/tools/start_alpha.sh" --voice-only; do
      start_attempt=$((start_attempt + 1))
      if [[ "$start_attempt" -ge 3 ]]; then
        echo "voice_listen=unavailable" >&2
        exit 1
      fi
      sleep 1
    done
    attempt=0
    while [[ "$attempt" -lt 30 ]]; do
      if "$PYTHON" "$ROOT/tools/voice_status.py" "$STATUS" \
        --require-mode listen_only --not-before-epoch "$not_before_epoch" \
        >/dev/null 2>&1; then
        exec "$PYTHON" "$ROOT/tools/voice_status.py" "$STATUS" \
          --require-mode listen_only --not-before-epoch "$not_before_epoch"
      fi
      attempt=$((attempt + 1))
      sleep 1
    done
    echo "voice_listen=unavailable" >&2
    exit 1
    ;;
  status)
    exec "$PYTHON" "$ROOT/tools/voice_status.py" "$STATUS" \
      --require-mode listen_only
    ;;
  stop)
    exec bash "$ROOT/tools/stop_alpha.sh" --voice-only
    ;;
  *)
    echo "voice_listen=invalid_action" >&2
    exit 2
    ;;
esac
