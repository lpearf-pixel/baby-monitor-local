#!/bin/bash
set -u

ROOT="$(cd "$(dirname "$0")/.." && pwd -P)"
PYTHON="$ROOT/.venv-alpha/bin/python"
STATUS_DIR="$ROOT/runtime/status"
STATUS_FILE="$STATUS_DIR/voice-keychain-check.txt"

if [[ ! -x "$PYTHON" || -L "$ROOT/runtime" || -L "$STATUS_DIR" ]]; then
  printf '%s\n' "key_state=unavailable"
  exit 1
fi

umask 077
mkdir -p "$STATUS_DIR" || exit 1
cd "$ROOT" || exit 1
"$PYTHON" -m tools.voice_keychain_migrate >"$STATUS_FILE" 2>&1
result=$?
cat "$STATUS_FILE"
exit "$result"
