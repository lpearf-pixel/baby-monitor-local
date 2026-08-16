from __future__ import annotations

import json
import os
import tempfile
from enum import StrEnum
from hashlib import sha256
from io import BytesIO
from pathlib import Path
from typing import Protocol

import cv2
import numpy as np
from PIL import Image, UnidentifiedImageError
from pydantic import BaseModel, ConfigDict, Field

from services.gauge.calibration import NormalizedRect
from services.gauge.locator import GaugeLocation
from services.stream.frame_source import CapturedFrame


MIN_CROP_EDGE = 64
MAX_CROP_EDGE = 2048
MAX_CROP_BYTES = 8 * 1024 * 1024
MIN_LAPLACIAN_VARIANCE = 20.0
MIN_MEAN_LUMA = 20.0
MAX_MEAN_LUMA = 245.0


class CollectionCode(StrEnum):
    ACCEPTED = "accepted"
    PRIVACY_REJECTED = "privacy_rejected"
    DUPLICATE_REJECTED = "duplicate_rejected"
    QUALITY_REJECTED = "quality_rejected"
    FAILED = "failed"


class CollectionCounts(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    accepted: int = Field(default=0, ge=0)
    privacy_rejected: int = Field(default=0, ge=0)
    duplicate_rejected: int = Field(default=0, ge=0)
    quality_rejected: int = Field(default=0, ge=0)
    failed: int = Field(default=0, ge=0)

    def record(self, code: CollectionCode) -> CollectionCounts:
        values = self.model_dump()
        values[code.value] += 1
        return CollectionCounts.model_validate(values)


class PrivacyOverlapGuard(Protocol):
    def overlaps(self, image: np.ndarray, box: NormalizedRect) -> bool: ...


class PrivacyCandidates(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    person_boxes: tuple[NormalizedRect, ...] = ()
    skin_boxes: tuple[NormalizedRect, ...] = ()


class PrivacyCandidateBackend(Protocol):
    def detect(self, image: np.ndarray) -> PrivacyCandidates: ...


class CandidatePrivacyGuard:
    def __init__(self, *, backend: PrivacyCandidateBackend) -> None:
        self._backend = backend

    def overlaps(self, image: np.ndarray, box: NormalizedRect) -> bool:
        candidates = self._backend.detect(image)
        return any(
            self._intersects(box, candidate)
            for candidate in (*candidates.person_boxes, *candidates.skin_boxes)
        )

    @staticmethod
    def _intersects(left: NormalizedRect, right: NormalizedRect) -> bool:
        return (
            left.x < right.x + right.width
            and right.x < left.x + left.width
            and left.y < right.y + right.height
            and right.y < left.y + left.height
        )


class CropStore(Protocol):
    def save(self, crop_jpeg: bytes) -> bool: ...


class Ws2021Collector:
    def __init__(
        self,
        *,
        store: CropStore,
        privacy_guard: PrivacyOverlapGuard,
    ) -> None:
        self._store = store
        self._privacy_guard = privacy_guard

    def collect(
        self,
        frame: CapturedFrame,
        location: GaugeLocation,
    ) -> CollectionCode:
        image = self._decode(frame)
        if image is None:
            return CollectionCode.FAILED
        try:
            if self._privacy_guard.overlaps(image, location.box):
                return CollectionCode.PRIVACY_REJECTED
        except Exception:
            return CollectionCode.PRIVACY_REJECTED

        crop = self._crop(image, location.box)
        if crop is None or not self._quality_is_usable(crop):
            return CollectionCode.QUALITY_REJECTED
        ok, encoded = cv2.imencode(".jpg", crop, [cv2.IMWRITE_JPEG_QUALITY, 92])
        if not ok:
            return CollectionCode.FAILED
        try:
            saved = self._store.save(encoded.tobytes())
        except Exception:
            return CollectionCode.FAILED
        return (
            CollectionCode.ACCEPTED
            if saved
            else CollectionCode.DUPLICATE_REJECTED
        )

    @staticmethod
    def _decode(frame: CapturedFrame) -> np.ndarray | None:
        encoded = np.frombuffer(frame.jpeg, dtype=np.uint8)
        image = cv2.imdecode(encoded, cv2.IMREAD_COLOR)
        if image is None or image.shape[:2] != (frame.height, frame.width):
            return None
        return image

    @staticmethod
    def _crop(image: np.ndarray, box: NormalizedRect) -> np.ndarray | None:
        height, width = image.shape[:2]
        left = round(box.x * width)
        top = round(box.y * height)
        right = round((box.x + box.width) * width)
        bottom = round((box.y + box.height) * height)
        if not (0 <= left < right <= width and 0 <= top < bottom <= height):
            return None
        return image[top:bottom, left:right].copy()

    @staticmethod
    def _quality_is_usable(crop: np.ndarray) -> bool:
        height, width = crop.shape[:2]
        if min(height, width) < MIN_CROP_EDGE or max(height, width) > MAX_CROP_EDGE:
            return False
        gray = cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY)
        mean_luma = float(np.mean(gray))
        sharpness = float(cv2.Laplacian(gray, cv2.CV_64F).var())
        return (
            MIN_MEAN_LUMA <= mean_luma <= MAX_MEAN_LUMA
            and sharpness >= MIN_LAPLACIAN_VARIANCE
        )


class PrivateCropStore:
    def __init__(self, root: Path) -> None:
        self._root = root

    def save(self, crop_jpeg: bytes) -> bool:
        width, height = self._validate_crop(crop_jpeg)
        digest = sha256(crop_jpeg).hexdigest()
        self._prepare_root()
        image_path = self._root / f"{digest}.jpg"
        metadata_path = self._root / f"{digest}.json"
        if image_path.exists() or metadata_path.exists():
            return False
        metadata = json.dumps(
            {
                "class_name": "ws2021",
                "height": height,
                "sha256": digest,
                "width": width,
            },
            sort_keys=True,
            separators=(",", ":"),
        ).encode("ascii")
        self._atomic_write(image_path, crop_jpeg)
        try:
            self._atomic_write(metadata_path, metadata)
        except Exception:
            image_path.unlink(missing_ok=True)
            raise
        self._fsync_directory()
        return True

    def _prepare_root(self) -> None:
        if self._root.is_symlink():
            raise ValueError("ws2021_collection_failed")
        self._root.mkdir(parents=True, exist_ok=True, mode=0o700)
        os.chmod(self._root, 0o700)

    @staticmethod
    def _validate_crop(payload: bytes) -> tuple[int, int]:
        if not payload or len(payload) > MAX_CROP_BYTES:
            raise ValueError("ws2021_collection_failed")
        try:
            with Image.open(BytesIO(payload)) as image:
                image.verify()
            with Image.open(BytesIO(payload)) as image:
                if image.format != "JPEG":
                    raise ValueError("ws2021_collection_failed")
                width, height = image.size
        except (UnidentifiedImageError, OSError, ValueError) as exc:
            raise ValueError("ws2021_collection_failed") from exc
        if (
            min(width, height) < MIN_CROP_EDGE
            or max(width, height) > MAX_CROP_EDGE
        ):
            raise ValueError("ws2021_collection_failed")
        return width, height

    def _atomic_write(self, destination: Path, payload: bytes) -> None:
        descriptor, temporary_name = tempfile.mkstemp(
            prefix=f".{destination.name}.",
            suffix=".partial",
            dir=self._root,
        )
        temporary = Path(temporary_name)
        try:
            os.fchmod(descriptor, 0o600)
            with os.fdopen(descriptor, "wb") as output:
                output.write(payload)
                output.flush()
                os.fsync(output.fileno())
            os.replace(temporary, destination)
            os.chmod(destination, 0o600)
        finally:
            try:
                os.close(descriptor)
            except OSError:
                pass
            temporary.unlink(missing_ok=True)

    def _fsync_directory(self) -> None:
        descriptor = os.open(self._root, os.O_RDONLY)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
