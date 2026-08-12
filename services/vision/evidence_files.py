from __future__ import annotations

import hashlib
from io import BytesIO
import os
from pathlib import Path
from uuid import uuid4

from PIL import Image, UnidentifiedImageError

from services.vision.frame_policy import PreparedAnalysisFrame


FRAME_DURATION_MS = 2_000
WEBP_QUALITY = 75


class GuardianEvidenceFiles:
    def __init__(self, root: Path) -> None:
        self._root = Path(root)

    def write_snapshot(
        self,
        event_id: str,
        frame: PreparedAnalysisFrame,
    ) -> str:
        self._load_safe_image(frame).close()
        key = self._key(event_id, "snapshot.jpg")
        self._atomic_write(key, frame.jpeg)
        return key

    def write_clip(
        self,
        event_id: str,
        frames: tuple[PreparedAnalysisFrame, ...],
    ) -> str:
        if not frames:
            raise ValueError("clip requires at least one safe frame")
        images: list[Image.Image] = []
        try:
            for frame in frames:
                with self._load_safe_image(frame) as image:
                    images.append(image.convert("RGB"))
            output = BytesIO()
            images[0].save(
                output,
                format="WEBP",
                save_all=True,
                append_images=images[1:],
                duration=FRAME_DURATION_MS,
                loop=0,
                quality=WEBP_QUALITY,
                method=4,
            )
            payload = output.getvalue()
        finally:
            for image in images:
                image.close()
        key = self._key(event_id, "clip.webp")
        self._atomic_write(key, payload)
        return key

    @staticmethod
    def _load_safe_image(frame: PreparedAnalysisFrame) -> Image.Image:
        try:
            image = Image.open(BytesIO(frame.jpeg))
            if image.format != "JPEG" or image.size != (frame.width, frame.height):
                image.close()
                raise ValueError("invalid safe frame")
            image.load()
            return image
        except ValueError:
            raise
        except (UnidentifiedImageError, OSError) as exc:
            raise ValueError("invalid safe frame") from exc

    @staticmethod
    def _key(event_id: str, filename: str) -> str:
        digest = hashlib.sha256(event_id.encode("utf-8")).hexdigest()
        return f"visual-risk/{digest}/{filename}"

    def _atomic_write(self, key: str, payload: bytes) -> None:
        destination = self._root / key
        self._ensure_private_directory(destination.parent)
        temporary = destination.parent / f".{destination.name}.{uuid4().hex}.tmp"
        descriptor = os.open(
            temporary,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL,
            0o600,
        )
        try:
            with os.fdopen(descriptor, "wb") as stream:
                stream.write(payload)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, destination)
            os.chmod(destination, 0o600)
            directory_descriptor = os.open(destination.parent, os.O_RDONLY)
            try:
                os.fsync(directory_descriptor)
            finally:
                os.close(directory_descriptor)
        except Exception:
            try:
                temporary.unlink()
            except FileNotFoundError:
                pass
            raise

    def _ensure_private_directory(self, directory: Path) -> None:
        self._root.mkdir(parents=True, exist_ok=True, mode=0o700)
        os.chmod(self._root, 0o700)
        visual_risk = self._root / "visual-risk"
        visual_risk.mkdir(exist_ok=True, mode=0o700)
        os.chmod(visual_risk, 0o700)
        directory.mkdir(exist_ok=True, mode=0o700)
        os.chmod(directory, 0o700)
