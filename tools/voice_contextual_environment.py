from __future__ import annotations

import json
import os
import re
import subprocess
from collections.abc import Callable
from pathlib import Path


INVALID_ENVIRONMENT = "VOICE_CONTEXTUAL_ENVIRONMENT_INVALID"
_PIN = re.compile(r"^([A-Za-z0-9_.-]+)==([^ ]+) \\$")
_REQUIREMENTS = Path(__file__).parents[1] / "config/voice-contextual-requirements.txt"
Runner = Callable[..., subprocess.CompletedProcess[str]]


def _load_pins() -> dict[str, str]:
    pins: dict[str, str] = {}
    for line in _REQUIREMENTS.read_text(encoding="ascii").splitlines():
        match = _PIN.fullmatch(line)
        if match is not None:
            pins[match.group(1).lower().replace("_", "-")] = match.group(2)
    pins["pip"] = "26.1.2"
    pins["setuptools"] = "83.0.0"
    if len(pins) != 40:
        raise RuntimeError(INVALID_ENVIRONMENT)
    return dict(sorted(pins.items()))


PINNED_CONTEXTUAL_PACKAGES = _load_pins()
_VERSION_PROBE = """\
import importlib
import importlib.metadata
import json

importlib.import_module("numpy")
importlib.import_module("onnxruntime")
module = importlib.import_module("funasr_onnx")
getattr(module, "ContextualParaformer")
observed = {
    distribution.metadata["Name"].lower().replace("_", "-"): distribution.version
    for distribution in importlib.metadata.distributions()
}
print(json.dumps(observed, sort_keys=True, separators=(",", ":")))
"""


def validate_contextual_environment_path(project_root: Path) -> Path:
    root = Path(project_root).absolute()
    if root.is_symlink() or not root.is_dir():
        raise ValueError(INVALID_ENVIRONMENT)
    current = root
    for component in ("runtime", "voice-contextual-venv"):
        current = current / component
        if current.is_symlink() or (current.exists() and not current.is_dir()):
            raise ValueError(INVALID_ENVIRONMENT)
    return current


def validate_contextual_environment(
    project_root: Path,
    expected_prefix: Path,
    *,
    runner: Runner = subprocess.run,
) -> Path:
    environment = validate_contextual_environment_path(project_root)
    if Path(expected_prefix).absolute() != environment:
        raise ValueError(INVALID_ENVIRONMENT)
    return _validate_environment(environment, runner)


def validate_contextual_environment_candidate(
    project_root: Path,
    expected_prefix: Path,
    *,
    runner: Runner = subprocess.run,
) -> Path:
    root = Path(project_root).absolute()
    environment = Path(expected_prefix).absolute()
    runtime = root / "runtime"
    if (
        root.is_symlink()
        or not root.is_dir()
        or runtime.is_symlink()
        or environment.parent != runtime
        or not environment.name.startswith(".voice-contextual-venv.staging-")
        or environment.is_symlink()
    ):
        raise ValueError(INVALID_ENVIRONMENT)
    return _validate_environment(environment, runner)


def _validate_environment(environment: Path, runner: Runner) -> Path:
    try:
        info = environment.lstat()
        configuration = environment / "pyvenv.cfg"
        python = environment / "bin/python"
        values = {
            key.strip(): value.strip()
            for line in configuration.read_text(encoding="ascii").splitlines()
            if "=" in line
            for key, value in (line.split("=", 1),)
        }
        configured_executable = values.get("executable")
        invalid_python_link = python.is_symlink() and (
            configured_executable is None
            or python.resolve(strict=True)
            != Path(configured_executable).resolve(strict=True)
        )
        if (
            (info.st_mode & 0o777) != 0o700
            or info.st_uid != os.getuid()
            or configuration.is_symlink()
            or not configuration.is_file()
            or invalid_python_link
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
            timeout=180,
        )
        observed = json.loads(result.stdout)
        if result.returncode != 0 or observed != PINNED_CONTEXTUAL_PACKAGES:
            raise ValueError(INVALID_ENVIRONMENT)
        return environment
    except (
        json.JSONDecodeError,
        OSError,
        subprocess.SubprocessError,
        UnicodeDecodeError,
        ValueError,
    ) as exc:
        if str(exc) == INVALID_ENVIRONMENT:
            raise
        raise ValueError(INVALID_ENVIRONMENT) from None
