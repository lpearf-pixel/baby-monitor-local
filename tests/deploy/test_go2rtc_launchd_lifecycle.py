from __future__ import annotations

import os
import plistlib
import shutil
import subprocess
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[2]


def _write_executable(path: Path, content: str) -> None:
    path.write_text(content, encoding="ascii")
    path.chmod(0o755)


def test_go2rtc_launchd_template_has_single_project_owned_command() -> None:
    with (ROOT / "deploy/launchd/com.babymonitor.go2rtc.plist.example").open(
        "rb"
    ) as handle:
        plist = plistlib.load(handle)

    assert plist["Label"] == "com.babymonitor.go2rtc"
    assert plist["ProgramArguments"] == [
        "__PROJECT_ROOT__/.local/bin/go2rtc",
        "-config",
        "__PROJECT_ROOT__/runtime/go2rtc.yaml",
    ]
    assert plist["WorkingDirectory"] == "__PROJECT_ROOT__"
    assert plist["RunAtLoad"] is True
    assert plist["KeepAlive"] == {"SuccessfulExit": False}


def test_installer_renders_and_installs_go2rtc_launch_agent() -> None:
    installer = (ROOT / "tools/install_alpha_macos.sh").read_text(encoding="ascii")

    assert '"$ROOT/deploy/launchd/com.babymonitor.go2rtc.plist.example"' in installer
    assert '>"$ROOT/runtime/launchd/com.babymonitor.go2rtc.plist"' in installer
    assert '"$HOME/Library/LaunchAgents/com.babymonitor.go2rtc.plist"' in installer


def _launchd_project(
    tmp_path: Path,
    *,
    go2rtc_loaded: bool = False,
    api_ready: bool = False,
    bootstrap_fails: bool = False,
) -> tuple[Path, dict[str, str], Path, Path]:
    project = tmp_path / "project"
    (project / "tools").mkdir(parents=True)
    shutil.copy2(ROOT / "tools/start_alpha.sh", project / "tools/start_alpha.sh")
    shutil.copy2(ROOT / "tools/stop_alpha.sh", project / "tools/stop_alpha.sh")
    (project / "runtime/pids").mkdir(parents=True)
    (project / "runtime/logs").mkdir(parents=True)
    (project / "runtime/launchd").mkdir(parents=True)
    (project / "runtime/settings.yaml").write_text(
        "environment: {}\n", encoding="ascii"
    )
    (project / "runtime/go2rtc.yaml").write_text(
        "streams: {}\n", encoding="ascii"
    )
    (project / "runtime/alpha.env").write_text(
        f"BABY_MONITOR_SETTINGS_PATH={project}/runtime/settings.yaml\n",
        encoding="ascii",
    )

    direct_marker = tmp_path / "direct-go2rtc.marker"
    (project / ".local/bin").mkdir(parents=True)
    _write_executable(
        project / ".local/bin/go2rtc",
        "#!/bin/sh\n: > \"$DIRECT_GO2RTC_MARKER\"\n",
    )
    (project / ".venv-alpha/bin").mkdir(parents=True)
    _write_executable(project / ".venv-alpha/bin/uvicorn", "#!/bin/sh\nexit 0\n")

    home = tmp_path / "home"
    agents = home / "Library/LaunchAgents"
    agents.mkdir(parents=True)
    labels = (
        "com.babymonitor.go2rtc",
        "com.babymonitor.ollama-tunnel",
        "com.babymonitor.visual",
        "com.babymonitor.audio",
        "com.babymonitor.environment-watchdog",
        "com.babymonitor.gauge",
    )
    for label in labels:
        plist = f"<plist><dict><key>Label</key><string>{label}</string></dict></plist>\n"
        (agents / f"{label}.plist").write_text(plist, encoding="ascii")
        (project / "runtime/launchd" / f"{label}.plist").write_text(
            plist, encoding="ascii"
        )

    state_dir = tmp_path / "launchctl-state"
    state_dir.mkdir()
    if go2rtc_loaded:
        (state_dir / "com.babymonitor.go2rtc").touch()
    if api_ready:
        (state_dir / "go2rtc-api-ready").touch()

    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    _write_executable(fake_bin / "uname", "#!/bin/sh\necho Darwin\n")
    _write_executable(fake_bin / "id", "#!/bin/sh\necho 501\n")
    _write_executable(fake_bin / "route", "#!/bin/sh\nexit 0\n")
    _write_executable(fake_bin / "sleep", "#!/bin/sh\n/bin/sleep 0.01\n")
    _write_executable(
        fake_bin / "ps",
        "#!/bin/sh\n"
        "if test \"$FAKE_PS_IDENTITY\" = expected; then\n"
        "  echo \"$GO2RTC_EXPECTED_COMMAND\"\n"
        "else\n"
        "  echo /usr/bin/unrelated-process\n"
        "fi\n",
    )
    _write_executable(
        fake_bin / "curl",
        "#!/bin/sh\n"
        "case \"$*\" in\n"
        "  *127.0.0.1:1984/api*)\n"
        "    test -f \"$FAKE_LAUNCHCTL_STATE_DIR/go2rtc-api-ready\" || "
        "test -f \"$DIRECT_GO2RTC_MARKER\"\n"
        "    ;;\n"
        "  *) exit 0 ;;\n"
        "esac\n",
    )
    _write_executable(
        fake_bin / "lsof",
        "#!/bin/sh\n"
        "if test -n \"${FAKE_LSOF_PID:-}\"; then echo \"$FAKE_LSOF_PID\"; fi\n",
    )
    _write_executable(
        fake_bin / "launchctl",
        """#!/bin/sh
set -eu
command=$1
shift
case $command in
  print)
    target=$1
    label=${target##*/}
    test -f "$FAKE_LAUNCHCTL_STATE_DIR/$label" || exit 1
    if test "$label" = com.babymonitor.go2rtc; then
      echo 'pid = 4242'
    fi
    ;;
  bootstrap)
    domain=$1
    plist=$2
    label=${plist##*/}
    label=${label%.plist}
    printf 'bootstrap %s\n' "$label" >> "$FAKE_LAUNCHCTL_STATE_DIR/calls"
    if test "$label" = com.babymonitor.go2rtc && test "$FAKE_BOOTSTRAP_FAILS" = 1; then
      exit 5
    fi
    : > "$FAKE_LAUNCHCTL_STATE_DIR/$label"
    if test "$label" = com.babymonitor.go2rtc; then
      : > "$FAKE_LAUNCHCTL_STATE_DIR/go2rtc-api-ready"
    fi
    ;;
  kickstart)
    test "$1" = -k
    target=$2
    label=${target##*/}
    printf 'kickstart %s\n' "$label" >> "$FAKE_LAUNCHCTL_STATE_DIR/calls"
    : > "$FAKE_LAUNCHCTL_STATE_DIR/go2rtc-api-ready"
    ;;
  bootout)
    target=$1
    label=${target##*/}
    printf 'bootout %s\n' "$label" >> "$FAKE_LAUNCHCTL_STATE_DIR/calls"
    rm -f "$FAKE_LAUNCHCTL_STATE_DIR/$label"
    if test "$label" = com.babymonitor.go2rtc; then
      rm -f "$FAKE_LAUNCHCTL_STATE_DIR/go2rtc-api-ready"
    fi
    ;;
  *) exit 2 ;;
esac
""",
    )

    environment = os.environ.copy()
    environment.update(
        {
            "HOME": str(home),
            "PATH": f"{fake_bin}:{environment['PATH']}",
            "FAKE_LAUNCHCTL_STATE_DIR": str(state_dir),
            "FAKE_BOOTSTRAP_FAILS": "1" if bootstrap_fails else "0",
            "FAKE_PS_IDENTITY": "expected",
            "GO2RTC_EXPECTED_COMMAND": (
                f"{project}/.local/bin/go2rtc -config "
                f"{project}/runtime/go2rtc.yaml"
            ),
            "DIRECT_GO2RTC_MARKER": str(direct_marker),
        }
    )
    return project, environment, state_dir, direct_marker


def _run(
    script: str,
    project: Path,
    environment: dict[str, str],
    *arguments: str,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["bash", script, *arguments],
        cwd=project,
        env=environment,
        check=False,
        capture_output=True,
        text=True,
        timeout=20,
    )


def test_alpha_start_does_not_direct_launch_when_go2rtc_bootstrap_fails(
    tmp_path: Path,
) -> None:
    project, environment, _, direct_marker = _launchd_project(
        tmp_path, bootstrap_fails=True
    )

    result = _run("tools/start_alpha.sh", project, environment)

    assert result.returncode != 0
    assert "go2rtc launchd start failed" in result.stderr
    assert not direct_marker.exists()


def test_alpha_start_kickstarts_loaded_unhealthy_go2rtc_without_bootout(
    tmp_path: Path,
) -> None:
    project, environment, state_dir, direct_marker = _launchd_project(
        tmp_path, go2rtc_loaded=True
    )

    result = _run("tools/start_alpha.sh", project, environment)

    assert result.returncode == 0, result.stderr
    calls = (state_dir / "calls").read_text(encoding="ascii").splitlines()
    assert calls.count("kickstart com.babymonitor.go2rtc") == 1
    assert "bootout com.babymonitor.go2rtc" not in calls
    assert "bootstrap com.babymonitor.go2rtc" not in calls
    assert not direct_marker.exists()


def test_alpha_start_rejects_healthy_api_from_unrelated_loaded_job(
    tmp_path: Path,
) -> None:
    project, environment, _, direct_marker = _launchd_project(
        tmp_path, go2rtc_loaded=True, api_ready=True
    )
    environment["FAKE_PS_IDENTITY"] = "unrelated"

    result = _run("tools/start_alpha.sh", project, environment)

    assert result.returncode != 0
    assert result.stderr.strip() == "go2rtc launchd identity mismatch"
    assert not direct_marker.exists()


def test_go2rtc_only_restart_kickstarts_no_sibling_service(
    tmp_path: Path,
) -> None:
    project, environment, state_dir, direct_marker = _launchd_project(
        tmp_path, go2rtc_loaded=True, api_ready=True
    )

    result = _run(
        "tools/start_alpha.sh", project, environment, "--go2rtc-only-restart"
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout.splitlines() == ["go2rtc_restart=PASS"]
    calls = (state_dir / "calls").read_text(encoding="ascii").splitlines()
    assert calls == ["kickstart com.babymonitor.go2rtc"]
    assert not direct_marker.exists()


def test_make_exposes_go2rtc_only_restart() -> None:
    result = subprocess.run(
        ["make", "-n", "alpha-go2rtc-restart"],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr
    assert "tools/start_alpha.sh --go2rtc-only-restart" in result.stdout


def test_alpha_stop_does_not_kill_listener_or_stale_pid_on_macos(
    tmp_path: Path, request: pytest.FixtureRequest
) -> None:
    project, environment, state_dir, _ = _launchd_project(
        tmp_path, go2rtc_loaded=True, api_ready=True
    )
    unrelated = subprocess.Popen([shutil.which("sleep") or "/bin/sleep", "60"])

    def cleanup() -> None:
        if unrelated.poll() is None:
            unrelated.terminate()
            unrelated.wait(timeout=2)

    request.addfinalizer(cleanup)
    (project / "runtime/pids/go2rtc.pid").write_text(
        f"{unrelated.pid}\n", encoding="ascii"
    )
    environment["FAKE_LSOF_PID"] = str(unrelated.pid)

    result = _run("tools/stop_alpha.sh", project, environment)

    assert result.returncode == 0, result.stderr
    assert unrelated.poll() is None
    calls = (state_dir / "calls").read_text(encoding="ascii").splitlines()
    assert calls.count("bootout com.babymonitor.go2rtc") == 1
