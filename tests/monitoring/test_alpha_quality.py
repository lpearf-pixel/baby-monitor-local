from __future__ import annotations

from copy import deepcopy

import pytest

from packages.monitoring.alpha_quality import (
    LIVE_HD,
    QualityConfigError,
    inspect_quality,
    upgrade_to_hd,
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
    rendered = repr(info)
    assert "xiaomi://" not in rendered
    assert "192.0.2.10" not in rendered
    assert "V1:" not in rendered


def test_upgrade_rejects_missing_source() -> None:
    with pytest.raises(QualityConfigError, match="SOURCE_NOT_CONFIGURED"):
        upgrade_to_hd({"streams": {"live": "old"}})
