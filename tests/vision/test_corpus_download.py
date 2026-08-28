from __future__ import annotations

import hashlib
import importlib
from contextlib import AbstractContextManager
from pathlib import Path
from typing import BinaryIO
from urllib.request import Request

import pytest

from packages.contracts.visual_corpus import VisualCorpusSource


def download_module():
    return importlib.import_module("services.vision.corpus_download")


def storage_module():
    return importlib.import_module("services.vision.corpus_storage")


class Response(AbstractContextManager[BinaryIO]):
    def __init__(
        self,
        payload: bytes,
        *,
        status: int = 200,
        url: str = "https://upload.wikimedia.org/example.webm",
    ) -> None:
        from io import BytesIO

        self._stream = BytesIO(payload)
        self.status = status
        self._url = url
        self.headers = {"Content-Length": str(len(payload))}

    def __enter__(self) -> "Response":
        return self

    def __exit__(self, *args: object) -> None:
        self._stream.close()

    def read(self, size: int = -1) -> bytes:
        return self._stream.read(size)

    def geturl(self) -> str:
        return self._url


class RecordingOpener:
    def __init__(self, response: Response) -> None:
        self.response = response
        self.calls: list[tuple[Request, float]] = []

    def __call__(self, request: Request, timeout: float) -> Response:
        self.calls.append((request, timeout))
        return self.response


def source(payload: bytes, **overrides: object) -> VisualCorpusSource:
    values: dict[str, object] = {
        "source_id": "public-source",
        "name": "Public source",
        "source_url": "https://upload.wikimedia.org/example.webm",
        "project_or_paper": "Wikimedia Commons",
        "license": "public-domain",
        "download_method": "DIRECT_HTTPS",
        "research_use_allowed": True,
        "commercial_use": "ALLOWED",
        "redistribution_allowed": True,
        "github_allowed": False,
        "privacy_notes": "released public media",
        "local_only": True,
        "expected_sha256": hashlib.sha256(payload).hexdigest(),
        "expected_bytes": len(payload),
    }
    values.update(overrides)
    return VisualCorpusSource.model_validate(values)


def layout(tmp_path: Path):
    repo = tmp_path / "repo"
    repo.mkdir()
    return storage_module().CorpusLayout.for_repository(repo)


def test_download_streams_verifies_and_publishes_private_file(tmp_path: Path) -> None:
    module = download_module()
    payload = b"public-video"
    opener = RecordingOpener(Response(payload))
    corpus_layout = layout(tmp_path)

    downloaded = module.CorpusDownloader(
        layout=corpus_layout,
        opener=opener,
    ).fetch(source(payload))

    assert downloaded.path == corpus_layout.downloads / "public-source.source"
    assert downloaded.sha256 == hashlib.sha256(payload).hexdigest()
    assert downloaded.byte_count == len(payload)
    assert downloaded.reused is False
    assert downloaded.path.read_bytes() == payload
    assert downloaded.path.stat().st_mode & 0o777 == 0o600
    request, timeout = opener.calls[0]
    assert request.full_url == "https://upload.wikimedia.org/example.webm"
    assert request.headers["User-agent"] == "baby-monitor-local-visual-corpus/1"
    assert timeout == 30.0


def test_valid_existing_download_is_reused_without_network(tmp_path: Path) -> None:
    module = download_module()
    payload = b"public-video"
    corpus_layout = layout(tmp_path)
    final = corpus_layout.downloads / "public-source.source"
    final.write_bytes(payload)
    final.chmod(0o600)

    def no_network(_request: Request, _timeout: float) -> Response:
        raise AssertionError("network must not be used")

    downloaded = module.CorpusDownloader(
        layout=corpus_layout,
        opener=no_network,
    ).fetch(source(payload))

    assert downloaded.reused is True
    assert downloaded.path == final


def test_checksum_mismatch_never_publishes_final(tmp_path: Path) -> None:
    module = download_module()
    corpus_layout = layout(tmp_path)
    opener = RecordingOpener(Response(b"wrong"))

    with pytest.raises(
        module.CorpusDownloadError,
        match="^visual_corpus_checksum_mismatch$",
    ):
        module.CorpusDownloader(layout=corpus_layout, opener=opener).fetch(
            source(b"right")
        )

    assert list(corpus_layout.downloads.iterdir()) == []


def test_oversized_response_stops_without_publishing(tmp_path: Path) -> None:
    module = download_module()
    corpus_layout = layout(tmp_path)
    payload = b"123456"
    opener = RecordingOpener(Response(payload))

    with pytest.raises(
        module.CorpusDownloadError,
        match="^visual_corpus_download_too_large$",
    ):
        module.CorpusDownloader(
            layout=corpus_layout,
            opener=opener,
            max_source_bytes=5,
        ).fetch(source(payload))

    assert list(corpus_layout.downloads.iterdir()) == []


def test_first_stage_aggregate_limit_fails_before_network(tmp_path: Path) -> None:
    module = download_module()
    calls = 0

    def no_network(_request: Request, _timeout: float) -> Response:
        nonlocal calls
        calls += 1
        raise AssertionError("aggregate admission must run before network")

    first = source(
        b"first",
        source_id="public-first",
        expected_bytes=128 * 1024 * 1024,
    )
    second = source(
        b"second",
        source_id="public-second",
        expected_bytes=128 * 1024 * 1024,
    )
    third = source(
        b"third",
        source_id="public-third",
        expected_bytes=1,
    )

    with pytest.raises(
        module.CorpusDownloadError,
        match="^visual_corpus_download_total_too_large$",
    ):
        module.CorpusDownloader(layout=layout(tmp_path), opener=no_network).fetch_all(
            (first, second, third)
        )

    assert calls == 0


@pytest.mark.parametrize(
    ("status", "url", "reason"),
    [
        (404, "https://upload.wikimedia.org/example.webm", "visual_corpus_download_failed"),
        (200, "http://upload.wikimedia.org/example.webm", "visual_corpus_redirect_unsafe"),
        (200, "https://unrelated.example/example.webm", "visual_corpus_redirect_unsafe"),
    ],
)
def test_response_and_redirect_fail_closed(
    tmp_path: Path,
    status: int,
    url: str,
    reason: str,
) -> None:
    module = download_module()
    payload = b"public-video"
    opener = RecordingOpener(Response(payload, status=status, url=url))

    with pytest.raises(module.CorpusDownloadError, match=f"^{reason}$"):
        module.CorpusDownloader(layout=layout(tmp_path), opener=opener).fetch(
            source(payload)
        )
