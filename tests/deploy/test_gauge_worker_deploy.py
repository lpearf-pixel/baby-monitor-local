from __future__ import annotations

import plistlib
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def test_gauge_launch_agent_is_independent_and_contains_no_secrets() -> None:
    path = ROOT / "deploy/launchd/com.babymonitor.gauge.plist.example"
    with path.open("rb") as source:
        payload = plistlib.load(source)

    assert payload["Label"] == "com.babymonitor.gauge"
    assert payload["KeepAlive"] == {"SuccessfulExit": False}
    assert payload["RunAtLoad"] is True
    assert payload["ProcessType"] == "Background"
    arguments = payload["ProgramArguments"]
    assert any(str(value).endswith("tools/run_gauge_worker.py") for value in arguments)
    assert "--settings" in arguments
    serialized = path.read_text(encoding="utf-8").lower()
    assert "ollama" not in serialized
    assert "qwen" not in serialized
    assert "token=" not in serialized
    assert "password=" not in serialized


def test_gauge_worker_entrypoint_has_safe_help_without_starting_services() -> None:
    result = subprocess.run(
        [
            str(ROOT / ".venv-alpha/bin/python"),
            str(ROOT / "tools/run_gauge_worker.py"),
            "--help",
        ],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0
    assert "--settings" in result.stdout
    assert "Traceback" not in result.stderr


def test_alpha_start_runs_gauge_as_a_separate_pid() -> None:
    content = (ROOT / "tools/start_alpha.sh").read_text(encoding="utf-8")

    assert 'GAUGE_PID="$ROOT/runtime/pids/gauge.pid"' in content
    assert 'tools/run_gauge_worker.py' in content
    assert 'BABY_MONITOR_SETTINGS_PATH' in content
    assert "launchctl bootstrap" in content
    assert "com.babymonitor.gauge" in content
    assert "com.babymonitor.environment-watchdog" in content
    assert "run_environment_watchdog.py" in content

    stop = (ROOT / "tools/stop_alpha.sh").read_text(encoding="utf-8")
    assert "launchctl bootout" in stop


def test_installer_renders_local_launch_agent_without_loading_it() -> None:
    content = (ROOT / "tools/install_alpha_macos.sh").read_text(encoding="utf-8")

    assert "com.babymonitor.gauge.plist.example" in content
    assert "com.babymonitor.environment-watchdog.plist.example" in content
    assert 'runtime/launchd/com.babymonitor.gauge.plist' in content
    assert 'Library/LaunchAgents/com.babymonitor.gauge.plist' in content
    assert "launchctl load" not in content
    assert "launchctl bootstrap" not in content


def test_independent_watchdog_launch_agent_is_restart_safe_and_redacted() -> None:
    path = (
        ROOT
        / "deploy/launchd/com.babymonitor.environment-watchdog.plist.example"
    )
    with path.open("rb") as source:
        payload = plistlib.load(source)

    assert payload["Label"] == "com.babymonitor.environment-watchdog"
    assert payload["KeepAlive"] == {"SuccessfulExit": False}
    assert payload["RunAtLoad"] is True
    assert any(
        str(value).endswith("tools/run_environment_watchdog.py")
        for value in payload["ProgramArguments"]
    )
    serialized = path.read_text(encoding="utf-8").lower()
    assert "ollama" not in serialized
    assert "qwen" not in serialized
    assert "token=" not in serialized
    assert "password=" not in serialized


def test_disabled_environment_exits_successfully_without_keepalive_loop(
    tmp_path: Path,
) -> None:
    settings = (ROOT / "config/settings.example.yaml").read_text(encoding="utf-8")
    settings = settings.replace("  enabled: true\n", "  enabled: false\n", 1)
    settings_path = tmp_path / "settings.yaml"
    settings_path.write_text(settings, encoding="utf-8")

    result = subprocess.run(
        [
            str(ROOT / ".venv-alpha/bin/python"),
            str(ROOT / "tools/run_gauge_worker.py"),
            "--settings",
            str(settings_path),
        ],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0
    assert "Traceback" not in result.stderr
