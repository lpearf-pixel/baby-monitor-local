#!/usr/bin/env bash
set -u

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PYTHON="$ROOT/.venv-alpha/bin/python"
ENV_FILE="$ROOT/runtime/alpha.env"
TEST_MODE="${BABY_MONITOR_GUARDIAN_LIVE_TEST_MODE:-0}"
HOOK_DIR="${BABY_MONITOR_GUARDIAN_LIVE_HOOK_DIR:-}"
readonly ROOT PYTHON ENV_FILE TEST_MODE HOOK_DIR

emit_success() {
  local stage="$1"
  if [[ "$TEST_MODE" == "1" ]]; then
    echo "SIMULATED live $stage"
  else
    echo "PASS live $stage"
  fi
}

fail_live() {
  local stage="$1"
  local code="$2"
  echo "FAIL live $stage $code"
  echo "guardian_live_test=FAIL"
  exit 1
}

confirm_yes() {
  local prompt="$1"
  local answer=""
  if [[ "$TEST_MODE" == "1" ]]; then
    IFS= read -r answer || return 1
  else
    printf '%s' "$prompt" >/dev/tty
    IFS= read -r answer </dev/tty || return 1
  fi
  [[ "$answer" == "YES" ]]
}

test_hooks_ready() {
  [[ -n "$HOOK_DIR" ]] && \
    [[ -x "$HOOK_DIR/readiness" ]] && \
    [[ -x "$HOOK_DIR/notification" ]]
}

run_readiness() {
  if [[ "$TEST_MODE" == "1" ]]; then
    "$HOOK_DIR/readiness" >/dev/null 2>&1
    return $?
  fi
  BABY_MONITOR_GUARDIAN_REPORT_PHASE=service \
    bash "$ROOT/tools/guardian_readiness.sh" >/dev/null 2>&1
}

send_notification() {
  if [[ "$TEST_MODE" == "1" ]]; then
    "$HOOK_DIR/notification" >/dev/null 2>&1
    return $?
  fi
  [[ -r "$ENV_FILE" && -x "$PYTHON" ]] || return 1
  (
    set -a
    # shellcheck disable=SC1090
    source "$ENV_FILE" >/dev/null 2>&1 || exit 1
    set +a
    "$PYTHON" "$ROOT/tools/send_guardian_live_notification.py" \
      >/dev/null 2>&1
  )
}

if [[ "$TEST_MODE" == "1" ]]; then
  test_hooks_ready || fail_live "readiness" "readiness_failed"
else
  if [[ ! -t 0 || ! -r /dev/tty || ! -w /dev/tty ]]; then
    fail_live "interactive" "interactive_required"
  fi
fi

confirm_yes "Confirm no real infant is present. Type YES: " || \
  fail_live "safety" "safety_not_confirmed"
confirm_yes "Confirm an adult is supervising. Type YES: " || \
  fail_live "safety" "safety_not_confirmed"
emit_success "safety"

run_readiness || fail_live "readiness" "readiness_failed"
emit_success "readiness"

send_notification || fail_live "notification" "notification_failed"
emit_success "notification"

confirm_yes "Confirm phone A received the test. Type YES: " || \
  fail_live "phone_a" "phone_a_unconfirmed"
emit_success "phone_a"

confirm_yes "Confirm phone B received the test. Type YES: " || \
  fail_live "phone_b" "phone_b_unconfirmed"
emit_success "phone_b"

confirm_yes "Confirm the authenticated live view is visible. Type YES: " || \
  fail_live "live_view" "live_view_unconfirmed"
emit_success "live_view"

confirm_yes "Confirm the Guardian event list is visible. Type YES: " || \
  fail_live "event_list" "event_list_unconfirmed"
emit_success "event_list"

if [[ "$TEST_MODE" == "1" ]]; then
  echo "guardian_live_test=SIMULATED"
else
  echo "guardian_live_test=PASS"
fi
