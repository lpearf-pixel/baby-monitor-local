from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_readme_lists_hd_preview_commands() -> None:
    content = (ROOT / "README.md").read_text(encoding="utf-8")
    for expected in (
        "1280×720",
        "10 FPS",
        "make alpha-quality-hd",
        "make alpha-quality-info",
        "make alpha-source-check",
        "make alpha-quality-rollback",
    ):
        assert expected in content


def test_quickstart_documents_hd_preview_boundary() -> None:
    content = (ROOT / "docs/runbooks/ALPHA_QUICKSTART.md").read_text(
        encoding="utf-8"
    )
    for expected in (
        "make alpha-quality-hd",
        "make alpha-quality-info",
        "make alpha-source-check",
        "make alpha-quality-rollback",
        "1280×720",
        "10 FPS",
        "transport=tcp",
        "transport=auto",
        "WebRTC/MSE",
    ):
        assert expected in content
