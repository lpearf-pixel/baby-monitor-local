from __future__ import annotations

import importlib

import pytest

from packages.contracts.events import ReadingFailureReason, ReadingState
from tests.gauge.synthetic_dial import NOW, burst, calibration, frame_jpeg


def reader_module():
    return importlib.import_module("services.gauge.reader")


def test_night_gray_needles_are_read_without_color() -> None:
    module = reader_module()
    reading = module.Ws2021Reader().read(
        burst([frame_jpeg(20.0, 55.0, mode="night") for _ in range(5)]),
        calibration(),
        requested_at=NOW,
    )

    assert reading.state is ReadingState.AVAILABLE
    assert reading.temperature_c == pytest.approx(20.0, abs=1.0)
    assert reading.humidity_rh == pytest.approx(55.0, abs=5.0)


def test_night_frame_with_no_needle_is_unavailable() -> None:
    module = reader_module()
    reading = module.Ws2021Reader().read(
        burst(
            [
                frame_jpeg(
                    mode="night",
                    omit_temperature=True,
                    omit_humidity=True,
                )
                for _ in range(5)
            ]
        ),
        calibration(),
        requested_at=NOW,
    )

    assert reading.state is ReadingState.UNAVAILABLE
    assert reading.failure_reason is ReadingFailureReason.NEEDLE_NOT_FOUND
