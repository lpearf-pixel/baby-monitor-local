from __future__ import annotations

import ipaddress
import time
from collections.abc import Callable
from contextlib import AbstractContextManager
from dataclasses import dataclass
from datetime import UTC, datetime
from io import BytesIO
from typing import BinaryIO, Iterator, Literal, Protocol
from urllib.parse import urlencode, urlsplit
from urllib.request import ProxyHandler, Request, build_opener

from PIL import Image, UnidentifiedImageError


MAX_FRAME_BYTES = 16 * 1024 * 1024
MAX_FRAME_WIDTH = 4096
MAX_FRAME_HEIGHT = 2160
MAX_FRAME_PIXELS = MAX_FRAME_WIDTH * MAX_FRAME_HEIGHT
MAX_BURST_FRAMES = 5
MAX_BURST_SECONDS = 8.0


class FrameSourceUnavailable(RuntimeError):
    """A stable, redacted frame-source failure."""


class ResponseContext(Protocol):
    headers: object

    def __enter__(self) -> BinaryIO: ...

    def __exit__(self, *args: object) -> None: ...


FrameOpener = Callable[[Request, float], AbstractContextManager[BinaryIO]]


@dataclass(frozen=True)
class CapturedFrame:
    jpeg: bytes
    captured_at: datetime
    width: int
    height: int


@dataclass(frozen=True)
class FrameBurst:
    frames: tuple[CapturedFrame, ...]


def _validate_jpeg(payload: bytes) -> tuple[int, int]:
    try:
        with Image.open(BytesIO(payload)) as image:
            width, height = image.size
            image.verify()
            if image.format != "JPEG":
                raise FrameSourceUnavailable("frame_invalid")
    except FrameSourceUnavailable:
        raise
    except (UnidentifiedImageError, OSError, ValueError) as exc:
        raise FrameSourceUnavailable("frame_invalid") from exc
    if (
        width > MAX_FRAME_WIDTH
        or height > MAX_FRAME_HEIGHT
        or width * height > MAX_FRAME_PIXELS
    ):
        raise FrameSourceUnavailable("frame_invalid")
    return width, height


def _default_opener(request: Request, timeout: float) -> AbstractContextManager[BinaryIO]:
    opener = build_opener(ProxyHandler({}))
    return opener.open(request, timeout=timeout)  # type: ignore[return-value]


class Go2RtcControlledFrameSource:
    """Captures a bounded burst from the fixed local go2rtc `gauge` stream."""

    def __init__(
        self,
        *,
        base_url: str = "http://127.0.0.1:1984",
        opener: FrameOpener = _default_opener,
        monotonic: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        self._base_url = self._validate_base_url(base_url)
        self._opener = opener
        self._monotonic = monotonic
        self._sleep = sleep
        self._now = now or (lambda: datetime.now(UTC))

    @staticmethod
    def _validate_base_url(value: str) -> str:
        parsed = urlsplit(value)
        valid_path = parsed.path in {"", "/"}
        if (
            parsed.scheme != "http"
            or not parsed.hostname
            or parsed.username is not None
            or parsed.password is not None
            or parsed.query
            or parsed.fragment
            or not valid_path
        ):
            raise ValueError("base_url must identify the loopback go2rtc origin")
        if parsed.hostname != "localhost":
            try:
                address = ipaddress.ip_address(parsed.hostname)
            except ValueError as exc:
                raise ValueError(
                    "base_url must identify the loopback go2rtc origin"
                ) from exc
            if not address.is_loopback:
                raise ValueError("base_url must identify the loopback go2rtc origin")
        if parsed.port is None:
            raise ValueError("base_url must identify the loopback go2rtc origin")
        return value.rstrip("/")

    def capture_burst(
        self,
        *,
        frame_count: int,
        interval_ms: int,
        timeout_seconds: float,
    ) -> FrameBurst:
        if not 1 <= frame_count <= MAX_BURST_FRAMES:
            raise ValueError("frame_count must be between 1 and 5")
        if not 0 <= interval_ms <= 2_000:
            raise ValueError("interval_ms must be between 0 and 2000")
        if not 0 < timeout_seconds <= MAX_BURST_SECONDS:
            raise ValueError("timeout_seconds must be between 0 and 8")

        request = Request(
            f"{self._base_url}/api/stream.mjpeg?{urlencode({'src': 'gauge'})}",
            headers={"Accept": "multipart/x-mixed-replace"},
        )
        started = self._monotonic()
        frames: list[CapturedFrame] = []
        try:
            with self._opener(request, timeout_seconds) as response:
                boundary = self._boundary_from_headers(response)
                for index in range(frame_count):
                    if self._monotonic() - started > timeout_seconds:
                        raise FrameSourceUnavailable("burst_timeout")
                    payload = self._read_part(response, boundary)
                    width, height = _validate_jpeg(payload)
                    captured_at = self._now()
                    if captured_at.tzinfo is None or captured_at.utcoffset() is None:
                        raise FrameSourceUnavailable("frame_invalid")
                    frames.append(
                        CapturedFrame(
                            jpeg=payload,
                            captured_at=captured_at,
                            width=width,
                            height=height,
                        )
                    )
                    if index + 1 < frame_count and interval_ms:
                        self._sleep(interval_ms / 1_000)
        except FrameSourceUnavailable:
            raise
        except Exception as exc:
            raise FrameSourceUnavailable("frame_source_unavailable") from exc
        return FrameBurst(frames=tuple(frames))

    @staticmethod
    def _boundary_from_headers(response: BinaryIO) -> bytes:
        headers = getattr(response, "headers", None)
        content_type = headers.get("Content-Type", "") if headers is not None else ""
        boundary_token = next(
            (
                part.split("=", 1)[1].strip().strip('"')
                for part in str(content_type).split(";")
                if part.strip().lower().startswith("boundary=")
            ),
            None,
        )
        if not boundary_token or len(boundary_token) > 128:
            raise FrameSourceUnavailable("malformed_mjpeg")
        return f"--{boundary_token}".encode("ascii", errors="strict")

    @staticmethod
    def _read_part(response: BinaryIO, boundary: bytes) -> bytes:
        boundary_line = response.readline(256).strip()
        if boundary_line != boundary:
            raise FrameSourceUnavailable("malformed_mjpeg")

        headers: dict[str, str] = {}
        header_bytes = 0
        for _ in range(16):
            line = response.readline(1_024)
            header_bytes += len(line)
            if header_bytes > 8_192 or not line:
                raise FrameSourceUnavailable("malformed_mjpeg")
            if line in {b"\r\n", b"\n"}:
                break
            try:
                name, value = line.decode("ascii").split(":", 1)
            except (UnicodeDecodeError, ValueError) as exc:
                raise FrameSourceUnavailable("malformed_mjpeg") from exc
            headers[name.strip().lower()] = value.strip()
        else:
            raise FrameSourceUnavailable("malformed_mjpeg")

        if headers.get("content-type", "").lower() != "image/jpeg":
            raise FrameSourceUnavailable("malformed_mjpeg")
        try:
            content_length = int(headers["content-length"])
        except (KeyError, ValueError) as exc:
            raise FrameSourceUnavailable("malformed_mjpeg") from exc
        if not 1 <= content_length <= MAX_FRAME_BYTES:
            raise FrameSourceUnavailable("frame_invalid")
        payload = response.read(content_length)
        if len(payload) != content_length:
            raise FrameSourceUnavailable("malformed_mjpeg")
        if response.readline(3) not in {b"\r\n", b"\n"}:
            raise FrameSourceUnavailable("malformed_mjpeg")
        return payload

class Go2RtcAnalysisFrameSource(Go2RtcControlledFrameSource):
    """Streams validated frames from the fixed local `analysis` stream."""

    def __init__(
        self,
        *,
        stream_name: Literal["analysis", "analysis_realtime"] = "analysis",
        **kwargs: object,
    ) -> None:
        if stream_name not in {"analysis", "analysis_realtime"}:
            raise ValueError("analysis stream name is not allowed")
        super().__init__(**kwargs)  # type: ignore[arg-type]
        self._stream_name = stream_name

    def iter_frames(self, *, timeout_seconds: float = 8) -> Iterator[CapturedFrame]:
        if not 0 < timeout_seconds <= MAX_BURST_SECONDS:
            raise ValueError("timeout_seconds must be between 0 and 8")

        request = Request(
            f"{self._base_url}/api/stream.mjpeg?"
            f"{urlencode({'src': self._stream_name})}",
            headers={"Accept": "multipart/x-mixed-replace"},
        )
        try:
            with self._opener(request, timeout_seconds) as response:
                boundary = self._boundary_from_headers(response)
                while True:
                    payload = self._read_part(response, boundary)
                    width, height = _validate_jpeg(payload)
                    captured_at = self._now()
                    if (
                        captured_at.tzinfo is None
                        or captured_at.utcoffset() is None
                    ):
                        raise FrameSourceUnavailable("frame_invalid")
                    yield CapturedFrame(
                        jpeg=payload,
                        captured_at=captured_at,
                        width=width,
                        height=height,
                    )
        except FrameSourceUnavailable:
            raise
        except Exception as exc:
            raise FrameSourceUnavailable("frame_source_unavailable") from exc
