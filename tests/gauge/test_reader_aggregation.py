from __future__ import annotations

from datetime import timedelta
import importlib

import pytest

from packages.contracts.events import ReadingFailureReason, ReadingState
from tests.gauge.synthetic_dial import NOW, burst, calibration, frame_jpeg


def reader_module():
    return importlib.import_module("services.gauge.reader")


def test_two_valid_frames_are_not_enough() -> None:
    module = reader_module()
    payloads = [frame_jpeg(), frame_jpeg()] + [
        frame_jpeg(omit_temperature=True, omit_humidity=True) for _ in range(3)
    ]
    reading = module.Ws2021Reader().read(
        burst(payloads), calibration(), requested_at=NOW
    )

    assert reading.state is ReadingState.UNAVAILABLE
    assert reading.failure_reason is ReadingFailureReason.INSUFFICIENT_VALID_FRAMES
    assert reading.valid_temperature_samples == 2
    assert reading.valid_humidity_samples == 2


def test_median_rejects_one_outlier_but_preserves_stable_values() -> None:
    module = reader_module()
    payloads = [frame_jpeg(22.0, 48.0) for _ in range(4)] + [
        frame_jpeg(28.0, 68.0)
    ]
    reading = module.Ws2021Reader().read(
        burst(payloads), calibration(), requested_at=NOW
    )

    assert reading.state is ReadingState.AVAILABLE
    assert reading.temperature_c == pytest.approx(22.0, abs=1.0)
    assert reading.humidity_rh == pytest.approx(48.0, abs=5.0)


def test_inconsistent_frames_fail_mad_gate() -> None:
    module = reader_module()
    payloads = [
        frame_jpeg(18.0, 40.0),
        frame_jpeg(20.0, 44.0),
        frame_jpeg(22.0, 48.0),
        frame_jpeg(24.0, 52.0),
        frame_jpeg(26.0, 56.0),
    ]
    reading = module.Ws2021Reader().read(
        burst(payloads), calibration(), requested_at=NOW
    )

    assert reading.state is ReadingState.UNAVAILABLE
    assert reading.failure_reason is ReadingFailureReason.INCONSISTENT_FRAMES


def test_low_confidence_faint_needles_are_not_published() -> None:
    module = reader_module()
    reading = module.Ws2021Reader().read(
        burst([frame_jpeg(needle_width=1) for _ in range(5)]),
        calibration(),
        requested_at=NOW,
    )

    assert reading.state is ReadingState.UNAVAILABLE
    assert reading.failure_reason is ReadingFailureReason.LOW_CONFIDENCE


def test_frames_older_than_five_seconds_are_stale() -> None:
    module = reader_module()
    reading = module.Ws2021Reader().read(
        burst([frame_jpeg() for _ in range(5)], captured_at=NOW),
        calibration(),
        requested_at=NOW + timedelta(seconds=6),
    )

    assert reading.state is ReadingState.UNAVAILABLE
    assert reading.failure_reason is ReadingFailureReason.FRAME_STALE
    assert reading.captured_at == NOW
