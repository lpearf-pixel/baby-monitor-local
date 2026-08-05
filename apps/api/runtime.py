from __future__ import annotations

import json
import os
import warnings
from io import BytesIO
from collections.abc import Iterator
from urllib.parse import quote, urlencode
from urllib.request import Request, urlopen

from PIL import Image, UnidentifiedImageError

from apps.api.alpha import AlphaRuntime, SnapshotViewport
from apps.api.hd_stream import HdStreamService
from apps.api.ptz import DisabledPtzAdapter, StepPtzController


MAX_SNAPSHOT_BYTES = 16 * 1024 * 1024
MAX_SNAPSHOT_WIDTH = 4096
MAX_SNAPSHOT_HEIGHT = 2160
MAX_SNAPSHOT_PIXELS = MAX_SNAPSHOT_WIDTH * MAX_SNAPSHOT_HEIGHT


class SnapshotFrameRejected(RuntimeError):
    pass


class Go2RTCAlphaGateway:
    _source_stream_name = "source"

    def __init__(
        self,
        *,
        base_url: str,
        stream_name: str,
        ntfy_base_url: str,
        ntfy_topic: str,
        ntfy_token: str | None,
        timeout_seconds: float = 10.0,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._stream_name = stream_name
        self._ntfy_base_url = ntfy_base_url.rstrip("/")
        self._ntfy_topic = ntfy_topic.strip()
        self._ntfy_token = ntfy_token
        self._timeout_seconds = timeout_seconds

    def _go2rtc_url(self, path: str, *, stream_name: str | None = None) -> str:
        query = urlencode({"src": stream_name or self._stream_name})
        return f"{self._base_url}{path}?{query}"

    def status(self) -> dict[str, object]:
        try:
            with urlopen(
                f"{self._base_url}/api/streams", timeout=self._timeout_seconds
            ) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except Exception as exc:
            return {
                "camera": "offline",
                "stream": self._stream_name,
                "detail": type(exc).__name__,
            }

        streams = payload if isinstance(payload, dict) else {}
        return {
            "camera": "online" if self._stream_name in streams else "unavailable",
            "stream": self._stream_name,
            "known_streams": sorted(str(name) for name in streams),
        }

    def iter_mjpeg(self) -> Iterator[bytes]:
        with urlopen(self._go2rtc_url("/api/stream.mjpeg"), timeout=60) as response:
            while True:
                chunk = response.read(64 * 1024)
                if not chunk:
                    return
                yield chunk

    def snapshot(self, viewport: SnapshotViewport) -> bytes:
        snapshot_stream = (
            self._stream_name if viewport.zoom == 1 else self._source_stream_name
        )
        with urlopen(
            self._go2rtc_url(
                "/api/frame.jpeg",
                stream_name=snapshot_stream,
            ),
            timeout=self._timeout_seconds,
        ) as response:
            payload = response.read(MAX_SNAPSHOT_BYTES + 1)
        if len(payload) > MAX_SNAPSHOT_BYTES:
            raise SnapshotFrameRejected("snapshot frame rejected")
        if viewport.zoom == 1:
            return payload

        try:
            with warnings.catch_warnings():
                warnings.simplefilter("error", Image.DecompressionBombWarning)
                with Image.open(BytesIO(payload)) as source:
                    width, height = source.size
                    if (
                        width > MAX_SNAPSHOT_WIDTH
                        or height > MAX_SNAPSHOT_HEIGHT
                        or width * height > MAX_SNAPSHOT_PIXELS
                    ):
                        raise SnapshotFrameRejected("snapshot frame rejected")
                    image = source.convert("RGB")
        except SnapshotFrameRejected:
            raise
        except (
            Image.DecompressionBombError,
            Image.DecompressionBombWarning,
            UnidentifiedImageError,
            OSError,
        ) as exc:
            raise SnapshotFrameRejected("snapshot frame rejected") from exc
        crop_width = max(1, round(image.width / viewport.zoom))
        crop_height = max(1, round(image.height / viewport.zoom))
        left = round(viewport.center_x * image.width - crop_width / 2)
        top = round(viewport.center_y * image.height - crop_height / 2)
        left = min(max(0, left), image.width - crop_width)
        top = min(max(0, top), image.height - crop_height)
        cropped = image.crop((left, top, left + crop_width, top + crop_height))
        output = BytesIO()
        cropped.save(output, format="JPEG", quality=95, subsampling=0)
        return output.getvalue()

    def send_test_notification(self) -> None:
        if not self._ntfy_topic:
            raise RuntimeError("NTFY_TOPIC is not configured")
        request = Request(
            f"{self._ntfy_base_url}/{quote(self._ntfy_topic, safe='')}",
            data="婴儿监控 Alpha 测试通知：Mac、网页和 ntfy 通道已连通。".encode("utf-8"),
            method="POST",
            headers={
                "Title": "Baby Monitor Local",
                "Priority": "high",
                "Tags": "baby,white_check_mark",
                **(
                    {"Authorization": f"Bearer {self._ntfy_token}"}
                    if self._ntfy_token
                    else {}
                ),
            },
        )
        with urlopen(request, timeout=self._timeout_seconds) as response:
            if not 200 <= response.status < 300:
                raise RuntimeError(f"ntfy returned HTTP {response.status}")


def runtime_from_env(environ: dict[str, str] | None = None) -> AlphaRuntime:
    env = os.environ if environ is None else environ
    username = env.get("BABY_MONITOR_USERNAME", "").strip()
    password = env.get("BABY_MONITOR_PASSWORD", "")
    if not username or not password:
        raise RuntimeError(
            "BABY_MONITOR_USERNAME and BABY_MONITOR_PASSWORD must be configured"
        )

    stream_name = env.get("BABY_MONITOR_STREAM", "live").strip() or "live"
    go2rtc_base_url = env.get("GO2RTC_BASE_URL", "http://127.0.0.1:1984")
    gateway = Go2RTCAlphaGateway(
        base_url=go2rtc_base_url,
        stream_name=stream_name,
        ntfy_base_url=env.get("NTFY_BASE_URL", "https://ntfy.sh"),
        ntfy_topic=env.get("NTFY_TOPIC", ""),
        ntfy_token=env.get("NTFY_TOKEN") or None,
    )
    return AlphaRuntime(
        username=username,
        password=password,
        stream_name=stream_name,
        gateway=gateway,
        ptz=StepPtzController(adapter=DisabledPtzAdapter()),
        hd_stream=HdStreamService(
            upstream_base_url=go2rtc_base_url,
            native_stream_name="source",
            compat_stream_name="source_compat",
        ),
    )
