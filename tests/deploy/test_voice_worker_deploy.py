from __future__ import annotations

import json
import os
import plistlib
import shutil
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def _write_executable(path: Path, content: str) -> None:
    path.write_text(content, encoding="ascii")
    path.chmod(0o755)


def _voice_stop_project(tmp_path: Path, *, settle: bool) -> tuple[Path, dict[str, str]]:
    project = tmp_path / "project"
    (project / "tools").mkdir(parents=True)
    shutil.copy2(ROOT / "tools/stop_alpha.sh", project / "tools/stop_alpha.sh")
    home = tmp_path / "home"
    (home / "Library/LaunchAgents").mkdir(parents=True)
    state = tmp_path / "state"
    state.mkdir()
    for label in ("com.babymonitor.voice", "com.babymonitor.voice-asr-operator"):
        (state / label).write_text("loaded\n", encoding="ascii")
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    _write_executable(fake_bin / "uname", "#!/bin/sh\necho Darwin\n")
    _write_executable(fake_bin / "id", "#!/bin/sh\necho 501\n")
    _write_executable(fake_bin / "sleep", "#!/bin/sh\nexit 0\n")
    settle_line = (
        'count=$(cat "$marker.linger")\n'
        'if test "$count" -le 1; then rm -f "$marker" "$marker.linger"; exit 1; fi\n'
        'count=$((count - 1))\nprintf "%s" "$count" > "$marker.linger"\n'
        if settle
        else ":\n"
    )
    _write_executable(
        fake_bin / "launchctl",
        "#!/bin/sh\n"
        "set -eu\n"
        "command=$1\ntarget=$2\nlabel=${target##*/}\n"
        'marker="$VOICE_STOP_STATE/$label"\n'
        "case $command in\n"
        "  print)\n"
        '    if test -f "$marker.linger"; then\n'
        f"      {settle_line}"
        "    fi\n"
        '    test -f "$marker"\n'
        "    ;;\n"
        "  bootout)\n"
        '    printf "2" > "$marker.linger"\n'
        "    ;;\n"
        "  *) exit 2;;\n"
        "esac\n",
    )
    environment = os.environ.copy()
    environment.update(
        {
            "HOME": str(home),
            "PATH": f"{fake_bin}:{environment['PATH']}",
            "VOICE_STOP_STATE": str(state),
        }
    )
    return project, environment


def test_voice_stop_waits_for_launchd_bootout_settlement(tmp_path: Path) -> None:
    project, environment = _voice_stop_project(tmp_path, settle=True)

    result = subprocess.run(
        ["bash", "tools/stop_alpha.sh", "--voice-only"],
        cwd=project,
        env=environment,
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0
    assert result.stdout == "voice_stop=PASS\n"
    state = Path(environment["VOICE_STOP_STATE"])
    assert not (state / "com.babymonitor.voice").exists()
    assert not (state / "com.babymonitor.voice-asr-operator").exists()


def test_voice_stop_fails_closed_when_launchd_never_settles(tmp_path: Path) -> None:
    project, environment = _voice_stop_project(tmp_path, settle=False)

    result = subprocess.run(
        ["bash", "tools/stop_alpha.sh", "--voice-only"],
        cwd=project,
        env=environment,
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode != 0
    assert result.stdout == ""
    assert result.stderr == "voice_stop=FAIL reason=service_stop_timeout\n"


def test_voice_launchd_is_independent_interactive_and_private() -> None:
    payload = plistlib.loads(
        (ROOT / "deploy/launchd/com.babymonitor.voice.plist.example").read_bytes()
    )
    assert payload["Label"] == "com.babymonitor.voice"
    assert payload["ProgramArguments"] == [
        "__PROJECT_ROOT__/.venv-alpha/bin/python",
        "__PROJECT_ROOT__/tools/run_voice_worker.py",
        "--settings",
        "__PROJECT_ROOT__/runtime/settings.yaml",
        "--voice-models",
        "__PROJECT_ROOT__/runtime/config/voice-care-models.json",
    ]
    assert payload["KeepAlive"] == {"SuccessfulExit": False}
    assert payload["ProcessType"] == "Interactive"
    assert payload["EnvironmentVariables"] == {
        "PATH": "/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin"
    }
    assert payload["StandardOutPath"].endswith("runtime/logs/voice.log")
    assert payload["StandardErrorPath"].endswith("runtime/logs/voice.log")


def test_voice_make_targets_are_bounded_and_separate() -> None:
    outputs = {}
    for target in (
        "alpha-voice-status",
        "alpha-voice-test",
        "alpha-voice-start",
        "alpha-voice-stop",
        "alpha-voice-preflight",
    ):
        completed = subprocess.run(
            ["make", "-n", target], cwd=ROOT, capture_output=True, text=True, check=False
        )
        assert completed.returncode == 0
        outputs[target] = completed.stdout
    assert "tools/voice_status.py" in outputs["alpha-voice-status"]
    assert "tests/voice" in outputs["alpha-voice-test"]
    assert "tests/tools/test_voice_diagnostic.py" in outputs["alpha-voice-test"]
    assert "--voice-only" in outputs["alpha-voice-start"]
    assert "--voice-only" in outputs["alpha-voice-stop"]
    assert "tools.voice_asr_capture_macos preflight" in outputs["alpha-voice-preflight"]
    for target in ("alpha-voice-start", "alpha-voice-stop"):
        assert "alpha-restart" not in outputs[target]
        assert "go2rtc" not in outputs[target]
    for sibling in ("alpha-restart", "go2rtc", "visual", "gauge", "watchdog", "audio"):
        assert sibling not in outputs["alpha-voice-preflight"].lower()


def test_voice_diagnostic_make_targets_use_only_fixed_tool_operations() -> None:
    for operation in ("start", "status", "stop"):
        target = f"alpha-voice-diagnostic-{operation}"
        completed = subprocess.run(
            ["make", "-n", target],
            cwd=ROOT,
            capture_output=True,
            text=True,
            check=False,
        )
        assert completed.returncode == 0
        assert completed.stdout.strip() == (
            f"./.venv-alpha/bin/python tools/voice_diagnostic.py {operation}"
        )
        lowered = completed.stdout.lower()
        for forbidden in ("go2rtc", "alpha-restart", "camera_reply", "transcript"):
            assert forbidden not in lowered


def test_listen_only_make_targets_use_one_bounded_voice_lifecycle_script() -> None:
    outputs = {}
    for target in (
        "alpha-voice-listen-start",
        "alpha-voice-listen-status",
        "alpha-voice-listen-stop",
    ):
        completed = subprocess.run(
            ["make", "-n", target], cwd=ROOT, capture_output=True, text=True, check=False
        )
        assert completed.returncode == 0
        outputs[target] = completed.stdout

    assert "tools/voice_listen_lifecycle.sh start" in outputs["alpha-voice-listen-start"]
    assert "tools/voice_listen_lifecycle.sh status" in outputs["alpha-voice-listen-status"]
    assert "tools/voice_listen_lifecycle.sh stop" in outputs["alpha-voice-listen-stop"]
    for output in outputs.values():
        for sibling in ("alpha-restart", "go2rtc", "visual", "gauge", "watchdog"):
            assert sibling not in output.lower()


def test_install_start_stop_and_guardian_gate_keep_voice_as_one_sibling() -> None:
    installer = (ROOT / "tools/install_alpha_macos.sh").read_text()
    start = (ROOT / "tools/start_alpha.sh").read_text()
    stop = (ROOT / "tools/stop_alpha.sh").read_text()
    guardian = (ROOT / "tools/test_guardian.sh").read_text()

    assert "com.babymonitor.voice.plist.example" in installer
    assert 'VOICE_LABEL="com.babymonitor.voice"' in start
    assert 'VOICE_LABEL="com.babymonitor.voice"' in stop
    assert "run_voice_worker.py" in start
    assert '--voice-models "$ROOT/runtime/config/voice-care-models.json"' in start
    assert "test_voice_worker_deploy.py" in guardian
    assert 'run_check "installation" "voice_preflight" check_voice_preflight' in guardian
    assert (
        "tests/tools/test_run_visual_worker.py \\\n"
        "    tests/deploy/test_voice_worker_deploy.py\n"
    ) in guardian
    voice_only_start = start.split('if [[ "$VOICE_ONLY_START" -eq 1 ]]', 1)[1].split("fi", 1)[0]
    voice_only_stop = stop.split('if [[ "$VOICE_ONLY_STOP" -eq 1 ]]', 1)[1].split("fi", 1)[0]
    for body in (voice_only_start, voice_only_stop):
        for sibling in ("go2rtc", "visual", "gauge", "watchdog", "audio"):
            assert sibling not in body.lower()


def test_guardian_gate_checks_camera_reply_provenance_without_playback() -> None:
    guardian = (ROOT / "tools/test_guardian.sh").read_text(encoding="ascii")
    required = guardian.split("check_required_binaries() {", 1)[1].split(
        "\n}\n\ncheck_runtime_config", 1
    )[0]

    assert 'patches/go2rtc-macos-hybrid-hd.patch' in guardian
    assert 'runtime/build/go2rtc.json' in guardian
    assert 'tests/voice/test_camera_reply.py' in required
    assert 'tests/tools/test_voice_camera_reply.py' in required
    assert 'alpha-voice-camera-test' in required
    assert 'tools/voice_camera_reply.py" verify-marker' in required
    assert "voice_camera_reply.py\" probe" not in required
    assert "_write_tone" not in guardian


def test_voice_only_start_stop_is_symmetric_for_worker_and_operator(
    tmp_path: Path,
) -> None:
    project = tmp_path / "project"
    (project / "tools").mkdir(parents=True)
    shutil.copy2(ROOT / "tools/start_alpha.sh", project / "tools/start_alpha.sh")
    shutil.copy2(ROOT / "tools/stop_alpha.sh", project / "tools/stop_alpha.sh")
    home = tmp_path / "home"
    agents = home / "Library/LaunchAgents"
    agents.mkdir(parents=True)
    labels = ("com.babymonitor.voice", "com.babymonitor.voice-asr-operator")
    for label in labels:
        (agents / f"{label}.plist").write_text("synthetic plist\n", encoding="ascii")
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    state = tmp_path / "state"
    state.mkdir()
    calls = state / "calls"
    _write_executable(fake_bin / "uname", "#!/bin/sh\necho Darwin\n")
    _write_executable(fake_bin / "id", "#!/bin/sh\necho 501\n")
    _write_executable(
        fake_bin / "launchctl",
        """#!/bin/sh
set -eu
command=$1
target=$2
label=${target##*/}
marker=$VOICE_LIFECYCLE_STATE/$label
case $command in
  print)
    test -f "$marker"
    ;;
  bootstrap)
    label=${3##*/}
    label=${label%.plist}
    : > "$VOICE_LIFECYCLE_STATE/$label"
    printf 'bootstrap %s\n' "$label" >> "$VOICE_LIFECYCLE_CALLS"
    ;;
  kickstart)
    printf 'kickstart %s\n' "$label" >> "$VOICE_LIFECYCLE_CALLS"
    ;;
  bootout)
    rm -f "$marker"
    printf 'bootout %s\n' "$label" >> "$VOICE_LIFECYCLE_CALLS"
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
            "VOICE_LIFECYCLE_STATE": str(state),
            "VOICE_LIFECYCLE_CALLS": str(calls),
        }
    )

    start = subprocess.run(
        ["bash", "tools/start_alpha.sh", "--voice-only"],
        cwd=project,
        env=environment,
        check=False,
        capture_output=True,
        text=True,
    )
    assert start.returncode == 0, start.stderr
    assert all((state / label).exists() for label in labels)

    stop = subprocess.run(
        ["bash", "tools/stop_alpha.sh", "--voice-only"],
        cwd=project,
        env=environment,
        check=False,
        capture_output=True,
        text=True,
    )
    assert stop.returncode == 0, stop.stderr
    assert all(not (state / label).exists() for label in labels)

    restarted = subprocess.run(
        ["bash", "tools/start_alpha.sh", "--voice-only"],
        cwd=project,
        env=environment,
        check=False,
        capture_output=True,
        text=True,
    )
    assert restarted.returncode == 0, restarted.stderr
    assert all((state / label).exists() for label in labels)
    assert calls.read_text(encoding="ascii").splitlines() == [
        "bootstrap com.babymonitor.voice",
        "bootstrap com.babymonitor.voice-asr-operator",
        "bootout com.babymonitor.voice",
        "bootout com.babymonitor.voice-asr-operator",
        "bootstrap com.babymonitor.voice",
        "bootstrap com.babymonitor.voice-asr-operator",
    ]


def test_disabled_runner_exits_without_opening_audio_or_models(tmp_path: Path) -> None:
    from tools.run_voice_worker import main

    project = tmp_path / "project"
    (project / "runtime").mkdir(parents=True)
    assert main(
        ["--settings", str(ROOT / "config/settings.example.yaml")],
        project_root=project,
    ) == 0
    status = json.loads((project / "runtime/status/voice.json").read_text())
    assert status["worker_state"] == "disabled"
    assert status["mode"] == "disabled"


def test_listen_only_runner_merges_fixed_model_manifest_and_builds_default_runtime(
    tmp_path: Path,
) -> None:
    import yaml

    from tools.run_voice_worker import main

    project = tmp_path / "project"
    runtime = project / "runtime"
    models = runtime / "config/voice-care-models.json"
    models.parent.mkdir(parents=True)
    models.write_text(
        json.dumps(
            {
                "enabled": False,
                "silero_vad_manifest_sha256": "a" * 64,
                "paraformer_zh_manifest_sha256": "b" * 64,
            }
        ),
        encoding="ascii",
    )
    raw = yaml.safe_load((ROOT / "config/settings.example.yaml").read_text())
    raw["voice_care"] = {"enabled": False, "listen_only_enabled": True}
    settings_path = runtime / "settings.yaml"
    settings_path.write_text(yaml.safe_dump(raw), encoding="utf-8")
    built: list[object] = []

    class Worker:
        def run(self, stop_event) -> None:
            built.append(stop_event)

    result = main(
        ["--settings", str(settings_path), "--voice-models", str(models)],
        project_root=project,
        runtime_builder=lambda settings, root: (
            built.append((settings.voice_care, root)) or Worker()
        ),
    )

    assert result == 0
    voice, root = built[0]
    assert voice.listen_only_enabled is True
    assert voice.silero_vad_manifest_sha256 == "a" * 64
    assert voice.paraformer_zh_manifest_sha256 == "b" * 64
    assert voice.speechbrain_ecapa_manifest_sha256 is None
    assert root == project


def test_preflight_runner_is_aggregate_only_and_never_builds_worker(
    tmp_path: Path,
) -> None:
    from services.voice.worker import VoicePreflightReport
    from tools.run_voice_worker import main

    project = tmp_path / "project"
    models = project / "runtime/config/voice-care-models.json"
    models.parent.mkdir(parents=True)
    models.write_text(
        json.dumps(
            {
                "enabled": False,
                "silero_vad_manifest_sha256": "a" * 64,
                "paraformer_zh_manifest_sha256": "b" * 64,
            }
        ),
        encoding="ascii",
    )
    output: list[str] = []

    result = main(
        ["--preflight", "--voice-models", str(models)],
        project_root=project,
        worker_factory=lambda *_args: (_ for _ in ()).throw(AssertionError("worker")),
        preflight_factory=lambda _settings, _root: VoicePreflightReport(
            True, "voice_preflight_available", "paraformer"
        ),
        printer=output.append,
    )

    assert result == 0
    assert output == [
        "result=PASS",
        "operation=preflight",
        "voice_preflight=available",
        "gate_passed=true",
        "asr_profile=paraformer",
        "keychain=available",
        "asr_artifact=available",
        "silero_artifact=available",
    ]
    assert not (project / "runtime/status/voice.json").exists()


def test_preflight_runner_redacts_failure_and_rejects_wrong_model_path(
    tmp_path: Path,
) -> None:
    from services.voice.worker import VoicePreflightReport
    from tools.run_voice_worker import main

    project = tmp_path / "project"
    models = project / "runtime/config/voice-care-models.json"
    models.parent.mkdir(parents=True)
    models.write_text(
        json.dumps(
            {
                "enabled": False,
                "silero_vad_manifest_sha256": "a" * 64,
                "paraformer_zh_manifest_sha256": "b" * 64,
            }
        ),
        encoding="ascii",
    )
    output: list[str] = []
    failed = main(
        ["--preflight", "--voice-models", str(models)],
        project_root=project,
        preflight_factory=lambda _settings, _root: VoicePreflightReport(
            False, "voice_model_unavailable", None
        ),
        printer=output.append,
    )
    wrong_output: list[str] = []
    wrong = main(
        ["--preflight", "--voice-models", str(tmp_path / "other.json")],
        project_root=project,
        printer=wrong_output.append,
    )

    assert failed == 1
    assert output == [
        "result=FAIL",
        "operation=preflight",
        "voice_preflight=unavailable",
        "gate_passed=false",
        "reason=voice_model_unavailable",
    ]
    assert wrong == 1
    assert wrong_output == [
        "result=FAIL",
        "operation=preflight",
        "voice_preflight=unavailable",
        "gate_passed=false",
        "reason=voice_preflight_unavailable",
    ]
