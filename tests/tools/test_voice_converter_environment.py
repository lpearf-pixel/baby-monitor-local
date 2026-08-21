from __future__ import annotations

from pathlib import Path

import pytest

from tools.voice_converter_environment import validate_converter_environment_path


def test_converter_environment_path_allows_an_absent_runtime_directory(
    tmp_path: Path,
) -> None:
    assert validate_converter_environment_path(tmp_path) == (
        tmp_path / "runtime/voice-converter-venv"
    )


def test_converter_environment_path_rejects_a_symlinked_runtime_parent(
    tmp_path: Path,
) -> None:
    outside = tmp_path / "outside"
    outside.mkdir()
    (tmp_path / "runtime").symlink_to(outside, target_is_directory=True)

    with pytest.raises(ValueError, match="^VOICE_CONVERTER_PATH_INVALID$"):
        validate_converter_environment_path(tmp_path)
