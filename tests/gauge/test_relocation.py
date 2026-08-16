from __future__ import annotations

import pytest

from services.gauge.calibration import NormalizedRect
from services.gauge.locator import GaugeLocation
from tests.gauge.synthetic_dial import calibration


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
