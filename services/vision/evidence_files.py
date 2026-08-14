from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
import hashlib
from io import BytesIO
import os
from pathlib import Path
import re
import stat
from uuid import uuid4

from PIL import Image, UnidentifiedImageError

from services.vision.frame_policy import PreparedAnalysisFrame


FRAME_DURATION_MS = 2_000
WEBP_QUALITY = 75
_CONTROLLED_TEMPORARY = re.compile(
    r"\A\.(?:snapshot\.jpg|clip\.webp)\.[0-9a-f]{32}\.tmp\Z"
)
_DIRECTORY_OPEN_FLAGS = os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW


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

    def total_bytes(self) -> int:
        root_descriptor = self._open_directory(self._root, missing_ok=True)
        if root_descriptor is None:
            return 0
        try:
            return self._directory_bytes(root_descriptor)
        finally:
            os.close(root_descriptor)

    def event_bytes(self, event_id: str) -> int:
        with self._open_event_directory(event_id) as opened:
            if opened is None:
                return 0
            _visual_risk_descriptor, event_descriptor, _digest = opened
            return sum(
                size for _name, size in self._controlled_entries(event_descriptor)
            )

    def delete_event(self, event_id: str) -> int:
        with self._open_event_directory(event_id) as opened:
            if opened is None:
                return 0
            visual_risk_descriptor, event_descriptor, digest = opened
            entries = self._controlled_entries(event_descriptor)
            reclaimed = sum(size for _name, size in entries)
            for name, _size in entries:
                os.unlink(name, dir_fd=event_descriptor)
            os.fsync(event_descriptor)
            os.rmdir(digest, dir_fd=visual_risk_descriptor)
            os.fsync(visual_risk_descriptor)
            return reclaimed

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

    @contextmanager
    def _open_event_directory(
        self,
        event_id: str,
    ) -> Iterator[tuple[int, int, str] | None]:
        root_descriptor = self._open_directory(self._root, missing_ok=True)
        if root_descriptor is None:
            yield None
            return
        visual_risk_descriptor: int | None = None
        event_descriptor: int | None = None
        try:
            visual_risk_descriptor = self._open_directory_at(
                root_descriptor,
                "visual-risk",
                missing_ok=True,
            )
            if visual_risk_descriptor is None:
                yield None
                return
            digest = hashlib.sha256(event_id.encode("utf-8")).hexdigest()
            event_descriptor = self._open_directory_at(
                visual_risk_descriptor,
                digest,
                missing_ok=True,
            )
            if event_descriptor is None:
                yield None
                return
            yield visual_risk_descriptor, event_descriptor, digest
        finally:
            if event_descriptor is not None:
                os.close(event_descriptor)
            if visual_risk_descriptor is not None:
                os.close(visual_risk_descriptor)
            os.close(root_descriptor)

    @staticmethod
    def _controlled_entries(directory_descriptor: int) -> tuple[tuple[str, int], ...]:
        entries: list[tuple[str, int]] = []
        with os.scandir(directory_descriptor) as directory_entries:
            for entry in directory_entries:
                entry_stat = os.stat(
                    entry.name,
                    dir_fd=directory_descriptor,
                    follow_symlinks=False,
                )
                controlled_name = entry.name in {"snapshot.jpg", "clip.webp"} or (
                    _CONTROLLED_TEMPORARY.fullmatch(entry.name) is not None
                )
                if not controlled_name or not stat.S_ISREG(entry_stat.st_mode):
                    raise ValueError("unsafe evidence entry")
                entries.append((entry.name, entry_stat.st_size))
        return tuple(sorted(entries))

    @classmethod
    def _directory_bytes(cls, directory_descriptor: int) -> int:
        total = 0
        with os.scandir(directory_descriptor) as directory_entries:
            for entry in directory_entries:
                entry_stat = os.stat(
                    entry.name,
                    dir_fd=directory_descriptor,
                    follow_symlinks=False,
                )
                if stat.S_ISREG(entry_stat.st_mode):
                    total += entry_stat.st_size
                    continue
                if not stat.S_ISDIR(entry_stat.st_mode):
                    raise ValueError("unsafe evidence entry")
                child_descriptor = cls._open_directory_at(
                    directory_descriptor,
                    entry.name,
                    missing_ok=False,
                )
                assert child_descriptor is not None
                try:
                    total += cls._directory_bytes(child_descriptor)
                finally:
                    os.close(child_descriptor)
        return total

    @staticmethod
    def _open_directory(path: Path, *, missing_ok: bool) -> int | None:
        try:
            return os.open(path, _DIRECTORY_OPEN_FLAGS)
        except FileNotFoundError:
            if missing_ok:
                return None
            raise

    @staticmethod
    def _open_directory_at(
        parent_descriptor: int,
        name: str,
        *,
        missing_ok: bool,
    ) -> int | None:
        try:
            return os.open(
                name,
                _DIRECTORY_OPEN_FLAGS,
                dir_fd=parent_descriptor,
            )
        except FileNotFoundError:
            if missing_ok:
                return None
            raise

    def _ensure_private_directory(self, directory: Path) -> None:
        self._root.mkdir(parents=True, exist_ok=True, mode=0o700)
        os.chmod(self._root, 0o700)
        visual_risk = self._root / "visual-risk"
        visual_risk.mkdir(exist_ok=True, mode=0o700)
        os.chmod(visual_risk, 0o700)
        directory.mkdir(exist_ok=True, mode=0o700)
        os.chmod(directory, 0o700)
