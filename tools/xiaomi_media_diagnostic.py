#!/usr/bin/env python3
"""Inspect the existing Xiaomi producer without opening another media connection."""

from __future__ import annotations

import sys
import time
from pathlib import Path
from typing import Protocol
from urllib.error import HTTPError, URLError
from urllib.request import (
    HTTPRedirectHandler,
    OpenerDirector,
    ProxyHandler,
    Request,
    build_opener,
)

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from packages.monitoring.xiaomi_media_diagnostic import (  # noqa: E402
    XiaomiMediaDiagnosticError,
    XiaomiMediaSnapshot,
    compare_source_observations,
    parse_source_observation,
    validate_single_source_config,
)
from packages.monitoring.xiaomi_macos_preflight import (  # noqa: E402
    MacOSMediaPreflight,
    run_macos_media_preflight,
)
from tools.xiaomi_macos_preflight import run_bounded  # noqa: E402


_URL = "http://127.0.0.1:1984/api/streams?src=source"
_MAX_BYTES = 1_048_576
_HTTP_TIMEOUT_SECONDS = 2.0
_MAX_INTERVAL_SECONDS = 5.0


class _Sleeper(Protocol):
    def __call__(self, seconds: float) -> None: ...


class _Preflight(Protocol):
    def __call__(self, root: Path) -> MacOSMediaPreflight: ...


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def _installed_preflight(root: Path) -> MacOSMediaPreflight:
    return run_macos_media_preflight(root, runner=run_bounded)


def collect_snapshot(
    root: Path,
    *,
    opener: OpenerDirector,
    preflight: _Preflight = _installed_preflight,
    sleeper: _Sleeper = time.sleep,
    interval_seconds: float = _MAX_INTERVAL_SECONDS,
) -> XiaomiMediaSnapshot:
    if (
        type(interval_seconds) is not float
        or not 0.0 <= interval_seconds <= _MAX_INTERVAL_SECONDS
    ):
        raise XiaomiMediaDiagnosticError("xiaomi_media_unavailable")
    if preflight(root).code != "ready":
        raise XiaomiMediaDiagnosticError("xiaomi_media_unavailable")
    config = root.resolve() / "runtime/go2rtc.yaml"
    try:
        config_payload = config.read_bytes()
    except OSError:
        raise XiaomiMediaDiagnosticError("xiaomi_media_config_invalid") from None
    validate_single_source_config(config_payload)

    before = parse_source_observation(_read_source(opener))
    sleeper(interval_seconds)
    after = parse_source_observation(_read_source(opener))
    return compare_source_observations(before, after)


def _read_source(opener: OpenerDirector) -> bytes:
    request = Request(_URL, headers={"Accept": "application/json"}, method="GET")
    try:
        with opener.open(request, timeout=_HTTP_TIMEOUT_SECONDS) as response:
            if getattr(response, "status", None) != 200:
                raise XiaomiMediaDiagnosticError("xiaomi_media_unavailable")
            payload = response.read(_MAX_BYTES + 1)
    except (HTTPError, URLError, OSError, TimeoutError, ValueError):
        raise XiaomiMediaDiagnosticError("xiaomi_media_unavailable") from None
    if len(payload) > _MAX_BYTES:
        raise XiaomiMediaDiagnosticError("xiaomi_media_unavailable")
    return payload


def format_report(snapshot: XiaomiMediaSnapshot) -> tuple[str, ...]:
    passed = (
        snapshot.configured_transport == "auto"
        and snapshot.producer_count == 1
        and snapshot.negotiated_protocol in {"cs2+udp", "cs2+tcp"}
        and snapshot.video_media_ready
        and snapshot.camera_audio_media_ready
        and snapshot.speaker_media_ready
        and snapshot.video_bytes_increased
        and snapshot.audio_bytes_increased
        and not snapshot.producer_replaced
    )
    boolean = lambda value: str(value).lower()  # noqa: E731
    return (
        f"result={'PASS' if passed else 'FAIL'}",
        "operation=xiaomi-media-diagnostic",
        f"configured_transport={snapshot.configured_transport}",
        f"producer_count={snapshot.producer_count}",
        f"negotiated_protocol={snapshot.negotiated_protocol}",
        f"producer_generation={snapshot.producer_generation}",
        f"consumer_count={snapshot.consumer_count}",
        f"video_media_ready={boolean(snapshot.video_media_ready)}",
        f"camera_audio_media_ready={boolean(snapshot.camera_audio_media_ready)}",
        f"speaker_media_ready={boolean(snapshot.speaker_media_ready)}",
        f"video_bytes_increased={boolean(snapshot.video_bytes_increased)}",
        f"audio_bytes_increased={boolean(snapshot.audio_bytes_increased)}",
        f"producer_replaced={boolean(snapshot.producer_replaced)}",
    )


def main() -> int:
    opener = build_opener(ProxyHandler({}), _NoRedirect())
    try:
        report = format_report(collect_snapshot(ROOT, opener=opener))
    except XiaomiMediaDiagnosticError:
        report = (
            "result=FAIL",
            "operation=xiaomi-media-diagnostic",
            "code=xiaomi_media_unavailable",
        )
    for line in report:
        print(line)
    return 0 if report[0] == "result=PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
