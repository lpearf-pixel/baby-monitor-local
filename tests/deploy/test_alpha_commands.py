from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


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
