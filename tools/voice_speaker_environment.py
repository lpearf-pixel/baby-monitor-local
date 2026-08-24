from __future__ import annotations

import argparse
import json
import os
import subprocess
from collections.abc import Callable
from pathlib import Path


INVALID_ENVIRONMENT = "VOICE_SPEAKER_ENVIRONMENT_INVALID"
PINNED_PACKAGES = {
    "huggingface-hub": "0.36.0",
    "numpy": "1.26.4",
    "speechbrain": "1.0.3",
    "torch": "2.2.2",
    "torchaudio": "2.2.2",
}
_VERSION_PROBE = """\
import importlib
import importlib.metadata
import json

packages = {
    "huggingface-hub": ("huggingface_hub", "0.36.0"),
    "numpy": ("numpy", "1.26.4"),
    "speechbrain": ("speechbrain", "1.0.3"),
    "torch": ("torch", "2.2.2"),
    "torchaudio": ("torchaudio", "2.2.2"),
}
observed = {}
for distribution, (module, _expected) in packages.items():
    importlib.import_module(module)
    observed[distribution] = importlib.metadata.version(distribution)
print(json.dumps(observed, sort_keys=True, separators=(",", ":")))
"""
Runner = Callable[..., subprocess.CompletedProcess[str]]


def validate_speaker_environment_path(project_root: Path) -> Path:
    root = project_root.absolute()
    if root.is_symlink() or not root.is_dir():
        raise ValueError(INVALID_ENVIRONMENT)
    current = root
    for component in ("runtime", "voice-speaker-venv"):
        current = current / component
        if current.is_symlink() or (current.exists() and not current.is_dir()):
            raise ValueError(INVALID_ENVIRONMENT)
    return current


def validate_speaker_environment(
    project_root: Path,
    expected_prefix: Path,
    *,
    runner: Runner = subprocess.run,
) -> Path:
    try:
        environment = validate_speaker_environment_path(project_root)
        if expected_prefix.absolute() != environment:
            raise ValueError(INVALID_ENVIRONMENT)
        configuration = environment / "pyvenv.cfg"
        python = environment / "bin/python"
        values = {
            key.strip(): value.strip()
            for line in configuration.read_text(encoding="ascii").splitlines()
            if "=" in line
            for key, value in (line.split("=", 1),)
        }
        if (
            configuration.is_symlink()
            or not configuration.is_file()
            or python.is_symlink()
            or not python.is_file()
            or not os.access(python, os.X_OK)
            or values.get("include-system-site-packages") != "false"
        ):
            raise ValueError(INVALID_ENVIRONMENT)
        result = runner(
            (str(python), "-I", "-c", _VERSION_PROBE),
            check=False,
            capture_output=True,
            text=True,
            timeout=60,
        )
        observed = json.loads(result.stdout)
        if result.returncode != 0 or observed != PINNED_PACKAGES:
            raise ValueError(INVALID_ENVIRONMENT)
    except (
        json.JSONDecodeError,
        OSError,
        subprocess.SubprocessError,
        UnicodeDecodeError,
        ValueError,
    ) as error:
        if isinstance(error, ValueError) and str(error) == INVALID_ENVIRONMENT:
            raise
        raise ValueError(INVALID_ENVIRONMENT) from None
    return environment


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Validate the fixed Voice speaker environment"
    )
    parser.add_argument("--project-root", type=Path, default=Path.cwd())
    parser.add_argument("--expected-prefix", type=Path)
    parser.add_argument("--path-only", action="store_true")
    arguments = parser.parse_args()
    try:
        if arguments.path_only:
            if arguments.expected_prefix is not None:
                raise ValueError(INVALID_ENVIRONMENT)
            validate_speaker_environment_path(arguments.project_root)
        else:
            if arguments.expected_prefix is None:
                raise ValueError(INVALID_ENVIRONMENT)
            validate_speaker_environment(
                arguments.project_root, arguments.expected_prefix
            )
    except (OSError, ValueError):
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
