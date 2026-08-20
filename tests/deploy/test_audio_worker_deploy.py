from __future__ import annotations

import plistlib
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def test_audio_launchd_is_independent_and_private() -> None:
    path = ROOT / "deploy/launchd/com.babymonitor.audio.plist.example"
    payload = plistlib.loads(path.read_bytes())

    assert payload["Label"] == "com.babymonitor.audio"
    assert payload["ProgramArguments"] == [
        "__PROJECT_ROOT__/.venv-alpha/bin/python",
        "__PROJECT_ROOT__/tools/run_audio_worker.py",
        "--settings",
        "__PROJECT_ROOT__/runtime/settings.yaml",
    ]
    assert payload["KeepAlive"] == {"SuccessfulExit": False}
    assert payload["ProcessType"] == "Background"
    assert payload["StandardOutPath"].endswith("runtime/logs/audio.log")
    assert payload["StandardErrorPath"].endswith("runtime/logs/audio.log")


def test_audio_make_targets_are_bounded_and_do_not_run_guardian_acceptance() -> None:
    status = subprocess.run(
        ["make", "-n", "alpha-audio-status"],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    test = subprocess.run(
        ["make", "-n", "alpha-audio-test"],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )

    assert status.returncode == 0
    assert "runtime/status/audio.json" in status.stdout
    assert test.returncode == 0
    assert "tests/audio" in test.stdout
    assert "test_guardian_live" not in test.stdout


def test_voice_v0_make_targets_separate_software_and_live_probes() -> None:
    software = subprocess.run(
        ["make", "-n", "alpha-voice-v0-test"],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    live = subprocess.run(
        ["make", "-n", "alpha-voice-v0-probe"],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    stability = subprocess.run(
        ["make", "-n", "alpha-voice-v0-stability"],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )

    assert software.returncode == 0
    assert "tests/audio" in software.stdout
    assert "voice_audio_probe.py synthetic" in software.stdout
    assert "voice_audio_probe.py live --duration 60" in live.stdout
    assert "voice_audio_probe.py live --duration 600" in stability.stdout
    assert "alpha-restart" not in live.stdout + stability.stdout


def test_install_start_and_stop_manage_only_the_audio_sibling_job() -> None:
    installer = (ROOT / "tools/install_alpha_macos.sh").read_text()
    start = (ROOT / "tools/start_alpha.sh").read_text()
    stop = (ROOT / "tools/stop_alpha.sh").read_text()

    assert "com.babymonitor.audio.plist.example" in installer
    assert "com.babymonitor.audio" in start
    assert "com.babymonitor.audio" in stop
    assert "run_audio_worker.py" in start
