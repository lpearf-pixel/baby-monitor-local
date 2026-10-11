#!/bin/bash
set -eu

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
TMP="$(mktemp -d "${TMPDIR:-/tmp}/ssh-tunnel-check.XXXXXX")"
trap 'rm -rf "$TMP"' EXIT HUP INT TERM
mkdir -p "$TMP/home/Library/LaunchAgents"
printf 'synthetic-key' >"$TMP/key"
chmod 600 "$TMP/key"
bash "$ROOT/scripts/tunnels/render.sh" --template "$ROOT/config/launchd/com.babymonitor.ssh-tunnels.plist.template" --output "$TMP/plist" --target 'kandysmith@192.168.2.141' --identity "$TMP/key" --log-dir "$TMP/logs"
cp "$TMP/plist" "$TMP/home/Library/LaunchAgents/com.babymonitor.ssh-tunnels.plist"
cat >"$TMP/fake-launchctl" <<'EOF'
#!/bin/bash
set -eu
case "${FAKE_SSH_PROCESS:-1}:$1" in 1:print) exit 0 ;; *) exit 1 ;; esac
EOF
cat >"$TMP/fake-lsof" <<'EOF'
#!/bin/bash
set -eu
case "${FAKE_LOCAL_PORT:-1}" in
  1) echo 'ssh 123 user 3u IPv4 0x0 0t0 TCP 127.0.0.1:1984 (LISTEN)' ;;
esac
EOF
cat >"$TMP/fake-ps" <<'EOF'
#!/bin/bash
set -eu
[ "${FAKE_SSH_PROCESS:-1}" = 1 ] && echo '/usr/bin/ssh -N -T -L 127.0.0.1:1984:127.0.0.1:1984 -R 127.0.0.1:11435:127.0.0.1:11434'
EOF
cat >"$TMP/fake-curl" <<'EOF'
#!/bin/bash
set -eu
case "$*" in
  *1984*) [ "${FAKE_GO2RTC:-1}" = 1 ] || exit 22 ;;
  *) exit 0 ;;
esac
EOF
cat >"$TMP/fake-ssh" <<'EOF'
#!/bin/bash
set -eu
case "$*" in
  */usr/sbin/lsof*) [ "${FAKE_REMOTE_PORT:-1}" = 1 ] && echo 'ssh 321 user 3u IPv4 0x0 0t0 TCP 127.0.0.1:11435 (LISTEN)' ;;
  */usr/bin/curl*) [ "${FAKE_OLLAMA:-1}" = 1 ] || exit 22 ;;
esac
EOF
chmod 700 "$TMP/fake-launchctl" "$TMP/fake-lsof" "$TMP/fake-curl" "$TMP/fake-ssh" "$TMP/fake-ps"
export HOME="$TMP/home" LAUNCH_AGENTS_DIR="$TMP/home/Library/LaunchAgents"
export LAUNCHCTL="$TMP/fake-launchctl" LSOF="$TMP/fake-lsof" CURL="$TMP/fake-curl" SSH="$TMP/fake-ssh" PS="$TMP/fake-ps"

healthy="$(bash "$ROOT/scripts/tunnels/check.sh" --target 'kandysmith@192.168.2.141' --identity "$TMP/key")"
echo "$healthy" | grep -q '^ssh_process=present$'
echo "$healthy" | grep -q '^launchd_registration=registered$'
echo "$healthy" | grep -q '^m2_port_1984=listening$'
echo "$healthy" | grep -q '^go2rtc_api=reachable$'
echo "$healthy" | grep -q '^i9_port_11435=listening$'
echo "$healthy" | grep -q '^ollama_api=reachable$'

export FAKE_LOCAL_PORT=0 FAKE_GO2RTC=0 FAKE_REMOTE_PORT=0 FAKE_OLLAMA=0 FAKE_SSH_PROCESS=0 FAKE_SSH_PROCESS=0
degraded="$(bash "$ROOT/scripts/tunnels/check.sh" --target 'kandysmith@192.168.2.141' --identity "$TMP/key")"
echo "$degraded" | grep -q '^ssh_process=absent$'
echo "$degraded" | grep -q '^m2_port_1984=not_listening$'
echo "$degraded" | grep -q '^go2rtc_api=unreachable$'
echo "$degraded" | grep -q '^i9_port_11435=unknown$'
echo "$degraded" | grep -q '^ollama_api=unreachable$'

echo 'test_check=PASS'
