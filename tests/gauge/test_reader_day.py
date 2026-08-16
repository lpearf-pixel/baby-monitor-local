from __future__ import annotations

import importlib

import cv2
import numpy as np
import pytest

from packages.contracts.events import ReadingFailureReason, ReadingState
from services.gauge.calibration import GaugeQuadrilateral
from tests.gauge.synthetic_dial import (
    NOW,
    blurred_frame,
    burst,
    calibration,
    frame_jpeg,
    glare_frame,
    occluded_frame,
    perspective_case,
    solid_frame,
    shifted_frame,
)


def reader_module():
    return importlib.import_module("services.gauge.reader")


def test_rectification_preserves_portrait_gauge_aspect_ratio() -> None:
    module = reader_module()
    source = np.zeros((480, 640, 3), dtype=np.uint8)
    portrait = calibration().model_copy(
        update={
            "gauge_quadrilateral": GaugeQuadrilateral.model_validate(
                {
                    "top_left": {"x": 0.3, "y": 0.1},
                    "top_right": {"x": 0.7, "y": 0.1},
                    "bottom_right": {"x": 0.7, "y": 0.9},
                    "bottom_left": {"x": 0.3, "y": 0.9},
                }
            )
        }
    )

    rectified, _transform = module.Ws2021Reader()._rectify(source, portrait)

    height, width = rectified.shape[:2]
    corners = np.asarray(
        [[
            [point.x * (source.shape[1] - 1), point.y * (source.shape[0] - 1)]
            for point in portrait.gauge_quadrilateral.points
        ]],
        dtype=np.float32,
    )
    transformed = cv2.perspectiveTransform(corners, _transform)[0]
    gauge_width = np.linalg.norm(transformed[1] - transformed[0])
    gauge_height = np.linalg.norm(transformed[3] - transformed[0])
    assert gauge_height / gauge_width == pytest.approx(1.5, rel=0.02)
    for face in (portrait.humidity, portrait.temperature):
        module.Ws2021Reader()._face_geometry(
            face,
            _transform,
            source.shape[1],
            source.shape[0],
            width,
            height,
        )


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


def test_blurred_dial_fails_sharpness_gate() -> None:
    reading = reader_module().Ws2021Reader().read(
        burst([blurred_frame() for _ in range(5)]),
        calibration(),
        requested_at=NOW,
    )

    assert reading.state is ReadingState.UNAVAILABLE
    assert reading.failure_reason is ReadingFailureReason.LOW_CONFIDENCE


def test_shifted_dial_invalidates_calibration() -> None:
    reading = reader_module().Ws2021Reader().read(
        burst([shifted_frame() for _ in range(5)]),
        calibration(),
        requested_at=NOW,
    )

    assert reading.state is ReadingState.UNAVAILABLE
    assert reading.failure_reason is ReadingFailureReason.CALIBRATION_INVALID


def test_perspective_calibration_uses_rectified_scale_angles() -> None:
    skewed_calibration, payload = perspective_case()

    reading = reader_module().Ws2021Reader().read(
        burst([payload for _ in range(5)]),
        skewed_calibration,
        requested_at=NOW,
    )

    assert reading.state is ReadingState.AVAILABLE
    assert reading.temperature_c == pytest.approx(22.0, abs=1.0)
    assert reading.humidity_rh == pytest.approx(48.0, abs=5.0)
