from __future__ import annotations

from datetime import UTC, datetime
from io import BytesIO

import pytest
from PIL import Image, ImageDraw

from services.gauge.calibration import NormalizedRect
from services.gauge.locator import GaugeLocation
from tests.gauge.synthetic_dial import calibration
from tests.gauge.synthetic_dial import frame_jpeg
from services.stream.frame_source import CapturedFrame


def test_relocation_moves_all_geometry_into_detected_upright_box() -> None:
    from services.gauge.relocation import relocate_calibration

    original = calibration()
    location = GaugeLocation(
        box=NormalizedRect(x=0.55, y=0.2, width=0.3, height=0.6),
        confidence=0.91,
        model_version="ws2021-test-v1",
    )

    relocated = relocate_calibration(original, location)

    assert relocated.calibration_id == original.calibration_id
    assert relocated.gauge_rect == location.box
    assert relocated.gauge_quadrilateral.top_left.x == pytest.approx(0.55)
    assert relocated.gauge_quadrilateral.bottom_right.y == pytest.approx(0.8)
    assert relocated.humidity.center.x == pytest.approx(0.64)
    assert relocated.temperature.center.x == pytest.approx(0.76)
    for face in (relocated.humidity, relocated.temperature):
        assert relocated.gauge_rect.contains(face.center)
        assert relocated.gauge_rect.contains(face.needle_tip)
        assert all(relocated.gauge_rect.contains(mark.point) for mark in face.scale_marks)


def test_refinement_requires_outer_quad_and_two_circle_layout() -> None:
    from services.gauge.relocation import refine_calibration

    image = Image.open(BytesIO(frame_jpeg())).convert("RGB")
    draw = ImageDraw.Draw(image)
    draw.rectangle((18, 18, 622, 462), outline=(25, 25, 25), width=5)
    output = BytesIO()
    image.save(output, format="JPEG", quality=95)
    frame = CapturedFrame(
        jpeg=output.getvalue(),
        captured_at=datetime(2026, 8, 16, tzinfo=UTC),
        width=640,
        height=480,
    )
    location = GaugeLocation(
        box=NormalizedRect(x=0, y=0, width=1, height=1),
        confidence=0.9,
        model_version="test-v1",
    )

    refined = refine_calibration(calibration(), location, frame)

    assert refined.gauge_rect.x == pytest.approx(18 / 640, abs=0.01)
    assert refined.gauge_rect.y == pytest.approx(18 / 480, abs=0.01)
    assert refined.gauge_rect.width < 1
    assert refined.gauge_rect.height < 1

    invalid = CapturedFrame(
        jpeg=frame_jpeg(omit_humidity=True, omit_temperature=True),
        captured_at=frame.captured_at,
        width=640,
        height=480,
    )
    with pytest.raises(ValueError, match="gauge_geometry_invalid"):
        refine_calibration(calibration(), location, invalid)
