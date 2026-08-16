from __future__ import annotations

import json
import os
import tempfile
from dataclasses import dataclass
from enum import StrEnum
from hashlib import sha256
from io import BytesIO
from pathlib import Path
from typing import Protocol
from urllib.parse import urlsplit

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


@dataclass(frozen=True)
class NegativeSample:
    path: Path
    license_id: str
    source_url: str

    def __post_init__(self) -> None:
        parsed = urlsplit(self.source_url)
        if (
            not self.license_id
            or len(self.license_id) > 64
            or any(
                character not in "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789.-"
                for character in self.license_id
            )
            or parsed.scheme != "https"
            or not parsed.hostname
            or parsed.username is not None
            or parsed.password is not None
        ):
            raise ValueError("ws2021_dataset_invalid")


class DatasetCounts(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    train: int = Field(ge=0)
    val: int = Field(ge=0)
    negative: int = Field(ge=0)


def build_training_dataset(
    source_root: Path,
    output_root: Path,
    *,
    negatives: tuple[NegativeSample, ...] = (),
    augmentation_count: int = 1,
) -> DatasetCounts:
    if not 0 <= augmentation_count <= 8:
        raise ValueError("ws2021_dataset_invalid")
    sources = _load_private_crops(source_root)
    if not sources:
        raise ValueError("ws2021_dataset_invalid")
    _prepare_dataset_root(output_root)
    samples: list[dict[str, object]] = []
    train_count = 0
    val_count = 0

    for digest, image in sources:
        split = _split_for_digest(digest)
        variants = 1 + (augmentation_count if split == "train" else 0)
        for variant in range(variants):
            augmented = variant > 0
            rendered, label, transform = _render_positive(
                image,
                digest=digest,
                variant=variant,
                augmented=augmented,
            )
            sample_id = sha256(f"{digest}:{variant}".encode("ascii")).hexdigest()
            image_relative = Path("images") / split / f"{sample_id}.jpg"
            label_relative = Path("labels") / split / f"{sample_id}.txt"
            _write_private(output_root / image_relative, rendered)
            _write_private(output_root / label_relative, label.encode("ascii"))
            samples.append(
                {
                    "augmented": augmented,
                    "class_name": "ws2021",
                    "image": image_relative.as_posix(),
                    "label": label_relative.as_posix(),
                    "source_digest": digest,
                    "split": split,
                    "transform": transform,
                }
            )
            if split == "train":
                train_count += 1
            else:
                val_count += 1

    for negative in negatives:
        payload, digest = _load_negative(negative)
        sample_id = sha256(f"negative:{digest}".encode("ascii")).hexdigest()
        image_relative = Path("images/train") / f"{sample_id}.jpg"
        label_relative = Path("labels/train") / f"{sample_id}.txt"
        _write_private(output_root / image_relative, payload)
        _write_private(output_root / label_relative, b"")
        samples.append(
            {
                "augmented": False,
                "class_name": "background",
                "image": image_relative.as_posix(),
                "label": label_relative.as_posix(),
                "license_id": negative.license_id,
                "source_digest": digest,
                "source_url": negative.source_url,
                "split": "train",
                "transform": {
                    "brightness": 1.0,
                    "rotation_degrees": 0.0,
                    "scale": 1.0,
                },
            }
        )

    manifest = {
        "format_version": 1,
        "input_size": 640,
        "samples": sorted(samples, key=lambda sample: str(sample["image"])),
    }
    _write_private(
        output_root / "manifest.json",
        json.dumps(manifest, sort_keys=True, separators=(",", ":")).encode("ascii"),
    )
    _fsync_path(output_root)
    return DatasetCounts(
        train=train_count,
        val=val_count,
        negative=len(negatives),
    )


def _load_private_crops(source_root: Path) -> list[tuple[str, np.ndarray]]:
    if not source_root.is_dir() or source_root.is_symlink():
        raise ValueError("ws2021_dataset_invalid")
    loaded: list[tuple[str, np.ndarray]] = []
    for metadata_path in sorted(source_root.glob("*.json")):
        try:
            metadata = json.loads(metadata_path.read_text(encoding="ascii"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            raise ValueError("ws2021_dataset_invalid") from exc
        if set(metadata) != {"class_name", "height", "sha256", "width"}:
            raise ValueError("ws2021_dataset_invalid")
        digest = metadata["sha256"]
        if (
            metadata["class_name"] != "ws2021"
            or not isinstance(digest, str)
            or len(digest) != 64
            or any(character not in "0123456789abcdef" for character in digest)
            or metadata_path.name != f"{digest}.json"
            or not isinstance(metadata["width"], int)
            or not isinstance(metadata["height"], int)
            or min(metadata["width"], metadata["height"]) < MIN_CROP_EDGE
            or max(metadata["width"], metadata["height"]) > MAX_CROP_EDGE
        ):
            raise ValueError("ws2021_dataset_invalid")
        image_path = source_root / f"{digest}.jpg"
        try:
            payload = image_path.read_bytes()
        except OSError as exc:
            raise ValueError("ws2021_dataset_invalid") from exc
        if sha256(payload).hexdigest() != digest:
            raise ValueError("ws2021_dataset_invalid")
        image = cv2.imdecode(np.frombuffer(payload, dtype=np.uint8), cv2.IMREAD_COLOR)
        if (
            image is None
            or image.shape[1] != metadata["width"]
            or image.shape[0] != metadata["height"]
        ):
            raise ValueError("ws2021_dataset_invalid")
        loaded.append((digest, image))
    return loaded


def _split_for_digest(digest: str) -> str:
    return "val" if int(sha256(f"split-v1:{digest}".encode("ascii")).hexdigest()[:8], 16) % 5 == 0 else "train"


def _render_positive(
    image: np.ndarray,
    *,
    digest: str,
    variant: int,
    augmented: bool,
) -> tuple[bytes, str, dict[str, float]]:
    rng = np.random.default_rng(
        int(sha256(f"augment-v1:{digest}:{variant}".encode("ascii")).hexdigest()[:16], 16)
    )
    rotation = float(rng.uniform(-3.0, 3.0)) if augmented else 0.0
    scale = float(rng.uniform(0.45, 0.8)) if augmented else 0.62
    brightness = float(rng.uniform(0.75, 1.25)) if augmented else 1.0
    adjusted = np.clip(image.astype(np.float32) * brightness, 0, 255).astype(np.uint8)
    height, width = adjusted.shape[:2]
    matrix = cv2.getRotationMatrix2D((width / 2, height / 2), rotation, 1.0)
    rotated = cv2.warpAffine(
        adjusted,
        matrix,
        (width, height),
        flags=cv2.INTER_LINEAR,
        borderMode=cv2.BORDER_CONSTANT,
        borderValue=(114, 114, 114),
    )
    resize_factor = (640 * scale) / max(width, height)
    resized_width = max(1, round(width * resize_factor))
    resized_height = max(1, round(height * resize_factor))
    resized = cv2.resize(rotated, (resized_width, resized_height))
    if augmented:
        left = int(rng.integers(0, 640 - resized_width + 1))
        top = int(rng.integers(0, 640 - resized_height + 1))
    else:
        left = (640 - resized_width) // 2
        top = (640 - resized_height) // 2
    canvas = np.full((640, 640, 3), 114, dtype=np.uint8)
    canvas[top : top + resized_height, left : left + resized_width] = resized
    ok, encoded = cv2.imencode(".jpg", canvas, [cv2.IMWRITE_JPEG_QUALITY, 92])
    if not ok:
        raise ValueError("ws2021_dataset_invalid")
    center_x = (left + resized_width / 2) / 640
    center_y = (top + resized_height / 2) / 640
    label = (
        f"0 {center_x:.8f} {center_y:.8f} "
        f"{resized_width / 640:.8f} {resized_height / 640:.8f}\n"
    )
    return (
        encoded.tobytes(),
        label,
        {
            "brightness": round(brightness, 6),
            "rotation_degrees": round(rotation, 6),
            "scale": round(scale, 6),
        },
    )


def _load_negative(sample: NegativeSample) -> tuple[bytes, str]:
    try:
        payload = sample.path.read_bytes()
    except OSError as exc:
        raise ValueError("ws2021_dataset_invalid") from exc
    image = cv2.imdecode(np.frombuffer(payload, dtype=np.uint8), cv2.IMREAD_COLOR)
    if image is None:
        raise ValueError("ws2021_dataset_invalid")
    resized = cv2.resize(image, (640, 640))
    ok, encoded = cv2.imencode(".jpg", resized, [cv2.IMWRITE_JPEG_QUALITY, 92])
    if not ok:
        raise ValueError("ws2021_dataset_invalid")
    normalized = encoded.tobytes()
    return normalized, sha256(payload).hexdigest()


def _prepare_dataset_root(root: Path) -> None:
    if root.is_symlink():
        raise ValueError("ws2021_dataset_invalid")
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(root, 0o700)


def _write_private(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(path.parent, 0o700)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".partial", dir=path.parent
    )
    temporary = Path(temporary_name)
    try:
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "wb") as output:
            output.write(payload)
            output.flush()
            os.fsync(output.fileno())
        os.replace(temporary, path)
        os.chmod(path, 0o600)
    finally:
        try:
            os.close(descriptor)
        except OSError:
            pass
        temporary.unlink(missing_ok=True)


def _fsync_path(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
