#!/bin/bash
set -u

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
export PATH="/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin"
export PYTHONUNBUFFERED=1

cd "$PROJECT_ROOT" || exit 1
exec "$PROJECT_ROOT/.venv-alpha/bin/python" -m tools.voice_asr_capture_macos terminal-job \
  > "$PROJECT_ROOT/runtime/status/voice-asr-capture.txt"
