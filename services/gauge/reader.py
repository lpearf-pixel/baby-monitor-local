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
    _MAX_ASPECT_RATIO_DRIFT_FRACTION = 0.05
    _MAX_FACE_CENTER_DRIFT_FRACTION = 0.25
    _MAX_FACE_RADIUS_DRIFT_FRACTION = 0.12
    _MAX_FRAME_CENTER_ERROR_FRACTION = 0.10
    _MAX_FRAME_RADIUS_ERROR_FRACTION = 0.08
    _MAX_BURST_CENTER_SPREAD_FRACTION = 0.08
    _MAX_BURST_RADIUS_SPREAD_FRACTION = 0.06

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

        try:
            adaptive_geometries = self._burst_face_geometries(
                burst, calibration, requested_at
            )
        except _FrameRejected as rejected:
            captured_at = max(
                (frame.captured_at for frame in burst.frames), default=requested_at
            )
            return EnvironmentReading.unavailable(
                reading_id=str(uuid4()),
                source_kind=EnvironmentSourceKind.WS2021_GAUGE,
                captured_at=captured_at,
                failure_reason=rejected.reason,
                calibration_version=calibration.calibration_id,
                sample_count=len(burst.frames),
                valid_temperature_samples=0,
                valid_humidity_samples=0,
                freshness_seconds=self._freshness_seconds,
            )

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
                result = self._read_frame(
                    frame,
                    calibration,
                    adaptive_geometries=adaptive_geometries,
                )
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
        *,
        adaptive_geometries: tuple[_FaceGeometry, _FaceGeometry] | None = None,
    ) -> GaugeFrameResult:
        encoded = np.frombuffer(frame.jpeg, dtype=np.uint8)
        image = cv2.imdecode(encoded, cv2.IMREAD_COLOR)
        if image is None:
            raise _FrameRejected(ReadingFailureReason.FRAME_SOURCE_UNAVAILABLE)
        height, width = image.shape[:2]
        if not self._frame_dimensions_match(width, height, frame, calibration):
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
            warped.shape[1],
            warped.shape[0],
        )
        temperature_geometry = self._face_geometry(
            calibration.temperature,
            transform,
            width,
            height,
            warped.shape[1],
            warped.shape[0],
        )
        if adaptive_geometries is not None:
            humidity_geometry, temperature_geometry = adaptive_geometries
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
            humidity_geometry,
        )
        temperature = self._rectified_value(
            calibration.temperature,
            temperature_candidate.angle_degrees,
            transform,
            width,
            height,
            temperature_geometry,
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

    def _burst_face_geometries(
        self,
        burst: FrameBurst,
        calibration: Ws2021Calibration,
        requested_at: datetime,
    ) -> tuple[_FaceGeometry, _FaceGeometry] | None:
        humidity_observations: list[_FaceGeometry] = []
        temperature_observations: list[_FaceGeometry] = []
        for frame in burst.frames:
            if (
                requested_at - frame.captured_at
            ).total_seconds() > self._maximum_frame_age_seconds:
                continue
            encoded = np.frombuffer(frame.jpeg, dtype=np.uint8)
            image = cv2.imdecode(encoded, cv2.IMREAD_COLOR)
            if image is None:
                continue
            height, width = image.shape[:2]
            if not self._frame_dimensions_match(width, height, frame, calibration):
                continue
            try:
                warped, transform = self._rectify(image, calibration)
                gray = cv2.cvtColor(warped, cv2.COLOR_BGR2GRAY)
                if float(np.mean(gray)) < 8 or float(np.mean(gray >= 250)) > 0.25:
                    continue
                expected_humidity = self._face_geometry(
                    calibration.humidity,
                    transform,
                    width,
                    height,
                    warped.shape[1],
                    warped.shape[0],
                )
                expected_temperature = self._face_geometry(
                    calibration.temperature,
                    transform,
                    width,
                    height,
                    warped.shape[1],
                    warped.shape[0],
                )
                if self._face_is_occluded(
                    gray, expected_humidity
                ) or self._face_is_occluded(gray, expected_temperature):
                    continue
                humidity = self._detect_face_geometry(gray, expected_humidity)
                temperature = self._detect_face_geometry(gray, expected_temperature)
            except _FrameRejected:
                continue
            humidity_observations.append(humidity)
            temperature_observations.append(temperature)

        if len(humidity_observations) < 3:
            return None
        return (
            self._consistent_face_geometry(humidity_observations),
            self._consistent_face_geometry(temperature_observations),
        )

    def _consistent_face_geometry(
        self,
        observations: list[_FaceGeometry],
    ) -> _FaceGeometry:
        center_x = float(np.median([item.center_x for item in observations]))
        center_y = float(np.median([item.center_y for item in observations]))
        radius = float(np.median([item.radius for item in observations]))
        for item in observations:
            center_spread = math.hypot(
                item.center_x - center_x, item.center_y - center_y
            )
            radius_spread = abs(item.radius - radius) / radius
            if (
                center_spread > radius * self._MAX_BURST_CENTER_SPREAD_FRACTION
                or radius_spread > self._MAX_BURST_RADIUS_SPREAD_FRACTION
            ):
                raise _FrameRejected(ReadingFailureReason.CALIBRATION_INVALID)
        return _FaceGeometry(
            calibration=observations[0].calibration,
            center_x=center_x,
            center_y=center_y,
            radius=radius,
        )

    @classmethod
    def _frame_dimensions_match(
        cls,
        width: int,
        height: int,
        frame: CapturedFrame,
        calibration: Ws2021Calibration,
    ) -> bool:
        if min(width, height, frame.width, frame.height) <= 0:
            return False
        if width != frame.width or height != frame.height:
            return False
        source_aspect = calibration.source_width / calibration.source_height
        frame_aspect = width / height
        if not math.isfinite(source_aspect) or not math.isfinite(frame_aspect):
            return False
        aspect_drift = abs(frame_aspect - source_aspect) / source_aspect
        return aspect_drift <= cls._MAX_ASPECT_RATIO_DRIFT_FRACTION

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
        output_width, output_height = Ws2021Reader._rectified_dimensions(
            source,
            calibration,
            width,
            height,
        )
        destination = np.asarray(
            [
                [0, 0],
                [output_width - 1, 0],
                [output_width - 1, output_height - 1],
                [0, output_height - 1],
            ],
            dtype=np.float32,
        )
        transform = cv2.getPerspectiveTransform(source, destination)
        if not np.isfinite(transform).all() or abs(float(np.linalg.det(transform))) < 1e-9:
            raise _FrameRejected(ReadingFailureReason.CALIBRATION_INVALID)
        left, top, right, bottom = Ws2021Reader._rectification_padding(
            transform,
            calibration,
            width,
            height,
            output_width,
            output_height,
        )
        translated_width = output_width + left + right
        translated_height = output_height + top + bottom
        scale = min(
            1.0,
            width / translated_width,
            height / translated_height,
        )
        translation = np.asarray(
            [[scale, 0, left * scale], [0, scale, top * scale], [0, 0, 1]],
            dtype=np.float64,
        )
        transform = translation @ transform
        output_width = max(2, round(translated_width * scale))
        output_height = max(2, round(translated_height * scale))
        return (
            cv2.warpPerspective(image, transform, (output_width, output_height)),
            transform,
        )

    @staticmethod
    def _rectification_padding(
        transform: np.ndarray,
        calibration: Ws2021Calibration,
        source_width: int,
        source_height: int,
        canvas_width: int,
        canvas_height: int,
    ) -> tuple[int, int, int, int]:
        left = top = right = bottom = 0.0
        for face in (calibration.humidity, calibration.temperature):
            center_x, center_y = Ws2021Reader._transform_point(
                face.center, transform, source_width, source_height
            )
            needle_x, needle_y = Ws2021Reader._transform_point(
                face.needle_tip, transform, source_width, source_height
            )
            radius = math.hypot(needle_x - center_x, needle_y - center_y) / 0.8
            search_radius = radius * 1.3
            left = max(left, search_radius - center_x)
            top = max(top, search_radius - center_y)
            right = max(right, center_x + search_radius - canvas_width)
            bottom = max(bottom, center_y + search_radius - canvas_height)
        return tuple(max(0, math.ceil(value)) for value in (left, top, right, bottom))

    @staticmethod
    def _rectified_dimensions(
        source: np.ndarray,
        calibration: Ws2021Calibration,
        source_width: int,
        source_height: int,
    ) -> tuple[int, int]:
        area = abs(float(cv2.contourArea(source)))
        if not math.isfinite(area) or area < 4:
            raise _FrameRejected(ReadingFailureReason.CALIBRATION_INVALID)

        def pixel(point: Point) -> np.ndarray:
            return np.asarray(
                [point.x * (source_width - 1), point.y * (source_height - 1)],
                dtype=np.float32,
            )

        faces = tuple(
            (
                pixel(face.center),
                tuple(pixel(mark.point) for mark in face.scale_marks),
            )
            for face in (calibration.humidity, calibration.temperature)
        )
        best_aspect: float | None = None
        best_score = math.inf
        for aspect in np.linspace(0.25, 4.0, 376):
            destination = np.asarray(
                [[0, 0], [aspect * 1_000, 0], [aspect * 1_000, 1_000], [0, 1_000]],
                dtype=np.float32,
            )
            transform = cv2.getPerspectiveTransform(source, destination)
            score = 0.0
            for center, marks in faces:
                points = np.asarray([[center, *marks]], dtype=np.float32)
                transformed = cv2.perspectiveTransform(points, transform)[0]
                radii = np.linalg.norm(transformed[1:] - transformed[0], axis=1)
                mean_radius = float(np.mean(radii))
                if mean_radius <= 0 or not np.isfinite(radii).all():
                    score = math.inf
                    break
                score += float(np.std(radii) / mean_radius)
            if score < best_score:
                best_score = score
                best_aspect = float(aspect)
        if best_aspect is None or not math.isfinite(best_score):
            raise _FrameRejected(ReadingFailureReason.CALIBRATION_INVALID)

        output_width = math.sqrt(area * best_aspect)
        output_height = math.sqrt(area / best_aspect)
        scale = min(1.0, source_width / output_width, source_height / output_height)
        return max(2, round(output_width * scale)), max(2, round(output_height * scale))

    @staticmethod
    def _transform_point(
        point: Point,
        transform: np.ndarray,
        source_width: int,
        source_height: int,
    ) -> tuple[float, float]:
        source = np.asarray(
            [
                [
                    [
                        point.x * (source_width - 1),
                        point.y * (source_height - 1),
                    ]
                ]
            ],
            dtype=np.float32,
        )
        transformed = cv2.perspectiveTransform(source, transform)[0, 0]
        return float(transformed[0]), float(transformed[1])

    def _face_geometry(
        self,
        face: GaugeFace,
        transform: np.ndarray,
        source_width: int,
        source_height: int,
        canvas_width: int,
        canvas_height: int,
    ) -> _FaceGeometry:
        center_x, center_y = self._transform_point(
            face.center, transform, source_width, source_height
        )
        needle_x, needle_y = self._transform_point(
            face.needle_tip,
            transform,
            source_width,
            source_height,
        )
        radius = math.hypot(needle_x - center_x, needle_y - center_y) / 0.8
        if radius < 12:
            raise _FrameRejected(ReadingFailureReason.CALIBRATION_INVALID)
        if not (
            radius <= center_x < canvas_width - radius
            and radius <= center_y < canvas_height - radius
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

    def _detect_face_geometry(
        self,
        gray: np.ndarray,
        geometry: _FaceGeometry,
    ) -> _FaceGeometry:
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
        candidates = [
            circle
            for circle in circles[0]
            if math.hypot(
                float(circle[0]) - expected_x,
                float(circle[1]) - expected_y,
            )
            <= geometry.radius * self._MAX_FACE_CENTER_DRIFT_FRACTION
            and abs(float(circle[2]) - geometry.radius) / geometry.radius
            <= self._MAX_FACE_RADIUS_DRIFT_FRACTION
        ]
        if len(candidates) != 1:
            raise _FrameRejected(ReadingFailureReason.CALIBRATION_INVALID)
        detected = candidates[0]
        return _FaceGeometry(
            calibration=geometry.calibration,
            center_x=left + float(detected[0]),
            center_y=top + float(detected[1]),
            radius=float(detected[2]),
        )

    def _validate_face_geometry(
        self,
        gray: np.ndarray,
        geometry: _FaceGeometry,
    ) -> None:
        detected = self._detect_face_geometry(gray, geometry)
        center_error = math.hypot(
            detected.center_x - geometry.center_x,
            detected.center_y - geometry.center_y,
        )
        radius_error = abs(detected.radius - geometry.radius) / geometry.radius
        if (
            center_error > geometry.radius * self._MAX_FRAME_CENTER_ERROR_FRACTION
            or radius_error > self._MAX_FRAME_RADIUS_ERROR_FRACTION
        ):
            raise _FrameRejected(ReadingFailureReason.CALIBRATION_INVALID)

    def _rectified_value(
        self,
        face: GaugeFace,
        candidate_angle: float,
        transform: np.ndarray,
        width: int,
        height: int,
        geometry: _FaceGeometry,
    ) -> float | None:
        calibrated_center_x, calibrated_center_y = self._transform_point(
            face.center,
            transform,
            width,
            height,
        )
        needle_x, needle_y = self._transform_point(
            face.needle_tip,
            transform,
            width,
            height,
        )
        calibrated_radius = (
            math.hypot(
                needle_x - calibrated_center_x,
                needle_y - calibrated_center_y,
            )
            / 0.8
        )
        radius_scale = geometry.radius / calibrated_radius
        rectified_marks: list[tuple[float, float]] = []
        previous: float | None = None
        for mark in face.scale_marks:
            mark_x, mark_y = self._transform_point(
                mark.point,
                transform,
                width,
                height,
            )
            adjusted_mark_x = geometry.center_x + (
                mark_x - calibrated_center_x
            ) * radius_scale
            adjusted_mark_y = geometry.center_y + (
                mark_y - calibrated_center_y
            ) * radius_scale
            angle = math.degrees(
                math.atan2(
                    adjusted_mark_y - geometry.center_y,
                    adjusted_mark_x - geometry.center_x,
                )
            ) % 360
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
