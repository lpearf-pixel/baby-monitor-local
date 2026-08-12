#!/usr/bin/env bash
set -u

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

run_alpha_start() {
  if [[ "${BABY_MONITOR_GUARDIAN_TEST_MODE:-0}" == "1" ]]; then
    local hook_dir="${BABY_MONITOR_GUARDIAN_HOOK_DIR:-}"
    if [[ -z "$hook_dir" || ! -x "$hook_dir/alpha_start" ]]; then
      return 1
    fi
    "$hook_dir/alpha_start" >/dev/null 2>&1
    return $?
  fi
  bash "$ROOT/tools/start_alpha.sh" >/dev/null 2>&1
}

if ! run_alpha_start; then
  echo "FAIL start alpha_start start_failed"
  echo "guardian_start=FAIL"
  exit 1
fi

echo "PASS start alpha_start"
if bash "$ROOT/tools/guardian_readiness.sh"; then
  echo "guardian_start=PASS"
  exit 0
fi

echo "guardian_start=FAIL"
exit 1
