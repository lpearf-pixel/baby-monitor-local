from __future__ import annotations

import math
from io import BytesIO

import cv2
import numpy as np
from PIL import Image, UnidentifiedImageError
from services.gauge.calibration import (
    GaugeFace,
    GaugeQuadrilateral,
    NormalizedRect,
    Point,
    ScaleMark,
    Ws2021Calibration,
)
from services.gauge.locator import GaugeLocation
from services.stream.frame_source import CapturedFrame


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


def refine_calibration(
    calibration: Ws2021Calibration,
    location: GaugeLocation,
    frame: CapturedFrame,
) -> Ws2021Calibration:
    image = _decode(frame)
    left = round(location.box.x * frame.width)
    top = round(location.box.y * frame.height)
    right = round((location.box.x + location.box.width) * frame.width)
    bottom = round((location.box.y + location.box.height) * frame.height)
    crop = image[top:bottom, left:right]
    if crop.size == 0:
        raise ValueError("gauge_geometry_invalid")
    gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
    local_quad = _outer_quadrilateral(gray)
    normalized_quad = tuple(
        Point(x=(left + x) / frame.width, y=(top + y) / frame.height)
        for x, y in local_quad
    )
    migrated = _relocate_to_quad(calibration, normalized_quad)
    _require_two_circle_layout(gray, migrated, left=left, top=top, frame=frame)
    return migrated


def _decode(frame: CapturedFrame) -> np.ndarray:
    try:
        with Image.open(BytesIO(frame.jpeg)) as source:
            source.verify()
        image = cv2.imdecode(np.frombuffer(frame.jpeg, dtype=np.uint8), cv2.IMREAD_COLOR)
    except (UnidentifiedImageError, OSError, ValueError) as exc:
        raise ValueError("gauge_geometry_invalid") from exc
    if image is None or image.shape[:2] != (frame.height, frame.width):
        raise ValueError("gauge_geometry_invalid")
    return image


def _outer_quadrilateral(gray: np.ndarray) -> tuple[tuple[float, float], ...]:
    blurred = cv2.GaussianBlur(gray, (5, 5), 0)
    edges = cv2.Canny(blurred, 40, 120)
    contours, _ = cv2.findContours(edges, cv2.RETR_LIST, cv2.CHAIN_APPROX_SIMPLE)
    minimum_area = gray.shape[0] * gray.shape[1] * 0.35
    candidates: list[np.ndarray] = []
    for contour in contours:
        perimeter = cv2.arcLength(contour, True)
        polygon = cv2.approxPolyDP(contour, 0.03 * perimeter, True)
        if (
            len(polygon) == 4
            and cv2.isContourConvex(polygon)
            and cv2.contourArea(polygon) >= minimum_area
        ):
            candidates.append(polygon.reshape(4, 2).astype(np.float32))
    if not candidates:
        raise ValueError("gauge_geometry_invalid")
    points = max(candidates, key=cv2.contourArea)
    sums = points.sum(axis=1)
    differences = np.diff(points, axis=1).reshape(-1)
    ordered = (
        points[int(np.argmin(sums))],
        points[int(np.argmin(differences))],
        points[int(np.argmax(sums))],
        points[int(np.argmax(differences))],
    )
    if len({(float(point[0]), float(point[1])) for point in ordered}) != 4:
        raise ValueError("gauge_geometry_invalid")
    return tuple((float(point[0]), float(point[1])) for point in ordered)


def _relocate_to_quad(
    calibration: Ws2021Calibration,
    points: tuple[Point, ...],
) -> Ws2021Calibration:
    old = np.asarray(
        [(point.x, point.y) for point in calibration.gauge_quadrilateral.points],
        dtype=np.float32,
    )
    new = np.asarray([(point.x, point.y) for point in points], dtype=np.float32)
    transform = cv2.getPerspectiveTransform(old, new)

    def relocate(point: Point) -> Point:
        mapped = cv2.perspectiveTransform(
            np.asarray([[[point.x, point.y]]], dtype=np.float32), transform
        )[0, 0]
        return Point(x=float(mapped[0]), y=float(mapped[1]))

    def relocate_face(face: GaugeFace) -> GaugeFace:
        center = relocate(face.center)
        needle_tip = relocate(face.needle_tip)
        return GaugeFace(
            center=center,
            needle_tip=needle_tip,
            radius=math.hypot(needle_tip.x - center.x, needle_tip.y - center.y) / 0.8,
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

    gauge_rect = NormalizedRect(
        x=min(point.x for point in points),
        y=min(point.y for point in points),
        width=max(point.x for point in points) - min(point.x for point in points),
        height=max(point.y for point in points) - min(point.y for point in points),
    )
    payload = calibration.model_dump()
    payload.update(
        {
            "gauge_quadrilateral": GaugeQuadrilateral(
                top_left=points[0],
                top_right=points[1],
                bottom_right=points[2],
                bottom_left=points[3],
            ),
            "gauge_rect": gauge_rect,
            "humidity": relocate_face(calibration.humidity),
            "temperature": relocate_face(calibration.temperature),
        }
    )
    return Ws2021Calibration.model_validate(payload)


def _require_two_circle_layout(
    gray: np.ndarray,
    calibration: Ws2021Calibration,
    *,
    left: int,
    top: int,
    frame: CapturedFrame,
) -> None:
    minimum_radius = max(8, round(min(gray.shape) * 0.1))
    maximum_radius = max(minimum_radius + 1, round(min(gray.shape) * 0.35))
    circles = cv2.HoughCircles(
        cv2.GaussianBlur(gray, (7, 7), 1.5),
        cv2.HOUGH_GRADIENT,
        dp=1.2,
        minDist=max(16, round(gray.shape[0] * 0.2)),
        param1=100,
        param2=24,
        minRadius=minimum_radius,
        maxRadius=maximum_radius,
    )
    if circles is None:
        raise ValueError("gauge_geometry_invalid")
    detected = circles[0]
    tolerance = math.hypot(gray.shape[1], gray.shape[0]) * 0.12
    expected = (
        (
            calibration.humidity.center.x * frame.width - left,
            calibration.humidity.center.y * frame.height - top,
        ),
        (
            calibration.temperature.center.x * frame.width - left,
            calibration.temperature.center.y * frame.height - top,
        ),
    )
    if any(
        not any(math.hypot(float(circle[0]) - x, float(circle[1]) - y) <= tolerance for circle in detected)
        for x, y in expected
    ):
        raise ValueError("gauge_geometry_invalid")
