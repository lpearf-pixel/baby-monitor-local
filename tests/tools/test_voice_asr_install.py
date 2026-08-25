from __future__ import annotations

import subprocess
from pathlib import Path

from tools.voice_asr_install import install_asr_environment


def test_installer_builds_a_clean_hash_locked_staging_environment_before_publish(
    tmp_path: Path,
) -> None:
    runtime = tmp_path / "runtime"
    destination = runtime / "voice-asr-venv"
    destination.mkdir(parents=True)
    (destination / "stale-package").write_text("must not survive", encoding="ascii")
    requirements = tmp_path / "config/voice-asr-requirements.txt"
    requirements.parent.mkdir()
    requirements.write_text("package==1 --hash=sha256:" + "a" * 64 + "\n", encoding="ascii")
    base_python = tmp_path / "python3.11"
    base_python.write_text("fixture", encoding="ascii")
    commands: list[tuple[str, ...]] = []
    validated: list[Path] = []

    def runner(command: tuple[str, ...], **_kwargs: object):
        commands.append(command)
        if command[1:] == ("-m", "venv", command[-1]):
            staging = Path(command[-1])
            (staging / "bin").mkdir(parents=True, exist_ok=True)
            (staging / "bin/python").write_text("fixture", encoding="ascii")
        return subprocess.CompletedProcess(command, 0, "", "")

    def validator(_root: Path, candidate: Path) -> Path:
        validated.append(candidate)
        return candidate

    def publisher(staging: Path, final: Path) -> Path | None:
        previous = runtime / ".voice-asr-venv.previous"
        final.rename(previous)
        staging.rename(final)
        return previous

    result = install_asr_environment(
        tmp_path,
        base_python=base_python,
        runner=runner,
        candidate_validator=validator,
        final_validator=validator,
        publisher=publisher,
    )

    assert result == destination
    assert not (destination / "stale-package").exists()
    assert len(commands) == 2
    assert commands[0][0:3] == (str(base_python), "-m", "venv")
    assert "--upgrade" not in commands[0]
    assert commands[1][1:4] == ("-m", "pip", "install")
    assert "--require-hashes" in commands[1]
    assert "--no-deps" in commands[1]
    assert commands[1][-2:] == ("--requirement", str(requirements))
    assert len(validated) == 2
    assert validated[0].name.startswith(".voice-asr-venv.staging-")
    assert validated[1] == destination
