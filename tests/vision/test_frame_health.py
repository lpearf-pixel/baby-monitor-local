from __future__ import annotations

from datetime import UTC, datetime, timedelta
from io import BytesIO

import pytest
from PIL import Image

from services.vision.frame_policy import PreparedAnalysisFrame


NOW = datetime(2026, 8, 5, 12, 0, tzinfo=UTC)


def prepared(
    color: str | tuple[int, int, int],
    *,
    seconds: int,
    aware: bool = True,
) -> PreparedAnalysisFrame:
    output = BytesIO()
    Image.new("RGB", (960, 540), color).save(output, format="JPEG", quality=80)
    captured_at = NOW + timedelta(seconds=seconds)
    if not aware:
        captured_at = captured_at.replace(tzinfo=None)
    return PreparedAnalysisFrame(
        jpeg=output.getvalue(),
        captured_at=captured_at,
        width=960,
        height=540,
        crop_box=(0, 0, 960, 540),
    )


def textured(*, seconds: int, inverted: bool = False) -> PreparedAnalysisFrame:
    image = Image.new("L", (960, 540))
    pixels = image.load()
    for y in range(540):
        for x in range(960):
            value = 220 if (x // 80 + y // 60) % 2 else 30
            pixels[x, y] = 255 - value if inverted else value
    output = BytesIO()
    image.convert("RGB").save(output, format="JPEG", quality=80)
    return PreparedAnalysisFrame(
        jpeg=output.getvalue(),
        captured_at=NOW + timedelta(seconds=seconds),
        width=960,
        height=540,
        crop_box=(0, 0, 960, 540),
    )


def health_module():
    from services.vision import frame_health

    return frame_health


def test_identical_usable_frames_require_sixty_seconds_and_reconnect() -> None:
    module = health_module()
    monitor = module.VisualFrameHealthMonitor()

    assert monitor.observe(textured(seconds=0), monotonic_now=0.0) is None
    assert monitor.observe(textured(seconds=59), monotonic_now=59.0) is None
    candidate = monitor.observe(textured(seconds=60), monotonic_now=60.0)
    duplicate = monitor.observe(textured(seconds=61), monotonic_now=61.0)

    assert candidate.code is module.FrameHealthCode.RECONNECT_REQUIRED
    assert candidate.state is module.FrameHealthState.RECONNECTING
    assert candidate.duration_seconds == 60.0
    assert duplicate is None


def test_identical_frame_after_reconnect_opens_frozen_state_once() -> None:
    module = health_module()
    monitor = module.VisualFrameHealthMonitor()
    monitor.observe(textured(seconds=0), monotonic_now=0.0)
    monitor.observe(textured(seconds=60), monotonic_now=60.0)

    frozen = monitor.confirm_reconnect(
        textured(seconds=61), monotonic_now=61.0
    )
    repeated = monitor.observe(textured(seconds=62), monotonic_now=62.0)

    assert frozen.code is module.FrameHealthCode.FRAME_FROZEN
    assert frozen.state is module.FrameHealthState.DEGRADED
    assert repeated is None


def test_changed_frame_after_reconnect_clears_candidate_without_alert() -> None:
    module = health_module()
    monitor = module.VisualFrameHealthMonitor()
    monitor.observe(textured(seconds=0), monotonic_now=0.0)
    monitor.observe(textured(seconds=60), monotonic_now=60.0)

    assert (
        monitor.confirm_reconnect(
            textured(seconds=61, inverted=True), monotonic_now=61.0
        )
        is None
    )
    assert monitor.open_code is None


@pytest.mark.parametrize("color", ["black", (2, 2, 2), (80, 80, 80)])
def test_dark_or_low_contrast_frames_are_not_freeze_evidence(
    color: str | tuple[int, int, int],
) -> None:
    module = health_module()
    monitor = module.VisualFrameHealthMonitor()

    assert monitor.observe(prepared(color, seconds=0), monotonic_now=0.0) is None
    assert monitor.observe(prepared(color, seconds=120), monotonic_now=120.0) is None


def test_source_failure_opens_once_after_sixty_seconds() -> None:
    module = health_module()
    monitor = module.VisualFrameHealthMonitor()

    assert monitor.source_failed(monotonic_now=0.0) is None
    assert monitor.source_failed(monotonic_now=59.0) is None
    offline = monitor.source_failed(monotonic_now=60.0)
    repeated = monitor.source_failed(monotonic_now=120.0)

    assert offline.code is module.FrameHealthCode.SOURCE_OFFLINE
    assert offline.state is module.FrameHealthState.DEGRADED
    assert offline.duration_seconds == 60.0
    assert repeated is None


def test_open_failure_recovers_only_after_changed_frames_span_twenty_seconds() -> None:
    module = health_module()
    monitor = module.VisualFrameHealthMonitor()
    monitor.source_failed(monotonic_now=0.0)
    monitor.source_failed(monotonic_now=60.0)

    assert monitor.observe(textured(seconds=61), monotonic_now=61.0) is None
    assert (
        monitor.observe(
            textured(seconds=70, inverted=True), monotonic_now=70.0
        )
        is None
    )
    recovered = monitor.observe(textured(seconds=81), monotonic_now=81.0)

    assert recovered.code is module.FrameHealthCode.RECOVERED
    assert recovered.state is module.FrameHealthState.HEALTHY
    assert recovered.duration_seconds == 20.0
    assert monitor.open_code is None


def test_health_monitor_rejects_naive_or_decreasing_time_before_mutation() -> None:
    module = health_module()
    monitor = module.VisualFrameHealthMonitor()

    with pytest.raises(ValueError, match="timezone-aware"):
        monitor.observe(
            prepared("red", seconds=0, aware=False), monotonic_now=0.0
        )

    monitor.observe(textured(seconds=10), monotonic_now=10.0)
    with pytest.raises(ValueError, match="monotonic"):
        monitor.observe(textured(seconds=9), monotonic_now=9.0)

    assert monitor.open_code is None
