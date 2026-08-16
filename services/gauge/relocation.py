from __future__ import annotations

import math

from services.gauge.calibration import (
    GaugeFace,
    GaugeQuadrilateral,
    Point,
    ScaleMark,
    Ws2021Calibration,
)
from services.gauge.locator import GaugeLocation


def relocate_calibration(
    calibration: Ws2021Calibration,
    location: GaugeLocation,
) -> Ws2021Calibration:
    old = calibration.gauge_rect
    new = location.box

    def relocate(point: Point) -> Point:
        return Point(
            x=new.x + (point.x - old.x) * new.width / old.width,
            y=new.y + (point.y - old.y) * new.height / old.height,
        )

    def relocate_face(face: GaugeFace) -> GaugeFace:
        center = relocate(face.center)
        needle_tip = relocate(face.needle_tip)
        return GaugeFace(
            center=center,
            needle_tip=needle_tip,
            radius=math.hypot(
                needle_tip.x - center.x,
                needle_tip.y - center.y,
            )
            / 0.8,
            scale_marks=tuple(
                ScaleMark(
                    point=relocate(mark.point),
                    angle_degrees=mark.angle_degrees,
                    unwrapped_angle_degrees=mark.unwrapped_angle_degrees,
                    value=mark.value,
                )
                for mark in face.scale_marks
            ),
        )

    points = tuple(relocate(point) for point in calibration.gauge_quadrilateral.points)
    payload = calibration.model_dump()
    payload.update(
        {
            "gauge_quadrilateral": GaugeQuadrilateral(
                top_left=points[0],
                top_right=points[1],
                bottom_right=points[2],
                bottom_left=points[3],
            ),
            "gauge_rect": new,
            "humidity": relocate_face(calibration.humidity),
            "temperature": relocate_face(calibration.temperature),
        }
    )
    return Ws2021Calibration.model_validate(payload)
