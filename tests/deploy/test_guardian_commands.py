from __future__ import annotations

import os
from pathlib import Path
import re
import shlex
import subprocess

import pytest


ROOT = Path(__file__).resolve().parents[2]
START_CHECKS = (
    "alpha_start",
    "go2rtc",
    "dashboard",
    "visual_worker",
    "environment_watchdog",
    "gauge_worker",
    "realtime_models",
    "visual_metrics",
    "semantic_review_required",
    "ollama_bridge",
)
AUTOMATIC_CHECKS = (
    "shell_policy",
    "make_wiring",
    "tracked_runtime",
    "sensitive_literals",
    "python_regression",
    "required_binaries",
    "runtime_config",
    "launchd_definitions",
    "voice_preflight",
    "source_check",
    "guardian_focused",
)
LIVE_CHECKS = ("readiness", "notification")


def _write_hook(path: Path, *, exit_code: int, counter: Path | None = None) -> None:
    lines = ["#!/bin/sh", "echo synthetic-secret >&2"]
    if counter is not None:
        lines.extend(
            [
                f"counter={shlex.quote(str(counter))}",
                'value=0; test ! -f "$counter" || value=$(cat "$counter")',
                'value=$((value + 1))',
                'printf "%s\\n" "$value" > "$counter"',
            ]
        )
    lines.append(f"exit {exit_code}")
    path.write_text("\n".join(lines) + "\n", encoding="ascii")
    path.chmod(0o755)


def _guardian_hooks(tmp_path: Path, *, failing: set[str] | None = None) -> Path:
    hook_dir = tmp_path / "hooks"
    hook_dir.mkdir()
    failures = failing or set()
    for check in dict.fromkeys(START_CHECKS + AUTOMATIC_CHECKS):
        _write_hook(
            hook_dir / check,
            exit_code=1 if check in failures else 0,
            counter=(hook_dir / "alpha_start.calls") if check == "alpha_start" else None,
        )
    return hook_dir


def _run(
    script: str,
    hook_dir: Path,
    *,
    extra_env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env.update(
        {
            "BABY_MONITOR_GUARDIAN_TEST_MODE": "1",
            "BABY_MONITOR_GUARDIAN_HOOK_DIR": str(hook_dir),
        }
    )
    env.update(extra_env or {})
    return subprocess.run(
        ["bash", script],
        cwd=ROOT,
        env=env,
        check=False,
        capture_output=True,
        text=True,
        timeout=30,
    )


def _live_hooks(
    tmp_path: Path,
    *,
    failing: set[str] | None = None,
) -> Path:
    hook_dir = tmp_path / "live-hooks"
    hook_dir.mkdir()
    failures = failing or set()
    for check in LIVE_CHECKS:
        _write_hook(
            hook_dir / check,
            exit_code=1 if check in failures else 0,
            counter=hook_dir / f"{check}.calls",
        )
    return hook_dir


def _run_live(
    tmp_path: Path,
    *,
    answers: list[str],
    failing: set[str] | None = None,
) -> tuple[subprocess.CompletedProcess[str], Path]:
    hook_dir = _live_hooks(tmp_path, failing=failing)
    env = os.environ.copy()
    env.update(
        {
            "BABY_MONITOR_GUARDIAN_LIVE_TEST_MODE": "1",
            "BABY_MONITOR_GUARDIAN_LIVE_HOOK_DIR": str(hook_dir),
        }
    )
    completed = subprocess.run(
        ["bash", "tools/test_guardian_live.sh"],
        cwd=ROOT,
        env=env,
        input="".join(f"{answer}\n" for answer in answers),
        check=False,
        capture_output=True,
        text=True,
        timeout=10,
    )
    return completed, hook_dir


def test_guardian_start_delegates_once_then_reports_all_readiness_checks(
    tmp_path: Path,
) -> None:
    hooks = _guardian_hooks(tmp_path)

    result = _run("tools/start_guardian.sh", hooks)

    assert result.returncode == 0
    assert result.stdout.splitlines() == [
        "PASS start alpha_start",
        "PASS start go2rtc",
        "PASS start dashboard",
        "PASS start visual_worker",
        "PASS start environment_watchdog",
        "PASS start gauge_worker",
        "PASS start realtime_models",
        "PASS start visual_metrics",
        "PASS start ollama_bridge",
        "guardian_start=PASS",
    ]
    assert (hooks / "alpha_start.calls").read_text(encoding="ascii") == "1\n"
    assert result.stderr == ""


def test_guardian_start_aggregates_fixed_failures_without_raw_output(
    tmp_path: Path,
) -> None:
    hooks = _guardian_hooks(tmp_path, failing={"visual_worker", "visual_metrics"})

    result = _run("tools/start_guardian.sh", hooks)

    assert result.returncode == 1
    assert "FAIL start visual_worker unavailable" in result.stdout
    assert "FAIL start visual_metrics unavailable" in result.stdout
    assert "PASS start ollama_bridge" in result.stdout
    assert result.stdout.splitlines()[-1] == "guardian_start=FAIL"
    assert "synthetic-secret" not in result.stdout + result.stderr
    assert result.stderr == ""


def test_guardian_start_output_uses_only_fixed_ascii_status_lines(tmp_path: Path) -> None:
    hooks = _guardian_hooks(tmp_path, failing={"dashboard"})

    result = _run("tools/start_guardian.sh", hooks)

    accepted = re.compile(
        r"^(?:PASS start [a-z0-9_]+|FAIL start [a-z0-9_]+ [a-z0-9_]+|guardian_start=(?:PASS|FAIL))$"
    )
    lines = result.stdout.splitlines()
    assert lines
    assert lines[-1] == "guardian_start=FAIL"
    assert all(accepted.fullmatch(line) for line in lines)


def _assert_phase_order(output: str, phases: list[str]) -> None:
    positions = []
    lines = output.splitlines()
    for phase in phases:
        positions.append(
            next(
                index
                for index, line in enumerate(lines)
                if line.startswith(f"PASS {phase} ") or line.startswith(f"FAIL {phase} ")
            )
        )
    assert positions == sorted(positions)


def test_guardian_test_runs_every_phase_and_reports_pass(tmp_path: Path) -> None:
    hooks = _guardian_hooks(tmp_path)
    files_before = {path.name for path in hooks.iterdir()}

    result = _run("tools/test_guardian.sh", hooks)

    assert result.returncode == 0
    _assert_phase_order(
        result.stdout,
        ["repository", "software", "installation", "service", "media", "isolation"],
    )
    lines = result.stdout.splitlines()
    assert lines[-2] == "SUMMARY pass=20 fail=0"
    assert lines[-1] == "guardian_test=PASS"
    assert result.stderr == ""
    assert not (hooks / "notification.calls").exists()
    assert {path.name for path in hooks.iterdir()} == files_before


def test_guardian_test_collects_later_safe_results_after_failure(
    tmp_path: Path,
) -> None:
    hooks = _guardian_hooks(tmp_path, failing={"python_regression", "source_check"})

    result = _run("tools/test_guardian.sh", hooks)

    assert result.returncode == 1
    assert "FAIL software python_regression check_failed" in result.stdout
    assert "FAIL media source_check check_failed" in result.stdout
    assert "PASS isolation guardian_focused" in result.stdout
    assert result.stdout.splitlines()[-2] == "SUMMARY pass=18 fail=2"
    assert result.stdout.splitlines()[-1] == "guardian_test=FAIL"
    assert "synthetic-secret" not in result.stdout + result.stderr
    assert result.stderr == ""


def test_guardian_test_fails_closed_when_test_hooks_are_incomplete(
    tmp_path: Path,
) -> None:
    hook_dir = tmp_path / "hooks"
    hook_dir.mkdir()

    result = _run("tools/test_guardian.sh", hook_dir)

    assert result.returncode == 1
    assert "PASS " not in result.stdout
    assert result.stdout.splitlines()[-1] == "guardian_test=FAIL"


def test_guardian_test_output_uses_only_fixed_ascii_status_lines(tmp_path: Path) -> None:
    hooks = _guardian_hooks(tmp_path, failing={"runtime_config"})

    result = _run("tools/test_guardian.sh", hooks)

    accepted = re.compile(
        r"^(?:PASS [a-z]+ [a-z0-9_]+|FAIL [a-z]+ [a-z0-9_]+ [a-z0-9_]+|SUMMARY pass=[0-9]+ fail=[0-9]+|guardian_test=(?:PASS|FAIL))$"
    )
    lines = result.stdout.splitlines()
    assert lines
    assert all(accepted.fullmatch(line) for line in lines)


def test_guardian_sensitive_scan_does_not_match_its_own_rules(tmp_path: Path) -> None:
    hooks = _guardian_hooks(tmp_path)
    (hooks / "sensitive_literals").unlink()

    result = _run(
        "tools/test_guardian.sh",
        hooks,
        extra_env={"BABY_MONITOR_GUARDIAN_REAL_CHECK": "sensitive_literals"},
    )

    assert result.returncode == 0
    assert "PASS repository sensitive_literals" in result.stdout
    assert result.stdout.splitlines()[-1] == "guardian_test=PASS"


def test_ci_fetches_history_required_by_the_sensitive_diff_gate() -> None:
    workflow = (ROOT / ".github/workflows/ci.yml").read_text(encoding="ascii")
    contracts = workflow.split("  contracts:", 1)[1].split("\n  go2rtc-patch:", 1)[0]

    assert "- uses: actions/checkout@v6\n        with:\n          fetch-depth: 0" in contracts


def test_guardian_installation_gate_requires_stable_go2rtc_app_identity() -> None:
    script = (ROOT / "tools/test_guardian.sh").read_text(encoding="ascii")

    assert 'GO2RTC_APP="$ROOT/.local/Go2RTC.app"' in script
    assert 'GO2RTC_EXECUTABLE="$GO2RTC_APP/Contents/MacOS/go2rtc"' in script
    assert 'codesign --verify --deep --strict' in script
    assert 'codesign -d -r-' in script
    assert 'designated => identifier "com.babymonitor.go2rtc"' in script
    assert '"$requirement" == *cdhash*' in script


def test_guardian_launchd_gate_requires_exact_go2rtc_app_command() -> None:
    script = (ROOT / "tools/test_guardian.sh").read_text(encoding="ascii")

    assert 'com.babymonitor.go2rtc.plist' in script
    assert 'payload["Label"] == "com.babymonitor.go2rtc"' in script
    assert 'payload["ProgramArguments"] == expected' in script


def test_makefile_exposes_guardian_commands_without_starting_services() -> None:
    start = subprocess.run(
        ["make", "-n", "alpha-guardian-start"],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    automatic = subprocess.run(
        ["make", "-n", "alpha-guardian-test"],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    live = subprocess.run(
        ["make", "-n", "alpha-guardian-test-live"],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )

    assert start.returncode == 0
    assert start.stdout.splitlines() == ["/bin/bash tools/start_guardian.sh"]
    assert automatic.returncode == 0
    assert automatic.stdout.splitlines() == ["/bin/bash tools/test_guardian.sh"]
    assert live.returncode == 0
    assert live.stdout.splitlines() == ["/bin/bash tools/test_guardian_live.sh"]
    assert start.stderr == ""
    assert automatic.stderr == ""
    assert live.stderr == ""


def test_guardian_live_success_is_simulated_and_not_physical_pass(
    tmp_path: Path,
) -> None:
    result, hooks = _run_live(tmp_path, answers=["YES"] * 6)

    assert result.returncode == 0
    assert result.stdout.splitlines() == [
        "SIMULATED live safety",
        "SIMULATED live readiness",
        "SIMULATED live notification",
        "SIMULATED live phone_a",
        "SIMULATED live phone_b",
        "SIMULATED live live_view",
        "SIMULATED live event_list",
        "guardian_live_test=SIMULATED",
    ]
    assert (hooks / "notification.calls").read_text(encoding="ascii") == "1\n"
    assert "guardian_live_test=PASS" not in result.stdout
    assert result.stderr == ""


def test_guardian_live_missing_hooks_fail_closed(tmp_path: Path) -> None:
    hook_dir = tmp_path / "empty-hooks"
    hook_dir.mkdir()
    env = os.environ.copy()
    env.update(
        {
            "BABY_MONITOR_GUARDIAN_LIVE_TEST_MODE": "1",
            "BABY_MONITOR_GUARDIAN_LIVE_HOOK_DIR": str(hook_dir),
        }
    )

    result = subprocess.run(
        ["bash", "tools/test_guardian_live.sh"],
        cwd=ROOT,
        env=env,
        input="YES\n" * 6,
        check=False,
        capture_output=True,
        text=True,
        timeout=10,
    )

    assert result.returncode == 1
    assert result.stdout.splitlines() == [
        "FAIL live readiness readiness_failed",
        "guardian_live_test=FAIL",
    ]
    assert result.stderr == ""


@pytest.mark.parametrize("answers", [["NO"], ["YES", "NO"]])
def test_guardian_live_safety_rejection_prevents_external_checks(
    tmp_path: Path,
    answers: list[str],
) -> None:
    result, hooks = _run_live(tmp_path, answers=answers)

    assert result.returncode == 1
    assert result.stdout.splitlines() == [
        "FAIL live safety safety_not_confirmed",
        "guardian_live_test=FAIL",
    ]
    assert not (hooks / "readiness.calls").exists()
    assert not (hooks / "notification.calls").exists()
    assert result.stderr == ""


@pytest.mark.parametrize("answer", ["yes", " YES", "YES ", "", " yes "])
def test_guardian_live_requires_exact_yes(
    tmp_path: Path,
    answer: str,
) -> None:
    result, hooks = _run_live(tmp_path, answers=[answer])

    assert result.returncode == 1
    assert "FAIL live safety safety_not_confirmed" in result.stdout
    assert not (hooks / "readiness.calls").exists()
    assert not (hooks / "notification.calls").exists()


def test_guardian_live_eof_fails_closed(tmp_path: Path) -> None:
    result, hooks = _run_live(tmp_path, answers=[])

    assert result.returncode == 1
    assert result.stdout.splitlines() == [
        "FAIL live safety safety_not_confirmed",
        "guardian_live_test=FAIL",
    ]
    assert not (hooks / "notification.calls").exists()


def test_guardian_live_readiness_failure_prevents_notification(
    tmp_path: Path,
) -> None:
    result, hooks = _run_live(
        tmp_path,
        answers=["YES", "YES"],
        failing={"readiness"},
    )

    assert result.returncode == 1
    assert result.stdout.splitlines() == [
        "SIMULATED live safety",
        "FAIL live readiness readiness_failed",
        "guardian_live_test=FAIL",
    ]
    assert (hooks / "readiness.calls").read_text(encoding="ascii") == "1\n"
    assert not (hooks / "notification.calls").exists()
    assert "synthetic-secret" not in result.stdout + result.stderr


def test_guardian_live_notification_failure_is_redacted_and_not_retried(
    tmp_path: Path,
) -> None:
    result, hooks = _run_live(
        tmp_path,
        answers=["YES", "YES"],
        failing={"notification"},
    )

    assert result.returncode == 1
    assert result.stdout.splitlines() == [
        "SIMULATED live safety",
        "SIMULATED live readiness",
        "FAIL live notification notification_failed",
        "guardian_live_test=FAIL",
    ]
    assert (hooks / "notification.calls").read_text(encoding="ascii") == "1\n"
    assert "synthetic-secret" not in result.stdout + result.stderr
    assert result.stderr == ""


@pytest.mark.parametrize(
    ("answers", "stage", "code", "completed"),
    [
        (["YES", "YES", "NO"], "phone_a", "phone_a_unconfirmed", []),
        (
            ["YES", "YES", "YES", "NO"],
            "phone_b",
            "phone_b_unconfirmed",
            ["phone_a"],
        ),
        (
            ["YES", "YES", "YES", "YES", "NO"],
            "live_view",
            "live_view_unconfirmed",
            ["phone_a", "phone_b"],
        ),
        (
            ["YES", "YES", "YES", "YES", "YES", "NO"],
            "event_list",
            "event_list_unconfirmed",
            ["phone_a", "phone_b", "live_view"],
        ),
    ],
)
def test_guardian_live_manual_stage_failures_stop_in_order(
    tmp_path: Path,
    answers: list[str],
    stage: str,
    code: str,
    completed: list[str],
) -> None:
    result, hooks = _run_live(tmp_path, answers=answers)

    assert result.returncode == 1
    lines = result.stdout.splitlines()
    assert lines[:3] == [
        "SIMULATED live safety",
        "SIMULATED live readiness",
        "SIMULATED live notification",
    ]
    for completed_stage in completed:
        assert f"SIMULATED live {completed_stage}" in lines
    assert lines[-2:] == [
        f"FAIL live {stage} {code}",
        "guardian_live_test=FAIL",
    ]
    assert (hooks / "notification.calls").read_text(encoding="ascii") == "1\n"


def test_guardian_live_output_uses_only_closed_ascii_status_lines(
    tmp_path: Path,
) -> None:
    result, _ = _run_live(tmp_path, answers=["YES"] * 6)
    accepted = re.compile(
        r"^(?:SIMULATED live [a-z0-9_]+|FAIL live [a-z0-9_]+ [a-z0-9_]+|guardian_live_test=(?:SIMULATED|FAIL))$"
    )

    assert result.stdout.splitlines()
    assert all(accepted.fullmatch(line) for line in result.stdout.splitlines())
    assert result.stderr == ""


def test_guardian_live_production_requires_terminal_before_side_effects() -> None:
    env = os.environ.copy()
    env.pop("BABY_MONITOR_GUARDIAN_LIVE_TEST_MODE", None)
    env.pop("BABY_MONITOR_GUARDIAN_LIVE_HOOK_DIR", None)
    env["NTFY_TOPIC"] = "must-not-be-used"

    result = subprocess.run(
        ["bash", "tools/test_guardian_live.sh"],
        cwd=ROOT,
        env=env,
        input="YES\n" * 6,
        check=False,
        capture_output=True,
        text=True,
        timeout=10,
    )

    assert result.returncode == 1
    assert result.stdout.splitlines() == [
        "FAIL live interactive interactive_required",
        "guardian_live_test=FAIL",
    ]
    assert "must-not-be-used" not in result.stdout + result.stderr
    assert result.stderr == ""


def test_automatic_guardian_test_never_invokes_live_notification(
    tmp_path: Path,
) -> None:
    hooks = _guardian_hooks(tmp_path)
    live_counter = hooks / "live_notification.calls"
    _write_hook(hooks / "notification", exit_code=0, counter=live_counter)

    result = _run(
        "tools/test_guardian.sh",
        hooks,
        extra_env={
            "BABY_MONITOR_GUARDIAN_LIVE_TEST_MODE": "1",
            "BABY_MONITOR_GUARDIAN_LIVE_HOOK_DIR": str(hooks),
        },
    )

    assert result.returncode == 0
    assert result.stdout.splitlines()[-1] == "guardian_test=PASS"
    assert not live_counter.exists()
