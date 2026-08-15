from __future__ import annotations

import atexit
import os
import shutil
import subprocess
from pathlib import Path

import pytest
import yaml


ROOT = Path(__file__).resolve().parents[2]


def _write_executable(path: Path, content: str) -> None:
    path.write_text(content, encoding="ascii")
    path.chmod(0o755)


class _Go2rtcStartFixture:
    def __init__(
        self,
        project: Path,
        marker: Path,
        original: subprocess.Popen[str],
        environment: dict[str, str],
    ):
        self.project = project
        self.replacement_marker = marker
        self._original = original
        self._environment = environment

    def run_start(self) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            ["bash", "tools/start_alpha.sh"],
            cwd=self.project,
            env=self._environment,
            check=False,
            capture_output=True,
            text=True,
        )

    def original_pid_is_alive(self) -> bool:
        return self._original.poll() is None


def _go2rtc_start_fixture(
    tmp_path: Path, *, ps_identity: str
) -> _Go2rtcStartFixture:
    project = tmp_path / "project"
    (project / "tools").mkdir(parents=True)
    shutil.copy2(ROOT / "tools/start_alpha.sh", project / "tools/start_alpha.sh")
    (project / "runtime/pids").mkdir(parents=True)
    (project / "runtime/logs").mkdir(parents=True)
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
    (project / ".local/bin").mkdir(parents=True)
    (project / ".venv-alpha/bin").mkdir(parents=True)

    marker = tmp_path / "replacement.marker"
    _write_executable(
        project / ".local/bin/go2rtc",
        "#!/bin/sh\n: > \"$GO2RTC_REPLACEMENT_MARKER\"\n",
    )
    _write_executable(project / ".venv-alpha/bin/uvicorn", "#!/bin/sh\nexit 0\n")

    original = subprocess.Popen([shutil.which("sleep") or "/bin/sleep", "60"])

    def cleanup_original() -> None:
        if original.poll() is None:
            original.terminate()
        try:
            original.wait(timeout=1)
        except subprocess.TimeoutExpired:
            original.kill()
            original.wait()

    atexit.register(cleanup_original)
    (project / "runtime/pids/go2rtc.pid").write_text(
        f"{original.pid}\n", encoding="ascii"
    )

    home = tmp_path / "home"
    agents = home / "Library/LaunchAgents"
    agents.mkdir(parents=True)
    labels = (
        "com.babymonitor.ollama-tunnel",
        "com.babymonitor.visual",
        "com.babymonitor.environment-watchdog",
        "com.babymonitor.gauge",
    )
    for label in labels:
        (agents / f"{label}.plist").write_text("synthetic plist\n", encoding="ascii")

    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    state_dir = tmp_path / "launchctl-state"
    state_dir.mkdir()
    _write_executable(
        fake_bin / "curl",
        "#!/bin/sh\ntest -f \"$GO2RTC_REPLACEMENT_MARKER\"\n",
    )
    _write_executable(fake_bin / "id", "#!/bin/sh\necho 501\n")
    _write_executable(fake_bin / "route", "#!/bin/sh\nexit 0\n")
    _write_executable(fake_bin / "sleep", "#!/bin/sh\n/bin/sleep 0.01\n")
    _write_executable(fake_bin / "uname", "#!/bin/sh\necho Darwin\n")
    _write_executable(
        fake_bin / "ps",
        """#!/bin/sh
if [ "$FAKE_PS_IDENTITY" = expected ]; then
  echo "$GO2RTC_EXPECTED_COMMAND"
else
  echo "/usr/bin/unrelated-process"
fi
""",
    )
    _write_executable(
        fake_bin / "launchctl",
        """#!/bin/sh
set -eu
command=$1
target=$2
label=${target##*/}
state=$FAKE_LAUNCHCTL_STATE_DIR/$label
case $command in
  print)
    test -f "$state"
    ;;
  bootstrap)
    plist=$3
    label=${plist##*/}
    label=${label%.plist}
    : > "$FAKE_LAUNCHCTL_STATE_DIR/$label"
    ;;
  *)
    exit 2
    ;;
esac
""",
    )

    environment = os.environ.copy()
    environment.update(
        {
            "HOME": str(home),
            "PATH": f"{fake_bin}:{environment['PATH']}",
            "FAKE_LAUNCHCTL_STATE_DIR": str(state_dir),
            "FAKE_PS_IDENTITY": ps_identity,
            "GO2RTC_EXPECTED_COMMAND": (
                f"{project}/.local/bin/go2rtc -config {project}/runtime/go2rtc.yaml"
            ),
            "GO2RTC_REPLACEMENT_MARKER": str(marker),
        }
    )
    return _Go2rtcStartFixture(project, marker, original, environment)


def test_alpha_start_replaces_verified_live_but_unhealthy_go2rtc(tmp_path: Path) -> None:
    fixture = _go2rtc_start_fixture(tmp_path, ps_identity="expected")
    result = fixture.run_start()

    assert result.returncode == 0, result.stderr
    assert fixture.replacement_marker.exists()
    assert not fixture.original_pid_is_alive()


def test_alpha_start_does_not_stop_unrelated_live_pid(tmp_path: Path) -> None:
    fixture = _go2rtc_start_fixture(tmp_path, ps_identity="unrelated")
    result = fixture.run_start()

    assert result.returncode != 0
    assert result.stderr.strip() == "go2rtc pid identity mismatch"
    assert fixture.original_pid_is_alive()
    assert not fixture.replacement_marker.exists()


def test_alpha_start_does_not_kickstart_freshly_bootstrapped_agents(
    tmp_path: Path,
) -> None:
    project = tmp_path / "project"
    shutil.copytree(ROOT / "tools", project / "tools")
    (project / "runtime/pids").mkdir(parents=True)
    (project / "runtime/logs").mkdir(parents=True)
    (project / "runtime/settings.yaml").write_text("environment: {}\n", encoding="ascii")
    (project / "runtime/alpha.env").write_text(
        f"BABY_MONITOR_SETTINGS_PATH={project}/runtime/settings.yaml\n",
        encoding="ascii",
    )
    (project / ".local/bin").mkdir(parents=True)
    (project / ".venv-alpha/bin").mkdir(parents=True)
    _write_executable(project / ".local/bin/go2rtc", "#!/bin/sh\nexit 0\n")
    _write_executable(project / ".venv-alpha/bin/uvicorn", "#!/bin/sh\nexit 0\n")

    home = tmp_path / "home"
    agents = home / "Library/LaunchAgents"
    agents.mkdir(parents=True)
    labels = (
        "com.babymonitor.ollama-tunnel",
        "com.babymonitor.visual",
        "com.babymonitor.environment-watchdog",
        "com.babymonitor.gauge",
    )
    for label in labels:
        (agents / f"{label}.plist").write_text("synthetic plist\n", encoding="ascii")

    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    state_dir = tmp_path / "launchctl-state"
    state_dir.mkdir()
    _write_executable(fake_bin / "uname", "#!/bin/sh\necho Darwin\n")
    _write_executable(fake_bin / "id", "#!/bin/sh\necho 501\n")
    _write_executable(fake_bin / "curl", "#!/bin/sh\nexit 0\n")
    _write_executable(fake_bin / "route", "#!/bin/sh\nexit 0\n")
    _write_executable(
        fake_bin / "launchctl",
        """#!/bin/sh
set -eu
command=$1
target=$2
label=${target##*/}
state=$FAKE_LAUNCHCTL_STATE_DIR/$label
case $command in
  print)
    printf 'print %s\n' "$label" >> "$FAKE_LAUNCHCTL_STATE_DIR/calls"
    test -f "$state"
    ;;
  bootstrap)
    plist=$3
    label=${plist##*/}
    label=${label%.plist}
    printf 'bootstrap %s\n' "$label" >> "$FAKE_LAUNCHCTL_STATE_DIR/calls"
    : > "$FAKE_LAUNCHCTL_STATE_DIR/$label"
    ;;
  kickstart)
    printf 'kickstart\n' >> "$FAKE_LAUNCHCTL_STATE_DIR/calls"
    echo "Operation not permitted" >&2
    exit 1
    ;;
  *)
    exit 2
    ;;
esac
""",
    )

    env = os.environ.copy()
    env.update(
        {
            "HOME": str(home),
            "PATH": f"{fake_bin}:{env['PATH']}",
            "FAKE_LAUNCHCTL_STATE_DIR": str(state_dir),
        }
    )
    result = subprocess.run(
        ["bash", "tools/start_alpha.sh"],
        cwd=project,
        env=env,
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr
    assert all((state_dir / label).exists() for label in labels)
    assert (project / "runtime/pids/api.pid").exists()

    second_result = subprocess.run(
        ["bash", "tools/start_alpha.sh"],
        cwd=project,
        env=env,
        check=False,
        capture_output=True,
        text=True,
    )

    assert second_result.returncode == 0, second_result.stderr
    launchctl_calls = (state_dir / "calls").read_text(encoding="ascii").splitlines()
    assert "kickstart" not in launchctl_calls
    for label in labels:
        assert launchctl_calls.count(f"bootstrap {label}") == 1


def test_alpha_status_is_clean_in_downloaded_archive(tmp_path: Path) -> None:
    shutil.copy2(ROOT / "Makefile", tmp_path / "Makefile")

    result = subprocess.run(
        ["make", "alpha-status"],
        cwd=tmp_path,
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0
    assert "Source: packaged archive" in result.stdout
    assert "fatal: not a git repository" not in result.stderr


def test_alpha_workflow_does_not_require_chmod() -> None:
    tracked_guides = [
        ROOT / "README.md",
        ROOT / "docs/runbooks/ALPHA_QUICKSTART.md",
        ROOT / "tools/install_alpha_macos.sh",
    ]

    combined = "\n".join(path.read_text(encoding="utf-8") for path in tracked_guides)

    assert "chmod +x tools/*.sh" not in combined
    assert "./tools/install_alpha_macos.sh" not in combined
    assert "./tools/start_alpha.sh" not in combined
    assert "./tools/stop_alpha.sh" not in combined


def test_alpha_installer_includes_automatic_acceptance_dependencies() -> None:
    content = (ROOT / "tools/install_alpha_macos.sh").read_text(encoding="utf-8")

    assert 'pip install -e "$ROOT[dev]"' in content


def test_makefile_exposes_stable_alpha_commands() -> None:
    content = (ROOT / "Makefile").read_text(encoding="utf-8")

    assert "alpha-update:" in content
    assert "alpha-install:" in content
    assert "alpha-start:" in content
    assert "alpha-stop:" in content
    assert "bash tools/install_alpha_macos.sh" in content
    assert "bash tools/start_alpha.sh" in content
    assert "bash tools/stop_alpha.sh" in content


def test_makefile_exposes_hd_quality_commands() -> None:
    content = (ROOT / "Makefile").read_text(encoding="utf-8")

    assert "alpha-quality-hd:" in content
    assert "alpha-quality-info:" in content
    assert "alpha-quality-rollback:" in content
    assert "alpha-source-check:" in content
    assert "tools/alpha_quality.py apply-hd" in content
    assert "tools/alpha_quality.py info" in content
    assert "tools/alpha_quality.py rollback" in content
    assert "tools/alpha_quality.py check" in content


def test_makefile_exposes_safe_subtype_probe() -> None:
    content = (ROOT / "Makefile").read_text(encoding="utf-8")

    assert "alpha-subtype-probe:" in content
    assert "tools/alpha_quality.py probe-subtypes" in content
    assert "--candidates 0 1 2 3 4 5" in content
    assert "--base-url" in content
    assert "--restart-command" in content


def test_makefile_exposes_verified_native_hd_subtype_apply() -> None:
    content = (ROOT / "Makefile").read_text(encoding="utf-8")

    assert "alpha-subtype-apply:" in content
    assert "tools/alpha_quality.py apply-subtype" in content
    assert "--subtype 3" in content
    assert "--minimum-width 1920" in content
    assert "--minimum-height 1080" in content
    assert "--dashboard-url" in content
    assert "--restart-command" in content


def test_subtype_probe_make_dry_run_does_not_start_services() -> None:
    result = subprocess.run(
        ["make", "-n", "alpha-subtype-probe"],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0
    assert "probe-subtypes" in result.stdout
    assert "No such file or directory" not in result.stderr


def test_subtype_apply_make_dry_run_does_not_start_services() -> None:
    result = subprocess.run(
        ["make", "-n", "alpha-subtype-apply"],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0
    assert "apply-subtype" in result.stdout
    assert "alpha-restart" in result.stdout
    assert "No such file or directory" not in result.stderr


def test_default_live_profile_is_hd_ten_fps() -> None:
    content = (ROOT / "config/go2rtc.alpha.yaml").read_text(encoding="utf-8")

    assert "#width=1280#height=720#raw=-r 10" in content
    assert "#fps=5" not in content


def test_default_config_has_fixed_on_demand_videotoolbox_profile() -> None:
    config = yaml.safe_load(
        (ROOT / "config/go2rtc.alpha.yaml").read_text(encoding="utf-8")
    )

    assert config["streams"]["source_compat"] == (
        "ffmpeg:source#video=h264#hardware=videotoolbox"
        "#width=2560#height=1440#bitrate=6M"
    )


def test_default_config_has_separate_one_and_five_fps_analysis_profiles() -> None:
    config = yaml.safe_load(
        (ROOT / "config/go2rtc.alpha.yaml").read_text(encoding="utf-8")
    )

    assert config["streams"]["analysis"] == (
        "ffmpeg:source#video=mjpeg#width=960#height=540#raw=-r 1"
    )
    assert config["streams"]["analysis_realtime"] == (
        "ffmpeg:source#video=mjpeg#width=960#height=540#raw=-r 5"
    )
    assert "audio" not in config["streams"]["analysis_realtime"]


def test_realtime_model_commands_are_explicit_and_not_part_of_startup() -> None:
    check = subprocess.run(
        ["make", "-n", "alpha-realtime-models-check"],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    install = subprocess.run(
        ["make", "-n", "alpha-realtime-models-install"],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    startup = (ROOT / "tools/start_alpha.sh").read_text(encoding="utf-8")

    assert check.returncode == 0
    assert "tools/realtime_models.py check" in check.stdout
    assert install.returncode == 0
    assert "tools/realtime_models.py install" in install.stdout
    assert "realtime_models.py install" not in startup


def test_installer_preserves_existing_runtime_config() -> None:
    content = (ROOT / "tools/install_alpha_macos.sh").read_text(encoding="utf-8")

    assert 'if [[ ! -f "$ROOT/runtime/go2rtc.yaml" ]]; then' in content
    assert 'cp "$ROOT/config/go2rtc.alpha.yaml" "$ROOT/runtime/go2rtc.yaml"' in content
    assert "1280x720 MJPEG at 10 FPS" in content


@pytest.mark.parametrize(
    ("target", "command"),
    [
        ("alpha-go2rtc-info", "info"),
        ("alpha-go2rtc-rebuild", "rebuild"),
        ("alpha-go2rtc-rollback", "rollback"),
    ],
)
def test_makefile_exposes_go2rtc_build_lifecycle(target: str, command: str) -> None:
    result = subprocess.run(
        ["make", "-n", target],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0
    assert f"tools/go2rtc_build.py {command}" in result.stdout


def test_installer_ensures_patched_build_instead_of_downloading_release() -> None:
    content = (ROOT / "tools/install_alpha_macos.sh").read_text(encoding="utf-8")

    assert 'brew list go >/dev/null 2>&1 || brew install go' in content
    assert 'tools/go2rtc_build.py" ensure' in content
    assert "go2rtc/releases/download" not in content
