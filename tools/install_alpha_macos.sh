#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
GO2RTC_VERSION="1.9.14"

if [[ "$(uname -s)" != "Darwin" || "$(uname -m)" != "x86_64" ]]; then
  echo "This installer is for Intel macOS (x86_64)." >&2
  exit 1
fi

if ! command -v brew >/dev/null 2>&1; then
  echo "Homebrew is required. Install it first, then rerun this script." >&2
  exit 1
fi

brew list python@3.11 >/dev/null 2>&1 || brew install python@3.11
brew list ffmpeg >/dev/null 2>&1 || brew install ffmpeg

PYTHON="$(brew --prefix python@3.11)/bin/python3.11"
mkdir -p "$ROOT/.local/bin" "$ROOT/runtime/logs" "$ROOT/runtime/pids"

if [[ ! -x "$ROOT/.local/bin/go2rtc" ]]; then
  tmp="$(mktemp -d)"
  trap 'rm -rf "$tmp"' EXIT
  curl -fL \
    "https://github.com/AlexxIT/go2rtc/releases/download/v${GO2RTC_VERSION}/go2rtc_mac_amd64.zip" \
    -o "$tmp/go2rtc.zip"
  unzip -q "$tmp/go2rtc.zip" -d "$tmp/unpacked"
  candidate="$(find "$tmp/unpacked" -type f | sed -n '1p')"
  if [[ -z "$candidate" ]]; then
    echo "go2rtc archive did not contain a binary." >&2
    exit 1
  fi
  install -m 755 "$candidate" "$ROOT/.local/bin/go2rtc"
fi

if [[ ! -x "$ROOT/.venv-alpha/bin/python" ]]; then
  "$PYTHON" -m venv "$ROOT/.venv-alpha"
fi
"$ROOT/.venv-alpha/bin/python" -m pip install --upgrade pip
"$ROOT/.venv-alpha/bin/python" -m pip install -e "$ROOT"

if [[ ! -f "$ROOT/runtime/go2rtc.yaml" ]]; then
  cp "$ROOT/config/go2rtc.alpha.yaml" "$ROOT/runtime/go2rtc.yaml"
fi

if [[ ! -f "$ROOT/runtime/alpha.env" ]]; then
  password="$(openssl rand -hex 20 | cut -c 1-28)"
  topic="baby-monitor-$(openssl rand -hex 16)"
  cat >"$ROOT/runtime/alpha.env" <<EOF
BABY_MONITOR_USERNAME=parent
BABY_MONITOR_PASSWORD=${password}
BABY_MONITOR_BIND_HOST=0.0.0.0
BABY_MONITOR_PORT=8080
BABY_MONITOR_STREAM=live
GO2RTC_BASE_URL=http://127.0.0.1:1984
NTFY_BASE_URL=https://ntfy.sh
NTFY_TOPIC=${topic}
NTFY_TOKEN=
EOF
  chmod 600 "$ROOT/runtime/alpha.env"
fi

cat <<EOF

Alpha installation prepared.

1. Start services:
   $ROOT/tools/start_alpha.sh

2. From the M2 Mac, use an SSH tunnel for the private Xiaomi setup interface:
   ssh -L 1984:127.0.0.1:1984 <i9-user>@<i9-lan-ip>
   Then open http://127.0.0.1:1984 on the M2 Mac.

3. Choose Add > Xiaomi, sign in, add MJSXJ17CM, and name the camera stream: source
   The preconfigured live stream converts source to 960x540 MJPEG at 5 FPS.

4. The start script prints the LAN dashboard URL for the M2 Mac.

Local credentials are stored with mode 600 in:
   $ROOT/runtime/alpha.env

Do not commit or share that file. The generated password is dedicated to this dashboard; do not reuse another account password.
EOF
