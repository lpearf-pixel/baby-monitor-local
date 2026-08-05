from __future__ import annotations

import subprocess
import shutil
from pathlib import Path

import pytest
import yaml


ROOT = Path(__file__).resolve().parents[2]


def test_alpha_status_is_clean_in_downloaded_archive(tmp_path: Path) -> None:
    shutil.copy2(ROOT / "Makefile", tmp_path / "Makefile")

    result = subprocess.run(
        ["make", "alpha-status"],
        cwd=tmp_path,
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0
    assert "Source: packaged archive" in result.stdout
    assert "fatal: not a git repository" not in result.stderr


def test_alpha_workflow_does_not_require_chmod() -> None:
    tracked_guides = [
        ROOT / "README.md",
        ROOT / "docs/runbooks/ALPHA_QUICKSTART.md",
        ROOT / "tools/install_alpha_macos.sh",
    ]

    combined = "\n".join(path.read_text(encoding="utf-8") for path in tracked_guides)

    assert "chmod +x tools/*.sh" not in combined
    assert "./tools/install_alpha_macos.sh" not in combined
    assert "./tools/start_alpha.sh" not in combined
    assert "./tools/stop_alpha.sh" not in combined


def test_makefile_exposes_stable_alpha_commands() -> None:
    content = (ROOT / "Makefile").read_text(encoding="utf-8")

    assert "alpha-update:" in content
    assert "alpha-install:" in content
    assert "alpha-start:" in content
    assert "alpha-stop:" in content
    assert "bash tools/install_alpha_macos.sh" in content
    assert "bash tools/start_alpha.sh" in content
    assert "bash tools/stop_alpha.sh" in content


def test_makefile_exposes_hd_quality_commands() -> None:
    content = (ROOT / "Makefile").read_text(encoding="utf-8")

    assert "alpha-quality-hd:" in content
    assert "alpha-quality-info:" in content
    assert "alpha-quality-rollback:" in content
    assert "alpha-source-check:" in content
    assert "tools/alpha_quality.py apply-hd" in content
    assert "tools/alpha_quality.py info" in content
    assert "tools/alpha_quality.py rollback" in content
    assert "tools/alpha_quality.py check" in content


def test_makefile_exposes_safe_subtype_probe() -> None:
    content = (ROOT / "Makefile").read_text(encoding="utf-8")

    assert "alpha-subtype-probe:" in content
    assert "tools/alpha_quality.py probe-subtypes" in content
    assert "--candidates 0 1 2 3 4 5" in content
    assert "--base-url" in content
    assert "--restart-command" in content


def test_makefile_exposes_verified_native_hd_subtype_apply() -> None:
    content = (ROOT / "Makefile").read_text(encoding="utf-8")

    assert "alpha-subtype-apply:" in content
    assert "tools/alpha_quality.py apply-subtype" in content
    assert "--subtype 3" in content
    assert "--minimum-width 1920" in content
    assert "--minimum-height 1080" in content
    assert "--dashboard-url" in content
    assert "--restart-command" in content


def test_subtype_probe_make_dry_run_does_not_start_services() -> None:
    result = subprocess.run(
        ["make", "-n", "alpha-subtype-probe"],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0
    assert "probe-subtypes" in result.stdout
    assert "No such file or directory" not in result.stderr


def test_subtype_apply_make_dry_run_does_not_start_services() -> None:
    result = subprocess.run(
        ["make", "-n", "alpha-subtype-apply"],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0
    assert "apply-subtype" in result.stdout
    assert "alpha-restart" in result.stdout
    assert "No such file or directory" not in result.stderr


def test_default_live_profile_is_hd_ten_fps() -> None:
    content = (ROOT / "config/go2rtc.alpha.yaml").read_text(encoding="utf-8")

    assert "#width=1280#height=720#raw=-r 10" in content
    assert "#fps=5" not in content


def test_default_config_has_fixed_on_demand_videotoolbox_profile() -> None:
    config = yaml.safe_load(
        (ROOT / "config/go2rtc.alpha.yaml").read_text(encoding="utf-8")
    )

    assert config["streams"]["source_compat"] == (
        "ffmpeg:source#video=h264#hardware=videotoolbox"
        "#width=2560#height=1440#bitrate=6M"
    )


def test_installer_preserves_existing_runtime_config() -> None:
    content = (ROOT / "tools/install_alpha_macos.sh").read_text(encoding="utf-8")

    assert 'if [[ ! -f "$ROOT/runtime/go2rtc.yaml" ]]; then' in content
    assert 'cp "$ROOT/config/go2rtc.alpha.yaml" "$ROOT/runtime/go2rtc.yaml"' in content
    assert "1280x720 MJPEG at 10 FPS" in content


@pytest.mark.parametrize(
    ("target", "command"),
    [
        ("alpha-go2rtc-info", "info"),
        ("alpha-go2rtc-rebuild", "rebuild"),
        ("alpha-go2rtc-rollback", "rollback"),
    ],
)
def test_makefile_exposes_go2rtc_build_lifecycle(target: str, command: str) -> None:
    result = subprocess.run(
        ["make", "-n", target],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0
    assert f"tools/go2rtc_build.py {command}" in result.stdout


def test_installer_ensures_patched_build_instead_of_downloading_release() -> None:
    content = (ROOT / "tools/install_alpha_macos.sh").read_text(encoding="utf-8")

    assert 'brew list go >/dev/null 2>&1 || brew install go' in content
    assert 'tools/go2rtc_build.py" ensure' in content
    assert "go2rtc/releases/download" not in content
