from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

LIVE_HD = "ffmpeg:source#video=mjpeg#width=1280#height=720#raw=-r 10"


class QualityConfigError(ValueError):
    """Raised when a runtime go2rtc config cannot be safely transformed."""


@dataclass(frozen=True)
class QualityInfo:
    source_quality: str
    transport: str
    live_width: int
    live_height: int
    live_fps: int


def _streams(config: dict[str, Any]) -> dict[str, Any]:
    streams = config.get("streams")
    if not isinstance(streams, dict):
        raise QualityConfigError("SOURCE_NOT_CONFIGURED")
    return streams


def upgrade_to_hd(config: dict[str, Any]) -> dict[str, Any]:
    result = deepcopy(config)
    streams = _streams(result)
    source = streams.get("source")
    if not isinstance(source, str) or not source.startswith("xiaomi://"):
        raise QualityConfigError("SOURCE_NOT_CONFIGURED")

    parsed = urlsplit(source)
    query = [
        (key, value)
        for key, value in parse_qsl(parsed.query, keep_blank_values=True)
        if key not in {"subtype", "transport"}
    ]
    query.append(("subtype", "hd"))

    streams["source"] = urlunsplit(
        (parsed.scheme, parsed.netloc, parsed.path, urlencode(query), parsed.fragment)
    )
    streams["live"] = LIVE_HD
    return result


def inspect_quality(config: dict[str, Any]) -> QualityInfo:
    streams = _streams(config)
    source = streams.get("source")
    live = streams.get("live")
    if not isinstance(source, str) or not isinstance(live, str):
        raise QualityConfigError("SOURCE_NOT_CONFIGURED")

    source_query = dict(parse_qsl(urlsplit(source).query, keep_blank_values=True))
    return QualityInfo(
        source_quality=source_query.get("subtype", "default"),
        transport=source_query.get("transport", "auto"),
        live_width=1280 if "#width=1280" in live else 0,
        live_height=720 if "#height=720" in live else 0,
        live_fps=10 if "#raw=-r 10" in live else 0,
    )
