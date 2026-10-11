#!/bin/bash
set -eu

SSH="${SSH:-/usr/bin/ssh}"
CURL="${CURL:-/usr/bin/curl}"
TARGET=""
IDENTITY=""
INSTALL_HOST=""
OLLAMA_HOST=""
usage() { echo "usage: preflight.sh --install-host m2|m3|i9 --target USER@192.168.2.141 --identity PATH --ollama-host HOST" >&2; exit 64; }
fail() { echo "MIGRATION_PREFLIGHT_BLOCKED reason=$1"; exit 1; }
while [ "$#" -gt 0 ]; do
  case "$1" in
    --install-host) [ "$#" -ge 2 ] || usage; INSTALL_HOST="$2"; shift 2 ;;
    --target) [ "$#" -ge 2 ] || usage; TARGET="$2"; shift 2 ;;
    --identity) [ "$#" -ge 2 ] || usage; IDENTITY="$2"; shift 2 ;;
    --ollama-host) [ "$#" -ge 2 ] || usage; OLLAMA_HOST="$2"; shift 2 ;;
    *) usage ;;
  esac
done
[ "$INSTALL_HOST" = m2 ] || [ "$INSTALL_HOST" = m3 ] || [ "$INSTALL_HOST" = i9 ] || usage
[ -n "$TARGET" ] && [ -n "$IDENTITY" ] && [ -n "$OLLAMA_HOST" ] || usage
case "$TARGET" in *'@192.168.2.141') ;; *) fail target_not_i9 ;; esac
case "$OLLAMA_HOST" in *[!A-Za-z0-9._:-]*) fail invalid_ollama_host ;; esac
[ -f "$IDENTITY" ] || fail identity_missing
[ "$(stat -f '%Lp' "$IDENTITY" 2>/dev/null || true)" = 600 ] || fail identity_not_0600

echo "code_machine=not_inferred_from_this_host"
echo "tunnel_install_machine=$INSTALL_HOST"
echo "ssh_target=$TARGET"
echo "ollama_destination_from_i9=$OLLAMA_HOST:11434"
echo 'legacy_services=must_be_reviewed_without_automatic_stop'
if [ "$OLLAMA_HOST" = 127.0.0.1 ]; then
  if "$CURL" -fsS --max-time 3 --noproxy '*' http://127.0.0.1:11434/api/tags -o /dev/null 2>/dev/null; then echo 'ollama_local_api=reachable'; else echo 'ollama_local_api=unreachable'; fi
else
  echo 'ollama_local_api=not_checked'
fi
set +e
"$SSH" -o BatchMode=yes -o ConnectTimeout=5 -o IdentitiesOnly=yes -o StrictHostKeyChecking=yes -i "$IDENTITY" "$TARGET" /usr/bin/true >/dev/null 2>&1
AUTH_RC=$?
set -e
echo "ssh_auth_exit=$AUTH_RC"
[ "$AUTH_RC" -eq 0 ] || fail ssh_authentication
set +e
"$SSH" -o BatchMode=yes -o ConnectTimeout=5 -o IdentitiesOnly=yes -o StrictHostKeyChecking=yes -i "$IDENTITY" "$TARGET" /usr/bin/curl -fsS --max-time 3 --noproxy '*' "http://$OLLAMA_HOST:11434/api/tags" -o /dev/null >/dev/null 2>&1
REMOTE_RC=$?
set -e
echo "ollama_from_i9_exit=$REMOTE_RC"
[ "$REMOTE_RC" -eq 0 ] || fail ollama_not_reachable_from_i9
echo 'MIGRATION_PREFLIGHT_PASS'
