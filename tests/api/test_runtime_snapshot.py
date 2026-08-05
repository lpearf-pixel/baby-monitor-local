from __future__ import annotations

from io import BytesIO

from PIL import Image
import pytest

from apps.api.alpha import SnapshotViewport
from apps.api.runtime import Go2RTCAlphaGateway, SnapshotFrameRejected


class ImageResponse:
    def __init__(self, payload: bytes) -> None:
        self._payload = payload
        self.read_sizes: list[int] = []

    def __enter__(self) -> "ImageResponse":
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def read(self, size: int = -1) -> bytes:
        self.read_sizes.append(size)
        return self._payload if size < 0 else self._payload[:size]


def jpeg_with_colored_halves() -> bytes:
    image = Image.new("RGB", (2560, 1440), "red")
    image.paste("blue", (1280, 0, 2560, 1440))
    output = BytesIO()
    image.save(output, format="JPEG", quality=95)
    return output.getvalue()


def jpeg_with_dimensions(width: int, height: int) -> bytes:
    image = Image.new("RGB", (width, height), "black")
    output = BytesIO()
    image.save(output, format="JPEG", quality=80)
    return output.getvalue()


def test_default_snapshot_preserves_the_live_stream_contract(monkeypatch) -> None:
    requested_urls: list[str] = []
    live_jpeg = b"existing-live-jpeg"

    def open_live(url: str, *, timeout: float) -> ImageResponse:
        requested_urls.append(url)
        assert timeout == 10.0
        return ImageResponse(live_jpeg)

    monkeypatch.setattr("apps.api.runtime.urlopen", open_live)
    gateway = Go2RTCAlphaGateway(
        base_url="http://127.0.0.1:1984",
        stream_name="live",
        ntfy_base_url="https://ntfy.sh",
        ntfy_topic="",
        ntfy_token=None,
    )

    payload = gateway.snapshot(SnapshotViewport())

    assert payload == live_jpeg
    assert requested_urls == [
        "http://127.0.0.1:1984/api/frame.jpeg?src=live"
    ]


def test_zoomed_snapshot_crops_the_native_source_viewport(monkeypatch) -> None:
    requested_urls: list[str] = []
    source_jpeg = jpeg_with_colored_halves()

    def open_source(url: str, *, timeout: float) -> ImageResponse:
        requested_urls.append(url)
        assert timeout == 10.0
        return ImageResponse(source_jpeg)

    monkeypatch.setattr("apps.api.runtime.urlopen", open_source)
    gateway = Go2RTCAlphaGateway(
        base_url="http://127.0.0.1:1984",
        stream_name="live",
        ntfy_base_url="https://ntfy.sh",
        ntfy_topic="",
        ntfy_token=None,
    )

    payload = gateway.snapshot(
        SnapshotViewport(zoom=2, center_x=0.25, center_y=0.5)
    )

    with Image.open(BytesIO(payload)) as cropped:
        assert cropped.size == (1280, 720)
        red, green, blue = cropped.getpixel((640, 360))
        assert red > 200
        assert green < 30
        assert blue < 30
    assert requested_urls == [
        "http://127.0.0.1:1984/api/frame.jpeg?src=source"
    ]


def test_snapshot_rejects_an_upstream_body_larger_than_sixteen_mib(
    monkeypatch,
) -> None:
    response = ImageResponse(b"x" * (16 * 1024 * 1024 + 1))
    monkeypatch.setattr("apps.api.runtime.urlopen", lambda *_args, **_kwargs: response)
    gateway = Go2RTCAlphaGateway(
        base_url="http://127.0.0.1:1984",
        stream_name="live",
        ntfy_base_url="https://ntfy.sh",
        ntfy_topic="",
        ntfy_token=None,
    )

    with pytest.raises(SnapshotFrameRejected):
        gateway.snapshot(SnapshotViewport(zoom=2))

    assert response.read_sizes == [16 * 1024 * 1024 + 1]


def test_zoomed_snapshot_rejects_dimensions_above_the_fixed_4k_envelope(
    monkeypatch,
) -> None:
    oversized_jpeg = jpeg_with_dimensions(4097, 1)
    monkeypatch.setattr(
        "apps.api.runtime.urlopen",
        lambda *_args, **_kwargs: ImageResponse(oversized_jpeg),
    )
    gateway = Go2RTCAlphaGateway(
        base_url="http://127.0.0.1:1984",
        stream_name="live",
        ntfy_base_url="https://ntfy.sh",
        ntfy_topic="",
        ntfy_token=None,
    )

    with pytest.raises(SnapshotFrameRejected):
        gateway.snapshot(SnapshotViewport(zoom=2))
