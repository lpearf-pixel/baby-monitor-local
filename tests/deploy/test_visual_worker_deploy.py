from __future__ import annotations

import subprocess
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def test_visual_worker_entrypoint_has_safe_help_without_starting_services() -> None:
    result = subprocess.run(
        [
            sys.executable,
            str(ROOT / "tools/run_visual_worker.py"),
            "--help",
        ],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0
    assert "--settings" in result.stdout
    assert "Traceback" not in result.stderr


def test_disabled_visual_worker_exits_without_opening_runtime_services(
    tmp_path: Path,
) -> None:
    settings_path = tmp_path / "settings.yaml"
    settings_path.write_text(
        (ROOT / "config/settings.example.yaml").read_text(encoding="utf-8"),
        encoding="utf-8",
    )

    result = subprocess.run(
        [
            sys.executable,
            str(ROOT / "tools/run_visual_worker.py"),
            "--settings",
            str(settings_path),
        ],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
        timeout=5,
    )

    assert result.returncode == 0
    assert result.stdout == ""
    assert result.stderr == ""


def test_invalid_visual_worker_configuration_is_redacted(tmp_path: Path) -> None:
    settings_path = tmp_path / "private-family-settings.yaml"
    settings_path.write_text("visual: [invalid", encoding="utf-8")

    result = subprocess.run(
        [
            sys.executable,
            str(ROOT / "tools/run_visual_worker.py"),
            "--settings",
            str(settings_path),
        ],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
        timeout=5,
    )

    assert result.returncode == 2
    assert result.stderr.strip() == "visual_worker_startup_failed"
    assert "private-family" not in result.stderr
    assert "Traceback" not in result.stderr

