from __future__ import annotations

import importlib
from io import BytesIO

import cv2
import numpy as np
import pytest
from PIL import Image

from packages.contracts.events import ReadingFailureReason, ReadingState
from services.gauge.calibration import GaugeQuadrilateral
from services.stream.frame_source import CapturedFrame, FrameBurst
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


def _scaled_burst(width: int, height: int) -> FrameBurst:
    if width > 0 and height > 0:
        source = Image.open(BytesIO(frame_jpeg()))
        output = BytesIO()
        source.resize((width, height)).save(output, format="JPEG", quality=95)
        payload = output.getvalue()
    else:
        payload = frame_jpeg()
    return FrameBurst(
        frames=tuple(
            CapturedFrame(payload, NOW, width, height) for _ in range(5)
        )
    )


def _moved_frame(*, offset_x: float, scale: float = 1.0) -> bytes:
    image = cv2.imdecode(np.frombuffer(frame_jpeg(), dtype=np.uint8), cv2.IMREAD_COLOR)
    height, width = image.shape[:2]
    transform = cv2.getRotationMatrix2D((width / 2, height / 2), 0, scale)
    transform[0, 2] += offset_x
    moved = cv2.warpAffine(
        image,
        transform,
        (width, height),
        borderValue=(210, 210, 210),
    )
    encoded, payload = cv2.imencode(".jpg", moved, [cv2.IMWRITE_JPEG_QUALITY, 95])
    assert encoded
    return payload.tobytes()


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


def test_same_aspect_scaled_frame_is_accepted_by_reader() -> None:
    high_resolution = calibration().model_copy(
        update={"source_width": 2560, "source_height": 1440}
    )

    reading = reader_module().Ws2021Reader().read(
        _scaled_burst(1280, 720), high_resolution, requested_at=NOW
    )

    assert reading.state is ReadingState.AVAILABLE


def test_aspect_ratio_drift_is_rejected_by_reader() -> None:
    high_resolution = calibration().model_copy(
        update={"source_width": 2560, "source_height": 1440}
    )

    reading = reader_module().Ws2021Reader().read(
        _scaled_burst(800, 480), high_resolution, requested_at=NOW
    )

    assert reading.state is ReadingState.UNAVAILABLE
    assert reading.failure_reason is ReadingFailureReason.CALIBRATION_INVALID


def test_invalid_frame_dimensions_are_rejected_by_reader() -> None:
    reading = reader_module().Ws2021Reader().read(
        _scaled_burst(0, 0), calibration(), requested_at=NOW
    )

    assert reading.state is ReadingState.UNAVAILABLE
    assert reading.failure_reason is ReadingFailureReason.CALIBRATION_INVALID


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


def test_stable_bounded_face_movement_is_read_without_mutating_calibration() -> None:
    source_calibration = calibration()
    original = source_calibration.model_dump_json()

    reading = reader_module().Ws2021Reader().read(
        burst([_moved_frame(offset_x=10, scale=1.04) for _ in range(5)]),
        source_calibration,
        requested_at=NOW,
    )

    assert reading.state is ReadingState.AVAILABLE
    assert reading.temperature_c == pytest.approx(22.0, abs=1.0)
    assert reading.humidity_rh == pytest.approx(48.0, abs=5.0)
    assert source_calibration.model_dump_json() == original


def test_inconsistent_face_movement_is_rejected_across_burst() -> None:
    reading = reader_module().Ws2021Reader().read(
        burst(
            [
                _moved_frame(offset_x=offset)
                for offset in (-5, 5, -5, 5, -5)
            ]
        ),
        calibration(),
        requested_at=NOW,
    )

    assert reading.state is ReadingState.UNAVAILABLE
    assert reading.failure_reason is ReadingFailureReason.CALIBRATION_INVALID


def test_ambiguous_nearby_face_circles_are_rejected(monkeypatch) -> None:
    module = reader_module()
    monkeypatch.setattr(
        module.cv2,
        "HoughCircles",
        lambda *_args, **_kwargs: np.asarray(
            [[[94.0, 94.0, 72.0], [104.0, 94.0, 72.0]]],
            dtype=np.float32,
        ),
    )

    reading = module.Ws2021Reader().read(
        burst([frame_jpeg() for _ in range(5)]),
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
