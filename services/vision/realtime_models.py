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
            heatmaps = next(
                np.asarray(value)
                for value in outputs.values()
                if np.asarray(value).ndim == 4 and np.asarray(value).shape[1] == 19
            )[0, 1]
            dilated = cv2.dilate(heatmaps, np.ones((3, 3), dtype=np.uint8))
            candidates = np.argwhere((heatmaps == dilated) & (heatmaps >= 0.1))
            ranked = sorted(
                candidates,
                key=lambda point: float(heatmaps[point[0], point[1]]),
                reverse=True,
            )[:4]
            pose_centers = tuple(
                (
                    float(column) / max(1, heatmaps.shape[1] - 1),
                    float(row) / max(1, heatmaps.shape[0] - 1),
                )
                for row, column in ranked
            )
            return RealtimeModelSignals(
                face_boxes=face_boxes,
                pose_centers=pose_centers,
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
