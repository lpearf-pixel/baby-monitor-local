from __future__ import annotations

import os
import plistlib
import subprocess
import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[2]


def tunnel_project(tmp_path: Path) -> Path:
    project = tmp_path / "project"
    template = project / "deploy/launchd/com.babymonitor.ollama-tunnel.plist.example"
    template.parent.mkdir(parents=True)
    template.write_bytes(
        (ROOT / "deploy/launchd/com.babymonitor.ollama-tunnel.plist.example").read_bytes()
    )
    return project


def test_visual_launch_agent_is_independent_and_redacted() -> None:
    path = ROOT / "deploy/launchd/com.babymonitor.visual.plist.example"
    with path.open("rb") as source:
        payload = plistlib.load(source)

    assert payload["Label"] == "com.babymonitor.visual"
    assert payload["KeepAlive"] == {"SuccessfulExit": False}
    assert payload["RunAtLoad"] is True
    assert payload["ProcessType"] == "Interactive"
    arguments = payload["ProgramArguments"]
    assert any(str(value).endswith("tools/run_visual_worker.py") for value in arguments)
    assert "--settings" in arguments
    serialized = path.read_text(encoding="utf-8").lower()
    assert "token=" not in serialized
    assert "password=" not in serialized
    assert "go2rtc" not in serialized
    assert "uvicorn" not in serialized


def test_ollama_tunnel_agent_is_one_restricted_local_forward() -> None:
    path = ROOT / "deploy/launchd/com.babymonitor.ollama-tunnel.plist.example"
    with path.open("rb") as source:
        payload = plistlib.load(source)

    assert payload["Label"] == "com.babymonitor.ollama-tunnel"
    assert payload["KeepAlive"] == {"SuccessfulExit": False}
    assert payload["RunAtLoad"] is True
    assert payload["ProcessType"] == "Background"
    arguments = payload["ProgramArguments"]
    assert arguments[0] == "/usr/bin/ssh"
    assert "-N" in arguments
    assert "-T" in arguments
    assert "BatchMode=yes" in arguments
    assert "ExitOnForwardFailure=yes" in arguments
    assert "IdentitiesOnly=yes" in arguments
    assert "StrictHostKeyChecking=yes" in arguments
    assert "127.0.0.1:11435:127.0.0.1:11434" in arguments
    assert arguments.count("-L") == 1
    serialized = path.read_text(encoding="utf-8").lower()
    assert "password=" not in serialized
    assert "0.0.0.0" not in serialized
    assert "remotecommand" not in serialized


def test_tunnel_configurator_writes_only_redacted_local_plists(tmp_path: Path) -> None:
    from tools.configure_ollama_tunnel import configure_tunnel

    home = tmp_path / "home"
    identity = home / ".ssh/baby-monitor-m2"
    identity.parent.mkdir(parents=True)
    identity.write_text("synthetic-test-key", encoding="utf-8")
    identity.chmod(0o600)
    project = tunnel_project(tmp_path)

    runtime_path, launch_path = configure_tunnel(
        target="monitor@192.168.50.10",
        identity=identity,
        project_root=project,
        home=home,
    )

    assert runtime_path == project / "runtime/launchd/com.babymonitor.ollama-tunnel.plist"
    assert launch_path == home / "Library/LaunchAgents/com.babymonitor.ollama-tunnel.plist"
    assert runtime_path.read_bytes() == launch_path.read_bytes()
    with runtime_path.open("rb") as source:
        payload = plistlib.load(source)
    arguments = payload["ProgramArguments"]
    assert "monitor@192.168.50.10" in arguments
    assert str(identity.resolve()) in arguments
    assert all("__" not in str(value) for value in arguments)
    assert os.stat(runtime_path).st_mode & 0o777 == 0o600


@pytest.mark.parametrize(
    "target",
    [
        "monitor@example.com",
        "monitor@0.0.0.0",
        "monitor@127.0.0.1",
        "monitor@192.168.50.10;touch-bad",
        "monitor with space@192.168.50.10",
    ],
)
def test_tunnel_configurator_rejects_public_or_unsafe_targets(
    tmp_path: Path,
    target: str,
) -> None:
    from tools.configure_ollama_tunnel import configure_tunnel

    home = tmp_path / "home"
    identity = home / ".ssh/baby-monitor-m2"
    identity.parent.mkdir(parents=True)
    identity.write_text("synthetic-test-key", encoding="utf-8")
    identity.chmod(0o600)
    project = tunnel_project(tmp_path)

    with pytest.raises(ValueError, match="private M2 SSH target"):
        configure_tunnel(
            target=target,
            identity=identity,
            project_root=project,
            home=home,
        )


def test_tunnel_configurator_rejects_unsafe_identity_file(tmp_path: Path) -> None:
    from tools.configure_ollama_tunnel import configure_tunnel

    home = tmp_path / "home"
    identity = home / ".ssh/baby-monitor-m2"
    identity.parent.mkdir(parents=True)
    identity.write_text("synthetic-test-key", encoding="utf-8")
    identity.chmod(0o644)
    project = tunnel_project(tmp_path)

    with pytest.raises(ValueError, match="mode 400 or 600"):
        configure_tunnel(
            target="monitor@m2-monitor.local",
            identity=identity,
            project_root=project,
            home=home,
        )


def test_alpha_scripts_manage_visual_services_without_coupling() -> None:
    start = (ROOT / "tools/start_alpha.sh").read_text(encoding="utf-8")
    stop = (ROOT / "tools/stop_alpha.sh").read_text(encoding="utf-8")
    makefile = (ROOT / "Makefile").read_text(encoding="utf-8")

    assert "com.babymonitor.visual" in start
    assert "com.babymonitor.ollama-tunnel" in start
    assert "run_visual_worker.py" in start
    assert "com.babymonitor.visual" in stop
    assert "com.babymonitor.ollama-tunnel" in stop
    assert "alpha-visual-status:" in makefile
    status_body = makefile.split("alpha-visual-status:", 1)[1]
    assert "127.0.0.1:11435" in status_body
    assert "api/version" in status_body
    assert "alpha-logs" not in status_body


def test_installer_renders_visual_worker_but_not_unconfigured_tunnel() -> None:
    content = (ROOT / "tools/install_alpha_macos.sh").read_text(encoding="utf-8")

    assert "com.babymonitor.visual.plist.example" in content
    assert "runtime/launchd/com.babymonitor.visual.plist" in content
    assert "Library/LaunchAgents/com.babymonitor.visual.plist" in content
    assert "configure_ollama_tunnel.py" in content
    assert "com.babymonitor.ollama-tunnel.plist.example" not in content


def test_visual_worker_entrypoint_has_safe_help_without_starting_services() -> None:
    result = subprocess.run(
        [
            sys.executable,
            str(ROOT / "tools/run_visual_worker.py"),
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


def test_disabled_visual_worker_exits_without_opening_runtime_services(
    tmp_path: Path,
) -> None:
    settings_path = tmp_path / "settings.yaml"
    settings_path.write_text(
        (ROOT / "config/settings.example.yaml").read_text(encoding="utf-8"),
        encoding="utf-8",
    )

    result = subprocess.run(
        [
            sys.executable,
            str(ROOT / "tools/run_visual_worker.py"),
            "--settings",
            str(settings_path),
        ],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
        timeout=5,
    )

    assert result.returncode == 0
    assert result.stdout == ""
    assert result.stderr == ""


def test_invalid_visual_worker_configuration_is_redacted(tmp_path: Path) -> None:
    settings_path = tmp_path / "private-family-settings.yaml"
    settings_path.write_text("visual: [invalid", encoding="utf-8")

    result = subprocess.run(
        [
            sys.executable,
            str(ROOT / "tools/run_visual_worker.py"),
            "--settings",
            str(settings_path),
        ],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
        timeout=5,
    )

    assert result.returncode == 2
    assert result.stderr.strip() == "visual_worker_startup_failed"
    assert "private-family" not in result.stderr
    assert "Traceback" not in result.stderr
