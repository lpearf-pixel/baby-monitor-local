from __future__ import annotations

import hashlib
import os
from contextlib import AbstractContextManager
from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO, Callable, Protocol
from urllib.parse import urlsplit
from urllib.request import ProxyHandler, Request, build_opener

from packages.contracts.visual_corpus import DownloadMethod, VisualCorpusSource
from services.vision.corpus_storage import (
    CorpusLayout,
    CorpusStorageError,
    PrivateTemporaryFile,
    sha256_file,
)


MAX_SOURCE_BYTES = 128 * 1024 * 1024
MAX_FIRST_STAGE_BYTES = 256 * 1024 * 1024
DOWNLOAD_TIMEOUT_SECONDS = 30.0
DOWNLOAD_CHUNK_BYTES = 1024 * 1024
USER_AGENT = "baby-monitor-local-visual-corpus/1"


class DownloadResponse(Protocol):
    status: int
    headers: object

    def read(self, size: int = -1) -> bytes: ...

    def geturl(self) -> str: ...

    def __enter__(self) -> BinaryIO: ...

    def __exit__(self, *args: object) -> None: ...


DownloadOpener = Callable[[Request, float], AbstractContextManager[BinaryIO]]


class CorpusDownloadError(RuntimeError):
    """A stable, redacted download failure."""


@dataclass(frozen=True)
class DownloadedSource:
    path: Path
    sha256: str
    byte_count: int
    reused: bool


def _default_opener(
    request: Request,
    timeout: float,
) -> AbstractContextManager[BinaryIO]:
    return build_opener(ProxyHandler({})).open(request, timeout=timeout)  # type: ignore[return-value]


class CorpusDownloader:
    def __init__(
        self,
        *,
        layout: CorpusLayout,
        opener: DownloadOpener = _default_opener,
        max_source_bytes: int = MAX_SOURCE_BYTES,
    ) -> None:
        if not 0 < max_source_bytes <= MAX_SOURCE_BYTES:
            raise ValueError("max_source_bytes is outside the fixed bound")
        self._layout = layout
        self._opener = opener
        self._max_source_bytes = max_source_bytes

    def fetch_all(
        self,
        sources: tuple[VisualCorpusSource, ...],
    ) -> tuple[DownloadedSource, ...]:
        expected_sizes: list[int] = []
        for source in sources:
            if (
                source.download_method is not DownloadMethod.DIRECT_HTTPS
                or source.expected_bytes is None
            ):
                raise CorpusDownloadError("visual_corpus_source_unavailable")
            expected_sizes.append(source.expected_bytes)
        if sum(expected_sizes) > MAX_FIRST_STAGE_BYTES:
            raise CorpusDownloadError("visual_corpus_download_total_too_large")
        return tuple(self.fetch(source) for source in sources)

    def fetch(self, source: VisualCorpusSource) -> DownloadedSource:
        if (
            source.download_method is not DownloadMethod.DIRECT_HTTPS
            or source.expected_sha256 is None
            or source.expected_bytes is None
        ):
            raise CorpusDownloadError("visual_corpus_source_unavailable")
        if source.expected_bytes > self._max_source_bytes:
            raise CorpusDownloadError("visual_corpus_download_too_large")
        final = self._layout.downloads / f"{source.source_id}.source"
        if final.exists():
            try:
                digest, byte_count = sha256_file(
                    final,
                    max_bytes=self._max_source_bytes,
                )
            except CorpusStorageError as exc:
                raise CorpusDownloadError("visual_corpus_existing_invalid") from exc
            if digest != source.expected_sha256 or byte_count != source.expected_bytes:
                raise CorpusDownloadError("visual_corpus_checksum_mismatch")
            return DownloadedSource(
                path=final,
                sha256=digest,
                byte_count=byte_count,
                reused=True,
            )

        temporary = self._layout.new_temporary_file(prefix="download")
        try:
            digest, byte_count = self._download(source, temporary)
            if digest != source.expected_sha256 or byte_count != source.expected_bytes:
                raise CorpusDownloadError("visual_corpus_checksum_mismatch")
            self._layout.publish_no_replace(temporary, final)
            return DownloadedSource(
                path=final,
                sha256=digest,
                byte_count=byte_count,
                reused=False,
            )
        except CorpusDownloadError:
            raise
        except CorpusStorageError as exc:
            raise CorpusDownloadError("visual_corpus_publish_failed") from exc
        finally:
            temporary.close()

    def _download(
        self,
        source: VisualCorpusSource,
        temporary: PrivateTemporaryFile,
    ) -> tuple[str, int]:
        request = Request(source.source_url, headers={"User-Agent": USER_AGENT})
        try:
            context = self._opener(request, DOWNLOAD_TIMEOUT_SECONDS)
            with context as raw_response:
                response = raw_response  # type: ignore[assignment]
                if getattr(response, "status", None) != 200:
                    raise CorpusDownloadError("visual_corpus_download_failed")
                self._require_safe_final_url(source.source_url, response.geturl())
                declared = self._content_length(getattr(response, "headers", None))
                if declared is not None and declared > self._max_source_bytes:
                    raise CorpusDownloadError("visual_corpus_download_too_large")
                digest = hashlib.sha256()
                total = 0
                while True:
                    chunk = response.read(DOWNLOAD_CHUNK_BYTES)
                    if not chunk:
                        break
                    total += len(chunk)
                    if total > self._max_source_bytes:
                        raise CorpusDownloadError("visual_corpus_download_too_large")
                    _write_all(temporary.descriptor, chunk)
                    digest.update(chunk)
                if declared is not None and total != declared:
                    raise CorpusDownloadError("visual_corpus_download_failed")
                os.fsync(temporary.descriptor)
                return digest.hexdigest(), total
        except CorpusDownloadError:
            raise
        except (OSError, TimeoutError, ValueError) as exc:
            raise CorpusDownloadError("visual_corpus_download_failed") from exc

    @staticmethod
    def _require_safe_final_url(requested: str, final: str) -> None:
        requested_url = urlsplit(requested)
        final_url = urlsplit(final)
        if (
            final_url.scheme != "https"
            or final_url.hostname != requested_url.hostname
            or final_url.username is not None
            or final_url.password is not None
            or final_url.fragment
        ):
            raise CorpusDownloadError("visual_corpus_redirect_unsafe")

    @staticmethod
    def _content_length(headers: object) -> int | None:
        if headers is None or not hasattr(headers, "get"):
            return None
        raw_value = headers.get("Content-Length")  # type: ignore[attr-defined]
        if raw_value in {None, ""}:
            return None
        try:
            value = int(raw_value)
        except (TypeError, ValueError) as exc:
            raise CorpusDownloadError("visual_corpus_download_failed") from exc
        if value < 0:
            raise CorpusDownloadError("visual_corpus_download_failed")
        return value


def _write_all(descriptor: int, payload: bytes) -> None:
    view = memoryview(payload)
    while view:
        written = os.write(descriptor, view)
        if written <= 0:
            raise OSError("write failed")
        view = view[written:]
