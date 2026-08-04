from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[2]
CLI = ROOT / "tools" / "alpha_quality.py"


def run_cli(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(CLI), *args],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )


def test_info_prints_only_derived_quality_fields(tmp_path: Path) -> None:
    config = tmp_path / "go2rtc.yaml"
    config.write_text(
        yaml.safe_dump(
            {
                "xiaomi": {"123": "V1:super-secret"},
                "streams": {
                    "source": (
                        "xiaomi://123:cn@192.0.2.10?did=456"
                        "&model=example.camera&subtype=hd"
                    ),
                    "live": (
                        "ffmpeg:source#video=mjpeg#width=1280"
                        "#height=720#raw=-r 10"
                    ),
                },
            }
        ),
        encoding="utf-8",
    )

    result = run_cli("info", "--config", str(config))

    assert result.returncode == 0
    assert result.stdout.splitlines() == [
        "source_quality=hd",
        "transport=auto",
        "live_width=1280",
        "live_height=720",
        "live_fps=10",
    ]
    combined = result.stdout + result.stderr
    assert "xiaomi://" not in combined
    assert "V1:" not in combined
    assert "192.0.2.10" not in combined
    assert "did=456" not in combined


def test_apply_hd_reports_backup_without_printing_config(tmp_path: Path) -> None:
    config = tmp_path / "go2rtc.yaml"
    backups = tmp_path / "backups"
    config.write_text(
        yaml.safe_dump(
            {
                "xiaomi": {"123": "V1:super-secret"},
                "streams": {
                    "source": (
                        "xiaomi://123:cn@192.0.2.10?did=456"
                        "&model=example.camera&transport=tcp"
                    ),
                    "live": "old",
                },
            }
        ),
        encoding="utf-8",
    )

    result = run_cli(
        "apply-hd",
        "--config",
        str(config),
        "--backups",
        str(backups),
    )

    assert result.returncode == 0
    assert "backup=" in result.stdout
    combined = result.stdout + result.stderr
    assert "xiaomi://" not in combined
    assert "V1:" not in combined
    assert "192.0.2.10" not in combined


def test_cli_returns_code_two_for_missing_source(tmp_path: Path) -> None:
    config = tmp_path / "go2rtc.yaml"
    config.write_text("streams: {live: old}\n", encoding="utf-8")

    result = run_cli("info", "--config", str(config))

    assert result.returncode == 2
    assert result.stderr.strip() == "SOURCE_NOT_CONFIGURED"
