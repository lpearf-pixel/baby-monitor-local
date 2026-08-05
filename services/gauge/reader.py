from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime
from typing import Literal
from uuid import uuid4

import cv2
import numpy as np

from packages.contracts.events import (
    EnvironmentReading,
    EnvironmentSourceKind,
    ReadingFailureReason,
)
from services.gauge.calibration import GaugeFace, Point, Ws2021Calibration
from services.stream.frame_source import CapturedFrame, FrameBurst


@dataclass(frozen=True)
class GaugeFrameResult:
    temperature_c: float
    humidity_rh: float
    temperature_confidence: float
    humidity_confidence: float
    captured_at: datetime


@dataclass(frozen=True)
class _FaceGeometry:
    calibration: GaugeFace
    center_x: float
    center_y: float
    radius: float


@dataclass(frozen=True)
class _Candidate:
    angle_degrees: float
    confidence: float


class Ws2021Reader:
    def __init__(
        self,
        *,
        minimum_confidence: float = 0.75,
        freshness_seconds: int = 90,
        maximum_frame_age_seconds: float = 5.0,
        temperature_mad_limit: float = 0.5,
        humidity_mad_limit: float = 2.5,
    ) -> None:
        self._minimum_confidence = minimum_confidence
        self._freshness_seconds = freshness_seconds
        self._maximum_frame_age_seconds = maximum_frame_age_seconds
        self._temperature_mad_limit = temperature_mad_limit
        self._humidity_mad_limit = humidity_mad_limit

    def read(
        self,
        burst: FrameBurst,
        calibration: Ws2021Calibration,
        requested_at: datetime,
    ) -> EnvironmentReading:
        if requested_at.tzinfo is None or requested_at.utcoffset() is None:
            raise ValueError("requested_at must be timezone-aware")

        valid: list[GaugeFrameResult] = []
        failures: list[ReadingFailureReason] = []
        observed_times: list[datetime] = []
        for frame in burst.frames:
            observed_times.append(frame.captured_at)
            age_seconds = (requested_at - frame.captured_at).total_seconds()
            if age_seconds > self._maximum_frame_age_seconds:
                failures.append(ReadingFailureReason.FRAME_STALE)
                continue
            try:
                result = self._read_frame(frame, calibration)
            except _FrameRejected as rejected:
                failures.append(rejected.reason)
            except Exception:
                failures.append(ReadingFailureReason.INTERNAL_ERROR)
            else:
                valid.append(result)

        sample_count = len(burst.frames)
        valid_count = len(valid)
        captured_at = max(observed_times, default=requested_at)
        if valid_count < 3:
            reason = self._insufficient_reason(valid_count, failures)
            return EnvironmentReading.unavailable(
                reading_id=str(uuid4()),
                source_kind=EnvironmentSourceKind.WS2021_GAUGE,
                captured_at=captured_at,
                failure_reason=reason,
                calibration_version=calibration.calibration_id,
                sample_count=sample_count,
                valid_temperature_samples=valid_count,
                valid_humidity_samples=valid_count,
                freshness_seconds=self._freshness_seconds,
            )

        temperatures = np.asarray(
            [item.temperature_c for item in valid], dtype=np.float64
        )
        humidities = np.asarray([item.humidity_rh for item in valid], dtype=np.float64)
        temperature = float(np.median(temperatures))
        humidity = float(np.median(humidities))
        temperature_mad = float(np.median(np.abs(temperatures - temperature)))
        humidity_mad = float(np.median(np.abs(humidities - humidity)))
        if (
            temperature_mad > self._temperature_mad_limit
            or humidity_mad > self._humidity_mad_limit
        ):
            return self._unavailable_from_valid(
                valid,
                calibration,
                sample_count,
                ReadingFailureReason.INCONSISTENT_FRAMES,
            )

        confidence = min(
            float(np.median([item.temperature_confidence for item in valid])),
            float(np.median([item.humidity_confidence for item in valid])),
        )
        if confidence < self._minimum_confidence:
            return self._unavailable_from_valid(
                valid,
                calibration,
                sample_count,
                ReadingFailureReason.LOW_CONFIDENCE,
                confidence=confidence,
            )
        return EnvironmentReading.available(
            reading_id=str(uuid4()),
            source_kind=EnvironmentSourceKind.WS2021_GAUGE,
            captured_at=max(item.captured_at for item in valid),
            temperature_c=temperature,
            humidity_rh=humidity,
            confidence=confidence,
            calibration_version=calibration.calibration_id,
            sample_count=sample_count,
            valid_temperature_samples=valid_count,
            valid_humidity_samples=valid_count,
            minimum_confidence=self._minimum_confidence,
            freshness_seconds=self._freshness_seconds,
        )

    @staticmethod
    def _insufficient_reason(
        valid_count: int,
        failures: list[ReadingFailureReason],
    ) -> ReadingFailureReason:
        if valid_count == 0 and failures and len(set(failures)) == 1:
            return failures[0]
        return ReadingFailureReason.INSUFFICIENT_VALID_FRAMES

    def _unavailable_from_valid(
        self,
        valid: list[GaugeFrameResult],
        calibration: Ws2021Calibration,
        sample_count: int,
        reason: ReadingFailureReason,
        *,
        confidence: float = 0,
    ) -> EnvironmentReading:
        return EnvironmentReading.unavailable(
            reading_id=str(uuid4()),
            source_kind=EnvironmentSourceKind.WS2021_GAUGE,
            captured_at=max(item.captured_at for item in valid),
            failure_reason=reason,
            calibration_version=calibration.calibration_id,
            sample_count=sample_count,
            valid_temperature_samples=len(valid),
            valid_humidity_samples=len(valid),
            confidence=confidence,
            freshness_seconds=self._freshness_seconds,
        )

    def _read_frame(
        self,
        frame: CapturedFrame,
        calibration: Ws2021Calibration,
    ) -> GaugeFrameResult:
        encoded = np.frombuffer(frame.jpeg, dtype=np.uint8)
        image = cv2.imdecode(encoded, cv2.IMREAD_COLOR)
        if image is None:
            raise _FrameRejected(ReadingFailureReason.FRAME_SOURCE_UNAVAILABLE)
        height, width = image.shape[:2]
        if (
            width != frame.width
            or height != frame.height
            or width != calibration.source_width
            or height != calibration.source_height
        ):
            raise _FrameRejected(ReadingFailureReason.CALIBRATION_INVALID)

        warped, transform = self._rectify(image, calibration)
        gray = cv2.cvtColor(warped, cv2.COLOR_BGR2GRAY)
        if float(np.mean(gray)) < 8:
            raise _FrameRejected(ReadingFailureReason.TOO_DARK)
        if float(np.mean(gray >= 250)) > 0.25:
            raise _FrameRejected(ReadingFailureReason.GLARE)

        humidity_geometry = self._face_geometry(
            calibration.humidity,
            transform,
            width,
            height,
        )
        temperature_geometry = self._face_geometry(
            calibration.temperature,
            transform,
            width,
            height,
        )
        if self._face_is_occluded(gray, humidity_geometry) or self._face_is_occluded(
            gray, temperature_geometry
        ):
            raise _FrameRejected(ReadingFailureReason.OCCLUDED)
        self._validate_face_geometry(gray, humidity_geometry)
        self._validate_face_geometry(gray, temperature_geometry)
        hsv = cv2.cvtColor(warped, cv2.COLOR_BGR2HSV)
        red_mask = cv2.bitwise_or(
            cv2.inRange(hsv, (0, 80, 70), (12, 255, 255)),
            cv2.inRange(hsv, (168, 80, 70), (179, 255, 255)),
        )
        mode: Literal["day", "night"] = (
            "day" if int(np.count_nonzero(red_mask)) >= 30 else "night"
        )

        if mode == "day":
            humidity_candidate = self._color_candidate(red_mask, humidity_geometry)
            temperature_candidate = self._color_candidate(
                red_mask, temperature_geometry
            )
        else:
            humidity_candidate = self._gray_candidate(gray, humidity_geometry)
            temperature_candidate = self._gray_candidate(gray, temperature_geometry)

        humidity = self._rectified_value(
            calibration.humidity,
            humidity_candidate.angle_degrees,
            transform,
            width,
            height,
        )
        temperature = self._rectified_value(
            calibration.temperature,
            temperature_candidate.angle_degrees,
            transform,
            width,
            height,
        )
        if humidity is None or temperature is None:
            raise _FrameRejected(ReadingFailureReason.CALIBRATION_INVALID)
        return GaugeFrameResult(
            temperature_c=temperature,
            humidity_rh=humidity,
            temperature_confidence=temperature_candidate.confidence,
            humidity_confidence=humidity_candidate.confidence,
            captured_at=frame.captured_at,
        )

    @staticmethod
    def _rectify(
        image: np.ndarray,
        calibration: Ws2021Calibration,
    ) -> tuple[np.ndarray, np.ndarray]:
        height, width = image.shape[:2]
        source = np.asarray(
            [
                [point.x * (width - 1), point.y * (height - 1)]
                for point in calibration.gauge_quadrilateral.points
            ],
            dtype=np.float32,
        )
        destination = np.asarray(
            [[0, 0], [width - 1, 0], [width - 1, height - 1], [0, height - 1]],
            dtype=np.float32,
        )
        transform = cv2.getPerspectiveTransform(source, destination)
        if not np.isfinite(transform).all() or abs(float(np.linalg.det(transform))) < 1e-9:
            raise _FrameRejected(ReadingFailureReason.CALIBRATION_INVALID)
        return (
            cv2.warpPerspective(image, transform, (width, height)),
            transform,
        )

    @staticmethod
    def _transform_point(
        point: Point,
        transform: np.ndarray,
        width: int,
        height: int,
    ) -> tuple[float, float]:
        source = np.asarray(
            [[[point.x * (width - 1), point.y * (height - 1)]]],
            dtype=np.float32,
        )
        transformed = cv2.perspectiveTransform(source, transform)[0, 0]
        return float(transformed[0]), float(transformed[1])

    def _face_geometry(
        self,
        face: GaugeFace,
        transform: np.ndarray,
        width: int,
        height: int,
    ) -> _FaceGeometry:
        center_x, center_y = self._transform_point(
            face.center, transform, width, height
        )
        needle_x, needle_y = self._transform_point(
            face.needle_tip,
            transform,
            width,
            height,
        )
        radius = math.hypot(needle_x - center_x, needle_y - center_y) / 0.8
        if radius < 12:
            raise _FrameRejected(ReadingFailureReason.CALIBRATION_INVALID)
        if not (
            radius <= center_x < width - radius
            and radius <= center_y < height - radius
        ):
            raise _FrameRejected(ReadingFailureReason.ROI_OUT_OF_BOUNDS)
        return _FaceGeometry(
            calibration=face,
            center_x=center_x,
            center_y=center_y,
            radius=radius,
        )

    @staticmethod
    def _face_is_occluded(gray: np.ndarray, geometry: _FaceGeometry) -> bool:
        radius = round(geometry.radius * 0.9)
        center_x = round(geometry.center_x)
        center_y = round(geometry.center_y)
        crop = gray[
            center_y - radius : center_y + radius + 1,
            center_x - radius : center_x + radius + 1,
        ]
        y, x = np.ogrid[-radius : radius + 1, -radius : radius + 1]
        inside = x * x + y * y <= radius * radius
        return float(np.mean(crop[inside] <= 8)) > 0.45

    @staticmethod
    def _validate_face_geometry(gray: np.ndarray, geometry: _FaceGeometry) -> None:
        search_radius = round(geometry.radius * 1.3)
        center_x = round(geometry.center_x)
        center_y = round(geometry.center_y)
        left = center_x - search_radius
        top = center_y - search_radius
        right = center_x + search_radius + 1
        bottom = center_y + search_radius + 1
        if left < 0 or top < 0 or right > gray.shape[1] or bottom > gray.shape[0]:
            raise _FrameRejected(ReadingFailureReason.ROI_OUT_OF_BOUNDS)
        crop = gray[top:bottom, left:right]
        sharpness = float(cv2.Laplacian(crop, cv2.CV_64F).var())
        if sharpness < 12:
            raise _FrameRejected(ReadingFailureReason.LOW_CONFIDENCE)
        blurred = cv2.GaussianBlur(crop, (5, 5), 1)
        circles = cv2.HoughCircles(
            blurred,
            cv2.HOUGH_GRADIENT,
            dp=1.2,
            minDist=max(12, geometry.radius),
            param1=80,
            param2=20,
            minRadius=max(8, round(geometry.radius * 0.72)),
            maxRadius=round(geometry.radius * 1.28),
        )
        if circles is None:
            raise _FrameRejected(ReadingFailureReason.CALIBRATION_INVALID)
        expected_x = geometry.center_x - left
        expected_y = geometry.center_y - top
        candidates = circles[0]
        detected = min(
            candidates,
            key=lambda circle: math.hypot(
                float(circle[0]) - expected_x,
                float(circle[1]) - expected_y,
            ),
        )
        center_offset = math.hypot(
            float(detected[0]) - expected_x,
            float(detected[1]) - expected_y,
        )
        radius_error = abs(float(detected[2]) - geometry.radius) / geometry.radius
        if center_offset > geometry.radius * 0.1 or radius_error > 0.08:
            raise _FrameRejected(ReadingFailureReason.CALIBRATION_INVALID)

    def _rectified_value(
        self,
        face: GaugeFace,
        candidate_angle: float,
        transform: np.ndarray,
        width: int,
        height: int,
    ) -> float | None:
        center_x, center_y = self._transform_point(
            face.center,
            transform,
            width,
            height,
        )
        rectified_marks: list[tuple[float, float]] = []
        previous: float | None = None
        for mark in face.scale_marks:
            mark_x, mark_y = self._transform_point(
                mark.point,
                transform,
                width,
                height,
            )
            angle = math.degrees(math.atan2(mark_y - center_y, mark_x - center_x)) % 360
            unwrapped = angle
            while previous is not None and unwrapped <= previous:
                unwrapped += 360
            rectified_marks.append((unwrapped, mark.value))
            previous = unwrapped
        first = rectified_marks[0][0]
        last = rectified_marks[-1][0]
        candidate = next(
            (
                candidate_angle % 360 + 360 * offset
                for offset in range(-3, 4)
                if first <= candidate_angle % 360 + 360 * offset <= last
            ),
            None,
        )
        if candidate is None:
            return None
        for (left_angle, left_value), (right_angle, right_value) in zip(
            rectified_marks,
            rectified_marks[1:],
            strict=True,
        ):
            if left_angle <= candidate <= right_angle:
                fraction = (candidate - left_angle) / (right_angle - left_angle)
                return left_value + fraction * (right_value - left_value)
        return None

    def _color_candidate(
        self,
        red_mask: np.ndarray,
        geometry: _FaceGeometry,
    ) -> _Candidate:
        scores = self._radial_scores(
            red_mask.astype(np.float32) / 255,
            geometry,
            absolute_from_median=False,
        )
        return self._select_candidate(scores)

    def _gray_candidate(
        self,
        gray: np.ndarray,
        geometry: _FaceGeometry,
    ) -> _Candidate:
        clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8)).apply(gray)
        scores = self._radial_scores(
            clahe.astype(np.float32),
            geometry,
            absolute_from_median=True,
        )
        scores = np.clip(scores / 160, 0, 1)
        return self._select_candidate(scores)

    @staticmethod
    def _radial_scores(
        image: np.ndarray,
        geometry: _FaceGeometry,
        *,
        absolute_from_median: bool,
    ) -> np.ndarray:
        radii = np.linspace(
            geometry.radius * 0.2,
            geometry.radius * 0.82,
            max(24, round(geometry.radius * 0.62)),
        )
        angles = np.deg2rad(np.arange(360, dtype=np.float32))[:, None]
        x = np.rint(geometry.center_x + np.cos(angles) * radii).astype(np.int32)
        y = np.rint(geometry.center_y + np.sin(angles) * radii).astype(np.int32)
        samples = image[y, x]
        if absolute_from_median:
            background = float(np.median(samples))
            samples = np.abs(samples - background)
        return np.mean(samples, axis=1)

    @staticmethod
    def _select_candidate(scores: np.ndarray) -> _Candidate:
        peak_index = int(np.argmax(scores))
        peak = float(scores[peak_index])
        if peak < 0.18:
            raise _FrameRejected(ReadingFailureReason.NEEDLE_NOT_FOUND)

        suppressed = scores.copy()
        for offset in range(-10, 11):
            suppressed[(peak_index + offset) % 360] = 0
        second = float(np.max(suppressed))
        if second >= peak * 0.75 and second >= 0.18:
            raise _FrameRejected(ReadingFailureReason.NEEDLE_NOT_FOUND)

        support = sum(
            scores[(peak_index + offset) % 360] >= peak * 0.5
            for offset in range(-8, 9)
        )
        confidence = min(1.0, peak * 0.5 + min(support / 6, 1.0) * 0.5)
        weighted_offsets = np.arange(-5, 6, dtype=np.float64)
        weights = np.asarray(
            [scores[(peak_index + int(offset)) % 360] for offset in weighted_offsets]
        )
        if float(np.sum(weights)) > 0:
            angle = (peak_index + float(np.average(weighted_offsets, weights=weights))) % 360
        else:
            angle = float(peak_index)
        return _Candidate(angle_degrees=angle, confidence=confidence)


class _FrameRejected(RuntimeError):
    def __init__(self, reason: ReadingFailureReason) -> None:
        super().__init__(reason.value)
        self.reason = reason
