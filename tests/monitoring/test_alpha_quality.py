from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path

import pytest
import yaml

from packages.monitoring.alpha_quality import (
    ANALYSIS_STREAM,
    COMPAT_HD,
    GAUGE_STREAM,
    LIVE_HD,
    QualityConfigError,
    apply_gauge_stream,
    apply_hd,
    inspect_quality,
    rollback_latest,
    upgrade_to_hd,
    with_visual_analysis_stream,
    with_source_subtype,
)


def test_upgrade_to_hd_preserves_unknown_xiaomi_parameters() -> None:
    original = {
        "xiaomi": {"123": "V1:secret"},
        "streams": {
            "source": (
                "xiaomi://123:cn@192.0.2.10?did=456&model=example.camera"
                "&subtype=sd&transport=tcp&channel=1&vendor_hint=keep"
            ),
            "live": "ffmpeg:source#video=mjpeg#width=960#height=540#fps=5",
        },
    }

    upgraded = upgrade_to_hd(deepcopy(original))
    source = upgraded["streams"]["source"]

    assert "subtype=hd" in source
    assert "transport=" not in source
    assert "channel=1" in source
    assert "vendor_hint=keep" in source
    assert upgraded["streams"]["live"] == LIVE_HD
    assert upgraded["streams"]["source_compat"] == COMPAT_HD
    assert upgraded["streams"]["gauge"] == GAUGE_STREAM
    assert upgraded["xiaomi"] == original["xiaomi"]


def test_upgrade_to_hd_does_not_mutate_input() -> None:
    original = {
        "streams": {
            "source": "xiaomi://123:cn@192.0.2.10?did=456&model=example.camera",
            "live": "old",
        }
    }
    before = deepcopy(original)

    upgrade_to_hd(original)

    assert original == before


def test_upgrade_is_idempotent() -> None:
    config = {
        "streams": {
            "source": "xiaomi://123:cn@192.0.2.10?did=456&model=example.camera",
            "live": LIVE_HD,
        }
    }

    once = upgrade_to_hd(deepcopy(config))
    twice = upgrade_to_hd(deepcopy(once))

    assert twice == once
    assert twice["streams"]["source"].count("subtype=hd") == 1
    assert twice["streams"]["source_compat"] == COMPAT_HD
    assert twice["streams"]["analysis"] == ANALYSIS_STREAM
    assert twice["streams"]["gauge"] == GAUGE_STREAM


def test_visual_analysis_profile_is_fixed_idempotent_and_preserves_input() -> None:
    original = {
        "streams": {
            "source": (
                "xiaomi://device:cn@192.0.2.10?"
                "did=example&vendor_hint=keep"
            ),
            "recording": "keep",
        }
    }

    updated = with_visual_analysis_stream(original)

    assert updated["streams"]["analysis"] == ANALYSIS_STREAM
    assert updated["streams"]["recording"] == "keep"
    assert original["streams"].get("analysis") is None
    assert with_visual_analysis_stream(updated) == updated


@pytest.mark.parametrize(
    "config",
    [
        {"streams": {}},
        {"streams": {"source": "rtsp://camera.example/stream"}},
    ],
)
def test_visual_analysis_profile_requires_configured_xiaomi_source(
    config: dict[str, object],
) -> None:
    with pytest.raises(QualityConfigError, match="SOURCE_NOT_CONFIGURED"):
        with_visual_analysis_stream(config)


def test_inspect_quality_returns_only_derived_values() -> None:
    config = upgrade_to_hd(
        {
            "streams": {
                "source": "xiaomi://123:cn@192.0.2.10?did=456&model=example.camera",
                "live": "old",
            }
        }
    )

    info = inspect_quality(config)

    assert info.source_quality == "hd"
    assert info.transport == "auto"
    assert (info.live_width, info.live_height, info.live_fps) == (1280, 720, 10)
    assert info.compat_profile == "videotoolbox-1440p-6M"
    rendered = repr(info)
    assert "xiaomi://" not in rendered
    assert "192.0.2.10" not in rendered
    assert "V1:" not in rendered


def test_upgrade_replaces_obsolete_compat_profile_without_touching_unknown_keys() -> None:
    original = {
        "streams": {
            "source": "xiaomi://123:cn@192.0.2.10?did=456&vendor_hint=keep",
            "live": "old",
            "source_compat": "ffmpeg:source#video=h264",
            "recording": "keep",
        }
    }

    upgraded = upgrade_to_hd(original)

    assert upgraded["streams"]["source_compat"] == COMPAT_HD
    assert upgraded["streams"]["recording"] == "keep"
    assert "vendor_hint=keep" in upgraded["streams"]["source"]
    assert original["streams"]["source_compat"] == "ffmpeg:source#video=h264"


def test_upgrade_rejects_missing_source() -> None:
    with pytest.raises(QualityConfigError, match="SOURCE_NOT_CONFIGURED"):
        upgrade_to_hd({"streams": {"live": "old"}})


def test_source_subtype_candidate_preserves_unknown_parameters_and_input() -> None:
    original = {
        "streams": {
            "source": (
                "xiaomi://123:cn@192.0.2.10?did=456&subtype=hd"
                "&transport=tcp&vendor_hint=keep"
            )
        }
    }

    updated = with_source_subtype(original, 3)

    assert "subtype=3" in updated["streams"]["source"]
    assert "transport=" not in updated["streams"]["source"]
    assert "vendor_hint=keep" in updated["streams"]["source"]
    assert updated["streams"]["live"] == LIVE_HD
    assert updated["streams"]["source_compat"] == COMPAT_HD
    assert updated["streams"]["analysis"] == ANALYSIS_STREAM
    assert updated["streams"]["gauge"] == GAUGE_STREAM
    assert "subtype=hd" in original["streams"]["source"]


@pytest.mark.parametrize("subtype", [-1, 6])
def test_source_subtype_candidate_rejects_out_of_range(subtype: int) -> None:
    with pytest.raises(QualityConfigError, match="INVALID_SUBTYPE"):
        with_source_subtype(
            {
                "streams": {
                    "source": "xiaomi://123:cn@192.0.2.10?did=456"
                }
            },
            subtype,
        )


def test_apply_hd_creates_backup_and_preserves_file_mode(tmp_path: Path) -> None:
    config_path = tmp_path / "go2rtc.yaml"
    backups = tmp_path / "backups"
    original = {
        "xiaomi": {"123": "V1:do-not-print"},
        "streams": {
            "source": "xiaomi://123:cn@192.0.2.10?did=456&model=example.camera",
            "live": "old",
        },
    }
    config_path.write_text(yaml.safe_dump(original), encoding="utf-8")
    config_path.chmod(0o600)

    backup = apply_hd(
        config_path,
        backups,
        datetime(2026, 8, 4, 13, 0, tzinfo=timezone.utc),
    )

    assert backup.name == "go2rtc-quality-20260804-130000.yaml"
    assert backup.exists()
    assert yaml.safe_load(backup.read_text(encoding="utf-8")) == original
    assert config_path.stat().st_mode & 0o777 == 0o600
    current = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    assert current["streams"]["live"] == LIVE_HD


def test_apply_gauge_stream_only_adds_profile_and_creates_backup(tmp_path: Path) -> None:
    config_path = tmp_path / "go2rtc.yaml"
    backups = tmp_path / "backups"
    original = {
        "streams": {
            "source": "xiaomi://device:cn@192.0.2.10?subtype=3&keep=yes",
            "live": "keep-live",
        }
    }
    config_path.write_text(yaml.safe_dump(original), encoding="utf-8")
    config_path.chmod(0o600)

    backup = apply_gauge_stream(
        config_path,
        backups,
        datetime(2026, 8, 16, 10, 0, tzinfo=timezone.utc),
    )

    current = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    assert backup.name == "go2rtc-gauge-20260816-100000.yaml"
    assert yaml.safe_load(backup.read_text(encoding="utf-8")) == original
    assert current["streams"]["source"] == original["streams"]["source"]
    assert current["streams"]["live"] == "keep-live"
    assert current["streams"]["gauge"] == GAUGE_STREAM
    assert config_path.stat().st_mode & 0o777 == 0o600


def test_apply_hd_rejects_missing_runtime_config(tmp_path: Path) -> None:
    with pytest.raises(QualityConfigError, match="SOURCE_NOT_CONFIGURED"):
        apply_hd(
            tmp_path / "missing.yaml",
            tmp_path / "backups",
            datetime(2026, 8, 4, 13, 0, tzinfo=timezone.utc),
        )


def test_rollback_restores_latest_quality_backup(tmp_path: Path) -> None:
    config_path = tmp_path / "go2rtc.yaml"
    backups = tmp_path / "backups"
    backups.mkdir()
    older = backups / "go2rtc-quality-20260804-120000.yaml"
    latest = backups / "go2rtc-quality-20260804-130000.yaml"
    older.write_text("streams: {live: older}\n", encoding="utf-8")
    latest.write_text("streams: {live: latest}\n", encoding="utf-8")
    config_path.write_text("streams: {live: current}\n", encoding="utf-8")
    config_path.chmod(0o600)

    restored = rollback_latest(config_path, backups)

    assert restored == latest
    current = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    assert current["streams"]["live"] == "latest"
    assert config_path.stat().st_mode & 0o777 == 0o600


def test_rollback_rejects_missing_backup(tmp_path: Path) -> None:
    config_path = tmp_path / "go2rtc.yaml"
    config_path.write_text("streams: {}\n", encoding="utf-8")

    with pytest.raises(QualityConfigError, match="NO_QUALITY_BACKUP"):
        rollback_latest(config_path, tmp_path / "backups")
