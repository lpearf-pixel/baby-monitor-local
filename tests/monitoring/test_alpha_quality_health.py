from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from packages.monitoring.alpha_quality import (
    check_hd_health,
    check_source_health,
    jpeg_dimensions,
)


def jpeg(width: int, height: int) -> bytes:
    return (
        b"\xff\xd8"
        b"\xff\xc0"
        b"\x00\x11"
        b"\x08"
        + height.to_bytes(2, "big")
        + width.to_bytes(2, "big")
        + b"\x03\x01\x11\x00\x02\x11\x00\x03\x11\x00"
        + b"\xff\xd9"
    )


@dataclass
class FakeResponse:
    payload: bytes

    def __enter__(self) -> "FakeResponse":
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def read(self, size: int = -1) -> bytes:
        if size < 0:
            return self.payload
        return self.payload[:size]


class FakeOpener:
    def __init__(self) -> None:
        self.responses: dict[str, list[bytes]] = {}
        self.calls: list[str] = []

    def add_json(self, url: str, payload: Any) -> None:
        self.add_bytes(url, json.dumps(payload).encode("utf-8"))

    def add_bytes(self, url: str, payload: bytes) -> None:
        self.responses.setdefault(url, []).append(payload)

    def __call__(self, url: str, timeout: float) -> FakeResponse:
        assert timeout > 0
        self.calls.append(url)
        responses = self.responses[url]
        payload = responses.pop(0) if len(responses) > 1 else responses[0]
        return FakeResponse(payload)


def test_jpeg_dimensions_reads_sof0() -> None:
    assert jpeg_dimensions(jpeg(1280, 720)) == (1280, 720)


def test_health_rejects_configured_only_source() -> None:
    opener = FakeOpener()
    opener.add_json(
        "http://127.0.0.1:1984/api/streams",
        {"source": {"producers": [{"url": "xiaomi://must-not-leak"}]}},
    )
    opener.add_json(
        "http://127.0.0.1:1984/api/streams?src=source&video",
        {"producers": [{"url": "xiaomi://must-not-leak"}], "consumers": []},
    )

    result = check_hd_health(
        "http://127.0.0.1:1984",
        "http://127.0.0.1:8080",
        opener=opener,
    )

    assert result.code == "SOURCE_OFFLINE"
    assert result.protocol == ""
    assert "xiaomi://" not in repr(result)


def test_health_rejects_source_without_video_media() -> None:
    opener = FakeOpener()
    opener.add_json(
        "http://127.0.0.1:1984/api/streams",
        {"source": {"producers": [{"url": "xiaomi://must-not-leak"}]}},
    )
    opener.add_json(
        "http://127.0.0.1:1984/api/streams?src=source&video",
        {
            "producers": [
                {
                    "protocol": "cs2+udp",
                    "medias": ["audio, recvonly, OPUS/48000/2"],
                    "bytes_recv": 2000,
                }
            ],
            "consumers": [],
        },
    )

    result = check_hd_health(
        "http://127.0.0.1:1984",
        "http://127.0.0.1:8080",
        opener=opener,
    )

    assert result.code == "SOURCE_NO_VIDEO"


def test_health_activates_source_before_inspecting_producer() -> None:
    opener = working_opener(live_jpeg=jpeg(1280, 720))

    result = check_hd_health(
        "http://127.0.0.1:1984",
        "http://127.0.0.1:8080",
        opener=opener,
    )

    assert result.code == "PASS"
    assert opener.calls[:2] == [
        "http://127.0.0.1:1984/api/streams",
        "http://127.0.0.1:1984/api/streams?src=source&video",
    ]


def test_source_health_returns_only_derived_media_fields() -> None:
    opener = working_opener(live_jpeg=jpeg(1280, 720))

    result = check_source_health(
        "http://127.0.0.1:1984",
        opener=opener,
    )

    assert result.code == "PASS"
    assert result.protocol == "cs2+udp"
    assert result.bytes_received == 50000
    assert result.source_dimensions == (1280, 720)
    assert result.source_codec == "H265"
    assert result.live_dimensions is None
    assert "xiaomi://" not in repr(result)


def test_health_rejects_wrong_live_dimensions() -> None:
    opener = working_opener(live_jpeg=jpeg(960, 540))

    result = check_hd_health(
        "http://127.0.0.1:1984",
        "http://127.0.0.1:8080",
        opener=opener,
    )

    assert result.code == "LIVE_WRONG_DIMENSIONS"
    assert result.live_dimensions == (960, 540)


def test_health_accepts_real_hd_media() -> None:
    opener = working_opener(live_jpeg=jpeg(1280, 720))

    result = check_hd_health(
        "http://127.0.0.1:1984",
        "http://127.0.0.1:8080",
        opener=opener,
    )

    assert result.code == "PASS"
    assert result.protocol == "cs2+udp"
    assert result.bytes_received == 50000
    assert result.source_dimensions == (1280, 720)
    assert result.source_codec == "H265"
    assert result.live_dimensions == (1280, 720)


def test_source_health_normalizes_h264_without_copying_media_text() -> None:
    opener = working_opener(live_jpeg=jpeg(1280, 720))
    source_url = "http://127.0.0.1:1984/api/streams?src=source&video"
    opener.responses[source_url] = [
        json.dumps(
            {
                "producers": [
                    {
                        "protocol": "cs2+udp",
                        "medias": ["video, recvonly, H264, private-marker"],
                        "bytes_recv": 50000,
                        "url": "xiaomi://must-not-leak",
                    }
                ],
                "consumers": [],
            }
        ).encode("utf-8")
    ]

    result = check_source_health("http://127.0.0.1:1984", opener=opener)

    assert result.source_codec == "H264"
    assert "private-marker" not in repr(result)
    assert "xiaomi://" not in repr(result)


def test_health_reconnects_when_first_mjpeg_consumer_gets_eof() -> None:
    opener = working_opener(live_jpeg=jpeg(1280, 720))
    mjpeg_url = "http://127.0.0.1:1984/api/stream.mjpeg?src=live"
    opener.responses[mjpeg_url] = [
        b"",
        b"--frame\r\nContent-Type: image/jpeg\r\n\r\nJPEG",
    ]

    result = check_hd_health(
        "http://127.0.0.1:1984",
        "http://127.0.0.1:8080",
        opener=opener,
    )

    assert result.code == "PASS"
    assert opener.calls.count(mjpeg_url) == 2


def working_opener(*, live_jpeg: bytes) -> FakeOpener:
    opener = FakeOpener()
    opener.add_json(
        "http://127.0.0.1:1984/api/streams",
        {"source": {"producers": [{"url": "xiaomi://must-not-leak"}]}},
    )
    opener.add_json(
        "http://127.0.0.1:1984/api/streams?src=source&video",
        {
            "producers": [
                {
                    "protocol": "cs2+udp",
                    "medias": ["video, recvonly, H265"],
                    "bytes_recv": 50000,
                    "url": "xiaomi://must-not-leak",
                }
            ],
            "consumers": [],
        },
    )
    opener.add_bytes(
        "http://127.0.0.1:1984/api/frame.jpeg?src=source",
        jpeg(1280, 720),
    )
    opener.add_bytes(
        "http://127.0.0.1:1984/api/frame.jpeg?src=live",
        live_jpeg,
    )
    opener.add_bytes(
        "http://127.0.0.1:1984/api/stream.mjpeg?src=live",
        b"--frame\r\nContent-Type: image/jpeg\r\n\r\nJPEG",
    )
    opener.add_json("http://127.0.0.1:8080/healthz", {"status": "ok"})
    return opener
