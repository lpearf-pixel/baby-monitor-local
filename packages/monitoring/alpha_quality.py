from __future__ import annotations

import os
import stat
from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import yaml

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


def _read_yaml_mapping(path: Path, *, missing_code: str) -> dict[str, Any]:
    if not path.is_file():
        raise QualityConfigError(missing_code)
    payload = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
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
