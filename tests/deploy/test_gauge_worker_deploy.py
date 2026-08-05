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
    assert payload["KeepAlive"] is True
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


def test_installer_renders_local_launch_agent_without_loading_it() -> None:
    content = (ROOT / "tools/install_alpha_macos.sh").read_text(encoding="utf-8")

    assert "com.babymonitor.gauge.plist.example" in content
    assert 'runtime/launchd/com.babymonitor.gauge.plist' in content
    assert "launchctl load" not in content
    assert "launchctl bootstrap" not in content
