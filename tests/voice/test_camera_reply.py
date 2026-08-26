from __future__ import annotations

import json
import os
import socket
import stat
import threading
from pathlib import Path
from urllib.parse import parse_qs, urlsplit
from urllib.request import Request

import pytest

from services.voice.camera_reply import (
    CameraReplyCode,
    CameraReplyEvidence,
    CameraReplyResult,
    CameraReplyStatus,
    CameraReplyStatusWriter,
    LoopbackCameraReplyTransport,
    parse_source_media,
)


MAX_RESPONSE_BYTES = 1_048_576


def _stream_payload(*, medias: list[object] | None = None) -> bytes:
    if medias is None:
        medias = [
            "video, recvonly, H265",
            "audio, recvonly, OPUS/48000/2",
            "audio, sendonly, OPUS/48000/2",
        ]
    return json.dumps(
        {
            "producers": [
                {
                    "protocol": "cs2+udp",
                    "remote_addr": "private-marker",
                    "url": "xiaomi://private-marker",
                    "medias": medias,
                }
            ],
            "consumers": [],
        },
        separators=(",", ":"),
    ).encode("utf-8")


def _wrapped_stream_payload(**kwargs: object) -> bytes:
    return b'{"source":' + _stream_payload(**kwargs) + b"}"


def test_parser_returns_only_closed_readiness_evidence() -> None:
    expected = CameraReplyEvidence(
        source_ready=True,
        video_ready=True,
        incoming_audio_ready=True,
        sendonly_audio_ready=True,
        protocol="cs2+udp",
        video_codec="HEVC",
        incoming_audio_codec="OPUS",
        sendonly_audio_codec="OPUS",
    )

    assert parse_source_media(_stream_payload()) == expected
    assert parse_source_media(_wrapped_stream_payload()) == expected
    assert "private-marker" not in repr(expected)
    assert not hasattr(expected, "url")
    assert not hasattr(expected, "payload")


@pytest.mark.parametrize(
    "payload",
    [
        b"",
        b"[]",
        b"null",
        b"not-json",
        b'{"source":null}',
        b'{"other":{"producers":[],"consumers":[]}}',
        b'{"source":{},"other":{}}',
        b'{"source":{},"source":{}}',
        b'{"producers":{},"consumers":[]}',
        b'{"producers":[],"consumers":[]}',
        b'{"producers":[null],"consumers":[]}',
        b'{"producers":[{"protocol":1,"medias":[]}],"consumers":[]}',
        b'{"producers":[{"protocol":"cs2+tcp","medias":[]}],"consumers":[]}',
        b'{"producers":[{"protocol":"cs2+udp","medias":"x"}],"consumers":[]}',
        b'{"producers":[{"protocol":"cs2+udp","medias":[]}],"consumers":{}}',
    ],
)
def test_parser_rejects_malformed_or_non_source_shapes(payload: bytes) -> None:
    with pytest.raises(ValueError, match="^CAMERA_REPLY_UNAVAILABLE$"):
        parse_source_media(payload)


@pytest.mark.parametrize(
    "medias",
    [
        ["audio, recvonly, OPUS/48000/2", "audio, sendonly, OPUS/48000/2"],
        ["video, recvonly, H264", "audio, recvonly, OPUS/48000/2", "audio, sendonly, OPUS/48000/2"],
        ["video, recvonly, H265", "audio, sendonly, OPUS/48000/2"],
        ["video, recvonly, H265", "audio, recvonly, OPUS/48000/2"],
        ["video, recvonly, H265", "audio, recvonly, PCMA/8000", "audio, sendonly, PCMA/8000"],
        ["video, recvonly, H265", "audio, recvonly, OPUS/16000/1", "audio, sendonly, OPUS/16000/1"],
        ["video, recvonly, H265", "audio, recvonly, OPUS/48000/1", "audio, sendonly, OPUS/48000/1"],
        ["video, recvonly, H265", "audio, recvonly, UNKNOWN/48000/2", "audio, sendonly, UNKNOWN/48000/2"],
        ["video, recvonly, H265", "audio, recvonly, OPUS/48000/2", 1],
    ],
)
def test_parser_rejects_every_nonmatching_media_contract(medias: list[object]) -> None:
    with pytest.raises(ValueError, match="^CAMERA_REPLY_UNAVAILABLE$"):
        parse_source_media(_stream_payload(medias=medias))


def test_parser_enforces_one_megabyte_cap() -> None:
    with pytest.raises(ValueError, match="^CAMERA_REPLY_UNAVAILABLE$"):
        parse_source_media(b" " * (MAX_RESPONSE_BYTES + 1))


class FakeResponse:
    def __init__(self, payload: bytes = b"{}", *, status: int = 200) -> None:
        self.payload = payload
        self.status = status
        self.closed = False
        self.read_sizes: list[int] = []

    def read(self, size: int) -> bytes:
        self.read_sizes.append(size)
        payload, self.payload = self.payload[:size], self.payload[size:]
        return payload

    def close(self) -> None:
        self.closed = True


class RecordingOpener:
    def __init__(
        self,
        responses: list[FakeResponse | BaseException] | None = None,
    ) -> None:
        self.responses = responses or []
        self.calls: list[tuple[Request, float]] = []

    def open(self, request: Request, *, timeout: float) -> FakeResponse:
        self.calls.append((request, timeout))
        item = self.responses.pop(0)
        if isinstance(item, BaseException):
            raise item
        return item


class ChunkedResponse(FakeResponse):
    def __init__(self, chunks: list[bytes], *, status: int = 200) -> None:
        super().__init__(b"", status=status)
        self.chunks = chunks

    def read(self, size: int) -> bytes:
        self.read_sizes.append(size)
        if not self.chunks:
            return b""
        chunk = self.chunks[0][:size]
        self.chunks[0] = self.chunks[0][size:]
        if not self.chunks[0]:
            self.chunks.pop(0)
        return chunk


def _media_file(root: Path, name: str = "reply.aiff") -> Path:
    root.chmod(0o700)
    path = root / name
    path.write_bytes(b"synthetic-reply")
    path.chmod(0o600)
    return path


def test_inspect_uses_only_fixed_loopback_get_timeout_and_cap(tmp_path: Path) -> None:
    response = FakeResponse(_stream_payload())
    opener = RecordingOpener([response])
    transport = LoopbackCameraReplyTransport(tmp_path, opener=opener)

    assert transport.inspect().source_ready is True

    request, timeout = opener.calls[0]
    assert request.full_url == "http://127.0.0.1:1984/api/streams?src=source"
    assert request.get_method() == "GET"
    assert timeout == 2.0
    assert response.read_sizes == [
        MAX_RESPONSE_BYTES + 1,
        MAX_RESPONSE_BYTES + 1 - len(_stream_payload()),
    ]
    assert response.closed is True


def test_start_and_stop_use_only_fixed_percent_encoded_posts(tmp_path: Path) -> None:
    media = _media_file(tmp_path)
    start_response = FakeResponse(b"{}")
    stop_response = FakeResponse(b"{}")
    opener = RecordingOpener([start_response, stop_response])
    transport = LoopbackCameraReplyTransport(tmp_path, opener=opener)

    assert transport.start(media) == CameraReplyResult(
        CameraReplyCode.READY, True
    )
    assert transport.stop() == CameraReplyResult(
        CameraReplyCode.COMPLETE, False
    )

    start_request, start_timeout = opener.calls[0]
    start_url = urlsplit(start_request.full_url)
    assert start_request.get_method() == "POST"
    assert start_timeout == 2.0
    assert start_url.scheme == "http"
    assert start_url.netloc == "127.0.0.1:1984"
    assert start_url.path == "/api/streams"
    assert parse_qs(start_url.query, keep_blank_values=True) == {
        "dst": ["source"],
        "src": [f"ffmpeg:{media.resolve()}#audio=opus#input=file"],
    }
    stop_request, stop_timeout = opener.calls[1]
    assert stop_request.get_method() == "POST"
    assert stop_timeout == 2.0
    assert stop_request.full_url == (
        "http://127.0.0.1:1984/api/streams?dst=source&src="
    )
    assert start_response.closed is True
    assert stop_response.closed is True


@pytest.mark.parametrize(
    "origin",
    [
        "http://localhost:1984",
        "http://127.0.0.1:1985",
        "http://192.0.2.1:1984",
        "http://127.0.0.1:1984?src=other",
        "http://127.0.0.1:1984/#fragment",
    ],
)
def test_transport_rejects_every_nonfixed_origin(tmp_path: Path, origin: str) -> None:
    with pytest.raises(ValueError, match="^CAMERA_REPLY_UNAVAILABLE$"):
        LoopbackCameraReplyTransport(tmp_path, origin=origin)


def test_default_opener_explicitly_disables_environment_proxies(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    handlers: list[object] = []

    class NoNetworkOpener:
        def open(self, request: Request, *, timeout: float) -> FakeResponse:
            raise AssertionError("network must not be used by constructor")

    def build_opener(*items: object) -> NoNetworkOpener:
        handlers.extend(items)
        return NoNetworkOpener()

    monkeypatch.setattr("services.voice.camera_reply.build_opener", build_opener)
    monkeypatch.setenv("HTTP_PROXY", "http://private-marker.invalid")

    LoopbackCameraReplyTransport(tmp_path)

    assert len(handlers) == 1
    assert getattr(handlers[0], "proxies") == {}


@pytest.mark.parametrize("invalid_kind", ["outside", "symlink", "mode", "directory"])
def test_start_rejects_invalid_generated_media_without_http(
    tmp_path: Path, invalid_kind: str
) -> None:
    root = tmp_path / "owned"
    root.mkdir(mode=0o700)
    valid = _media_file(root)
    candidate = valid
    if invalid_kind == "outside":
        candidate = _media_file(tmp_path, "outside.aiff")
    elif invalid_kind == "symlink":
        candidate = root / "link.aiff"
        candidate.symlink_to(valid)
    elif invalid_kind == "mode":
        valid.chmod(0o644)
    else:
        candidate = root
    opener = RecordingOpener([])
    transport = LoopbackCameraReplyTransport(root, opener=opener)

    assert transport.start(candidate) == CameraReplyResult(
        CameraReplyCode.REJECTED, False
    )
    assert opener.calls == []


def test_start_rejects_oversized_or_nonowned_media_without_http(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    media = _media_file(tmp_path)
    media.write_bytes(b"x" * (MAX_RESPONSE_BYTES + 1))
    transport = LoopbackCameraReplyTransport(tmp_path, opener=RecordingOpener([]))
    assert transport.start(media).code is CameraReplyCode.REJECTED

    media.write_bytes(b"x")
    real_stat = os.stat

    def wrong_owner(path: os.PathLike[str] | str, *args: object, **kwargs: object) -> os.stat_result:
        current = real_stat(path, *args, **kwargs)
        values = list(current)
        values[stat.ST_UID] = current.st_uid + 1
        return os.stat_result(values)

    monkeypatch.setattr("services.voice.camera_reply.os.stat", wrong_owner)
    assert transport.start(media).code is CameraReplyCode.REJECTED


@pytest.mark.parametrize(
    "failure",
    [socket.timeout("private-marker"), RuntimeError("private-marker")],
)
def test_http_failures_are_redacted_and_never_retried(
    tmp_path: Path, failure: BaseException
) -> None:
    media = _media_file(tmp_path)
    opener = RecordingOpener([failure])
    transport = LoopbackCameraReplyTransport(tmp_path, opener=opener)

    result = transport.start(media)

    assert result == CameraReplyResult(CameraReplyCode.AMBIGUOUS, True)
    assert len(opener.calls) == 1
    assert "private-marker" not in repr(result)


def test_non_success_http_status_fails_closed_without_retry(tmp_path: Path) -> None:
    media = _media_file(tmp_path)
    response = FakeResponse(b"private-marker", status=500)
    opener = RecordingOpener([response])
    result = LoopbackCameraReplyTransport(tmp_path, opener=opener).start(media)

    assert result == CameraReplyResult(CameraReplyCode.AMBIGUOUS, True)
    assert len(opener.calls) == 1
    assert response.closed is True
    assert "private-marker" not in repr(result)


def test_chunked_response_cannot_bypass_total_response_cap(tmp_path: Path) -> None:
    media = _media_file(tmp_path)
    response = ChunkedResponse([b"x" * 600_000, b"y" * 600_000])
    opener = RecordingOpener([response])

    result = LoopbackCameraReplyTransport(tmp_path, opener=opener).start(media)

    assert result == CameraReplyResult(CameraReplyCode.AMBIGUOUS, True)
    assert response.closed is True
    assert len(opener.calls) == 1


def test_concurrent_request_is_busy_and_not_queued(tmp_path: Path) -> None:
    media = _media_file(tmp_path)
    entered = threading.Event()
    release = threading.Event()

    class BlockingOpener:
        def open(self, request: Request, *, timeout: float) -> FakeResponse:
            entered.set()
            assert release.wait(1.0)
            return FakeResponse()

    transport = LoopbackCameraReplyTransport(tmp_path, opener=BlockingOpener())
    outcomes: list[CameraReplyResult] = []
    worker = threading.Thread(target=lambda: outcomes.append(transport.start(media)))
    worker.start()
    assert entered.wait(1.0)

    assert transport.stop() == CameraReplyResult(CameraReplyCode.BUSY, False)

    release.set()
    worker.join(1.0)
    assert not worker.is_alive()
    assert outcomes == [CameraReplyResult(CameraReplyCode.READY, True)]


def test_stop_is_repeatable_and_releases_single_flight_after_failure(
    tmp_path: Path,
) -> None:
    success = FakeResponse()
    opener = RecordingOpener([socket.timeout("private-marker"), success])
    transport = LoopbackCameraReplyTransport(tmp_path, opener=opener)

    assert transport.stop() == CameraReplyResult(
        CameraReplyCode.AMBIGUOUS, False
    )
    assert transport.stop() == CameraReplyResult(
        CameraReplyCode.COMPLETE, False
    )
    assert len(opener.calls) == 2
    assert success.closed is True


def test_status_writer_atomically_publishes_only_bounded_fields(tmp_path: Path) -> None:
    status_path = tmp_path / "status" / "camera-reply.json"
    writer = CameraReplyStatusWriter(status_path, boundary=tmp_path)
    status = CameraReplyStatus(
        backend="camera",
        ready=True,
        last_code=CameraReplyCode.COMPLETE,
        completed_count=2,
        failed_count=1,
        latency_ms=125,
    )

    writer.write(status)

    assert json.loads(status_path.read_text(encoding="utf-8")) == {
        "backend": "camera",
        "completed_count": 2,
        "failed_count": 1,
        "last_code": "CAMERA_REPLY_COMPLETE",
        "latency_ms": 125,
        "ready": True,
    }
    assert stat.S_IMODE(status_path.stat().st_mode) == 0o600
    assert list(status_path.parent.iterdir()) == [status_path]
