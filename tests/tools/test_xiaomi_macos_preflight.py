from __future__ import annotations

import sys
import time
from pathlib import Path

from packages.monitoring.xiaomi_macos_preflight import MacOSMediaPreflight
from tools.xiaomi_macos_preflight import format_report, run_bounded


def test_cli_report_contains_only_fixed_aggregate_fields() -> None:
    report = MacOSMediaPreflight(
        code="ready",
        app_identity_ready=True,
        launchd_owner_count=1,
        listener_owned_by_launchd=True,
        local_network_state="available",
    )

    output = format_report(report)

    assert output == (
        "result=PASS",
        "operation=xiaomi-media-preflight",
        "code=ready",
        "app_identity_ready=true",
        "launchd_owner_count=1",
        "listener_owned_by_launchd=true",
        "local_network_state=available",
    )


def test_cli_report_never_contains_command_output_or_local_paths() -> None:
    report = MacOSMediaPreflight(
        code="local_network_unknown",
        app_identity_ready=True,
        launchd_owner_count=1,
        listener_owned_by_launchd=True,
        local_network_state="unknown",
    )

    combined = "\n".join(format_report(report))

    assert "FAIL" in combined
    assert "/Users/" not in combined
    assert "pid=" not in combined
    assert "exception" not in combined.lower()


def test_bounded_runner_uses_devnull_stdin_and_captures_small_output() -> None:
    result = run_bounded(
        (
            sys.executable,
            "-c",
            "import sys; data=sys.stdin.buffer.read(); print(len(data))",
        ),
        1.0,
    )

    assert result.started is True
    assert result.returncode == 0
    assert result.stdout == b"0\n"
    assert result.stderr == b""


def test_bounded_runner_settles_timeout_without_returning_child_output() -> None:
    started = time.monotonic()

    result = run_bounded(
        (sys.executable, "-c", "import time; print('private'); time.sleep(5)"),
        0.1,
    )

    assert time.monotonic() - started < 2.0
    assert result.started is True
    assert result.returncode is None
    assert result.stdout == b""
    assert result.stderr == b""


def test_bounded_runner_rejects_output_over_fixed_cap() -> None:
    result = run_bounded(
        (sys.executable, "-c", "import sys; sys.stdout.write('x' * 1048577)"),
        2.0,
    )

    assert result.started is True
    assert result.returncode is None
    assert result.stdout == b""
    assert result.stderr == b""


def test_bounded_runner_does_not_interpret_shell_metacharacters(tmp_path: Path) -> None:
    marker = tmp_path / "should-not-exist"

    result = run_bounded(("/bin/echo", f"safe;touch {marker}"), 1.0)

    assert result.returncode == 0
    assert not marker.exists()
