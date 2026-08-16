from __future__ import annotations

from enum import StrEnum
from io import BytesIO
from typing import Protocol

import cv2
import numpy as np
from PIL import Image, UnidentifiedImageError
from pydantic import BaseModel, ConfigDict, Field

from services.gauge.calibration import NormalizedRect
from services.stream.frame_source import CapturedFrame


INPUT_SIZE = 640
MIN_CONFIDENCE = 0.75
NMS_THRESHOLD = 0.45
MIN_SOURCE_WIDTH_FRACTION = 0.10
MIN_UPRIGHT_RATIO = 0.85
MAX_UPRIGHT_RATIO = 1.35


class GaugeLocalizationCode(StrEnum):
    NOT_FOUND = "gauge_not_found"
    AMBIGUOUS = "gauge_ambiguous"
    BOX_INVALID = "gauge_box_invalid"
    POSE_INVALID = "gauge_pose_invalid"
    MODEL_INVALID = "gauge_model_invalid"
    INFERENCE_FAILED = "gauge_inference_failed"


class GaugeLocalizationError(RuntimeError):
    def __init__(self, code: GaugeLocalizationCode) -> None:
        self.code = code
        super().__init__(code.value)


class GaugeLocation(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    box: NormalizedRect
    confidence: float = Field(ge=0, le=1)
    model_version: str = Field(
        min_length=1,
        max_length=128,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9._-]*$",
    )


class GaugeInferenceBackend(Protocol):
    model_version: str

    def infer(self, tensor: np.ndarray) -> np.ndarray: ...


class GaugeLocator:
    def __init__(self, *, backend: GaugeInferenceBackend) -> None:
        self._backend = backend

    def locate(self, frame: CapturedFrame) -> GaugeLocation:
        tensor, scale, pad_x, pad_y = self._preprocess(frame)
        try:
            output = np.asarray(self._backend.infer(tensor), dtype=np.float32)
        except Exception as exc:
            raise GaugeLocalizationError(
                GaugeLocalizationCode.INFERENCE_FAILED
            ) from exc
        rows = self._validated_rows(output)
        candidates: list[tuple[list[float], float]] = []
        for center_x, center_y, width, height, objectness, class_score in rows:
            confidence = float(objectness * class_score)
            if confidence < MIN_CONFIDENCE:
                continue
            left = float(center_x - width / 2)
            top = float(center_y - height / 2)
            candidates.append(([left, top, float(width), float(height)], confidence))
        if not candidates:
            raise GaugeLocalizationError(GaugeLocalizationCode.NOT_FOUND)

        kept = cv2.dnn.NMSBoxes(
            [item[0] for item in candidates],
            [item[1] for item in candidates],
            MIN_CONFIDENCE,
            NMS_THRESHOLD,
        )
        indexes = [int(index) for index in np.asarray(kept).reshape(-1)]
        if not indexes:
            raise GaugeLocalizationError(GaugeLocalizationCode.NOT_FOUND)
        if len(indexes) != 1:
            raise GaugeLocalizationError(GaugeLocalizationCode.AMBIGUOUS)

        encoded_box, confidence = candidates[indexes[0]]
        left = (encoded_box[0] - pad_x) / scale
        top = (encoded_box[1] - pad_y) / scale
        width = encoded_box[2] / scale
        height = encoded_box[3] / scale
        if (
            left < 0
            or top < 0
            or width <= 0
            or height <= 0
            or left + width > frame.width
            or top + height > frame.height
            or width / frame.width < MIN_SOURCE_WIDTH_FRACTION
        ):
            raise GaugeLocalizationError(GaugeLocalizationCode.BOX_INVALID)
        ratio = height / width
        if not MIN_UPRIGHT_RATIO <= ratio <= MAX_UPRIGHT_RATIO:
            raise GaugeLocalizationError(GaugeLocalizationCode.POSE_INVALID)
        try:
            return GaugeLocation(
                box=NormalizedRect(
                    x=left / frame.width,
                    y=top / frame.height,
                    width=width / frame.width,
                    height=height / frame.height,
                ),
                confidence=confidence,
                model_version=self._backend.model_version,
            )
        except Exception as exc:
            raise GaugeLocalizationError(GaugeLocalizationCode.MODEL_INVALID) from exc

    @staticmethod
    def _validated_rows(output: np.ndarray) -> np.ndarray:
        if output.size == 0:
            return np.empty((0, 6), dtype=np.float32)
        if output.ndim == 3 and output.shape[0] == 1:
            output = output[0]
        if (
            output.ndim != 2
            or output.shape[1] != 6
            or not np.isfinite(output).all()
            or np.any(output[:, 2:4] <= 0)
            or np.any(output[:, 4:6] < 0)
            or np.any(output[:, 4:6] > 1)
        ):
            raise GaugeLocalizationError(GaugeLocalizationCode.MODEL_INVALID)
        return output

    @staticmethod
    def _preprocess(
        frame: CapturedFrame,
    ) -> tuple[np.ndarray, float, float, float]:
        try:
            with Image.open(BytesIO(frame.jpeg)) as source:
                source.verify()
            encoded = np.frombuffer(frame.jpeg, dtype=np.uint8)
            image = cv2.imdecode(encoded, cv2.IMREAD_COLOR)
        except (UnidentifiedImageError, OSError, ValueError) as exc:
            raise GaugeLocalizationError(GaugeLocalizationCode.BOX_INVALID) from exc
        if image is None or image.shape[:2] != (frame.height, frame.width):
            raise GaugeLocalizationError(GaugeLocalizationCode.BOX_INVALID)
        scale = min(INPUT_SIZE / frame.width, INPUT_SIZE / frame.height)
        resized_width = max(1, round(frame.width * scale))
        resized_height = max(1, round(frame.height * scale))
        resized = cv2.resize(image, (resized_width, resized_height))
        pad_x = (INPUT_SIZE - resized_width) // 2
        pad_y = (INPUT_SIZE - resized_height) // 2
        canvas = np.full((INPUT_SIZE, INPUT_SIZE, 3), 114, dtype=np.uint8)
        canvas[
            pad_y : pad_y + resized_height,
            pad_x : pad_x + resized_width,
        ] = resized
        tensor = np.ascontiguousarray(canvas.transpose(2, 0, 1)[None], dtype=np.float32)
        return tensor, scale, float(pad_x), float(pad_y)
