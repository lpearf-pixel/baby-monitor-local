from __future__ import annotations

import json
import os
from collections.abc import Iterator
from urllib.parse import quote, urlencode
from urllib.request import Request, urlopen

from apps.api.alpha import AlphaRuntime


class Go2RTCAlphaGateway:
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

    def _go2rtc_url(self, path: str) -> str:
        query = urlencode({"src": self._stream_name})
        return f"{self._base_url}{path}?{query}"

    def status(self) -> dict[str, object]:
        try:
            with urlopen(
                f"{self._base_url}/api/streams", timeout=self._timeout_seconds
            ) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except Exception as exc:  # alpha status must degrade rather than crash dashboard
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
        with urlopen(
            self._go2rtc_url("/api/stream.mjpeg"), timeout=60
        ) as response:
            while True:
                chunk = response.read(64 * 1024)
                if not chunk:
                    return
                yield chunk

    def snapshot(self) -> bytes:
        with urlopen(
            self._go2rtc_url("/api/frame.jpeg"), timeout=self._timeout_seconds
        ) as response:
            return response.read()

    def send_test_notification(self) -> None:
        if not self._ntfy_topic:
            raise RuntimeError("NTFY_TOPIC is not configured")
        request = Request(
            f"{self._ntfy_base_url}/{quote(self._ntfy_topic, safe='')}",
            data="婴儿监控 Alpha 测试通知：Mac、网页和 ntfy 通道已连通。".encode(
                "utf-8"
            ),
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
    gateway = Go2RTCAlphaGateway(
        base_url=env.get("GO2RTC_BASE_URL", "http://127.0.0.1:1984"),
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
    )
