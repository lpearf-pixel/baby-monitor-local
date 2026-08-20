#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

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
brew list go >/dev/null 2>&1 || brew install go

PYTHON="$(brew --prefix python@3.11)/bin/python3.11"
mkdir -p "$ROOT/.local/bin" "$ROOT/runtime/logs" "$ROOT/runtime/pids" "$ROOT/runtime/launchd"

if [[ ! -x "$ROOT/.venv-alpha/bin/python" ]]; then
  "$PYTHON" -m venv "$ROOT/.venv-alpha"
fi
"$ROOT/.venv-alpha/bin/python" -m pip install --upgrade pip
"$ROOT/.venv-alpha/bin/python" -m pip install -e "$ROOT[dev]"
"$ROOT/.venv-alpha/bin/python" "$ROOT/tools/go2rtc_build.py" ensure

if [[ ! -f "$ROOT/runtime/go2rtc.yaml" ]]; then
  cp "$ROOT/config/go2rtc.alpha.yaml" "$ROOT/runtime/go2rtc.yaml"
fi

if [[ ! -f "$ROOT/runtime/settings.yaml" ]]; then
  cp "$ROOT/config/settings.example.yaml" "$ROOT/runtime/settings.yaml"
fi

sed "s|__PROJECT_ROOT__|$ROOT|g" \
  "$ROOT/deploy/launchd/com.babymonitor.go2rtc.plist.example" \
  >"$ROOT/runtime/launchd/com.babymonitor.go2rtc.plist"
sed "s|__PROJECT_ROOT__|$ROOT|g" \
  "$ROOT/deploy/launchd/com.babymonitor.gauge.plist.example" \
  >"$ROOT/runtime/launchd/com.babymonitor.gauge.plist"
sed "s|__PROJECT_ROOT__|$ROOT|g" \
  "$ROOT/deploy/launchd/com.babymonitor.environment-watchdog.plist.example" \
  >"$ROOT/runtime/launchd/com.babymonitor.environment-watchdog.plist"
sed "s|__PROJECT_ROOT__|$ROOT|g" \
  "$ROOT/deploy/launchd/com.babymonitor.visual.plist.example" \
  >"$ROOT/runtime/launchd/com.babymonitor.visual.plist"
sed "s|__PROJECT_ROOT__|$ROOT|g" \
  "$ROOT/deploy/launchd/com.babymonitor.audio.plist.example" \
  >"$ROOT/runtime/launchd/com.babymonitor.audio.plist"
mkdir -p "$HOME/Library/LaunchAgents"
cp "$ROOT/runtime/launchd/com.babymonitor.go2rtc.plist" \
  "$HOME/Library/LaunchAgents/com.babymonitor.go2rtc.plist"
cp "$ROOT/runtime/launchd/com.babymonitor.gauge.plist" \
  "$HOME/Library/LaunchAgents/com.babymonitor.gauge.plist"
cp "$ROOT/runtime/launchd/com.babymonitor.environment-watchdog.plist" \
  "$HOME/Library/LaunchAgents/com.babymonitor.environment-watchdog.plist"
cp "$ROOT/runtime/launchd/com.babymonitor.visual.plist" \
  "$HOME/Library/LaunchAgents/com.babymonitor.visual.plist"
cp "$ROOT/runtime/launchd/com.babymonitor.audio.plist" \
  "$HOME/Library/LaunchAgents/com.babymonitor.audio.plist"

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
BABY_MONITOR_SETTINGS_PATH=${ROOT}/runtime/settings.yaml
BABY_MONITOR_DASHBOARD_URL=
NTFY_BASE_URL=https://ntfy.sh
NTFY_TOPIC=${topic}
NTFY_TOKEN=
EOF
  chmod 600 "$ROOT/runtime/alpha.env"
fi

cat <<EOF

Alpha installation prepared.

1. Start services without changing tracked file permissions:
   make -C "$ROOT" alpha-start

2. From the M2 Mac, use an SSH tunnel for the private Xiaomi setup interface:
   ssh -L 1984:127.0.0.1:1984 <i9-user>@<i9-lan-ip>
   Then open http://127.0.0.1:1984 on the M2 Mac.

3. Choose Add > Xiaomi, sign in, add MJSXJ17CM, and name the camera stream: source
   The preconfigured live stream converts source to 1280x720 MJPEG at 10 FPS.
   Existing runtime/go2rtc.yaml files are preserved; use make alpha-quality-hd to upgrade one safely.

4. The start command prints the LAN dashboard URL for the M2 Mac.

5. Use the authenticated Tailscale Serve HTTPS URL as BABY_MONITOR_DASHBOARD_URL
   in runtime/alpha.env before enabling environment ntfy incident links.

6. Visual review remains disabled until runtime/settings.yaml contains a private
   bed_zone. Configure the dedicated M2 SSH key and tunnel with:
   $ROOT/.venv-alpha/bin/python $ROOT/tools/configure_ollama_tunnel.py \
     --target '<dedicated-user>@<private-M2-host>' \
     --identity '$HOME/.ssh/baby-monitor-m2'

Useful commands:
   make -C "$ROOT" alpha-quality-hd
   make -C "$ROOT" alpha-quality-info
   make -C "$ROOT" alpha-source-check
   make -C "$ROOT" alpha-status
   make -C "$ROOT" alpha-visual-status
   make -C "$ROOT" alpha-logs
   make -C "$ROOT" alpha-stop

Local credentials are stored with mode 600 in:
   $ROOT/runtime/alpha.env

Do not commit or share that file. The generated password is dedicated to this dashboard; do not reuse another account password.
EOF
