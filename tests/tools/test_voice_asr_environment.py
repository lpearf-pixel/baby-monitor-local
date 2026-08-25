from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from unittest.mock import ANY

import pytest

from tools.voice_asr_environment import (
    INVALID_ENVIRONMENT,
    PINNED_PACKAGES,
    validate_asr_environment,
    validate_asr_environment_path,
)


def _environment(tmp_path: Path) -> tuple[Path, Path]:
    environment = tmp_path / "runtime/voice-asr-venv"
    (environment / "bin").mkdir(parents=True)
    python = environment / "bin/python"
    python.write_text("#!/bin/sh\nexit 0\n", encoding="ascii")
    python.chmod(0o755)
    (environment / "pyvenv.cfg").write_text(
        "include-system-site-packages = false\n", encoding="ascii"
    )
    return environment, python


def test_asr_environment_path_allows_only_private_runtime_components(
    tmp_path: Path,
) -> None:
    assert validate_asr_environment_path(tmp_path) == (
        tmp_path / "runtime/voice-asr-venv"
    )
    outside = tmp_path / "outside"
    outside.mkdir()
    (tmp_path / "runtime").symlink_to(outside, target_is_directory=True)
    with pytest.raises(ValueError, match=f"^{INVALID_ENVIRONMENT}$"):
        validate_asr_environment_path(tmp_path)


def test_asr_environment_checks_exact_isolated_runtime_versions(
    tmp_path: Path,
) -> None:
    environment, python = _environment(tmp_path)
    calls: list[tuple[str, ...]] = []

    def runner(command: tuple[str, ...], **_kwargs: object) -> subprocess.CompletedProcess[str]:
        calls.append(command)
        return subprocess.CompletedProcess(
            command,
            0,
            stdout=json.dumps(PINNED_PACKAGES, sort_keys=True, separators=(",", ":")),
            stderr="",
        )

    assert validate_asr_environment(tmp_path, environment, runner=runner) == environment
    assert calls == [(str(python), "-I", "-c", ANY)]
    assert PINNED_PACKAGES == {
        "numpy": "2.3.5",
        "pip": "26.1.2",
        "setuptools": "83.0.0",
        "sherpa-onnx": "1.13.6",
        "sherpa-onnx-core": "1.13.6",
    }


def test_asr_environment_rejects_drift_system_packages_and_wrong_prefix(
    tmp_path: Path,
) -> None:
    environment, _python = _environment(tmp_path)
    observed = dict(PINNED_PACKAGES)
    observed["sherpa-onnx"] = "9.9.9"

    def runner(command: tuple[str, ...], **_kwargs: object) -> subprocess.CompletedProcess[str]:
        return subprocess.CompletedProcess(
            command,
            0,
            stdout=json.dumps(observed, sort_keys=True, separators=(",", ":")),
            stderr="private path",
        )

    with pytest.raises(ValueError, match=f"^{INVALID_ENVIRONMENT}$"):
        validate_asr_environment(tmp_path, environment, runner=runner)
    with pytest.raises(ValueError, match=f"^{INVALID_ENVIRONMENT}$"):
        validate_asr_environment(tmp_path, tmp_path / "elsewhere", runner=runner)
    (environment / "pyvenv.cfg").write_text(
        "include-system-site-packages = true\n", encoding="ascii"
    )
    with pytest.raises(ValueError, match=f"^{INVALID_ENVIRONMENT}$"):
        validate_asr_environment(tmp_path, environment, runner=runner)


def test_asr_environment_accepts_standard_venv_python_symlink(
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

    assert validate_asr_environment(tmp_path, environment, runner=runner) == environment
