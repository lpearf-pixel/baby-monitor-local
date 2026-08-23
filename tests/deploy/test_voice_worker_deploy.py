from __future__ import annotations

import json
import plistlib
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


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
    ]
    assert payload["KeepAlive"] == {"SuccessfulExit": False}
    assert payload["ProcessType"] == "Interactive"
    assert payload["StandardOutPath"].endswith("runtime/logs/voice.log")
    assert payload["StandardErrorPath"].endswith("runtime/logs/voice.log")


def test_voice_make_targets_are_bounded_and_separate() -> None:
    outputs = {}
    for target in (
        "alpha-voice-status",
        "alpha-voice-test",
        "alpha-voice-start",
        "alpha-voice-stop",
    ):
        completed = subprocess.run(
            ["make", "-n", target], cwd=ROOT, capture_output=True, text=True, check=False
        )
        assert completed.returncode == 0
        outputs[target] = completed.stdout
    assert "tools/voice_status.py" in outputs["alpha-voice-status"]
    assert "tests/voice" in outputs["alpha-voice-test"]
    assert "--voice-only" in outputs["alpha-voice-start"]
    assert "--voice-only" in outputs["alpha-voice-stop"]
    for target in ("alpha-voice-start", "alpha-voice-stop"):
        assert "alpha-restart" not in outputs[target]
        assert "go2rtc" not in outputs[target]


def test_install_start_stop_and_guardian_gate_keep_voice_as_one_sibling() -> None:
    installer = (ROOT / "tools/install_alpha_macos.sh").read_text()
    start = (ROOT / "tools/start_alpha.sh").read_text()
    stop = (ROOT / "tools/stop_alpha.sh").read_text()
    guardian = (ROOT / "tools/test_guardian.sh").read_text()

    assert "com.babymonitor.voice.plist.example" in installer
    assert 'VOICE_LABEL="com.babymonitor.voice"' in start
    assert 'VOICE_LABEL="com.babymonitor.voice"' in stop
    assert "run_voice_worker.py" in start
    assert "test_voice_worker_deploy.py" in guardian
    assert (
        "tests/tools/test_run_visual_worker.py \\\n"
        "    tests/deploy/test_voice_worker_deploy.py\n"
    ) in guardian
    voice_only_start = start.split('if [[ "$VOICE_ONLY_START" -eq 1 ]]', 1)[1].split("fi", 1)[0]
    voice_only_stop = stop.split('if [[ "$VOICE_ONLY_STOP" -eq 1 ]]', 1)[1].split("fi", 1)[0]
    for body in (voice_only_start, voice_only_stop):
        for sibling in ("go2rtc", "visual", "gauge", "watchdog", "audio"):
            assert sibling not in body.lower()


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
