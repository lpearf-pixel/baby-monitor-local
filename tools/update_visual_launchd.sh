#!/bin/bash
set -Eeuo pipefail

ROOT="${BABY_MONITOR_PROJECT_ROOT:-$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)}"
DOMAIN="gui/$(id -u)"
LABEL="com.babymonitor.visual"
SERVICE="$DOMAIN/$LABEL"
TEMPLATE="$ROOT/deploy/launchd/$LABEL.plist.example"
RUNTIME_PLIST="$ROOT/runtime/launchd/$LABEL.plist"
PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"
BACKGROUND_BACKUP="$PLIST.r3-background.bak"
CANDIDATE=""
ROLLBACK=""
WORKER_STOPPED=0
UPDATE_FINISHED=0
FAIL_REASON="update_failed"

remove_temporary_files() {
  if [[ -n "$CANDIDATE" ]]; then
    rm -f "$CANDIDATE" || true
  fi
  if [[ -n "$ROLLBACK" ]]; then
    rm -f "$ROLLBACK" || true
  fi
}

atomic_copy() {
  local source="$1"
  local target="$2"
  local target_dir
  local temporary

  target_dir="$(dirname -- "$target")"
  temporary="$(mktemp "$target_dir/.visual-launchd-install.XXXXXX")" || return 1
  if ! cp -p "$source" "$temporary"; then
    rm -f "$temporary" || true
    return 1
  fi
  if ! mv -f "$temporary" "$target"; then
    rm -f "$temporary" || true
    return 1
  fi
}

finish_or_restore() {
  local status=$?

  trap - EXIT HUP INT TERM
  if [[ "$UPDATE_FINISHED" -eq 1 ]]; then
    remove_temporary_files
    exit 0
  fi

  if [[ "$WORKER_STOPPED" -eq 1 && -n "$ROLLBACK" ]]; then
    if launchctl print "$SERVICE" >/dev/null 2>&1; then
      launchctl bootout "$SERVICE" >/dev/null 2>&1 || true
    fi
    if atomic_copy "$ROLLBACK" "$PLIST" \
      && launchctl bootstrap "$DOMAIN" "$PLIST" >/dev/null 2>&1 \
      && launchctl kickstart -k "$SERVICE" >/dev/null 2>&1 \
      && launchctl print "$SERVICE" >/dev/null 2>&1; then
      remove_temporary_files
      printf '%s\n' "visual_launchd_update=FAIL reason=$FAIL_REASON"
      exit 2
    fi
    remove_temporary_files
    printf '%s\n' "visual_launchd_update=FAIL reason=rollback_failed"
    exit 3
  fi

  remove_temporary_files
  if [[ "$status" -eq 0 ]]; then
    status=2
  fi
  printf '%s\n' "visual_launchd_update=FAIL reason=$FAIL_REASON"
  exit "$status"
}

trap finish_or_restore EXIT
trap 'FAIL_REASON="interrupted"; exit 2' HUP INT TERM

if [[ "$(uname -s)" != "Darwin" || "$(uname -m)" != "x86_64" ]]; then
  FAIL_REASON="intel_macos_required"
  exit 2
fi
if ! command -v launchctl >/dev/null 2>&1 \
  || ! command -v plutil >/dev/null 2>&1 \
  || [[ ! -f "$TEMPLATE" || ! -f "$PLIST" ]]; then
  FAIL_REASON="update_unavailable"
  exit 2
fi
if ! launchctl print "$SERVICE" >/dev/null 2>&1; then
  FAIL_REASON="visual_worker_offline"
  exit 2
fi

mkdir -p "$ROOT/runtime/launchd"
CANDIDATE="$(mktemp "$ROOT/runtime/launchd/.visual-launchd-candidate.XXXXXX")"
if ! sed "s|__PROJECT_ROOT__|$ROOT|g" "$TEMPLATE" >"$CANDIDATE"; then
  FAIL_REASON="template_render_failed"
  exit 2
fi
if ! plutil -lint "$CANDIDATE" >/dev/null 2>&1; then
  FAIL_REASON="template_invalid"
  exit 2
fi
ROLLBACK="$(mktemp "$HOME/Library/LaunchAgents/.visual-launchd-rollback.XXXXXX")"
if ! cp -p "$PLIST" "$ROLLBACK"; then
  FAIL_REASON="snapshot_failed"
  exit 2
fi
if [[ ! -e "$BACKGROUND_BACKUP" ]] \
  && ! atomic_copy "$PLIST" "$BACKGROUND_BACKUP"; then
  FAIL_REASON="backup_failed"
  exit 2
fi

if ! launchctl bootout "$SERVICE" >/dev/null 2>&1; then
  FAIL_REASON="stop_failed"
  exit 2
fi
WORKER_STOPPED=1

if ! atomic_copy "$CANDIDATE" "$PLIST"; then
  FAIL_REASON="install_failed"
  exit 2
fi
if ! launchctl bootstrap "$DOMAIN" "$PLIST" >/dev/null 2>&1 \
  || ! launchctl kickstart -k "$SERVICE" >/dev/null 2>&1 \
  || ! launchctl print "$SERVICE" >/dev/null 2>&1; then
  FAIL_REASON="activation_failed"
  exit 2
fi
if ! atomic_copy "$CANDIDATE" "$RUNTIME_PLIST"; then
  FAIL_REASON="runtime_sync_failed"
  exit 2
fi

UPDATE_FINISHED=1
trap - EXIT HUP INT TERM
remove_temporary_files
printf '%s\n' "visual_launchd_update=PASS process_type=Interactive"
