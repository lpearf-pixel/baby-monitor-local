from __future__ import annotations

import json
import os
import re
import stat
from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from time import monotonic, sleep
from typing import Any, Callable
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit
from urllib.request import urlopen

import yaml

LIVE_HD = "ffmpeg:source#video=mjpeg#width=1280#height=720#raw=-r 10"
ANALYSIS_STREAM = "ffmpeg:source#video=mjpeg#width=960#height=540#raw=-r 1"
COMPAT_HD = (
    "ffmpeg:source#video=h264#hardware=videotoolbox"
    "#width=2560#height=1440#bitrate=6M"
)


class QualityConfigError(ValueError):
    """Raised when a runtime go2rtc config cannot be safely transformed."""


@dataclass(frozen=True)
class QualityInfo:
    source_quality: str
    transport: str
    live_width: int
    live_height: int
    live_fps: int
    compat_profile: str


@dataclass(frozen=True)
class HealthResult:
    code: str
    protocol: str = ""
    source_codec: str = ""
    bytes_received: int = 0
    source_dimensions: tuple[int, int] | None = None
    live_dimensions: tuple[int, int] | None = None


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
    streams["analysis"] = ANALYSIS_STREAM
    streams["source_compat"] = COMPAT_HD
    return result


def with_visual_analysis_stream(config: dict[str, Any]) -> dict[str, Any]:
    result = deepcopy(config)
    streams = _streams(result)
    source = streams.get("source")
    if not isinstance(source, str) or not source.startswith("xiaomi://"):
        raise QualityConfigError("SOURCE_NOT_CONFIGURED")
    streams["analysis"] = ANALYSIS_STREAM
    return result


def with_source_subtype(config: dict[str, Any], subtype: int) -> dict[str, Any]:
    if subtype not in range(6):
        raise QualityConfigError("INVALID_SUBTYPE")

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
    query.append(("subtype", str(subtype)))
    streams["source"] = urlunsplit(
        (parsed.scheme, parsed.netloc, parsed.path, urlencode(query), parsed.fragment)
    )
    streams["live"] = LIVE_HD
    streams["analysis"] = ANALYSIS_STREAM
    streams["source_compat"] = COMPAT_HD
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
        compat_profile=(
            "videotoolbox-1440p-6M"
            if streams.get("source_compat") == COMPAT_HD
            else "missing"
        ),
    )


def _read_yaml_mapping(path: Path, *, missing_code: str) -> dict[str, Any]:
    if not path.is_file():
        raise QualityConfigError(missing_code)
    try:
        payload = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except (OSError, yaml.YAMLError) as exc:
        raise QualityConfigError(missing_code) from exc
    if not isinstance(payload, dict):
        raise QualityConfigError(missing_code)
    return payload


def _atomic_write(path: Path, content: str, mode: int) -> None:
    temporary = path.with_name(f".{path.name}.tmp-{os.getpid()}")
    try:
        temporary.write_text(content, encoding="utf-8")
        temporary.chmod(mode)
        yaml.safe_load(temporary.read_text(encoding="utf-8"))
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def apply_hd(config_path: Path, backups_dir: Path, now: datetime) -> Path:
    original = _read_yaml_mapping(config_path, missing_code="SOURCE_NOT_CONFIGURED")
    original_text = config_path.read_text(encoding="utf-8")
    updated = upgrade_to_hd(original)
    mode = stat.S_IMODE(config_path.stat().st_mode)

    backups_dir.mkdir(parents=True, exist_ok=True)
    backup = backups_dir / f"go2rtc-quality-{now.strftime('%Y%m%d-%H%M%S')}.yaml"
    backup.write_text(original_text, encoding="utf-8")
    backup.chmod(mode)

    rendered = yaml.safe_dump(updated, sort_keys=False, allow_unicode=True)
    _atomic_write(config_path, rendered, mode)
    return backup


def rollback_latest(config_path: Path, backups_dir: Path) -> Path:
    backups = sorted(backups_dir.glob("go2rtc-quality-*.yaml"))
    if not backups:
        raise QualityConfigError("NO_QUALITY_BACKUP")

    latest = backups[-1]
    restored_text = latest.read_text(encoding="utf-8")
    yaml.safe_load(restored_text)
    mode = (
        stat.S_IMODE(config_path.stat().st_mode)
        if config_path.exists()
        else stat.S_IMODE(latest.stat().st_mode)
    )
    _atomic_write(config_path, restored_text, mode)
    return latest


def jpeg_dimensions(payload: bytes) -> tuple[int, int]:
    if len(payload) < 4 or payload[:2] != b"\xff\xd8":
        raise QualityConfigError("INVALID_SNAPSHOT")

    offset = 2
    sof_markers = {
        0xC0,
        0xC1,
        0xC2,
        0xC3,
        0xC5,
        0xC6,
        0xC7,
        0xC9,
        0xCA,
        0xCB,
        0xCD,
        0xCE,
        0xCF,
    }
    while offset + 3 < len(payload):
        if payload[offset] != 0xFF:
            offset += 1
            continue
        while offset < len(payload) and payload[offset] == 0xFF:
            offset += 1
        if offset >= len(payload):
            break
        marker = payload[offset]
        offset += 1
        if marker in {0xD8, 0xD9}:
            continue
        if offset + 2 > len(payload):
            break
        length = int.from_bytes(payload[offset : offset + 2], "big")
        if length < 2 or offset + length > len(payload):
            break
        if marker in sof_markers and length >= 7:
            height = int.from_bytes(payload[offset + 3 : offset + 5], "big")
            width = int.from_bytes(payload[offset + 5 : offset + 7], "big")
            if width > 0 and height > 0:
                return width, height
        offset += length

    raise QualityConfigError("INVALID_SNAPSHOT")


def _read_bytes(
    url: str,
    *,
    opener: Callable[..., Any],
    timeout: float = 10.0,
    limit: int | None = None,
) -> bytes:
    with opener(url, timeout=timeout) as response:
        return response.read() if limit is None else response.read(limit)


def _read_json(
    url: str,
    *,
    opener: Callable[..., Any],
    timeout: float = 10.0,
) -> Any:
    return json.loads(_read_bytes(url, opener=opener, timeout=timeout).decode("utf-8"))


def _read_nonempty_with_reconnect(
    url: str,
    *,
    opener: Callable[..., Any],
    timeout: float,
    limit: int,
    retry_interval: float = 0.25,
) -> bytes:
    deadline = monotonic() + timeout
    while True:
        remaining = deadline - monotonic()
        if remaining <= 0:
            return b""
        try:
            payload = _read_bytes(
                url,
                opener=opener,
                timeout=remaining,
                limit=limit,
            )
        except Exception:
            payload = b""
        if payload:
            return payload

        remaining = deadline - monotonic()
        if remaining <= 0:
            return b""
        sleep(min(retry_interval, remaining))


def _health(
    code: str,
    *,
    protocol: str = "",
    source_codec: str = "",
    bytes_received: int = 0,
    source_dimensions: tuple[int, int] | None = None,
    live_dimensions: tuple[int, int] | None = None,
) -> HealthResult:
    return HealthResult(
        code=code,
        protocol=protocol,
        source_codec=source_codec,
        bytes_received=bytes_received,
        source_dimensions=source_dimensions,
        live_dimensions=live_dimensions,
    )


def check_source_health(
    base_url: str,
    *,
    opener: Callable[..., Any] = urlopen,
) -> HealthResult:
    base_url = base_url.rstrip("/")

    # First confirm that the named source exists without exposing its URL.
    try:
        catalog = _read_json(f"{base_url}/api/streams", opener=opener)
    except Exception:
        return _health("SOURCE_OFFLINE")
    if not isinstance(catalog, dict) or "source" not in catalog:
        return _health("SOURCE_NOT_CONFIGURED")

    # A plain /api/streams response can contain only the configured URL while the
    # producer is idle. Asking for a video probe makes go2rtc connect the Xiaomi
    # source and serialise the active producer before removing the probe consumer.
    try:
        source = _read_json(
            f"{base_url}/api/streams?src=source&video",
            opener=opener,
            timeout=40.0,
        )
    except Exception:
        return _health("SOURCE_OFFLINE")

    producers = source.get("producers") if isinstance(source, dict) else None
    if not isinstance(producers, list):
        return _health("SOURCE_OFFLINE")

    active = [
        producer
        for producer in producers
        if isinstance(producer, dict)
        and isinstance(producer.get("protocol"), str)
        and producer.get("protocol")
    ]
    if not active:
        return _health("SOURCE_OFFLINE")

    protocol = str(active[0]["protocol"])
    medias = [
        str(media)
        for producer in active
        if isinstance(producer.get("medias"), list)
        for media in producer["medias"]
    ]
    bytes_received = sum(
        int(producer.get("bytes_recv", producer.get("bytes_received", 0)) or 0)
        for producer in active
        if isinstance(
            producer.get("bytes_recv", producer.get("bytes_received", 0)),
            (int, float),
        )
    )
    if not any("video" in media.lower() for media in medias):
        return _health(
            "SOURCE_NO_VIDEO",
            protocol=protocol,
            bytes_received=bytes_received,
        )
    source_codec = ""
    for media in medias:
        if "video" not in media.lower():
            continue
        match = re.search(r"(?<![A-Z0-9])(H264|H265)(?![A-Z0-9])", media.upper())
        if match:
            source_codec = match.group(1)
            break
    if not source_codec:
        return _health(
            "SOURCE_CODEC_UNSUPPORTED",
            protocol=protocol,
            bytes_received=bytes_received,
        )

    try:
        source_jpeg = _read_bytes(
            f"{base_url}/api/frame.jpeg?src=source",
            opener=opener,
            timeout=30.0,
        )
        source_dimensions = jpeg_dimensions(source_jpeg)
    except Exception:
        return _health(
            "SOURCE_OFFLINE",
            protocol=protocol,
            source_codec=source_codec,
            bytes_received=bytes_received,
        )

    # Some producers only increment bytes_recv after their worker starts. A valid
    # source JPEG is stronger evidence than a zero counter captured during probe.
    if bytes_received <= 0:
        bytes_received = len(source_jpeg)

    return _health(
        "PASS",
        protocol=protocol,
        source_codec=source_codec,
        bytes_received=bytes_received,
        source_dimensions=source_dimensions,
    )


def check_hd_health(
    base_url: str,
    dashboard_url: str,
    *,
    opener: Callable[..., Any] = urlopen,
) -> HealthResult:
    base_url = base_url.rstrip("/")
    dashboard_url = dashboard_url.rstrip("/")

    source_result = check_source_health(base_url, opener=opener)
    if source_result.code != "PASS":
        return source_result

    protocol = source_result.protocol
    source_codec = source_result.source_codec
    bytes_received = source_result.bytes_received
    source_dimensions = source_result.source_dimensions

    mjpeg_sample = _read_nonempty_with_reconnect(
        f"{base_url}/api/stream.mjpeg?src=live",
        opener=opener,
        timeout=12.0,
        limit=16 * 1024,
    )
    if not mjpeg_sample:
        return _health(
            "LIVE_MJPEG_EMPTY",
            protocol=protocol,
            source_codec=source_codec,
            bytes_received=bytes_received,
            source_dimensions=source_dimensions,
        )

    jpeg_start = mjpeg_sample.find(b"\xff\xd8")
    try:
        live_dimensions = jpeg_dimensions(mjpeg_sample[jpeg_start:])
    except QualityConfigError:
        return _health(
            "LIVE_EMPTY_FRAME",
            protocol=protocol,
            source_codec=source_codec,
            bytes_received=bytes_received,
            source_dimensions=source_dimensions,
        )
    if live_dimensions != (1280, 720):
        return _health(
            "LIVE_WRONG_DIMENSIONS",
            protocol=protocol,
            source_codec=source_codec,
            bytes_received=bytes_received,
            source_dimensions=source_dimensions,
            live_dimensions=live_dimensions,
        )

    try:
        dashboard = _read_json(f"{dashboard_url}/healthz", opener=opener)
    except Exception:
        return _health(
            "DASHBOARD_OFFLINE",
            protocol=protocol,
            source_codec=source_codec,
            bytes_received=bytes_received,
            source_dimensions=source_dimensions,
            live_dimensions=live_dimensions,
        )
    if dashboard != {"status": "ok"}:
        return _health(
            "DASHBOARD_OFFLINE",
            protocol=protocol,
            source_codec=source_codec,
            bytes_received=bytes_received,
            source_dimensions=source_dimensions,
            live_dimensions=live_dimensions,
        )

    return _health(
        "PASS",
        protocol=protocol,
        source_codec=source_codec,
        bytes_received=bytes_received,
        source_dimensions=source_dimensions,
        live_dimensions=live_dimensions,
    )
