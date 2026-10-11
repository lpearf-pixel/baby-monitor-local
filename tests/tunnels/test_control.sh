#!/bin/bash
set -eu

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
TMP="$(mktemp -d "${TMPDIR:-/tmp}/ssh-tunnel-control.XXXXXX")"
trap 'rm -rf "$TMP"' EXIT HUP INT TERM
mkdir -p "$TMP/home/Library/LaunchAgents" "$TMP/logs"
printf 'synthetic-key' >"$TMP/key"
chmod 600 "$TMP/key"
cat >"$TMP/fake-launchctl" <<'EOF'
#!/bin/bash
set -eu
printf 'launchctl %s\n' "$*" >>"$FAKE_LOG"
case "${1:-}" in
  print) exit 1 ;;
  bootstrap|kickstart|bootout) exit 0 ;;
  *) exit 0 ;;
esac
EOF
cat >"$TMP/fake-lsof" <<'EOF'
#!/bin/bash
set -eu
if [ "${FAKE_CONFLICT:-0}" = 1 ]; then
  echo 'foreign 999 user 3u IPv4 0x0 0t0 TCP 127.0.0.1:1984 (LISTEN)'
fi
exit 0
EOF
cat >"$TMP/fake-ssh" <<'EOF'
#!/bin/bash
set -eu
printf 'ssh %s\n' "$*" >>"$FAKE_LOG"
exit 0
EOF
chmod 700 "$TMP/fake-launchctl" "$TMP/fake-lsof" "$TMP/fake-ssh"

export HOME="$TMP/home" FAKE_LOG="$TMP/calls.log"
export LAUNCHCTL="$TMP/fake-launchctl" LSOF="$TMP/fake-lsof" SSH="$TMP/fake-ssh"
export LAUNCH_AGENTS_DIR="$TMP/home/Library/LaunchAgents"

bash "$ROOT/scripts/tunnels/install.sh" --target 'kandysmith@192.168.2.141' --identity "$TMP/key" --log-dir "$TMP/logs"
bash "$ROOT/scripts/tunnels/install.sh" --target 'kandysmith@192.168.2.141' --identity "$TMP/key" --log-dir "$TMP/logs"
[ -f "$LAUNCH_AGENTS_DIR/com.babymonitor.ssh-tunnels.plist" ]
grep -q 'bootstrap' "$TMP/calls.log"

bash "$ROOT/scripts/tunnels/control.sh" stop
grep -q 'bootout' "$TMP/calls.log"
if grep -q 'com.babymonitor.ollama-tunnel' "$TMP/calls.log"; then
  echo 'control touched legacy label' >&2
  exit 1
fi

export FAKE_CONFLICT=1
if bash "$ROOT/scripts/tunnels/install.sh" --target 'kandysmith@192.168.2.141' --identity "$TMP/key" --log-dir "$TMP/logs"; then
  echo 'expected port conflict rejection' >&2
  exit 1
fi

echo 'test_control=PASS'
