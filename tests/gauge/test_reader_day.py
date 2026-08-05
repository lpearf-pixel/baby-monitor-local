from __future__ import annotations

import importlib

import pytest

from packages.contracts.events import ReadingFailureReason, ReadingState
from tests.gauge.synthetic_dial import (
    NOW,
    burst,
    calibration,
    frame_jpeg,
    glare_frame,
    occluded_frame,
    solid_frame,
)


def reader_module():
    return importlib.import_module("services.gauge.reader")


def test_red_needles_produce_both_values() -> None:
    module = reader_module()
    reading = module.Ws2021Reader().read(
        burst([frame_jpeg(22.0, 48.0) for _ in range(5)]),
        calibration(),
        requested_at=NOW,
    )

    assert reading.state is ReadingState.AVAILABLE
    assert reading.temperature_c == pytest.approx(22.0, abs=1.0)
    assert reading.humidity_rh == pytest.approx(48.0, abs=5.0)
    assert reading.valid_temperature_samples == 5
    assert reading.valid_humidity_samples == 5


def test_missing_one_face_never_publishes_partial_values() -> None:
    module = reader_module()
    reading = module.Ws2021Reader().read(
        burst([frame_jpeg(omit_temperature=True) for _ in range(5)]),
        calibration(),
        requested_at=NOW,
    )

    assert reading.state is ReadingState.UNAVAILABLE
    assert reading.temperature_c is None
    assert reading.humidity_rh is None
    assert reading.failure_reason is ReadingFailureReason.NEEDLE_NOT_FOUND


def test_dark_and_glare_frames_fail_quality_gates() -> None:
    module = reader_module()
    dark = module.Ws2021Reader().read(
        burst([solid_frame((0, 0, 0)) for _ in range(5)]),
        calibration(),
        requested_at=NOW,
    )
    glare = module.Ws2021Reader().read(
        burst([glare_frame() for _ in range(5)]),
        calibration(),
        requested_at=NOW,
    )

    assert dark.failure_reason is ReadingFailureReason.TOO_DARK
    assert glare.failure_reason is ReadingFailureReason.GLARE


def test_two_similarly_strong_needles_are_rejected() -> None:
    module = reader_module()
    reading = module.Ws2021Reader().read(
        burst(
            [
                frame_jpeg(18.0, 48.0, second_temperature=26.0)
                for _ in range(5)
            ]
        ),
        calibration(),
        requested_at=NOW,
    )

    assert reading.state is ReadingState.UNAVAILABLE
    assert reading.failure_reason is ReadingFailureReason.NEEDLE_NOT_FOUND


def test_face_occlusion_is_distinguished_from_missing_needle() -> None:
    module = reader_module()
    reading = module.Ws2021Reader().read(
        burst([occluded_frame() for _ in range(5)]),
        calibration(),
        requested_at=NOW,
    )

    assert reading.state is ReadingState.UNAVAILABLE
    assert reading.failure_reason is ReadingFailureReason.OCCLUDED
