from __future__ import annotations

import os
from pathlib import Path
import re
import shlex
import subprocess


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
    "source_check",
    "guardian_focused",
)


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
        timeout=10,
    )


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
    assert lines[-2] == "SUMMARY pass=19 fail=0"
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
    assert result.stdout.splitlines()[-2] == "SUMMARY pass=17 fail=2"
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
