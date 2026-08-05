from __future__ import annotations

import importlib
from contextlib import AbstractContextManager
from datetime import UTC, datetime
from io import BytesIO
from typing import BinaryIO

import pytest
from PIL import Image


def frame_source_module():
    return importlib.import_module("services.stream.frame_source")


def jpeg_frame(color: str = "red", *, size: tuple[int, int] = (64, 48)) -> bytes:
    output = BytesIO()
    Image.new("RGB", size, color).save(output, format="JPEG")
    return output.getvalue()


def mjpeg_payload(frames: list[bytes]) -> bytes:
    parts: list[bytes] = []
    for frame in frames:
        parts.extend(
            [
                b"--frame\r\n",
                b"Content-Type: image/jpeg\r\n",
                f"Content-Length: {len(frame)}\r\n\r\n".encode(),
                frame,
                b"\r\n",
            ]
        )
    parts.append(b"--frame--\r\n")
    return b"".join(parts)


class FakeResponse(BytesIO, AbstractContextManager[BinaryIO]):
    def __init__(self, payload: bytes) -> None:
        super().__init__(payload)
        self.headers = {
            "Content-Type": "multipart/x-mixed-replace; boundary=frame"
        }
        self.enter_count = 0
        self.exit_count = 0

    def __enter__(self) -> "FakeResponse":
        self.enter_count += 1
        return self

    def __exit__(self, *args: object) -> None:
        self.exit_count += 1
        self.close()


class RecordingOpener:
    def __init__(self, response: FakeResponse) -> None:
        self.response = response
        self.requests: list[tuple[str, float]] = []

    def __call__(self, request: object, timeout: float) -> FakeResponse:
        self.requests.append((request.full_url, timeout))  # type: ignore[attr-defined]
        return self.response


def test_one_burst_uses_one_continuous_mjpeg_response() -> None:
    module = frame_source_module()
    response = FakeResponse(
        mjpeg_payload(
            [jpeg_frame(color) for color in ["red", "blue", "green", "white", "black"]]
        )
    )
    opener = RecordingOpener(response)
    source = module.Go2RtcControlledFrameSource(opener=opener)

    burst = source.capture_burst(
        frame_count=5,
        interval_ms=0,
        timeout_seconds=8,
    )

    assert len(burst.frames) == 5
    assert response.enter_count == 1
    assert response.exit_count == 1
    assert opener.requests == [("http://127.0.0.1:1984/api/stream.mjpeg?src=source", 8)]
    assert all(frame.captured_at.tzinfo is UTC for frame in burst.frames)


@pytest.mark.parametrize(
    "base_url",
    [
        "http://0.0.0.0:1984",
        "http://192.168.1.8:1984",
        "https://example.test",
        "http://127.0.0.1:1984/path?src=attacker",
    ],
)
def test_source_rejects_non_loopback_or_unbounded_base_urls(base_url: str) -> None:
    module = frame_source_module()

    with pytest.raises(ValueError, match="loopback go2rtc"):
        module.Go2RtcControlledFrameSource(base_url=base_url)


def test_malformed_or_missing_content_length_fails_closed() -> None:
    module = frame_source_module()
    response = FakeResponse(
        b"--frame\r\nContent-Type: image/jpeg\r\n\r\n" + jpeg_frame()
    )
    source = module.Go2RtcControlledFrameSource(opener=RecordingOpener(response))

    with pytest.raises(module.FrameSourceUnavailable, match="malformed_mjpeg"):
        source.capture_burst(frame_count=1, interval_ms=0, timeout_seconds=8)


def test_non_jpeg_frame_fails_closed() -> None:
    module = frame_source_module()
    response = FakeResponse(mjpeg_payload([b"not-a-jpeg"]))
    source = module.Go2RtcControlledFrameSource(opener=RecordingOpener(response))

    with pytest.raises(module.FrameSourceUnavailable, match="frame_invalid"):
        source.capture_burst(frame_count=1, interval_ms=0, timeout_seconds=8)


def test_oversized_dimensions_fail_closed() -> None:
    module = frame_source_module()
    response = FakeResponse(mjpeg_payload([jpeg_frame(size=(4097, 1))]))
    source = module.Go2RtcControlledFrameSource(opener=RecordingOpener(response))

    with pytest.raises(module.FrameSourceUnavailable, match="frame_invalid"):
        source.capture_burst(frame_count=1, interval_ms=0, timeout_seconds=8)


def test_burst_rejects_more_than_five_frames_or_more_than_eight_seconds() -> None:
    module = frame_source_module()
    source = module.Go2RtcControlledFrameSource(
        opener=RecordingOpener(FakeResponse(b""))
    )

    with pytest.raises(ValueError, match="frame_count"):
        source.capture_burst(frame_count=6, interval_ms=0, timeout_seconds=8)
    with pytest.raises(ValueError, match="timeout_seconds"):
        source.capture_burst(frame_count=5, interval_ms=500, timeout_seconds=9)


def test_burst_deadline_stops_without_creating_a_second_connection() -> None:
    module = frame_source_module()
    response = FakeResponse(mjpeg_payload([jpeg_frame(), jpeg_frame("blue")]))
    opener = RecordingOpener(response)
    ticks = iter([0.0, 0.0, 9.0])
    source = module.Go2RtcControlledFrameSource(
        opener=opener,
        monotonic=lambda: next(ticks),
    )

    with pytest.raises(module.FrameSourceUnavailable, match="burst_timeout"):
        source.capture_burst(frame_count=2, interval_ms=0, timeout_seconds=8)

    assert len(opener.requests) == 1


def test_transport_details_are_replaced_by_stable_error_code() -> None:
    module = frame_source_module()

    def failing_opener(request: object, timeout: float) -> FakeResponse:
        raise OSError("credential at /private/family/camera")

    source = module.Go2RtcControlledFrameSource(opener=failing_opener)

    with pytest.raises(module.FrameSourceUnavailable) as failure:
        source.capture_burst(frame_count=1, interval_ms=0, timeout_seconds=8)

    assert str(failure.value) == "frame_source_unavailable"
    assert failure.value.__cause__ is not None
    assert "/private" not in str(failure.value)
