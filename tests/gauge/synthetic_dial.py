from __future__ import annotations

import math
from datetime import UTC, datetime, timedelta
from io import BytesIO

from PIL import Image, ImageDraw, ImageFilter
import cv2
import numpy as np

from services.gauge.calibration import Ws2021Calibration
from services.stream.frame_source import CapturedFrame, FrameBurst


WIDTH = 640
HEIGHT = 480
RADIUS = 72
HUMIDITY_CENTER = (192, 240)
TEMPERATURE_CENTER = (448, 240)
NOW = datetime(2026, 8, 5, 12, 0, tzinfo=UTC)


def _point(x: float, y: float) -> dict[str, float]:
    return {"x": x / WIDTH, "y": y / HEIGHT}


def _face(
    center: tuple[int, int],
    values: tuple[float, float, float],
) -> dict[str, object]:
    marks = []
    for angle, value in zip((20.0, 90.0, 160.0), values, strict=True):
        radians = math.radians(angle)
        marks.append(
            {
                "point": _point(
                    center[0] + math.cos(radians) * RADIUS,
                    center[1] + math.sin(radians) * RADIUS,
                ),
                "angle_degrees": angle,
                "unwrapped_angle_degrees": angle,
                "value": value,
            }
        )
    return {
        "center": _point(*center),
        "needle_tip": _point(center[0], center[1] + RADIUS * 0.8),
        "radius": RADIUS / WIDTH,
        "scale_marks": marks,
    }


def calibration() -> Ws2021Calibration:
    return Ws2021Calibration.model_validate(
        {
            "schema_version": 2,
            "calibration_id": "synthetic-calibration-v2",
            "created_at": NOW,
            "source_width": WIDTH,
            "source_height": HEIGHT,
            "orientation": "landscape",
            "zoom": 2,
            "center_x": 0.5,
            "center_y": 0.5,
            "gauge_quadrilateral": {
                "top_left": {"x": 0, "y": 0},
                "top_right": {"x": 1, "y": 0},
                "bottom_right": {"x": 1, "y": 1},
                "bottom_left": {"x": 0, "y": 1},
            },
            "gauge_rect": {"x": 0, "y": 0, "width": 1, "height": 1},
            "humidity": _face(HUMIDITY_CENTER, (30, 50, 70)),
            "temperature": _face(TEMPERATURE_CENTER, (10, 20, 30)),
            "reference_version": "synthetic-v1",
        }
    )


def angle_for_value(value: float, *, humidity: bool) -> float:
    low, high = (30.0, 70.0) if humidity else (10.0, 30.0)
    return 20 + (value - low) * 140 / (high - low)


def _draw_needle(
    draw: ImageDraw.ImageDraw,
    center: tuple[int, int],
    angle: float,
    *,
    color: tuple[int, int, int],
    width: int,
) -> None:
    radians = math.radians(angle)
    tip = (
        center[0] + math.cos(radians) * RADIUS * 0.82,
        center[1] + math.sin(radians) * RADIUS * 0.82,
    )
    draw.line([center, tip], fill=color, width=width)
    draw.ellipse(
        [center[0] - 5, center[1] - 5, center[0] + 5, center[1] + 5],
        fill=color,
    )


def frame_jpeg(
    temperature_c: float = 22.0,
    humidity_rh: float = 48.0,
    *,
    mode: str = "day",
    omit_temperature: bool = False,
    omit_humidity: bool = False,
    second_temperature: float | None = None,
    needle_width: int = 5,
) -> bytes:
    background = (210, 210, 210) if mode == "day" else (28, 28, 28)
    dial_color = (70, 70, 70) if mode == "day" else (75, 75, 75)
    needle_color = (225, 25, 25) if mode == "day" else (220, 220, 220)
    image = Image.new("RGB", (WIDTH, HEIGHT), background)
    draw = ImageDraw.Draw(image)
    for center in (HUMIDITY_CENTER, TEMPERATURE_CENTER):
        draw.ellipse(
            [
                center[0] - RADIUS,
                center[1] - RADIUS,
                center[0] + RADIUS,
                center[1] + RADIUS,
            ],
            outline=dial_color,
            width=3,
        )
    if not omit_humidity:
        _draw_needle(
            draw,
            HUMIDITY_CENTER,
            angle_for_value(humidity_rh, humidity=True),
            color=needle_color,
            width=needle_width,
        )
    if not omit_temperature:
        _draw_needle(
            draw,
            TEMPERATURE_CENTER,
            angle_for_value(temperature_c, humidity=False),
            color=needle_color,
            width=needle_width,
        )
    if second_temperature is not None:
        _draw_needle(
            draw,
            TEMPERATURE_CENTER,
            angle_for_value(second_temperature, humidity=False),
            color=needle_color,
            width=needle_width,
        )
    output = BytesIO()
    image.save(output, format="JPEG", quality=95)
    return output.getvalue()


def solid_frame(color: tuple[int, int, int]) -> bytes:
    output = BytesIO()
    Image.new("RGB", (WIDTH, HEIGHT), color).save(output, format="JPEG", quality=95)
    return output.getvalue()


def glare_frame() -> bytes:
    image = Image.open(BytesIO(frame_jpeg())).convert("RGB")
    draw = ImageDraw.Draw(image)
    draw.rectangle([80, 100, 560, 380], fill=(255, 255, 255))
    output = BytesIO()
    image.save(output, format="JPEG", quality=95)
    return output.getvalue()


def occluded_frame() -> bytes:
    image = Image.open(BytesIO(frame_jpeg())).convert("RGB")
    draw = ImageDraw.Draw(image)
    draw.rectangle(
        [
            TEMPERATURE_CENTER[0] - RADIUS,
            TEMPERATURE_CENTER[1] - RADIUS,
            TEMPERATURE_CENTER[0] + RADIUS,
            TEMPERATURE_CENTER[1] + RADIUS,
        ],
        fill=(0, 0, 0),
    )
    output = BytesIO()
    image.save(output, format="JPEG", quality=95)
    return output.getvalue()


def blurred_frame() -> bytes:
    image = Image.open(BytesIO(frame_jpeg())).convert("RGB")
    output = BytesIO()
    image.filter(ImageFilter.GaussianBlur(radius=10)).save(
        output, format="JPEG", quality=95
    )
    return output.getvalue()


def shifted_frame(offset_x: int = 24) -> bytes:
    image = Image.open(BytesIO(frame_jpeg())).convert("RGB")
    shifted = image.transform(
        image.size,
        Image.Transform.AFFINE,
        (1, 0, -offset_x, 0, 1, 0),
        fillcolor=(210, 210, 210),
    )
    output = BytesIO()
    shifted.save(output, format="JPEG", quality=95)
    return output.getvalue()


def perspective_case() -> tuple[Ws2021Calibration, bytes]:
    base = cv2.imdecode(np.frombuffer(frame_jpeg(), dtype=np.uint8), cv2.IMREAD_COLOR)
    source_corners = np.asarray(
        [[0, 0], [WIDTH - 1, 0], [WIDTH - 1, HEIGHT - 1], [0, HEIGHT - 1]],
        dtype=np.float32,
    )
    skewed_corners = np.asarray(
        [[70, 35], [595, 65], [620, 445], [25, 415]],
        dtype=np.float32,
    )
    forward = cv2.getPerspectiveTransform(source_corners, skewed_corners)
    skewed = cv2.warpPerspective(
        base,
        forward,
        (WIDTH, HEIGHT),
        borderValue=(210, 210, 210),
    )
    original = calibration()

    def transform_point(point: object) -> dict[str, float]:
        source = np.asarray(
            [[[point.x * (WIDTH - 1), point.y * (HEIGHT - 1)]]],
            dtype=np.float32,
        )
        x, y = cv2.perspectiveTransform(source, forward)[0, 0]
        return _point(float(x), float(y))

    def transform_face(face: object) -> dict[str, object]:
        center = transform_point(face.center)
        marks = []
        previous = None
        for mark in face.scale_marks:
            point = transform_point(mark.point)
            angle = math.degrees(
                math.atan2(point["y"] - center["y"], point["x"] - center["x"])
            ) % 360
            unwrapped = angle
            while previous is not None and unwrapped <= previous:
                unwrapped += 360
            previous = unwrapped
            marks.append(
                {
                    "point": point,
                    "angle_degrees": angle,
                    "unwrapped_angle_degrees": unwrapped,
                    "value": mark.value,
                }
            )
        needle_tip = transform_point(face.needle_tip)
        return {
            "center": center,
            "needle_tip": needle_tip,
            "radius": math.hypot(
                needle_tip["x"] - center["x"],
                needle_tip["y"] - center["y"],
            ) / 0.8,
            "scale_marks": marks,
        }

    corners = [_point(float(x), float(y)) for x, y in skewed_corners]
    xs = [point["x"] for point in corners]
    ys = [point["y"] for point in corners]
    payload = original.model_dump(mode="json")
    payload.update(
        {
            "gauge_quadrilateral": {
                "top_left": corners[0],
                "top_right": corners[1],
                "bottom_right": corners[2],
                "bottom_left": corners[3],
            },
            "gauge_rect": {
                "x": min(xs),
                "y": min(ys),
                "width": max(xs) - min(xs),
                "height": max(ys) - min(ys),
            },
            "humidity": transform_face(original.humidity),
            "temperature": transform_face(original.temperature),
        }
    )
    output = BytesIO()
    Image.fromarray(cv2.cvtColor(skewed, cv2.COLOR_BGR2RGB)).save(
        output, format="JPEG", quality=95
    )
    return Ws2021Calibration.model_validate(payload), output.getvalue()


def burst(
    payloads: list[bytes],
    *,
    captured_at: datetime = NOW,
    spacing_seconds: int = 0,
) -> FrameBurst:
    return FrameBurst(
        frames=tuple(
            CapturedFrame(
                jpeg=payload,
                captured_at=captured_at + timedelta(seconds=index * spacing_seconds),
                width=WIDTH,
                height=HEIGHT,
            )
            for index, payload in enumerate(payloads)
        )
    )
