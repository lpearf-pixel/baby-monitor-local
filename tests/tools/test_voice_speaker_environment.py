from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from tools.voice_speaker_environment import (
    INVALID_ENVIRONMENT,
    PINNED_PACKAGES,
    validate_speaker_environment,
    validate_speaker_environment_path,
)


def _environment(tmp_path: Path) -> tuple[Path, Path]:
    environment = tmp_path / "runtime/voice-speaker-venv"
    (environment / "bin").mkdir(parents=True)
    python = environment / "bin/python"
    python.write_text("#!/bin/sh\nexit 0\n", encoding="ascii")
    python.chmod(0o755)
    (environment / "pyvenv.cfg").write_text(
        "include-system-site-packages = false\n", encoding="ascii"
    )
    return environment, python


def test_speaker_environment_path_allows_an_absent_private_runtime(
    tmp_path: Path,
) -> None:
    assert validate_speaker_environment_path(tmp_path) == (
        tmp_path / "runtime/voice-speaker-venv"
    )


@pytest.mark.parametrize("component", ("runtime", "voice-speaker-venv"))
def test_speaker_environment_path_rejects_symlink_components(
    tmp_path: Path, component: str
) -> None:
    outside = tmp_path / "outside"
    outside.mkdir()
    if component == "runtime":
        (tmp_path / "runtime").symlink_to(outside, target_is_directory=True)
    else:
        (tmp_path / "runtime").mkdir()
        (tmp_path / "runtime/voice-speaker-venv").symlink_to(
            outside, target_is_directory=True
        )

    with pytest.raises(ValueError, match=f"^{INVALID_ENVIRONMENT}$"):
        validate_speaker_environment_path(tmp_path)


def test_speaker_environment_accepts_only_the_fixed_isolated_prefix(
    tmp_path: Path,
) -> None:
    environment, _python = _environment(tmp_path)

    with pytest.raises(ValueError, match=f"^{INVALID_ENVIRONMENT}$"):
        validate_speaker_environment(tmp_path, tmp_path / "somewhere-else")

    (environment / "pyvenv.cfg").write_text(
        "include-system-site-packages = true\n", encoding="ascii"
    )
    with pytest.raises(ValueError, match=f"^{INVALID_ENVIRONMENT}$"):
        validate_speaker_environment(tmp_path, environment)


def test_speaker_environment_checks_all_pinned_versions_in_one_child(
    tmp_path: Path,
) -> None:
    environment, python = _environment(tmp_path)
    calls: list[tuple[str, ...]] = []
    options: list[dict[str, object]] = []

    def runner(command: tuple[str, ...], **kwargs: object) -> subprocess.CompletedProcess[str]:
        calls.append(command)
        options.append(kwargs)
        return subprocess.CompletedProcess(
            command,
            0,
            stdout=json.dumps(PINNED_PACKAGES, sort_keys=True, separators=(",", ":")),
            stderr="",
        )

    assert validate_speaker_environment(tmp_path, environment, runner=runner) == environment
    assert len(calls) == 1
    assert calls[0][0] == str(python)
    assert calls[0][1] == "-I"
    assert options[0]["timeout"] == 180


def test_speaker_environment_rejects_version_drift_without_exposing_output(
    tmp_path: Path,
) -> None:
    environment, _python = _environment(tmp_path)
    observed = dict(PINNED_PACKAGES)
    observed["torch"] = "9.9.9"

    def runner(command: tuple[str, ...], **_kwargs: object) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(
            command,
            0,
            stdout=json.dumps(observed, sort_keys=True, separators=(",", ":")),
            stderr="private child path",
        )

    with pytest.raises(ValueError, match=f"^{INVALID_ENVIRONMENT}$") as error:
        validate_speaker_environment(tmp_path, environment, runner=runner)
    assert "private" not in str(error.value)


def test_speaker_environment_accepts_the_standard_venv_python_symlink(
    tmp_path: Path,
) -> None:
    environment, python = _environment(tmp_path)
    python.unlink()
    python.symlink_to(Path(sys.executable).resolve())
    (environment / "pyvenv.cfg").write_text(
        "include-system-site-packages = false\n"
        f"executable = {Path(sys.executable).resolve()}\n",
        encoding="ascii",
    )

    def runner(command: tuple[str, ...], **_kwargs: object) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(
            command,
            0,
            stdout=json.dumps(PINNED_PACKAGES, sort_keys=True, separators=(",", ":")),
            stderr="",
        )

    assert validate_speaker_environment(tmp_path, environment, runner=runner) == environment
