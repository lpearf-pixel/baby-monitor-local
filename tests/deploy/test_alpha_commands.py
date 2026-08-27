from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tomllib
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
        expected_command: str,
    ):
        self.project = project
        self.replacement_marker = marker
        self._original = original
        self._environment = environment
        self.expected_command = expected_command

    def run_start(self) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            ["bash", "tools/start_alpha.sh"],
            cwd=self.project,
            env=self._environment,
            check=False,
            capture_output=True,
            text=True,
            timeout=20,
        )

    def original_pid_is_alive(self) -> bool:
        return self._original.poll() is None

    def close(self) -> None:
        if self._original.poll() is None:
            self._original.terminate()
        try:
            self._original.wait(timeout=1)
        except subprocess.TimeoutExpired:
            self._original.kill()
            self._original.wait()


def _go2rtc_start_fixture(
    tmp_path: Path,
    request: pytest.FixtureRequest,
    *,
    ps_identity: str,
    api_ready: bool = False,
    pid_state: str = "live",
    listener_owned: bool = True,
) -> _Go2rtcStartFixture:
    project = tmp_path / ("project-" + "x" * 120)
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

    pidfile = project / "runtime/pids/go2rtc.pid"
    if pid_state == "live":
        pidfile.write_text(f"{original.pid}\n", encoding="ascii")
    elif pid_state == "dead":
        original.terminate()
        original.wait(timeout=1)
        pidfile.write_text(f"{original.pid}\n", encoding="ascii")
    else:
        assert pid_state == "missing"

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
        "#!/bin/sh\n"
        "test \"$FAKE_API_READY\" = 1 || "
        "test -f \"$GO2RTC_REPLACEMENT_MARKER\"\n",
    )
    _write_executable(fake_bin / "id", "#!/bin/sh\necho 501\n")
    _write_executable(
        fake_bin / "lsof",
        "#!/bin/sh\ntest \"$FAKE_LISTENER_OWNED\" = 1\n",
    )
    _write_executable(fake_bin / "route", "#!/bin/sh\nexit 0\n")
    _write_executable(fake_bin / "sleep", "#!/bin/sh\n/bin/sleep 0.01\n")
    _write_executable(fake_bin / "uname", "#!/bin/sh\necho Linux\n")
    _write_executable(
        fake_bin / "ps",
        """#!/bin/sh
if [ "$1" != "-ww" ] || [ "$2" != "-p" ] || [ "$4" != "-o" ] || [ "$5" != "command=" ]; then
  echo "/truncated/go2rtc-command"
  exit 0
fi
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
            "FAKE_API_READY": "1" if api_ready else "0",
            "FAKE_LISTENER_OWNED": "1" if listener_owned else "0",
            "GO2RTC_EXPECTED_COMMAND": (
                f"{project}/.local/bin/go2rtc -config {project}/runtime/go2rtc.yaml"
            ),
            "GO2RTC_REPLACEMENT_MARKER": str(marker),
        }
    )
    fixture = _Go2rtcStartFixture(
        project,
        marker,
        original,
        environment,
        environment["GO2RTC_EXPECTED_COMMAND"],
    )
    request.addfinalizer(fixture.close)
    return fixture


def test_alpha_start_replaces_verified_live_but_unhealthy_go2rtc(
    tmp_path: Path, request: pytest.FixtureRequest
) -> None:
    fixture = _go2rtc_start_fixture(tmp_path, request, ps_identity="expected")
    result = fixture.run_start()

    assert result.returncode == 0, result.stderr
    assert len(fixture.expected_command) > 160
    assert fixture.replacement_marker.exists()
    assert not fixture.original_pid_is_alive()


def test_alpha_start_does_not_stop_unrelated_live_pid(
    tmp_path: Path, request: pytest.FixtureRequest
) -> None:
    fixture = _go2rtc_start_fixture(tmp_path, request, ps_identity="unrelated")
    result = fixture.run_start()

    assert result.returncode != 0
    assert result.stderr.strip() == "go2rtc pid identity mismatch"
    assert fixture.original_pid_is_alive()
    assert not fixture.replacement_marker.exists()


@pytest.mark.parametrize(
    ("pid_state", "ps_identity"),
    [
        ("missing", "expected"),
        ("dead", "expected"),
        ("live", "unrelated"),
    ],
)
def test_alpha_start_rejects_healthy_api_without_verified_go2rtc_pid(
    tmp_path: Path,
    request: pytest.FixtureRequest,
    pid_state: str,
    ps_identity: str,
) -> None:
    fixture = _go2rtc_start_fixture(
        tmp_path,
        request,
        ps_identity=ps_identity,
        api_ready=True,
        pid_state=pid_state,
    )
    result = fixture.run_start()

    assert result.returncode != 0
    assert result.stderr.strip() == "go2rtc pid identity mismatch"
    assert not fixture.replacement_marker.exists()
    if pid_state == "live":
        assert fixture.original_pid_is_alive()


def test_alpha_start_preserves_verified_healthy_go2rtc(
    tmp_path: Path, request: pytest.FixtureRequest
) -> None:
    fixture = _go2rtc_start_fixture(
        tmp_path, request, ps_identity="expected", api_ready=True
    )
    result = fixture.run_start()

    assert result.returncode == 0, result.stderr
    assert fixture.original_pid_is_alive()
    assert not fixture.replacement_marker.exists()


def test_alpha_start_rejects_healthy_api_not_owned_by_verified_go2rtc(
    tmp_path: Path, request: pytest.FixtureRequest
) -> None:
    fixture = _go2rtc_start_fixture(
        tmp_path,
        request,
        ps_identity="expected",
        api_ready=True,
        listener_owned=False,
    )
    result = fixture.run_start()

    assert result.returncode != 0
    assert result.stderr.strip() == "go2rtc pid identity mismatch"
    assert fixture.original_pid_is_alive()
    assert not fixture.replacement_marker.exists()


def test_alpha_start_does_not_kickstart_freshly_bootstrapped_agents(
    tmp_path: Path,
    request: pytest.FixtureRequest,
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
    (project / ".local/Go2RTC.app/Contents/MacOS").mkdir(parents=True)
    (project / ".venv-alpha/bin").mkdir(parents=True)
    _write_executable(project / ".local/bin/go2rtc", "#!/bin/sh\nexit 0\n")
    _write_executable(
        project / ".local/Go2RTC.app/Contents/MacOS/go2rtc",
        "#!/bin/sh\nexit 0\n",
    )
    _write_executable(project / ".venv-alpha/bin/uvicorn", "#!/bin/sh\nexit 0\n")
    go2rtc = subprocess.Popen([shutil.which("sleep") or "/bin/sleep", "60"])

    def cleanup_go2rtc() -> None:
        if go2rtc.poll() is None:
            go2rtc.terminate()
        try:
            go2rtc.wait(timeout=1)
        except subprocess.TimeoutExpired:
            go2rtc.kill()
            go2rtc.wait()

    request.addfinalizer(cleanup_go2rtc)
    (project / "runtime/pids/go2rtc.pid").write_text(
        f"{go2rtc.pid}\n", encoding="ascii"
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
    (agents / "com.babymonitor.go2rtc.plist").write_text(
        "synthetic plist\n", encoding="ascii"
    )

    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    state_dir = tmp_path / "launchctl-state"
    state_dir.mkdir()
    (state_dir / "com.babymonitor.go2rtc").touch()
    _write_executable(fake_bin / "uname", "#!/bin/sh\necho Darwin\n")
    _write_executable(fake_bin / "id", "#!/bin/sh\necho 501\n")
    _write_executable(fake_bin / "curl", "#!/bin/sh\nexit 0\n")
    _write_executable(fake_bin / "lsof", "#!/bin/sh\nexit 0\n")
    _write_executable(
        fake_bin / "ps",
        """#!/bin/sh
test "$1" = "-ww" && test "$2" = "-p" && test "$4" = "-o" && test "$5" = "command="
echo "$GO2RTC_EXPECTED_COMMAND"
""",
    )
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
    test -f "$state" || exit 1
    if test "$label" = com.babymonitor.go2rtc; then
      echo "pid = $FAKE_GO2RTC_PID"
    fi
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
            "GO2RTC_EXPECTED_COMMAND": (
                f"{project}/.local/Go2RTC.app/Contents/MacOS/go2rtc "
                f"-config {project}/runtime/go2rtc.yaml"
            ),
            "FAKE_GO2RTC_PID": str(go2rtc.pid),
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


def test_voice_model_install_make_target_is_phony_closed_and_local(
    tmp_path: Path,
) -> None:
    shutil.copy2(ROOT / "Makefile", tmp_path / "Makefile")
    (tmp_path / "alpha-voice-models-install").touch()

    dry_run = subprocess.run(
        ["make", "-n", "alpha-voice-models-install"],
        cwd=tmp_path,
        check=False,
        capture_output=True,
        text=True,
    )
    help_result = subprocess.run(
        ["make", "help"],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )

    assert dry_run.returncode == 0, dry_run.stderr
    assert dry_run.stdout.count("tools/voice_models.py") == 2
    assert "runtime/config/voice-care-models.json" in dry_run.stdout
    assert (
        "runtime/models/voice-care-sources/openai-whisper-base/source"
        in dry_run.stdout
    )
    assert (
        "runtime/models/voice-care-sources/openai-whisper-small/source"
        in dry_run.stdout
    )
    assert "source-manifest.json" in dry_run.stdout
    assert "curl" not in dry_run.stdout
    assert "wget" not in dry_run.stdout
    assert "http://" not in dry_run.stdout
    assert "https://" not in dry_run.stdout
    assert help_result.returncode == 0
    assert "make alpha-voice-models-install" in help_result.stdout


def test_voice_model_install_fails_closed_before_installer_when_inputs_are_absent(
    tmp_path: Path,
) -> None:
    shutil.copy2(ROOT / "Makefile", tmp_path / "Makefile")
    fake_python = tmp_path / ".venv-alpha/bin/python"
    marker = tmp_path / "installer-called"
    fake_python.parent.mkdir(parents=True)
    _write_executable(fake_python, f"#!/bin/sh\n: > '{marker}'\n")

    result = subprocess.run(
        ["make", "alpha-voice-models-install"],
        cwd=tmp_path,
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode != 0
    assert result.stdout.strip() == "voice_models_install=unavailable"
    assert not marker.exists()


def test_voice_model_install_runs_both_fixed_local_conversions(
    tmp_path: Path,
) -> None:
    shutil.copy2(ROOT / "Makefile", tmp_path / "Makefile")
    settings = tmp_path / "runtime/config/voice-care-models.json"
    settings.parent.mkdir(parents=True)
    settings.write_text("{}\n", encoding="ascii")
    for artifact_id in ("openai-whisper-base", "openai-whisper-small"):
        source_root = tmp_path / "runtime/models/voice-care-sources" / artifact_id
        (source_root / "source").mkdir(parents=True)
        (source_root / "source-manifest.json").write_text("{}\n", encoding="ascii")
    calls = tmp_path / "installer-calls"
    fake_python = tmp_path / ".test-bin/python"
    fake_python.parent.mkdir()
    _write_executable(
        fake_python,
        '#!/bin/sh\nprintf "%s\\n" "$*" >> "$VOICE_TEST_CALLS"\n',
    )

    result = subprocess.run(
        ["make", "alpha-voice-models-install", f"PYTHON={fake_python}"],
        cwd=tmp_path,
        env={**os.environ, "VOICE_TEST_CALLS": str(calls)},
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "voice_models_install=ready"
    recorded = calls.read_text(encoding="ascii")
    assert recorded.count("tools/voice_models.py") == 2
    assert '--artifact openai-whisper-base --operation convert-whisper' in recorded
    assert '--artifact openai-whisper-small --operation convert-whisper' in recorded


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


def test_default_config_has_fixed_audio_only_analysis_profile() -> None:
    config = yaml.safe_load(
        (ROOT / "config/go2rtc.alpha.yaml").read_text(encoding="utf-8")
    )

    assert config["streams"]["audio_analysis"] == (
        "ffmpeg:source#audio=opus/16000"
    )


def test_default_config_has_fixed_native_resolution_gauge_profile() -> None:
    config = yaml.safe_load(
        (ROOT / "config/go2rtc.alpha.yaml").read_text(encoding="utf-8")
    )

    assert config["streams"]["gauge"] == (
        "ffmpeg:source#video=mjpeg#width=2560#height=1440#raw=-r 2"
    )


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


def test_dev_dependencies_cover_supported_starlette_test_clients() -> None:
    project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    dependencies = project["project"]["optional-dependencies"]["dev"]

    assert any(item.startswith("httpx>=") for item in dependencies)
    assert any(item.startswith("httpx2>=") for item in dependencies)


def test_intel_voice_converter_dependencies_are_isolated_and_fully_pinned() -> None:
    project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    dependencies = project["project"]["dependencies"]
    requirements = (
        ROOT / "config/voice-converter-requirements.txt"
    ).read_text(encoding="ascii").splitlines()

    assert not any(item.startswith("torch") for item in dependencies)
    assert not any(item.startswith("transformers") for item in dependencies)
    assert requirements == [
        "ctranslate2==4.8.1",
        "numpy==1.26.4",
        "pydantic==2.13.4",
        "torch==2.2.2",
        "transformers==4.56.2",
    ]
    makefile = (ROOT / "Makefile").read_text(encoding="utf-8")
    startup = (ROOT / "tools/start_alpha.sh").read_text(encoding="utf-8")
    assert "alpha-voice-converter-install:" in makefile
    assert "runtime/voice-converter-venv" in makefile
    assert "config/voice-converter-requirements.txt" in makefile
    assert "-m venv" in makefile
    assert "alpha-voice-converter-install" not in startup
    path_gate = "tools/voice_converter_environment.py --project-root ."
    assert path_gate in makefile
    assert makefile.index(path_gate) < makefile.index('"$(PYTHON311)" -m venv')
    assert makefile.index(path_gate) < makefile.index("-m pip install --requirement")


def test_intel_voice_speaker_install_is_explicit_and_host_gated(tmp_path: Path) -> None:
    requirements = (
        ROOT / "config/voice-speaker-requirements.txt"
    ).read_text(encoding="ascii").splitlines()
    assert requirements == [
        "huggingface-hub==0.36.0",
        "numpy==1.26.4",
        "pydantic==2.13.4",
        "speechbrain==1.0.3",
        "torch==2.2.2",
        "torchaudio==2.2.2",
    ]

    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    marker = tmp_path / "python-called"
    _write_executable(
        fake_bin / "uname",
        "#!/bin/sh\n"
        "if test \"$1\" = -s; then echo Linux; else echo x86_64; fi\n",
    )
    fake_python = tmp_path / "python3.11"
    _write_executable(fake_python, f"#!/bin/sh\n: > '{marker}'\nexit 1\n")
    environment = os.environ.copy()
    environment["PATH"] = f"{fake_bin}:{environment['PATH']}"

    result = subprocess.run(
        [
            shutil.which("make") or "make",
            "alpha-voice-speaker-install",
            f"PYTHON311={fake_python}",
        ],
        cwd=ROOT,
        env=environment,
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode != 0
    assert result.stdout.strip() == "voice_speaker_install=unavailable"
    assert not marker.exists()


def test_voice_speaker_check_fails_closed_without_an_environment(
    tmp_path: Path,
) -> None:
    shutil.copy2(ROOT / "Makefile", tmp_path / "Makefile")
    (tmp_path / "tools").mkdir()
    shutil.copy2(
        ROOT / "tools/voice_speaker_environment.py",
        tmp_path / "tools/voice_speaker_environment.py",
    )
    result = subprocess.run(
        [
            "make",
            "alpha-voice-speaker-check",
            f"PYTHON311={shutil.which('python3') or '/usr/bin/python3'}",
        ],
        cwd=tmp_path,
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode != 0
    assert result.stdout.strip() == "voice_speaker_check=unavailable"


def test_ecapa_source_and_install_commands_fail_closed_without_private_inputs(
    tmp_path: Path,
) -> None:
    shutil.copy2(ROOT / "Makefile", tmp_path / "Makefile")
    fake_python = tmp_path / ".venv-alpha/bin/python"
    marker = tmp_path / "python-called"
    fake_python.parent.mkdir(parents=True)
    _write_executable(fake_python, f"#!/bin/sh\n: > '{marker}'\nexit 1\n")

    source = subprocess.run(
        ["make", "alpha-voice-ecapa-source", f"PYTHON311={fake_python}"],
        cwd=tmp_path,
        check=False,
        capture_output=True,
        text=True,
    )
    install = subprocess.run(
        ["make", "alpha-voice-ecapa-install", f"PYTHON={fake_python}"],
        cwd=tmp_path,
        check=False,
        capture_output=True,
        text=True,
    )

    assert source.returncode != 0
    assert source.stdout.strip() == "voice_ecapa_source=unavailable"
    assert install.returncode != 0
    assert install.stdout.strip() == "voice_ecapa_install=unavailable"
    assert not marker.exists()


def test_ecapa_probe_command_fails_closed_without_installed_runtime(
    tmp_path: Path,
) -> None:
    shutil.copy2(ROOT / "Makefile", tmp_path / "Makefile")
    result = subprocess.run(
        [
            "make",
            "alpha-voice-ecapa-probe",
            f"PYTHON={sys.executable}",
        ],
        cwd=tmp_path,
        env={**os.environ, "PYTHONPATH": str(ROOT)},
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode != 0
    assert result.stdout.splitlines() == [
        "result=FAIL",
        "reason=voice_model_unavailable",
        "raw_audio_persisted=false",
    ]


def test_ecapa_install_runs_the_current_checkout_model_module(tmp_path: Path) -> None:
    shutil.copy2(ROOT / "Makefile", tmp_path / "Makefile")
    settings = tmp_path / "runtime/config/voice-care-models.json"
    source_root = (
        tmp_path
        / "runtime/models/voice-care-sources/speechbrain-ecapa-voxceleb"
    )
    settings.parent.mkdir(parents=True)
    (source_root / "source").mkdir(parents=True)
    settings.write_text("{}\n", encoding="ascii")
    (source_root / "source-manifest.json").write_text("{}\n", encoding="ascii")
    calls = tmp_path / "calls"
    fake_python = tmp_path / "python"
    _write_executable(
        fake_python,
        '#!/bin/sh\nprintf "%s\\n" "$*" >> "$VOICE_TEST_CALLS"\n',
    )

    result = subprocess.run(
        ["make", "alpha-voice-ecapa-install", f"PYTHON={fake_python}"],
        cwd=tmp_path,
        env={**os.environ, "VOICE_TEST_CALLS": str(calls)},
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0
    assert result.stdout.strip() == "voice_ecapa_install=ready"
    assert calls.read_text(encoding="ascii").startswith("-m tools.voice_models ")


def test_private_adult_enrollment_commands_fix_the_role_and_current_module() -> None:
    content = (ROOT / "Makefile").read_text(encoding="utf-8")

    assert "alpha-voice-enroll-dad:" in content
    assert "alpha-voice-enroll-mom:" in content
    assert "$(PYTHON) -m tools.voice_enroll --role dad" in content
    assert "$(PYTHON) -m tools.voice_enroll --role mom" in content
    assert "VOICE_PROFILE" not in content


def test_private_asr_calibration_commands_use_fixed_local_module() -> None:
    content = (ROOT / "Makefile").read_text(encoding="utf-8")

    assert "alpha-voice-asr-capture:" in content
    assert "alpha-voice-asr-capture-fixed:" in content
    assert "alpha-voice-asr-capture-fixed-all:" in content
    assert "alpha-voice-asr-capture-all:" in content
    assert "alpha-voice-asr-evaluate:" in content
    assert "alpha-voice-asr-bakeoff:" in content
    assert "alpha-voice-asr-install:" in content
    assert "alpha-voice-paraformer-install:" in content
    assert "alpha-voice-asr-paraformer:" in content
    assert "alpha-voice-vad-diagnostic:" in content
    assert "-m tools.voice_asr_calibrate capture --prompt-id \"$(PROMPT)\"" in content
    assert (
        "-m tools.voice_asr_capture_macos record --prompt-id \"$(PROMPT)\""
        in content
    )
    assert (
        "-m tools.voice_asr_calibrate capture-fixed --prompt-id \"$(PROMPT)\""
        not in content
    )
    assert "for prompt in feeding_start_dad feeding_start_mom feeding_amount feeding_finish care_cancel negative_weather" in content
    assert "-m tools.voice_asr_calibrate capture-all" in content
    assert "-m tools.voice_asr_calibrate evaluate" in content
    assert "-m tools.voice_asr_calibrate bakeoff" in content
    assert "-m tools.voice_asr_capture_macos paraformer" in content
    assert "-m tools.voice_asr_capture_macos vad-diagnostic" in content
    assert "-m tools.voice_asr_calibrate paraformer" not in content
    assert "$(PYTHON) -m tools.voice_vad_diagnostic" not in content
    assert (ROOT / "config/voice-asr-requirements.txt").is_file()
    assert "-m tools.voice_asr_install --project-root . --base-python" in content
    asr_install = content.split("alpha-voice-asr-install:", 1)[1].split(
        "alpha-voice-ecapa-source:", 1
    )[0]
    assert "venv --upgrade" not in asr_install
    assert "pip install" not in asr_install
    assert 'artifact "sherpa-onnx-paraformer-zh-2023-09-14"' in content
    assert "-m tools.voice_asr_capture_macos vad-diagnostic" in content


def test_makefile_exposes_explicit_headless_voice_recovery() -> None:
    result = subprocess.run(
        ["make", "-n", "alpha-voice-asr-recover"],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0
    assert result.stdout.strip() == (
        "./.venv-alpha/bin/python -m tools.voice_asr_capture_macos recover"
    )


def test_makefile_exposes_fixed_voice_keychain_helper_lifecycle() -> None:
    build = subprocess.run(
        ["make", "-n", "alpha-voice-keychain-helper-build"],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    check = subprocess.run(
        ["make", "-n", "alpha-voice-keychain-check"],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    migrate = subprocess.run(
        ["make", "-n", "alpha-voice-keychain-migrate"],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )

    assert build.returncode == 0
    assert "-m tools.voice_keychain_helper_build ensure" in build.stdout
    assert check.returncode == 0
    assert "-m tools.voice_keychain_probe" in check.stdout
    assert migrate.returncode == 0
    assert "-m tools.voice_keychain_migrate" in migrate.stdout


def test_installer_and_guardian_gate_require_stable_voice_keychain_helper() -> None:
    installer = (ROOT / "tools/install_alpha_macos.sh").read_text(encoding="ascii")
    guardian = (ROOT / "tools/test_guardian.sh").read_text(encoding="ascii")

    assert 'tools.voice_keychain_helper_build ensure' in installer
    assert 'VOICE_KEYCHAIN_APP="$ROOT/.local/VoiceKeychainHelper.app"' in guardian
    assert 'com.babymonitor.voice-keychain-helper' in guardian
    assert 'codesign --verify --deep --strict' in guardian


def test_installer_installs_acceptance_test_dependencies() -> None:
    content = (ROOT / "tools/install_alpha_macos.sh").read_text(encoding="utf-8")

    assert 'python" -m pip install -e "$ROOT[dev]"' in content


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


def test_makefile_exposes_closed_camera_reply_operations() -> None:
    outputs = {}
    for target in (
        "alpha-voice-camera-test",
        "alpha-voice-camera-status",
        "alpha-voice-camera-probe",
    ):
        result = subprocess.run(
            ["make", "-n", target],
            cwd=ROOT,
            check=False,
            capture_output=True,
            text=True,
        )
        assert result.returncode == 0
        outputs[target] = result.stdout

    assert "tests/voice/test_camera_reply.py" in outputs["alpha-voice-camera-test"]
    assert "tests/tools/test_voice_camera_reply.py" in outputs["alpha-voice-camera-test"]
    assert "tools/voice_camera_reply.py status" in outputs["alpha-voice-camera-status"]
    assert "tools/voice_camera_reply.py probe" in outputs["alpha-voice-camera-probe"]
    for target in ("alpha-voice-camera-test", "alpha-voice-camera-status"):
        output = outputs[target].lower()
        assert "http://" not in output
        assert "curl" not in output
        assert "voice_camera_reply.py probe" not in output


def test_makefile_exposes_read_only_xiaomi_macos_preflight() -> None:
    result = subprocess.run(
        ["make", "-n", "alpha-xiaomi-media-preflight"],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0
    assert result.stdout.strip() == (
        "./.venv-alpha/bin/python tools/xiaomi_macos_preflight.py"
    )
    lowered = result.stdout.lower()
    assert "restart" not in lowered
    assert "rebuild" not in lowered
    assert "install" not in lowered
    assert "probe" not in lowered


def test_makefile_exposes_read_only_xiaomi_media_diagnostic() -> None:
    result = subprocess.run(
        ["make", "-n", "alpha-xiaomi-media-diagnostic"],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0
    assert result.stdout.strip() == (
        "./.venv-alpha/bin/python tools/xiaomi_media_diagnostic.py"
    )
    lowered = result.stdout.lower()
    assert "restart" not in lowered
    assert "rebuild" not in lowered
    assert "install" not in lowered
    assert "camera_reply" not in lowered


def test_installer_ensures_patched_build_instead_of_downloading_release() -> None:
    content = (ROOT / "tools/install_alpha_macos.sh").read_text(encoding="utf-8")

    assert 'brew list go >/dev/null 2>&1 || brew install go' in content
    assert 'tools/go2rtc_build.py" ensure' in content
    assert "go2rtc/releases/download" not in content
