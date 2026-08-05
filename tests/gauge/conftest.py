from __future__ import annotations

from datetime import UTC, datetime
from io import BytesIO

import pytest
from PIL import Image


@pytest.fixture
def reference_jpeg() -> bytes:
    output = BytesIO()
    Image.new("RGB", (64, 48), "white").save(output, format="JPEG")
    return output.getvalue()


@pytest.fixture
def calibration_data() -> dict[str, object]:
    def face(
        center: tuple[float, float],
        marks: list[tuple[float, float, float, float]],
    ) -> dict[str, object]:
        return {
            "center": {"x": center[0], "y": center[1]},
            "needle_tip": {"x": center[0], "y": center[1] - 0.08},
            "radius": 0.1,
            "scale_marks": [
                {
                    "point": {"x": x, "y": y},
                    "angle_degrees": angle % 360,
                    "unwrapped_angle_degrees": angle,
                    "value": value,
                }
                for angle, value, x, y in marks
            ],
        }

    return {
        "schema_version": 2,
        "calibration_id": "calibration-test-0001",
        "created_at": datetime(2026, 8, 5, 12, 0, tzinfo=UTC),
        "source_width": 2560,
        "source_height": 1440,
        "orientation": "landscape",
        "zoom": 2,
        "center_x": 0.5,
        "center_y": 0.5,
        "gauge_quadrilateral": {
            "top_left": {"x": 0.2, "y": 0.2},
            "top_right": {"x": 0.8, "y": 0.2},
            "bottom_right": {"x": 0.8, "y": 0.8},
            "bottom_left": {"x": 0.2, "y": 0.8},
        },
        "gauge_rect": {"x": 0.2, "y": 0.2, "width": 0.6, "height": 0.6},
        "humidity": face(
            (0.38, 0.5),
            [
                (350, 30, 0.36, 0.42),
                (370, 50, 0.39, 0.42),
                (390, 70, 0.42, 0.44),
            ],
        ),
        "temperature": face(
            (0.62, 0.5),
            [
                (200, 10, 0.55, 0.55),
                (270, 20, 0.62, 0.42),
                (340, 30, 0.69, 0.55),
            ],
        ),
        "reference_version": "local-reference-v1",
    }
