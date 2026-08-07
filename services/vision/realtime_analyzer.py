from __future__ import annotations

import time
from collections.abc import Callable

import cv2
import numpy as np

from packages.contracts.vision import (
    AdultTrack,
    BedSubjectTrack,
    HeadFaceState,
    RealtimeObservation,
    SceneQuality,
)
from services.vision.frame_policy import PreparedAnalysisFrame
from services.vision.realtime_models import RealtimeModelBackend, RealtimeModelError


class RealtimeAnalyzerError(RuntimeError):
    """A stable, non-sensitive realtime analysis failure."""


class RealtimeVisualAnalyzer:
    def __init__(
        self,
        *,
        model_backend: RealtimeModelBackend | None = None,
        perf_counter: Callable[[], float] = time.perf_counter,
    ) -> None:
        self._model_backend = model_backend
        self._perf_counter = perf_counter
        self._previous_gray: np.ndarray | None = None
        self._previous_mean_luma: float | None = None
        self._uncertain_until: float | None = None
        self._last_monotonic: float | None = None

    def analyze(
        self,
        frame: PreparedAnalysisFrame,
        *,
        monotonic_now: float,
    ) -> RealtimeObservation:
        self._require_monotonic(monotonic_now)
        started = self._perf_counter()
        bgr = self._decode(frame)
        gray = cv2.cvtColor(bgr, cv2.COLOR_BGR2GRAY)
        mean_luma = float(np.mean(gray))
        scene_quality = self._scene_quality(gray)
        motion_ratio = self._motion_ratio(gray)

        if self._is_global_luma_switch(gray, mean_luma):
            self._uncertain_until = monotonic_now + 3.0
        if self._uncertain_until is not None:
            if monotonic_now <= self._uncertain_until:
                scene_quality = SceneQuality.UNCERTAIN
            else:
                self._uncertain_until = None

        self._previous_gray = gray
        self._previous_mean_luma = mean_luma
        (
            pose_count,
            face_count,
            bed_subject_track,
            adult_track,
            head_face_state,
        ) = self._semantic_tracks(bgr, scene_quality)
        processing_ms = max(0.0, (self._perf_counter() - started) * 1000)
        return RealtimeObservation(
            motion_ratio=motion_ratio,
            scene_quality=scene_quality,
            pose_count=pose_count,
            face_count=face_count,
            bed_subject_track=bed_subject_track,
            adult_track=adult_track,
            head_face_state=head_face_state,
            processing_ms=processing_ms,
        )

    def _semantic_tracks(
        self,
        bgr: np.ndarray,
        scene_quality: SceneQuality,
    ) -> tuple[
        int | None,
        int | None,
        BedSubjectTrack,
        AdultTrack,
        HeadFaceState,
    ]:
        if self._model_backend is None or scene_quality is not SceneQuality.USABLE:
            return (
                None,
                None,
                BedSubjectTrack.UNCERTAIN,
                AdultTrack.UNCERTAIN,
                HeadFaceState.UNCERTAIN,
            )
        try:
            signals = self._model_backend.infer(bgr)
        except (RealtimeModelError, ValueError, RuntimeError):
            return (
                None,
                None,
                BedSubjectTrack.UNCERTAIN,
                AdultTrack.UNCERTAIN,
                HeadFaceState.UNCERTAIN,
            )
        pose_count = len(signals.pose_centers)
        face_count = len(signals.face_boxes)
        if not signals.pose_centers:
            bed_track = BedSubjectTrack.MISSING
        elif any(
            x < 0.12 or x > 0.88 or y < 0.12 or y > 0.88
            for x, y in signals.pose_centers
        ):
            bed_track = BedSubjectTrack.BOUNDARY
        else:
            bed_track = BedSubjectTrack.INSIDE
        adult_track = (
            AdultTrack.INTERSECTING_BED
            if pose_count >= 2
            else AdultTrack.ABSENT
        )
        if face_count:
            face_state = HeadFaceState.VISIBLE
        elif pose_count:
            face_state = HeadFaceState.TEMPORARILY_MISSING
        else:
            face_state = HeadFaceState.UNCERTAIN
        return pose_count, face_count, bed_track, adult_track, face_state

    def _motion_ratio(self, gray: np.ndarray) -> float:
        previous = self._previous_gray
        if previous is None or previous.shape != gray.shape:
            return 0.0
        height, width = gray.shape
        top, bottom = round(height * 0.1), round(height * 0.9)
        left, right = round(width * 0.1), round(width * 0.9)
        current_center = gray[top:bottom, left:right]
        previous_center = previous[top:bottom, left:right]
        difference = cv2.absdiff(current_center, previous_center)
        changed = difference >= 20
        return round(float(np.count_nonzero(changed)) / changed.size, 6)

    def _is_global_luma_switch(
        self,
        gray: np.ndarray,
        mean_luma: float,
    ) -> bool:
        previous = self._previous_gray
        previous_mean = self._previous_mean_luma
        if previous is None or previous_mean is None or previous.shape != gray.shape:
            return False
        if abs(mean_luma - previous_mean) <= 35:
            return False
        difference = cv2.absdiff(gray, previous)
        return float(np.std(difference)) < 12

    @staticmethod
    def _scene_quality(gray: np.ndarray) -> SceneQuality:
        mean_luma = float(np.mean(gray))
        if mean_luma < 8:
            return SceneQuality.DARK
        if float(np.std(gray)) < 4:
            return SceneQuality.FLAT
        laplacian_variance = float(cv2.Laplacian(gray, cv2.CV_64F).var())
        if laplacian_variance < 25:
            return SceneQuality.BLURRED
        return SceneQuality.USABLE

    @staticmethod
    def _decode(frame: PreparedAnalysisFrame) -> np.ndarray:
        encoded = np.frombuffer(frame.jpeg, dtype=np.uint8)
        bgr = cv2.imdecode(encoded, cv2.IMREAD_COLOR)
        if (
            bgr is None
            or bgr.shape != (frame.height, frame.width, 3)
            or frame.width != 960
            or frame.height != 540
        ):
            raise RealtimeAnalyzerError("realtime_frame_invalid")
        return bgr

    def _require_monotonic(self, value: float) -> None:
        if value < 0 or not np.isfinite(value):
            raise ValueError("monotonic time must be finite and non-negative")
        if self._last_monotonic is not None and value < self._last_monotonic:
            raise ValueError("monotonic time cannot decrease")
        self._last_monotonic = value
