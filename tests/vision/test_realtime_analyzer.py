from __future__ import annotations

from datetime import UTC, datetime
from io import BytesIO

import cv2
import numpy as np
from PIL import Image

from packages.contracts.vision import (
    AdultTrack,
    BedSubjectTrack,
    HeadFaceState,
    NormalizedPoint,
    NormalizedPolygon,
    SceneQuality,
)
from services.stream.frame_source import CapturedFrame
from services.vision.frame_policy import PreparedAnalysisFrame, VisionFramePolicy
from services.vision.realtime_models import RealtimeModelSignals


NOW = datetime(2026, 8, 6, 12, 0, tzinfo=UTC)


def jpeg(image: np.ndarray) -> bytes:
    ok, encoded = cv2.imencode(".jpg", image, [cv2.IMWRITE_JPEG_QUALITY, 95])
    assert ok
    return encoded.tobytes()


def frame(image: np.ndarray) -> PreparedAnalysisFrame:
    height, width = image.shape[:2]
    return PreparedAnalysisFrame(
        jpeg=jpeg(image),
        captured_at=NOW,
        width=width,
        height=height,
        crop_box=(0, 0, width, height),
    )


def textured(value: int = 80) -> np.ndarray:
    image = np.full((540, 960, 3), value, dtype=np.uint8)
    for y in range(0, 540, 24):
        cv2.line(image, (0, y), (959, y), (value + 50,) * 3, 2)
    for x in range(0, 960, 24):
        cv2.line(image, (x, 0), (x, 539), (value + 30,) * 3, 2)
    return image


class RecordingBackend:
    def __init__(self, signals: RealtimeModelSignals) -> None:
        self.signals = signals
        self.frames: list[np.ndarray] = []

    def infer(self, bgr: np.ndarray) -> RealtimeModelSignals:
        self.frames.append(bgr.copy())
        return self.signals


def analyzer_module():
    from services.vision import realtime_analyzer

    return realtime_analyzer


def test_first_frame_has_no_motion_and_missing_models_remain_unknown() -> None:
    module = analyzer_module()
    analyzer = module.RealtimeVisualAnalyzer(perf_counter=lambda: 1.0)

    observation = analyzer.analyze(frame(textured()), monotonic_now=0.0)

    assert observation.motion_ratio == 0.0
    assert observation.scene_quality is SceneQuality.USABLE
    assert observation.pose_count is None
    assert observation.face_count is None
    assert observation.bed_subject_track is BedSubjectTrack.UNCERTAIN
    assert observation.adult_track is AdultTrack.UNCERTAIN
    assert observation.head_face_state is HeadFaceState.UNCERTAIN


def test_center_motion_is_measured_but_edge_only_motion_is_excluded() -> None:
    module = analyzer_module()
    base = textured()
    center_changed = base.copy()
    center_changed[180:360, 300:660] = 230
    edge_changed = center_changed.copy()
    edge_changed[:50, :] = 0
    edge_changed[-50:, :] = 0
    edge_changed[:, :80] = 0
    edge_changed[:, -80:] = 0

    center = module.RealtimeVisualAnalyzer(perf_counter=lambda: 1.0)
    center.analyze(frame(base), monotonic_now=0.0)
    center_observation = center.analyze(frame(center_changed), monotonic_now=0.2)

    edge = module.RealtimeVisualAnalyzer(perf_counter=lambda: 1.0)
    edge.analyze(frame(center_changed), monotonic_now=0.0)
    edge_observation = edge.analyze(frame(edge_changed), monotonic_now=0.2)

    assert center_observation.motion_ratio > 0.05
    assert edge_observation.motion_ratio < 0.01


def test_scene_quality_classifies_dark_flat_and_blurred() -> None:
    module = analyzer_module()
    dark = np.zeros((540, 960, 3), dtype=np.uint8)
    flat = np.full((540, 960, 3), 120, dtype=np.uint8)
    structured = np.full((540, 960, 3), 60, dtype=np.uint8)
    structured[:, 240:480] = 130
    structured[:, 480:720] = 80
    structured[:, 720:] = 170
    blurred = cv2.GaussianBlur(structured, (101, 101), 0)

    assert module.RealtimeVisualAnalyzer().analyze(
        frame(dark), monotonic_now=0.0
    ).scene_quality is SceneQuality.DARK
    assert module.RealtimeVisualAnalyzer().analyze(
        frame(flat), monotonic_now=0.0
    ).scene_quality is SceneQuality.FLAT
    assert module.RealtimeVisualAnalyzer().analyze(
        frame(blurred), monotonic_now=0.0
    ).scene_quality is SceneQuality.BLURRED


def test_global_luma_switch_has_three_second_uncertain_grace() -> None:
    module = analyzer_module()
    analyzer = module.RealtimeVisualAnalyzer()
    before = textured(50)
    after = textured(120)

    analyzer.analyze(frame(before), monotonic_now=0.0)
    switched = analyzer.analyze(frame(after), monotonic_now=1.0)
    grace = analyzer.analyze(frame(after), monotonic_now=3.9)
    recovered = analyzer.analyze(frame(after), monotonic_now=4.1)

    assert switched.scene_quality is SceneQuality.UNCERTAIN
    assert grace.scene_quality is SceneQuality.UNCERTAIN
    assert recovered.scene_quality is SceneQuality.USABLE


def test_model_signals_map_to_bounded_semantic_tracks() -> None:
    module = analyzer_module()
    backend = RecordingBackend(
        RealtimeModelSignals(
            face_boxes=((0.4, 0.3, 0.1, 0.1),),
            pose_centers=((0.5, 0.5), (0.7, 0.6)),
        )
    )
    analyzer = module.RealtimeVisualAnalyzer(
        model_backend=backend,
        perf_counter=lambda: 1.0,
    )

    observation = analyzer.analyze(frame(textured()), monotonic_now=0.0)

    assert observation.pose_count == 2
    assert observation.face_count == 1
    assert observation.bed_subject_track is BedSubjectTrack.INSIDE
    assert observation.adult_track is AdultTrack.INTERSECTING_BED
    assert observation.head_face_state is HeadFaceState.VISIBLE


def test_privacy_mask_is_applied_before_model_backend() -> None:
    module = analyzer_module()
    source = np.full((540, 960, 3), (20, 100, 20), dtype=np.uint8)
    for x in range(0, 960, 24):
        cv2.line(source, (x, 0), (x, 539), (180, 40, 60), 2)
    for y in range(0, 540, 24):
        cv2.line(source, (0, y), (959, y), (40, 180, 100), 2)
    source[162:378, 336:624] = (0, 0, 255)
    bed = NormalizedPolygon(
        points=(
            NormalizedPoint(x=0, y=0),
            NormalizedPoint(x=1, y=0),
            NormalizedPoint(x=1, y=1),
            NormalizedPoint(x=0, y=1),
        )
    )
    mask = NormalizedPolygon(
        points=(
            NormalizedPoint(x=0.35, y=0.3),
            NormalizedPoint(x=0.65, y=0.3),
            NormalizedPoint(x=0.65, y=0.7),
            NormalizedPoint(x=0.35, y=0.7),
        )
    )
    buffer = BytesIO()
    Image.fromarray(cv2.cvtColor(source, cv2.COLOR_BGR2RGB)).save(buffer, "JPEG")
    prepared = VisionFramePolicy(bed_zone=bed, privacy_masks=(mask,)).prepare(
        CapturedFrame(
            jpeg=buffer.getvalue(),
            captured_at=NOW,
            width=960,
            height=540,
        )
    )
    backend = RecordingBackend(RealtimeModelSignals())

    module.RealtimeVisualAnalyzer(model_backend=backend).analyze(
        prepared,
        monotonic_now=0.0,
    )

    assert len(backend.frames) == 1
    center = backend.frames[0][270, 480]
    assert int(center.max()) < 10
