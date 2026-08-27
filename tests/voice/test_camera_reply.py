from __future__ import annotations

import json
import os
import socket
import stat
import struct
import threading
from pathlib import Path
from urllib.parse import parse_qs, urlsplit
from urllib.request import Request

import pytest

from services.voice.camera_reply import (
    CameraReplyCode,
    CameraReplyEvidence,
    CameraReplyOutput,
    CameraPreferredVoiceOutput,
    CameraReplyResult,
    CameraReplyStatus,
    CameraReplyStatusWriter,
    FixedReplyRenderer,
    LoopbackCameraReplyTransport,
    RenderedReply,
    parse_source_media,
)


MAX_RESPONSE_BYTES = 1_048_576


def _aiff(frames: int = 8_000) -> bytes:
    sample_rate = b"\x40\x0c\xfa\x00\x00\x00\x00\x00\x00\x00"
    comm = struct.pack(">hIh", 1, frames, 16) + sample_rate
    sound = struct.pack(">II", 0, 0) + (b"\x00\x01" * frames)
    chunks = b"COMM" + struct.pack(">I", len(comm)) + comm
    chunks += b"SSND" + struct.pack(">I", len(sound)) + sound
    return b"FORM" + struct.pack(">I", 4 + len(chunks)) + b"AIFF" + chunks


def _stream_payload(
    *,
    medias: list[object] | None = None,
    speaker_state: str = "closed",
    generation: int = 2,
) -> bytes:
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
                    "speaker_state": speaker_state,
                    "speaker_session_generation": generation,
                    "speaker_start_requests": generation,
                    "speaker_start_responses": generation,
                    "speaker_stop_commands": generation - (speaker_state == "active"),
                    "speaker_write_failures": 0,
                    "speaker_stop_failures": 0,
                    "pending_command_responses": 0,
                    "residual_sender_count": int(speaker_state == "active"),
                    "last_failure_stage": "none",
                    "producer_generation": generation,
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
        speaker_state="closed",
        speaker_session_generation=2,
        speaker_start_requests=2,
        speaker_start_responses=2,
        speaker_stop_commands=2,
        speaker_write_failures=0,
        speaker_stop_failures=0,
        pending_command_responses=0,
        residual_sender_count=0,
        last_failure_stage="none",
        producer_generation=2,
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


def test_parser_requires_closed_lifecycle_evidence() -> None:
    document = json.loads(_stream_payload())
    producer = document["producers"][0]
    producer.pop("speaker_state")
    with pytest.raises(ValueError, match="^CAMERA_REPLY_UNAVAILABLE$"):
        parse_source_media(json.dumps(document).encode())

    for key, value in {
        "speaker_state": "active",
        "speaker_start_responses": 1,
        "speaker_stop_commands": 1,
        "speaker_write_failures": 1,
        "speaker_stop_failures": 1,
        "pending_command_responses": 1,
        "residual_sender_count": 1,
        "last_failure_stage": "audio_write",
        "producer_generation": 3,
    }.items():
        document = json.loads(_stream_payload())
        document["producers"][0][key] = value
        with pytest.raises(ValueError, match="^CAMERA_REPLY_UNAVAILABLE$"):
            parse_source_media(json.dumps(document).encode())


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
    start_response = FakeResponse(
        _stream_payload(speaker_state="active", generation=2)
    )
    stop_response = FakeResponse(_stream_payload())
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
    "payload",
    [b"", b"{}", _stream_payload(), _stream_payload(generation=0)],
)
def test_start_requires_a_nonzero_active_generation(
    tmp_path: Path, payload: bytes
) -> None:
    response = FakeResponse(payload)
    transport = LoopbackCameraReplyTransport(
        tmp_path, opener=RecordingOpener([response])
    )

    assert transport.start(_media_file(tmp_path)) == CameraReplyResult(
        CameraReplyCode.AMBIGUOUS, True
    )


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
            return FakeResponse(
                _stream_payload(speaker_state="active", generation=2)
            )

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
    success = FakeResponse(_stream_payload(generation=2))
    opener = RecordingOpener(
        [
            FakeResponse(_stream_payload(speaker_state="active", generation=2)),
            socket.timeout("private-marker"),
            success,
        ]
    )
    transport = LoopbackCameraReplyTransport(tmp_path, opener=opener)

    assert transport.start(_media_file(tmp_path)).code is CameraReplyCode.READY
    assert transport.stop() == CameraReplyResult(
        CameraReplyCode.AMBIGUOUS, False
    )
    assert transport.stop() == CameraReplyResult(
        CameraReplyCode.COMPLETE, False
    )
    assert len(opener.calls) == 3
    assert success.closed is True


@pytest.mark.parametrize(
    "payload",
    [
        b"",
        b"{}",
        b"not-json",
        _stream_payload(),
        _stream_payload().replace(b'"closed"', b'"active"'),
    ],
)
def test_stop_never_completes_without_closed_lifecycle_evidence(
    tmp_path: Path, payload: bytes
) -> None:
    response = FakeResponse(payload)
    transport = LoopbackCameraReplyTransport(
        tmp_path, opener=RecordingOpener([response])
    )

    assert transport.stop() == CameraReplyResult(
        CameraReplyCode.AMBIGUOUS, False
    )
    assert response.closed is True


@pytest.mark.parametrize(
    "stop_payload",
    [
        _stream_payload(generation=0),
        _stream_payload(generation=1),
        _stream_payload(generation=3),
    ],
)
def test_stop_requires_the_generation_owned_by_this_start(
    tmp_path: Path, stop_payload: bytes
) -> None:
    media = _media_file(tmp_path)
    opener = RecordingOpener(
        [
            FakeResponse(_stream_payload(speaker_state="active", generation=2)),
            FakeResponse(stop_payload),
        ]
    )
    transport = LoopbackCameraReplyTransport(tmp_path, opener=opener)

    assert transport.start(media).code is CameraReplyCode.READY
    assert transport.stop() == CameraReplyResult(
        CameraReplyCode.AMBIGUOUS, False
    )


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


class RenderingRunner:
    def __init__(self, writer=None, *, outcome: bool = True) -> None:
        self.writer = writer or (lambda path: path.write_bytes(_aiff()))
        self.outcome = outcome
        self.calls: list[tuple[tuple[str, ...], bytes | None, float]] = []

    def run(self, command, *, input_bytes, timeout_seconds, cancelled) -> bool:
        command = tuple(command)
        self.calls.append((command, input_bytes, timeout_seconds))
        output = Path(command[command.index("-o") + 1])
        self.writer(output)
        return self.outcome and not cancelled.is_set()


@pytest.mark.parametrize(
    ("code", "phrase"),
    [
        ("listen_only_ready", "我在，请说。"),
        ("listen_only_received", "我听到了。"),
    ],
)
def test_renderer_generates_only_fixed_linear_pcm_aiff(
    tmp_path: Path, code: str, phrase: str
) -> None:
    tmp_path.chmod(0o700)
    runner = RenderingRunner()
    renderer = FixedReplyRenderer(runner=runner, temporary_root=tmp_path)

    rendered = renderer.render(code, threading.Event())

    assert rendered is not None
    assert rendered.temporary_root == tmp_path.resolve()
    assert rendered.duration_seconds == 0.5
    assert rendered.path.parent == tmp_path.resolve()
    assert stat.S_IMODE(rendered.path.stat().st_mode) == 0o600
    command, input_bytes, timeout = runner.calls[0]
    assert command == (
        "/usr/bin/say",
        "-v",
        "Tingting",
        "-r",
        "180",
        "-f",
        "-",
        "-o",
        str(rendered.path),
        "--file-format=AIFF",
        "--data-format=BEI16@16000",
        "--channels=1",
    )
    assert input_bytes == phrase.encode("utf-8")
    assert timeout == 10.0
    rendered.path.unlink()


def test_renderer_rejects_non_camera_code_before_file_or_subprocess(
    tmp_path: Path,
) -> None:
    runner = RenderingRunner()
    renderer = FixedReplyRenderer(runner=runner, temporary_root=tmp_path)

    assert renderer.render("saved", threading.Event()) is None
    assert runner.calls == []
    assert list(tmp_path.iterdir()) == []


def test_renderer_redacts_unexpected_runner_failure_and_cleans_file(
    tmp_path: Path,
) -> None:
    class RaisingRunner:
        def run(self, command, **kwargs):
            raise KeyError("private-marker")

    renderer = FixedReplyRenderer(
        runner=RaisingRunner(), temporary_root=tmp_path
    )

    assert renderer.render("listen_only_ready", threading.Event()) is None
    assert list(tmp_path.iterdir()) == []


@pytest.mark.parametrize(
    "kind",
    [
        "malformed",
        "mode",
        "hardlink",
        "duration",
        "symlink",
        "fifo",
        "oversized",
    ],
)
def test_renderer_rejects_invalid_generated_aiff(tmp_path: Path, kind: str) -> None:
    def writer(path: Path) -> None:
        if kind == "malformed":
            path.write_bytes(b"not-aiff")
        elif kind == "oversized":
            path.write_bytes(b"x" * (MAX_RESPONSE_BYTES + 1))
        else:
            frames = 72_000 if kind == "duration" else 8_000
            path.write_bytes(_aiff(frames))
        if kind == "mode":
            path.chmod(0o644)
        if kind == "hardlink":
            os.link(path, path.with_suffix(".link"))
        if kind == "symlink":
            target = path.with_suffix(".target")
            target.write_bytes(_aiff())
            path.unlink()
            path.symlink_to(target)
        if kind == "fifo":
            path.unlink()
            os.mkfifo(path)

    runner = RenderingRunner(writer)
    renderer = FixedReplyRenderer(runner=runner, temporary_root=tmp_path)

    assert renderer.render("listen_only_ready", threading.Event()) is None
    assert not any(path.name.endswith(".aiff") for path in tmp_path.iterdir())


def test_renderer_rejects_wrong_owner_without_reading_generated_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    runner = RenderingRunner()
    renderer = FixedReplyRenderer(runner=runner, temporary_root=tmp_path)
    real_stat = os.stat

    def wrong_file_owner(
        path: os.PathLike[str] | str, *args: object, **kwargs: object
    ) -> os.stat_result:
        current = real_stat(path, *args, **kwargs)
        if Path(path).name.startswith("voice-camera-reply-"):
            values = list(current)
            values[stat.ST_UID] = current.st_uid + 1
            return os.stat_result(values)
        return current

    monkeypatch.setattr("services.voice.tts.os.stat", wrong_file_owner)

    assert renderer.render("listen_only_ready", threading.Event()) is None
    assert not any(path.name.endswith(".aiff") for path in tmp_path.iterdir())


def _ready_evidence() -> CameraReplyEvidence:
    return CameraReplyEvidence(
        source_ready=True,
        video_ready=True,
        incoming_audio_ready=True,
        sendonly_audio_ready=True,
        protocol="cs2+udp",
        video_codec="HEVC",
        incoming_audio_codec="OPUS",
        sendonly_audio_codec="OPUS",
    )


class OutputTransport:
    def __init__(
        self,
        events: list[str],
        *,
        evidence: CameraReplyEvidence | None = None,
        start_result: CameraReplyResult | None = None,
        stop_result: CameraReplyResult | None = None,
    ) -> None:
        self.events = events
        self.evidence = evidence if evidence is not None else _ready_evidence()
        self.start_result = start_result or CameraReplyResult(
            CameraReplyCode.READY, True
        )
        self.stop_result = stop_result or CameraReplyResult(
            CameraReplyCode.COMPLETE, False
        )

    def inspect(self) -> CameraReplyEvidence | None:
        self.events.append("inspect")
        return self.evidence

    def start(self, media: Path) -> CameraReplyResult:
        self.events.append("start")
        assert media.exists()
        return self.start_result

    def stop(self) -> CameraReplyResult:
        self.events.append("stop")
        return self.stop_result


class OutputRenderer:
    def __init__(self, events: list[str], rendered: RenderedReply | None) -> None:
        self.events = events
        self.rendered = rendered

    def render(self, code: str, cancelled: threading.Event) -> RenderedReply | None:
        self.events.append("render")
        return None if cancelled.is_set() else self.rendered


class OutputDucker:
    def __init__(self, events: list[str]) -> None:
        self.events = events

    def pause(self) -> None:
        self.events.append("pause")

    def resume(self) -> None:
        self.events.append("resume")


class OutputStatusWriter:
    def __init__(self, events: list[str]) -> None:
        self.events = events
        self.statuses: list[CameraReplyStatus] = []

    def write(self, status: CameraReplyStatus) -> None:
        self.events.append("status")
        self.statuses.append(status)


class OutputClock:
    def __init__(self, events: list[str], media: Path) -> None:
        self.events = events
        self.media = media
        self.value = 100.0
        self.sleeps: list[float] = []

    def monotonic(self) -> float:
        return self.value

    def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.value += seconds
        if seconds <= 0.05:
            self.events.append("wait")
            assert self.media.exists()
        else:
            self.events.append("guard")
            assert not self.media.exists()


def test_camera_output_closes_success_lifecycle_before_resuming_capture(
    tmp_path: Path,
) -> None:
    media = _media_file(tmp_path)
    rendered = RenderedReply(media, 0.10, tmp_path.resolve())
    events: list[str] = []
    clock = OutputClock(events, media)
    status_writer = OutputStatusWriter(events)
    output = CameraReplyOutput(
        transport=OutputTransport(events),
        renderer=OutputRenderer(events, rendered),
        ducker=OutputDucker(events),
        status_writer=status_writer,
        monotonic=clock.monotonic,
        sleep=clock.sleep,
        post_playback_guard_seconds=0.5,
    )

    result = output.deliver_code("listen_only_ready", threading.Event())

    assert result == CameraReplyResult(CameraReplyCode.COMPLETE, True)
    assert events == [
        "pause",
        "inspect",
        "render",
        "start",
        "wait",
        "wait",
        "stop",
        "guard",
        "resume",
        "status",
    ]
    assert max(clock.sleeps[:-1]) <= 0.05
    assert output.speak_code("private-code", threading.Event()) is False
    assert status_writer.statuses[0].completed_count == 1
    assert status_writer.statuses[0].failed_count == 0


@pytest.mark.parametrize(
    ("start_result", "stop_result", "expected"),
    [
        (
            CameraReplyResult(CameraReplyCode.REJECTED, False),
            CameraReplyResult(CameraReplyCode.COMPLETE, False),
            CameraReplyCode.REJECTED,
        ),
        (
            CameraReplyResult(CameraReplyCode.AMBIGUOUS, True),
            CameraReplyResult(CameraReplyCode.COMPLETE, False),
            CameraReplyCode.AMBIGUOUS,
        ),
        (
            CameraReplyResult(CameraReplyCode.READY, True),
            CameraReplyResult(CameraReplyCode.AMBIGUOUS, False),
            CameraReplyCode.AMBIGUOUS,
        ),
    ],
)
def test_camera_output_stops_exactly_every_started_send_and_unlinks(
    tmp_path: Path,
    start_result: CameraReplyResult,
    stop_result: CameraReplyResult,
    expected: CameraReplyCode,
) -> None:
    media = _media_file(tmp_path)
    rendered = RenderedReply(media, 0.05, tmp_path.resolve())
    events: list[str] = []
    clock = OutputClock(events, media)
    output = CameraReplyOutput(
        transport=OutputTransport(
            events, start_result=start_result, stop_result=stop_result
        ),
        renderer=OutputRenderer(events, rendered),
        ducker=OutputDucker(events),
        monotonic=clock.monotonic,
        sleep=clock.sleep,
        post_playback_guard_seconds=0.0,
    )

    result = output.deliver_code("listen_only_received", threading.Event())

    assert result.code is expected
    assert events.count("stop") == int(start_result.delivery_started)
    assert not media.exists()
    assert events[-1] == "resume"


def test_camera_output_stops_and_unlinks_when_wait_boundary_raises(
    tmp_path: Path,
) -> None:
    media = _media_file(tmp_path)
    rendered = RenderedReply(media, 0.10, tmp_path.resolve())
    events: list[str] = []
    clock = OutputClock(events, media)

    def raising_sleep(seconds: float) -> None:
        clock.sleep(seconds)
        raise RuntimeError("private-marker")

    output = CameraReplyOutput(
        transport=OutputTransport(events),
        renderer=OutputRenderer(events, rendered),
        ducker=OutputDucker(events),
        monotonic=clock.monotonic,
        sleep=raising_sleep,
        post_playback_guard_seconds=0.0,
    )

    result = output.deliver_code("listen_only_ready", threading.Event())

    assert result == CameraReplyResult(CameraReplyCode.AMBIGUOUS, True)
    assert events.count("stop") == 1
    assert not media.exists()
    assert events[-1] == "resume"


def test_camera_output_releases_single_flight_when_capture_resume_raises(
    tmp_path: Path,
) -> None:
    events: list[str] = []

    class RaisingOnceDucker(OutputDucker):
        def __init__(self, output_events: list[str]) -> None:
            super().__init__(output_events)
            self.raise_once = True

        def resume(self) -> None:
            super().resume()
            if self.raise_once:
                self.raise_once = False
                raise RuntimeError("private-marker")

    ducker = RaisingOnceDucker(events)

    class FreshRenderer:
        def render(self, code: str, cancelled: threading.Event) -> RenderedReply:
            events.append("render")
            media = _media_file(tmp_path)
            return RenderedReply(media, 0.05, tmp_path.resolve())

    class AdvancingClock:
        value = 100.0

        def monotonic(self) -> float:
            return self.value

        def sleep(self, seconds: float) -> None:
            self.value += seconds

    clock = AdvancingClock()

    output = CameraReplyOutput(
        transport=OutputTransport(events),
        renderer=FreshRenderer(),
        ducker=ducker,
        monotonic=clock.monotonic,
        sleep=clock.sleep,
        post_playback_guard_seconds=0.0,
    )

    first = output.deliver_code("listen_only_ready", threading.Event())
    second = output.deliver_code("listen_only_ready", threading.Event())

    assert first == CameraReplyResult(CameraReplyCode.AMBIGUOUS, True)
    assert second.code is CameraReplyCode.COMPLETE


class SelectionCamera:
    def __init__(self, result: CameraReplyResult) -> None:
        self.result = result
        self.calls = 0

    def deliver_code(self, code: str, cancelled: threading.Event) -> CameraReplyResult:
        self.calls += 1
        return self.result


class SelectionFallback:
    def __init__(self, result: bool) -> None:
        self.result = result
        self.calls = 0

    def speak_code(self, code: str, cancelled: threading.Event) -> bool:
        self.calls += 1
        return self.result


@pytest.mark.parametrize(
    ("code", "started", "fallback_calls", "expected"),
    [
        (CameraReplyCode.DISABLED, False, 1, True),
        (CameraReplyCode.NOT_PROVEN, False, 1, True),
        (CameraReplyCode.UNAVAILABLE, False, 1, True),
        (CameraReplyCode.BUSY, False, 0, False),
        (CameraReplyCode.REJECTED, False, 0, False),
        (CameraReplyCode.TIMEOUT, True, 0, False),
        (CameraReplyCode.AMBIGUOUS, True, 0, False),
        (CameraReplyCode.COMPLETE, True, 0, True),
    ],
)
def test_camera_reply_fallback_policy_is_pre_send_only(
    code: CameraReplyCode,
    started: bool,
    fallback_calls: int,
    expected: bool,
) -> None:
    camera = SelectionCamera(CameraReplyResult(code, started))
    fallback = SelectionFallback(True)
    output = CameraPreferredVoiceOutput(camera, fallback)

    assert output.speak_code("listen_only_ready", threading.Event()) is expected
    assert camera.calls == 1
    assert fallback.calls == fallback_calls


def test_camera_reply_selection_cancellation_calls_neither_backend() -> None:
    camera = SelectionCamera(
        CameraReplyResult(CameraReplyCode.UNAVAILABLE, False)
    )
    fallback = SelectionFallback(True)
    output = CameraPreferredVoiceOutput(camera, fallback)
    cancelled = threading.Event()
    cancelled.set()

    assert output.speak_code("listen_only_ready", cancelled) is False
    assert camera.calls == 0
    assert fallback.calls == 0


def test_camera_reply_fallback_failure_is_not_retried() -> None:
    camera = SelectionCamera(
        CameraReplyResult(CameraReplyCode.NOT_PROVEN, False)
    )
    fallback = SelectionFallback(False)

    assert CameraPreferredVoiceOutput(camera, fallback).speak_code(
        "listen_only_received", threading.Event()
    ) is False
    assert fallback.calls == 1
