from __future__ import annotations

import argparse
from pathlib import Path


INVALID_PATH = "VOICE_CONVERTER_PATH_INVALID"


def validate_converter_environment_path(project_root: Path) -> Path:
    root = project_root.absolute()
    if root.is_symlink() or not root.is_dir():
        raise ValueError(INVALID_PATH)
    current = root
    for component in ("runtime", "voice-converter-venv"):
        current = current / component
        if current.is_symlink() or (current.exists() and not current.is_dir()):
            raise ValueError(INVALID_PATH)
    return current


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Validate the fixed Voice converter environment path"
    )
    parser.add_argument("--project-root", type=Path, default=Path.cwd())
    arguments = parser.parse_args()
    try:
        validate_converter_environment_path(arguments.project_root)
    except (OSError, ValueError):
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
