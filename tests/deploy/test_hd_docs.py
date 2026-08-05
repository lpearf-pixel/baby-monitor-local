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
        "make alpha-go2rtc-info",
        "H.265",
        "source_compat",
        "VideoToolbox",
        "native",
        "compat",
    ):
        assert expected in content
    assert "2560×1440 H.264 原流" not in content
    assert "不增加 1440p FFmpeg 编码" not in content


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
        "make alpha-go2rtc-info",
        "source_codec=H265",
        "source_compat",
        "VideoToolbox",
        "active_profile",
        "compat_encoder_count",
        "PTZ_DISABLED",
    ):
        assert expected in content
    assert "2560×1440 H.264 原流" not in content
    assert "不会启动 1440p FFmpeg 编码" not in content


def test_checkpoint_and_decisions_record_hybrid_hd_boundary() -> None:
    checkpoint = (ROOT / "docs/CHECKPOINT.md").read_text(encoding="utf-8")
    decisions = (ROOT / "docs/DECISIONS.md").read_text(encoding="utf-8")

    for expected in ("PR #4", "Draft", "H.265", "VideoToolbox", "实机"):
        assert expected in checkpoint
    for expected in (
        "ADR-006",
        "H.265",
        "source_compat",
        "VideoToolbox",
        "按需",
    ):
        assert expected in decisions


def test_go2rtc_build_design_covers_both_audited_patch_hunks() -> None:
    content = (
        ROOT
        / "docs/superpowers/specs/2026-08-04-intel-macos-go2rtc-build-design.md"
    ).read_text(encoding="utf-8")

    for expected in ("udp4", "hev1", "hvc1", "source_codec=H265"):
        assert expected in content
