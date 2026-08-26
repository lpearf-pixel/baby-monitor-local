#!/usr/bin/env bash
set -u

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PYTHON="$ROOT/.venv-alpha/bin/python"
GO2RTC_APP="$ROOT/.local/Go2RTC.app"
GO2RTC_EXECUTABLE="$GO2RTC_APP/Contents/MacOS/go2rtc"
GO2RTC_REQUIREMENT='designated => identifier "com.babymonitor.go2rtc"'
VOICE_KEYCHAIN_APP="$ROOT/.local/VoiceKeychainHelper.app"
VOICE_KEYCHAIN_EXECUTABLE="$VOICE_KEYCHAIN_APP/Contents/MacOS/voice-keychain-helper"
VOICE_KEYCHAIN_REQUIREMENT='designated => identifier "com.babymonitor.voice-keychain-helper"'
GO2RTC_PATCH="$ROOT/patches/go2rtc-macos-hybrid-hd.patch"
GO2RTC_METADATA="$ROOT/runtime/build/go2rtc.json"
PASS_COUNT=0
FAIL_COUNT=0

run_probe() {
  local name="$1"
  shift
  if [[ "${BABY_MONITOR_GUARDIAN_TEST_MODE:-0}" == "1" ]]; then
    if [[ "${BABY_MONITOR_GUARDIAN_REAL_CHECK:-}" == "$name" ]]; then
      "$@" >/dev/null 2>&1
      return $?
    fi
    local hook_dir="${BABY_MONITOR_GUARDIAN_HOOK_DIR:-}"
    if [[ -z "$hook_dir" || ! -x "$hook_dir/$name" ]]; then
      return 1
    fi
    "$hook_dir/$name" >/dev/null 2>&1
    return $?
  fi
  "$@" >/dev/null 2>&1
}

run_check() {
  local phase="$1"
  local name="$2"
  shift 2
  if run_probe "$name" "$@"; then
    echo "PASS $phase $name"
    PASS_COUNT=$((PASS_COUNT + 1))
  else
    echo "FAIL $phase $name check_failed"
    FAIL_COUNT=$((FAIL_COUNT + 1))
  fi
}

check_shell_policy() {
  local files
  files="$(git -C "$ROOT" ls-files '*.sh')" || return 1
  if [[ -z "$files" ]]; then
    return 1
  fi
  local file
  while IFS= read -r file; do
    [[ -n "$file" ]] || continue
    bash -n "$ROOT/$file" || return 1
    if LC_ALL=C grep -q '[^	 -~]' "$ROOT/$file"; then
      return 1
    fi
  done <<EOF
$files
EOF
}

check_make_wiring() {
  make -C "$ROOT" -n \
    alpha-guardian-start alpha-guardian-test alpha-guardian-test-live
}

check_tracked_runtime() {
  local file
  local files
  files="$(git -C "$ROOT" ls-files)" || return 1
  while IFS= read -r file; do
    case "$file" in
      runtime/*|*.jpg|*.jpeg|*.webp|*.mp4|*.mov|*.sqlite|*.sqlite3|*.db)
        return 1
        ;;
    esac
  done <<EOF
$files
EOF
}

check_sensitive_literals() {
  local base
  base="$(git -C "$ROOT" merge-base HEAD origin/stable/xiaomi-alpha 2>/dev/null)" || \
    base="$(git -C "$ROOT" rev-parse HEAD^ 2>/dev/null)" || return 1
  local files
  files="$({
    git -C "$ROOT" diff --name-only "$base" -- \
      apps services tools config deploy Makefile
    git -C "$ROOT" ls-files --others --exclude-standard -- \
      apps services tools config deploy Makefile
  } | sort -u)" || return 1
  local credential_prefix='github_''pat_'
  local sensitive_pattern
  sensitive_pattern="${credential_prefix}|AKIA[0-9A-Z]{16}|BEGIN [A-Z ]*PRIVATE KEY|192\\.168\\.[0-9]+\\.[0-9]+|10\\.[0-9]+\\.[0-9]+\\.[0-9]+|172\\.(1[6-9]|2[0-9]|3[01])\\.[0-9]+\\.[0-9]+"
  local file
  while IFS= read -r file; do
    [[ -n "$file" && -f "$ROOT/$file" ]] || continue
    if grep -E -q "$sensitive_pattern" "$ROOT/$file"; then
      return 1
    fi
  done <<EOF
$files
EOF
}

check_python_regression() {
  "$PYTHON" -m pytest -q
}

check_required_binaries() {
  command -v bash >/dev/null 2>&1 && \
    command -v curl >/dev/null 2>&1 && \
    command -v codesign >/dev/null 2>&1 && \
    command -v git >/dev/null 2>&1 && \
    command -v make >/dev/null 2>&1 && \
    [[ -x "$PYTHON" ]] && \
    [[ -x "$ROOT/.venv-alpha/bin/uvicorn" ]] && \
    [[ -x "$ROOT/.local/bin/go2rtc" ]] && \
    [[ -x "$GO2RTC_EXECUTABLE" ]] && \
    [[ -x "$VOICE_KEYCHAIN_EXECUTABLE" ]] && \
    [[ -r "$GO2RTC_PATCH" ]] && \
    [[ -r "$GO2RTC_METADATA" ]] && \
    [[ -r "$ROOT/tests/voice/test_camera_reply.py" ]] && \
    [[ -r "$ROOT/tests/tools/test_voice_camera_reply.py" ]] || return 1

  codesign --verify --deep --strict \
    --requirements "=$GO2RTC_REQUIREMENT" "$GO2RTC_APP" || return 1
  local requirement
  requirement="$(codesign -d -r- "$GO2RTC_APP" 2>&1)" || return 1
  if [[ "$requirement" == *cdhash* ]]; then
    return 1
  fi
  [[ "$requirement" == *"$GO2RTC_REQUIREMENT"* ]] || return 1

  codesign --verify --deep --strict \
    --requirements "=$VOICE_KEYCHAIN_REQUIREMENT" \
    "$VOICE_KEYCHAIN_APP" || return 1
  requirement="$(codesign -d -r- "$VOICE_KEYCHAIN_APP" 2>&1)" || return 1
  if [[ "$requirement" == *cdhash* ]]; then
    return 1
  fi
  [[ "$requirement" == *"$VOICE_KEYCHAIN_REQUIREMENT"* ]] && \
    make -C "$ROOT" --no-print-directory alpha-voice-camera-test \
      >/dev/null 2>&1 && \
    "$PYTHON" "$ROOT/tools/voice_camera_reply.py" verify-marker \
      >/dev/null 2>&1
}

check_runtime_config() {
  [[ -r "$ROOT/runtime/alpha.env" ]] && \
    [[ -r "$ROOT/runtime/settings.yaml" ]] && \
    [[ -r "$ROOT/runtime/go2rtc.yaml" ]] && \
    "$PYTHON" -c \
      'import sys,yaml; data=yaml.safe_load(open(sys.argv[1], encoding="utf-8")); sys.exit(0 if isinstance(data, dict) else 1)' \
      "$ROOT/runtime/settings.yaml"
}

check_launchd_definitions() {
  if [[ "$(uname -s)" != "Darwin" ]]; then
    return 1
  fi
  local agents="$HOME/Library/LaunchAgents"
  local go2rtc_plist="$agents/com.babymonitor.go2rtc.plist"
  [[ -r "$go2rtc_plist" ]] && \
    [[ -r "$agents/com.babymonitor.visual.plist" ]] && \
    [[ -r "$agents/com.babymonitor.environment-watchdog.plist" ]] && \
    [[ -r "$agents/com.babymonitor.gauge.plist" ]] && \
    "$PYTHON" -c \
      'import plistlib,sys; payload=plistlib.load(open(sys.argv[1], "rb")); expected=[sys.argv[2], "-config", sys.argv[3]]; raise SystemExit(0 if payload["Label"] == "com.babymonitor.go2rtc" and payload["ProgramArguments"] == expected else 1)' \
      "$go2rtc_plist" "$GO2RTC_EXECUTABLE" "$ROOT/runtime/go2rtc.yaml"
}

check_realtime_models() {
  "$PYTHON" "$ROOT/tools/realtime_models.py" check
}

check_voice_preflight() {
  make -C "$ROOT" --no-print-directory alpha-voice-preflight
}

check_source() {
  make -C "$ROOT" --no-print-directory alpha-source-check
}

check_guardian_focused() {
  "$PYTHON" -m pytest -q \
    tests/api/test_runtime.py \
    tests/deploy/test_guardian_commands.py \
    tests/notifications/test_guardian_dispatcher.py \
    tests/notifications/test_guardian_ntfy.py \
    tests/storage/test_visual_risk_store.py \
    tests/vision/test_evidence_files.py \
    tests/vision/test_evidence_recorder.py \
    tests/vision/test_frame_ring.py \
    tests/vision/test_notification_config.py \
    tests/vision/test_risk_event_pipeline.py \
    tests/tools/test_send_guardian_live_notification.py \
    tests/tools/test_run_visual_worker.py \
    tests/deploy/test_voice_worker_deploy.py
}

run_service_readiness() {
  local output
  output="$(BABY_MONITOR_GUARDIAN_REPORT_PHASE=service \
    bash "$ROOT/tools/guardian_readiness.sh" 2>/dev/null)"
  local seen=0
  local invalid=0
  local line
  while IFS= read -r line; do
    [[ -n "$line" ]] || continue
    case "$line" in
      "PASS service "*)
        echo "$line"
        PASS_COUNT=$((PASS_COUNT + 1))
        seen=$((seen + 1))
        ;;
      "FAIL service "*)
        echo "$line"
        FAIL_COUNT=$((FAIL_COUNT + 1))
        seen=$((seen + 1))
        ;;
      *)
        invalid=1
        ;;
    esac
  done <<EOF
$output
EOF
  if [[ "$seen" -eq 0 || "$invalid" -ne 0 ]]; then
    echo "FAIL service guardian_readiness check_failed"
    FAIL_COUNT=$((FAIL_COUNT + 1))
  fi
}

run_check "repository" "shell_policy" check_shell_policy
run_check "repository" "make_wiring" check_make_wiring
run_check "repository" "tracked_runtime" check_tracked_runtime
run_check "repository" "sensitive_literals" check_sensitive_literals
run_check "software" "python_regression" check_python_regression
run_check "installation" "required_binaries" check_required_binaries
run_check "installation" "runtime_config" check_runtime_config
run_check "installation" "launchd_definitions" check_launchd_definitions
run_check "installation" "realtime_models" check_realtime_models
run_check "installation" "voice_preflight" check_voice_preflight
run_service_readiness
run_check "media" "source_check" check_source
run_check "isolation" "guardian_focused" check_guardian_focused

echo "SUMMARY pass=$PASS_COUNT fail=$FAIL_COUNT"
if [[ "$FAIL_COUNT" -eq 0 ]]; then
  echo "guardian_test=PASS"
  exit 0
fi
echo "guardian_test=FAIL"
exit 1
