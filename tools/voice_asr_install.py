from __future__ import annotations

import argparse
import ctypes
import os
import platform
import shutil
import subprocess
import tempfile
import uuid
from collections.abc import Callable
from pathlib import Path

from tools.voice_asr_environment import (
    validate_asr_environment,
    validate_asr_environment_candidate,
    validate_asr_environment_path,
)


INSTALL_FAILED = "VOICE_ASR_INSTALL_FAILED"
Runner = Callable[..., subprocess.CompletedProcess[str]]
Validator = Callable[[Path, Path], Path]
Publisher = Callable[[Path, Path], Path | None]
_RENAME_SWAP = 0x00000002


def install_asr_environment(
    project_root: Path,
    *,
    base_python: Path,
    runner: Runner = subprocess.run,
    candidate_validator: Validator = validate_asr_environment_candidate,
    final_validator: Validator = validate_asr_environment,
    publisher: Publisher | None = None,
) -> Path:
    """Build a clean hash-locked venv and atomically publish it at the fixed path."""

    root = project_root.resolve(strict=True)
    destination = validate_asr_environment_path(root)
    requirements = root / "config/voice-asr-requirements.txt"
    if (
        not base_python.resolve(strict=True).is_file()
        or requirements.is_symlink()
        or not requirements.is_file()
    ):
        raise ValueError(INSTALL_FAILED)
    runtime = destination.parent
    runtime.mkdir(mode=0o700, parents=True, exist_ok=True)
    staging = Path(
        tempfile.mkdtemp(prefix=".voice-asr-venv.staging-", dir=runtime)
    )
    published_previous: Path | None = None
    publish = publisher or _publish_environment
    try:
        first = runner(
            (str(base_python), "-m", "venv", str(staging)),
            check=False,
            capture_output=True,
            text=True,
            timeout=300,
        )
        python = staging / "bin/python"
        if first.returncode != 0 or not python.is_file():
            raise ValueError(INSTALL_FAILED)
        second = runner(
            (
                str(python),
                "-m",
                "pip",
                "install",
                "--disable-pip-version-check",
                "--index-url",
                "https://pypi.org/simple",
                "--require-hashes",
                "--no-deps",
                "--requirement",
                str(requirements),
            ),
            check=False,
            capture_output=True,
            text=True,
            timeout=900,
        )
        if second.returncode != 0:
            raise ValueError(INSTALL_FAILED)
        candidate_validator(root, staging)
        published_previous = publish(staging, destination)
        try:
            final_validator(root, destination)
        except Exception:
            if published_previous is not None and published_previous.exists():
                _rename_swap(destination, published_previous)
            raise
        return destination
    except (OSError, subprocess.SubprocessError, ValueError):
        raise ValueError(INSTALL_FAILED) from None
    finally:
        if staging.exists():
            shutil.rmtree(staging, ignore_errors=True)


def _publish_environment(staging: Path, destination: Path) -> Path | None:
    if not destination.exists():
        staging.rename(destination)
        return None
    _rename_swap(staging, destination)
    retained = destination.parent / f".voice-asr-venv.retired-{uuid.uuid4().hex}"
    staging.rename(retained)
    return retained


def _rename_swap(first: Path, second: Path) -> None:
    if platform.system() != "Darwin":
        raise ValueError(INSTALL_FAILED)
    function = ctypes.CDLL(None, use_errno=True).renamex_np
    function.argtypes = (ctypes.c_char_p, ctypes.c_char_p, ctypes.c_uint)
    function.restype = ctypes.c_int
    result = function(os.fsencode(first), os.fsencode(second), _RENAME_SWAP)
    if result != 0:
        raise OSError(ctypes.get_errno(), INSTALL_FAILED)


def main() -> int:
    parser = argparse.ArgumentParser(description="Install the fixed Voice ASR runtime")
    parser.add_argument("--project-root", type=Path, default=Path.cwd())
    parser.add_argument("--base-python", type=Path, required=True)
    arguments = parser.parse_args()
    try:
        install_asr_environment(
            arguments.project_root,
            base_python=arguments.base_python,
        )
    except (OSError, ValueError):
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
