from __future__ import annotations

import math
import os
import shutil
import tempfile
import time
from collections.abc import Mapping
from datetime import datetime
from io import BytesIO
from pathlib import Path
from typing import Any, Literal, Self

from PIL import Image, UnidentifiedImageError
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    ValidationError,
    field_validator,
    model_validator,
)


MAX_REFERENCE_BYTES = 16 * 1024 * 1024
MAX_SOURCE_WIDTH = 4096
MAX_SOURCE_HEIGHT = 2160


class CalibrationMissing(RuntimeError):
    """Raised when no current calibration exists."""


class CalibrationInvalid(RuntimeError):
    """Raised when a calibration or its private reference JPEG is invalid."""


class CalibrationModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class Point(CalibrationModel):
    x: float = Field(ge=0, le=1)
    y: float = Field(ge=0, le=1)


class NormalizedRect(CalibrationModel):
    x: float = Field(ge=0, lt=1)
    y: float = Field(ge=0, lt=1)
    width: float = Field(gt=0, le=1)
    height: float = Field(gt=0, le=1)

    @model_validator(mode="after")
    def require_inside_frame(self) -> Self:
        if self.x + self.width > 1 or self.y + self.height > 1:
            raise ValueError("gauge_rect must remain inside the source frame")
        return self

    def contains(self, point: Point) -> bool:
        return (
            self.x <= point.x <= self.x + self.width
            and self.y <= point.y <= self.y + self.height
        )


class GaugeQuadrilateral(CalibrationModel):
    top_left: Point
    top_right: Point
    bottom_right: Point
    bottom_left: Point

    @property
    def points(self) -> tuple[Point, Point, Point, Point]:
        return (
            self.top_left,
            self.top_right,
            self.bottom_right,
            self.bottom_left,
        )

    @model_validator(mode="after")
    def require_non_degenerate_clockwise_shape(self) -> Self:
        coordinates = [(point.x, point.y) for point in self.points]
        twice_area = sum(
            x1 * y2 - x2 * y1
            for (x1, y1), (x2, y2) in zip(
                coordinates,
                (*coordinates[1:], coordinates[0]),
                strict=True,
            )
        )
        if abs(twice_area) <= 1e-6:
            raise ValueError("gauge quadrilateral must be non-degenerate")

        cross_products: list[float] = []
        for index in range(4):
            current = coordinates[index]
            following = coordinates[(index + 1) % 4]
            after = coordinates[(index + 2) % 4]
            cross_products.append(
                (following[0] - current[0]) * (after[1] - following[1])
                - (following[1] - current[1]) * (after[0] - following[0])
            )
        if any(value == 0 for value in cross_products) or not (
            all(value > 0 for value in cross_products)
            or all(value < 0 for value in cross_products)
        ):
            raise ValueError("gauge quadrilateral must be non-degenerate and convex")
        return self


class ScaleMark(CalibrationModel):
    point: Point
    angle_degrees: float = Field(ge=0, lt=360)
    unwrapped_angle_degrees: float = Field(ge=-720, le=1080)
    value: float

    @model_validator(mode="after")
    def require_equivalent_angles(self) -> Self:
        if not math.isclose(
            self.angle_degrees,
            self.unwrapped_angle_degrees % 360,
            abs_tol=1e-6,
        ):
            raise ValueError("raw and unwrapped scale angles must be equivalent")
        return self


class GaugeFace(CalibrationModel):
    center: Point
    needle_tip: Point
    radius: float = Field(gt=0, le=1)
    scale_marks: tuple[ScaleMark, ...] = Field(min_length=3, max_length=64)

    @model_validator(mode="after")
    def require_usable_scale(self) -> Self:
        center_to_tip = math.hypot(
            self.needle_tip.x - self.center.x,
            self.needle_tip.y - self.center.y,
        )
        if center_to_tip <= 1e-6:
            raise ValueError("needle_tip must not equal center")

        angles = [mark.unwrapped_angle_degrees for mark in self.scale_marks]
        values = [mark.value for mark in self.scale_marks]
        if any(right <= left for left, right in zip(angles, angles[1:])):
            raise ValueError("scale angles must be strictly increasing")
        increasing_values = all(
            right > left for left, right in zip(values, values[1:])
        )
        decreasing_values = all(
            right < left for left, right in zip(values, values[1:])
        )
        if not (increasing_values or decreasing_values):
            raise ValueError("scale values must be strictly monotonic")
        for mark in self.scale_marks:
            if math.hypot(
                mark.point.x - self.center.x,
                mark.point.y - self.center.y,
            ) <= 1e-6:
                raise ValueError("scale mark must not equal center")
        return self

    def value_for_angle(self, angle_degrees: float) -> float | None:
        if not math.isfinite(angle_degrees):
            return None
        first = self.scale_marks[0].unwrapped_angle_degrees
        last = self.scale_marks[-1].unwrapped_angle_degrees
        raw = angle_degrees % 360
        candidates = (raw + 360 * offset for offset in range(-3, 4))
        unwrapped = next(
            (candidate for candidate in candidates if first <= candidate <= last),
            None,
        )
        if unwrapped is None:
            return None
        for left, right in zip(self.scale_marks, self.scale_marks[1:]):
            if left.unwrapped_angle_degrees <= unwrapped <= right.unwrapped_angle_degrees:
                span = right.unwrapped_angle_degrees - left.unwrapped_angle_degrees
                fraction = (unwrapped - left.unwrapped_angle_degrees) / span
                return left.value + fraction * (right.value - left.value)
        return None


class Ws2021Calibration(CalibrationModel):
    schema_version: Literal[2]
    calibration_id: str = Field(
        min_length=8,
        max_length=128,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]+$",
    )
    created_at: datetime
    source_width: int = Field(gt=0, le=MAX_SOURCE_WIDTH)
    source_height: int = Field(gt=0, le=MAX_SOURCE_HEIGHT)
    orientation: Literal["landscape", "portrait"]
    zoom: Literal[2, 3]
    center_x: float = Field(ge=0, le=1)
    center_y: float = Field(ge=0, le=1)
    gauge_quadrilateral: GaugeQuadrilateral
    gauge_rect: NormalizedRect
    humidity: GaugeFace
    temperature: GaugeFace
    reference_version: str = Field(
        min_length=1,
        max_length=128,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]*$",
    )

    @field_validator("created_at")
    @classmethod
    def require_aware_created_at(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("created_at must be timezone-aware")
        return value

    @model_validator(mode="after")
    def require_geometry_inside_gauge(self) -> Self:
        if self.orientation == "landscape" and self.source_width < self.source_height:
            raise ValueError("orientation does not match source dimensions")
        if self.orientation == "portrait" and self.source_height < self.source_width:
            raise ValueError("orientation does not match source dimensions")

        points = [
            *self.gauge_quadrilateral.points,
            self.humidity.center,
            self.humidity.needle_tip,
            *(mark.point for mark in self.humidity.scale_marks),
            self.temperature.center,
            self.temperature.needle_tip,
            *(mark.point for mark in self.temperature.scale_marks),
        ]
        if not all(self.gauge_rect.contains(point) for point in points):
            raise ValueError("all gauge geometry must remain inside gauge_rect")
        if any(not 0 <= mark.value <= 100 for mark in self.humidity.scale_marks):
            raise ValueError("humidity scale values must remain between 0 and 100")
        if any(not -50 <= mark.value <= 60 for mark in self.temperature.scale_marks):
            raise ValueError("temperature scale values must remain between -50 and 60")
        return self


def viewport_to_source(
    point: Point,
    *,
    zoom: Literal[2, 3],
    center_x: float,
    center_y: float,
) -> Point:
    visible = 1 / zoom
    left = min(max(0.0, center_x - visible / 2), 1 - visible)
    top = min(max(0.0, center_y - visible / 2), 1 - visible)
    return Point(x=left + point.x * visible, y=top + point.y * visible)


class GaugeCalibrationStore:
    def __init__(self, calibration_path: Path, *, backup_limit: int = 3) -> None:
        self._calibration_path = calibration_path
        self._reference_path = calibration_path.with_name("ws2021-reference.jpg")
        self._backup_dir = calibration_path.parent / "backups"
        self._backup_limit = backup_limit

    def current(self) -> Ws2021Calibration:
        if not self._calibration_path.is_file():
            raise CalibrationMissing("calibration is not configured")
        try:
            return Ws2021Calibration.model_validate_json(
                self._calibration_path.read_bytes()
            )
        except (OSError, ValidationError, ValueError) as exc:
            raise CalibrationInvalid("calibration is invalid") from exc

    def save(
        self,
        calibration: Ws2021Calibration | Mapping[str, Any],
        reference_jpeg: bytes,
    ) -> Ws2021Calibration:
        try:
            validated = Ws2021Calibration.model_validate(calibration)
        except (ValidationError, ValueError, TypeError) as exc:
            raise CalibrationInvalid("calibration is invalid") from exc
        self._validate_reference_jpeg(reference_jpeg)

        self._calibration_path.parent.mkdir(parents=True, exist_ok=True)
        json_bytes = validated.model_dump_json(indent=2).encode("utf-8")
        temp_json = self._write_temp(json_bytes, suffix=".json")
        temp_reference = self._write_temp(reference_jpeg, suffix=".jpg")
        try:
            self._backup_current()
            os.replace(temp_reference, self._reference_path)
            os.replace(temp_json, self._calibration_path)
            self._fsync_directory(self._calibration_path.parent)
            self._prune_backups()
        finally:
            for path in (temp_json, temp_reference):
                try:
                    path.unlink()
                except FileNotFoundError:
                    pass
        return validated

    @staticmethod
    def _validate_reference_jpeg(payload: bytes) -> None:
        if not payload or len(payload) > MAX_REFERENCE_BYTES:
            raise CalibrationInvalid("reference JPEG is invalid")
        try:
            with Image.open(BytesIO(payload)) as image:
                image.verify()
                if image.format != "JPEG":
                    raise CalibrationInvalid("reference JPEG is invalid")
        except CalibrationInvalid:
            raise
        except (UnidentifiedImageError, OSError, ValueError) as exc:
            raise CalibrationInvalid("reference JPEG is invalid") from exc

    def _write_temp(self, payload: bytes, *, suffix: str) -> Path:
        descriptor, raw_path = tempfile.mkstemp(
            prefix=".ws2021-",
            suffix=suffix,
            dir=self._calibration_path.parent,
        )
        path = Path(raw_path)
        try:
            with os.fdopen(descriptor, "wb") as output:
                output.write(payload)
                output.flush()
                os.fsync(output.fileno())
        except Exception:
            path.unlink(missing_ok=True)
            raise
        return path

    def _backup_current(self) -> None:
        if not (self._calibration_path.is_file() and self._reference_path.is_file()):
            return
        self._backup_dir.mkdir(parents=True, exist_ok=True)
        try:
            current_id = self.current().calibration_id
        except (CalibrationMissing, CalibrationInvalid):
            current_id = "invalid"
        prefix = f"{time.time_ns()}-{current_id}"
        shutil.copy2(self._calibration_path, self._backup_dir / f"{prefix}.json")
        shutil.copy2(self._reference_path, self._backup_dir / f"{prefix}.jpg")

    def _prune_backups(self) -> None:
        if not self._backup_dir.is_dir():
            return
        json_backups = sorted(self._backup_dir.glob("*.json"), reverse=True)
        for old_json in json_backups[self._backup_limit :]:
            old_jpeg = old_json.with_suffix(".jpg")
            old_json.unlink(missing_ok=True)
            old_jpeg.unlink(missing_ok=True)

    @staticmethod
    def _fsync_directory(directory: Path) -> None:
        try:
            descriptor = os.open(directory, os.O_RDONLY)
        except OSError:
            return
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
