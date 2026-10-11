#!/bin/bash
set -eu

usage() {
  echo "usage: render.sh --template PATH --output PATH --target USER@HOST --identity PATH --log-dir PATH" >&2
  exit 64
}

TEMPLATE=""
OUTPUT=""
TARGET=""
IDENTITY=""
LOG_DIR=""
while [ "$#" -gt 0 ]; do
  case "$1" in
    --template) [ "$#" -ge 2 ] || usage; TEMPLATE="$2"; shift 2 ;;
    --output) [ "$#" -ge 2 ] || usage; OUTPUT="$2"; shift 2 ;;
    --target) [ "$#" -ge 2 ] || usage; TARGET="$2"; shift 2 ;;
    --identity) [ "$#" -ge 2 ] || usage; IDENTITY="$2"; shift 2 ;;
    --log-dir) [ "$#" -ge 2 ] || usage; LOG_DIR="$2"; shift 2 ;;
    *) usage ;;
  esac
done

[ -n "$TEMPLATE" ] && [ -f "$TEMPLATE" ] || usage
[ -n "$OUTPUT" ] && [ -n "$TARGET" ] && [ -n "$IDENTITY" ] && [ -n "$LOG_DIR" ] || usage
case "$TARGET" in *[!A-Za-z0-9._@-]*) echo "invalid ssh target" >&2; exit 65 ;; esac
[ -f "$IDENTITY" ] || { echo "identity is missing" >&2; exit 66; }
MODE="$(stat -f '%Lp' "$IDENTITY" 2>/dev/null || true)"
[ "$MODE" = "600" ] || { echo "identity must be mode 0600" >&2; exit 66; }

escape_sed() { printf '%s' "$1" | sed 's/[\\&|]/\\&/g'; }
T_ESC="$(escape_sed "$TARGET")"
I_ESC="$(escape_sed "$IDENTITY")"
L_ESC="$(escape_sed "$LOG_DIR")"
OUT_DIR="$(dirname "$OUTPUT")"
mkdir -p "$OUT_DIR"
TEMP="$OUT_DIR/.ssh-tunnels-render.$$.tmp"
trap 'rm -f "$TEMP"' EXIT HUP INT TERM
sed -e "s|__SSH_TARGET__|$T_ESC|g" -e "s|__SSH_IDENTITY__|$I_ESC|g" -e "s|__LOG_DIR__|$L_ESC|g" "$TEMPLATE" >"$TEMP"
mv "$TEMP" "$OUTPUT"
chmod 600 "$OUTPUT"
