#!/bin/bash
set -eu

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
TMP="$(mktemp -d "${TMPDIR:-/tmp}/ssh-tunnel-preflight.XXXXXX")"
trap 'rm -rf "$TMP"' EXIT HUP INT TERM
printf 'synthetic-key' >"$TMP/key"
chmod 600 "$TMP/key"
cat >"$TMP/fake-curl" <<'EOF'
#!/bin/bash
set -eu
exit 0
EOF
cat >"$TMP/fake-ssh" <<'EOF'
#!/bin/bash
set -eu
exit "${FAKE_SSH_RC:-0}"
EOF
chmod 700 "$TMP/fake-curl" "$TMP/fake-ssh"
export CURL="$TMP/fake-curl" SSH="$TMP/fake-ssh"
output="$(bash "$ROOT/scripts/tunnels/preflight.sh" --install-host m3 --target kandysmith@192.168.2.141 --identity "$TMP/key" --ollama-host 192.168.2.144)"
echo "$output" | grep -q '^code_machine=not_inferred_from_this_host$'
echo "$output" | grep -q '^tunnel_install_machine=m3$'
echo "$output" | grep -q '^ollama_destination_from_i9=192.168.2.144:11434$'
echo "$output" | grep -q '^MIGRATION_PREFLIGHT_PASS$'
export FAKE_SSH_RC=255
if bash "$ROOT/scripts/tunnels/preflight.sh" --install-host m3 --target kandysmith@192.168.2.141 --identity "$TMP/key" --ollama-host 192.168.2.144; then
  echo 'expected auth failure' >&2
  exit 1
fi
echo 'test_preflight=PASS'
