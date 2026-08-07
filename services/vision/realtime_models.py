from __future__ import annotations

import math
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

import cv2
import numpy as np

from packages.monitoring.realtime_models import (
    ModelAssetCode,
    verify_realtime_model_assets,
)


_POSE_KEYPOINT_PAIRS = (
    (1, 2),
    (1, 5),
    (2, 3),
    (3, 4),
    (5, 6),
    (6, 7),
    (1, 8),
    (8, 9),
    (9, 10),
    (1, 11),
    (11, 12),
    (12, 13),
    (1, 0),
    (0, 14),
    (14, 16),
    (0, 15),
    (15, 17),
    (2, 16),
    (5, 17),
)
_POSE_PAF_CHANNELS = (
    (12, 13),
    (20, 21),
    (14, 15),
    (16, 17),
    (22, 23),
    (24, 25),
    (0, 1),
    (2, 3),
    (4, 5),
    (6, 7),
    (8, 9),
    (10, 11),
    (28, 29),
    (30, 31),
    (34, 35),
    (32, 33),
    (36, 37),
    (18, 19),
    (26, 27),
)


class RealtimeModelError(RuntimeError):
    """A stable, non-sensitive realtime model failure."""


@dataclass(frozen=True)
class RealtimeModelSignals:
    face_boxes: tuple[tuple[float, float, float, float], ...] = ()
    pose_centers: tuple[tuple[float, float], ...] = ()
    torso_angles: tuple[float, ...] = ()

    def __post_init__(self) -> None:
        values = [value for box in self.face_boxes for value in box]
        values.extend(value for center in self.pose_centers for value in center)
        if any(not math.isfinite(value) or not 0 <= value <= 1 for value in values):
            raise ValueError("realtime_model_output_invalid")
        if any(not math.isfinite(angle) for angle in self.torso_angles):
            raise ValueError("realtime_model_output_invalid")


class RealtimeModelBackend(Protocol):
    def infer(self, bgr: np.ndarray) -> RealtimeModelSignals: ...


def decode_pose_maps(
    pafs: np.ndarray,
    heatmaps: np.ndarray,
) -> tuple[tuple[tuple[float, float], ...], tuple[float, ...]]:
    """Decode OpenPose heatmaps/PAFs into grouped, bounded person summaries."""
    if (
        pafs.ndim != 3
        or heatmaps.ndim != 3
        or pafs.shape[0] != 38
        or heatmaps.shape[0] != 19
        or pafs.shape[1:] != heatmaps.shape[1:]
    ):
        raise ValueError("realtime_model_output_invalid")
    height, width = heatmaps.shape[1:]
    keypoints: list[tuple[int, int, int, float]] = []
    by_type: list[list[int]] = [[] for _ in range(18)]
    for keypoint_type in range(18):
        heatmap = heatmaps[keypoint_type]
        dilated = cv2.dilate(heatmap, np.ones((3, 3), dtype=np.uint8))
        peaks = np.argwhere((heatmap == dilated) & (heatmap >= 0.1))
        ranked = sorted(
            peaks,
            key=lambda point: float(heatmap[point[0], point[1]]),
            reverse=True,
        )[:20]
        for row, column in ranked:
            identifier = len(keypoints)
            keypoints.append(
                (
                    keypoint_type,
                    int(column),
                    int(row),
                    float(heatmap[row, column]),
                )
            )
            by_type[keypoint_type].append(identifier)

    poses: list[dict[int, int]] = []
    for (start_type, end_type), (paf_x_id, paf_y_id) in zip(
        _POSE_KEYPOINT_PAIRS,
        _POSE_PAF_CHANNELS,
        strict=True,
    ):
        candidates: list[tuple[float, int, int]] = []
        for start_id in by_type[start_type]:
            for end_id in by_type[end_type]:
                score = _connection_score(
                    keypoints[start_id],
                    keypoints[end_id],
                    pafs[paf_x_id],
                    pafs[paf_y_id],
                )
                if score is not None:
                    candidates.append((score, start_id, end_id))
        used_start: set[int] = set()
        used_end: set[int] = set()
        for _score, start_id, end_id in sorted(candidates, reverse=True):
            if start_id in used_start or end_id in used_end:
                continue
            used_start.add(start_id)
            used_end.add(end_id)
            _join_pose(poses, start_type, start_id, end_type, end_id)

    decoded: list[tuple[tuple[float, float], float]] = []
    for pose in poses:
        if len(pose) < 3:
            continue
        points = [keypoints[identifier] for identifier in pose.values()]
        center = (
            sum(point[1] for point in points) / len(points) / max(1, width - 1),
            sum(point[2] for point in points) / len(points) / max(1, height - 1),
        )
        angle = _torso_angle(pose, keypoints)
        if angle is not None:
            decoded.append((center, angle))
    decoded.sort(key=lambda item: item[0][0])
    return (
        tuple(center for center, _angle in decoded),
        tuple(angle for _center, angle in decoded),
    )


def _connection_score(
    start: tuple[int, int, int, float],
    end: tuple[int, int, int, float],
    paf_x: np.ndarray,
    paf_y: np.ndarray,
) -> float | None:
    vector = np.asarray((end[1] - start[1], end[2] - start[2]), dtype=np.float32)
    length = float(np.linalg.norm(vector))
    if length < 1.0:
        return None
    direction = vector / length
    columns = np.rint(np.linspace(start[1], end[1], 10)).astype(int)
    rows = np.rint(np.linspace(start[2], end[2], 10)).astype(int)
    scores = paf_x[rows, columns] * direction[0] + paf_y[rows, columns] * direction[1]
    if float(np.count_nonzero(scores > 0.05)) / scores.size < 0.8:
        return None
    mean_score = float(np.mean(scores))
    return mean_score if mean_score > 0.05 else None


def _join_pose(
    poses: list[dict[int, int]],
    start_type: int,
    start_id: int,
    end_type: int,
    end_id: int,
) -> None:
    start_pose = next((pose for pose in poses if start_id in pose.values()), None)
    end_pose = next((pose for pose in poses if end_id in pose.values()), None)
    if start_pose is None and end_pose is None:
        poses.append({start_type: start_id, end_type: end_id})
    elif start_pose is not None and end_pose is None:
        if end_type not in start_pose:
            start_pose[end_type] = end_id
    elif start_pose is None and end_pose is not None:
        if start_type not in end_pose:
            end_pose[start_type] = start_id
    elif start_pose is not end_pose and start_pose is not None and end_pose is not None:
        if set(start_pose).isdisjoint(end_pose):
            start_pose.update(end_pose)
            poses.remove(end_pose)


def _torso_angle(
    pose: dict[int, int],
    keypoints: list[tuple[int, int, int, float]],
) -> float | None:
    if 1 not in pose:
        return None
    hip_ids = [pose[index] for index in (8, 11) if index in pose]
    if not hip_ids:
        return None
    neck = keypoints[pose[1]]
    hip_x = sum(keypoints[index][1] for index in hip_ids) / len(hip_ids)
    hip_y = sum(keypoints[index][2] for index in hip_ids) / len(hip_ids)
    return float(math.degrees(math.atan2(hip_y - neck[2], hip_x - neck[1])))


class OpenVinoYuNetBackend:
    def __init__(self, root: Path, openvino_module: object) -> None:
        try:
            self._face_detector = cv2.FaceDetectorYN_create(
                str(root / "face_detection_yunet_2023mar.onnx"),
                "",
                (320, 320),
                0.85,
                0.3,
                5_000,
            )
            core = openvino_module.Core()  # type: ignore[attr-defined]
            model = core.read_model(root / "human-pose-estimation-0001.xml")
            self._pose_model = core.compile_model(model, "CPU")
        except Exception as exc:
            raise RealtimeModelError("realtime_model_unavailable") from exc

    def infer(self, bgr: np.ndarray) -> RealtimeModelSignals:
        if (
            not isinstance(bgr, np.ndarray)
            or bgr.dtype != np.uint8
            or bgr.ndim != 3
            or bgr.shape[2] != 3
        ):
            raise RealtimeModelError("realtime_inference_failed")
        height, width = bgr.shape[:2]
        try:
            self._face_detector.setInputSize((width, height))
            _, faces = self._face_detector.detect(bgr)
            face_boxes = () if faces is None else tuple(
                (
                    max(0.0, float(face[0]) / width),
                    max(0.0, float(face[1]) / height),
                    min(1.0, float(face[2]) / width),
                    min(1.0, float(face[3]) / height),
                )
                for face in faces[:4]
            )
            resized = cv2.resize(bgr, (456, 256), interpolation=cv2.INTER_LINEAR)
            tensor = np.transpose(resized, (2, 0, 1))[None].astype(np.float32)
            outputs = self._pose_model([tensor])
            arrays = tuple(np.asarray(value) for value in outputs.values())
            heatmaps = next(
                value[0]
                for value in arrays
                if value.ndim == 4 and value.shape[1] == 19
            )
            pafs = next(
                value[0]
                for value in arrays
                if value.ndim == 4 and value.shape[1] == 38
            )
            pose_centers, torso_angles = decode_pose_maps(pafs, heatmaps)
            return RealtimeModelSignals(
                face_boxes=face_boxes,
                pose_centers=pose_centers,
                torso_angles=torso_angles,
            )
        except RealtimeModelError:
            raise
        except Exception as exc:
            raise RealtimeModelError("realtime_inference_failed") from exc


def build_realtime_model_backend(root: Path) -> RealtimeModelBackend | None:
    if verify_realtime_model_assets(root).code is not ModelAssetCode.OK:
        return None
    try:
        import openvino

        version = str(getattr(openvino, "__version__", ""))
        if not version.startswith("2025.4"):
            return None
        return OpenVinoYuNetBackend(root, openvino)
    except Exception:
        return None
