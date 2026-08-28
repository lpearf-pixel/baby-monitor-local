from __future__ import annotations

import hashlib
import os
import stat
import tempfile
from dataclasses import dataclass
from pathlib import Path


PRIVATE_DIRECTORY_MODE = 0o700
PRIVATE_FILE_MODE = 0o600
READ_CHUNK_BYTES = 1024 * 1024


class CorpusStorageError(RuntimeError):
    """A stable, redacted corpus-storage failure."""


@dataclass
class PrivateTemporaryFile:
    path: Path
    descriptor: int

    def close(self) -> None:
        if self.descriptor >= 0:
            os.close(self.descriptor)
            self.descriptor = -1


@dataclass(frozen=True)
class CorpusLayout:
    repository: Path
    root: Path
    downloads: Path
    prepared: Path
    results: Path
    temp: Path

    @classmethod
    def for_repository(cls, root: Path) -> "CorpusLayout":
        repository = Path(root).absolute()
        _require_owned_directory(repository, private=False)
        runtime = repository / "runtime"
        test_corpus = runtime / "test-corpus"
        visual = test_corpus / "visual"
        downloads = visual / "downloads"
        prepared = visual / "prepared"
        results = visual / "results"
        temporary = visual / "temp"
        for path, private in (
            (runtime, False),
            (test_corpus, True),
            (visual, True),
            (downloads, True),
            (prepared, True),
            (results, True),
            (temporary, True),
        ):
            _ensure_owned_directory(path, private=private)
        return cls(
            repository=repository,
            root=visual,
            downloads=downloads,
            prepared=prepared,
            results=results,
            temp=temporary,
        )

    def new_temporary_file(self, *, prefix: str) -> PrivateTemporaryFile:
        if not prefix or not prefix.replace("-", "").isalnum():
            raise CorpusStorageError("visual_corpus_storage_unsafe")
        descriptor, raw_path = tempfile.mkstemp(
            prefix=f".{prefix}-",
            dir=self.temp,
        )
        os.fchmod(descriptor, PRIVATE_FILE_MODE)
        return PrivateTemporaryFile(path=Path(raw_path), descriptor=descriptor)

    def publish_no_replace(
        self,
        temporary: PrivateTemporaryFile,
        final: Path,
    ) -> None:
        destination = Path(final)
        if destination.parent not in {
            self.downloads,
            self.prepared,
            self.results,
        } or destination.name in {"", ".", ".."}:
            raise CorpusStorageError("visual_corpus_storage_unsafe")
        if temporary.path.parent != self.temp or temporary.descriptor < 0:
            raise CorpusStorageError("visual_corpus_storage_unsafe")
        _require_open_private_file(temporary.descriptor)
        os.fsync(temporary.descriptor)
        try:
            os.link(temporary.path, destination, follow_symlinks=False)
        except FileExistsError as exc:
            raise CorpusStorageError("visual_corpus_artifact_exists") from exc
        except OSError as exc:
            raise CorpusStorageError("visual_corpus_publish_failed") from exc
        try:
            os.unlink(temporary.path)
            _fsync_directory(self.temp)
            _fsync_directory(destination.parent)
        except OSError as exc:
            raise CorpusStorageError("visual_corpus_publish_incomplete") from exc


def sha256_file(path: Path, *, max_bytes: int) -> tuple[str, int]:
    if max_bytes <= 0:
        raise ValueError("max_bytes must be positive")
    candidate = Path(path)
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(candidate, flags)
    except OSError as exc:
        raise CorpusStorageError("visual_corpus_artifact_unsafe") from exc
    try:
        before = os.fstat(descriptor)
        _validate_private_file_info(before)
        if before.st_size > max_bytes:
            raise CorpusStorageError("visual_corpus_artifact_too_large")
        digest = hashlib.sha256()
        total = 0
        while True:
            chunk = os.read(descriptor, min(READ_CHUNK_BYTES, max_bytes - total + 1))
            if not chunk:
                break
            total += len(chunk)
            if total > max_bytes:
                raise CorpusStorageError("visual_corpus_artifact_too_large")
            digest.update(chunk)
        after = os.fstat(descriptor)
        if (
            before.st_dev,
            before.st_ino,
            before.st_size,
            before.st_mtime_ns,
            before.st_ctime_ns,
        ) != (
            after.st_dev,
            after.st_ino,
            after.st_size,
            after.st_mtime_ns,
            after.st_ctime_ns,
        ) or total != after.st_size:
            raise CorpusStorageError("visual_corpus_artifact_changed")
        return digest.hexdigest(), total
    finally:
        os.close(descriptor)


def _ensure_owned_directory(path: Path, *, private: bool) -> None:
    try:
        path.mkdir(mode=PRIVATE_DIRECTORY_MODE, exist_ok=True)
    except OSError as exc:
        raise CorpusStorageError("visual_corpus_storage_unsafe") from exc
    _require_owned_directory(path, private=private)


def _require_owned_directory(path: Path, *, private: bool) -> None:
    try:
        info = path.lstat()
    except OSError as exc:
        raise CorpusStorageError("visual_corpus_storage_unsafe") from exc
    if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid():
        raise CorpusStorageError("visual_corpus_storage_unsafe")
    if private and stat.S_IMODE(info.st_mode) != PRIVATE_DIRECTORY_MODE:
        raise CorpusStorageError("visual_corpus_storage_unsafe")


def _require_open_private_file(descriptor: int) -> None:
    _validate_private_file_info(os.fstat(descriptor))


def _validate_private_file_info(info: os.stat_result) -> None:
    if (
        not stat.S_ISREG(info.st_mode)
        or info.st_uid != os.getuid()
        or info.st_nlink != 1
        or stat.S_IMODE(info.st_mode) != PRIVATE_FILE_MODE
    ):
        raise CorpusStorageError("visual_corpus_artifact_unsafe")


def _fsync_directory(path: Path) -> None:
    flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(path, flags)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
