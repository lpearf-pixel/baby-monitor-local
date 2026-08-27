from __future__ import annotations

import io
import json
from pathlib import Path

import pytest
import yaml

from packages.monitoring.xiaomi_media_diagnostic import (
    XiaomiMediaDiagnosticError,
    XiaomiMediaSnapshot,
)
from packages.monitoring.xiaomi_macos_preflight import MacOSMediaPreflight
from tools.xiaomi_media_diagnostic import collect_snapshot, format_report


def _config() -> bytes:
    streams = {"source": "xiaomi:private-source-marker?channel=0"}
    for name in (
        "analysis",
        "analysis_realtime",
        "gauge",
        "audio_analysis",
        "live",
        "source_compat",
    ):
        streams[name] = "ffmpeg:source#video=copy"
    return yaml.safe_dump({"streams": streams}).encode()


def _body(producer_id: int, video_bytes: int, audio_bytes: int) -> bytes:
    producer = {
        "id": producer_id,
        "protocol": "cs2+udp",
        "remote_addr": "private-address-marker",
        "medias": [
            "video, recvonly, H265",
            "audio, recvonly, OPUS/48000/2",
            "audio, sendonly, OPUS/48000/2",
        ],
        "receivers": [
            {
                "codec": {"codec_name": "hevc", "codec_type": "video"},
                "bytes": video_bytes,
            },
            {
                "codec": {
                    "codec_name": "opus",
                    "codec_type": "audio",
                    "sample_rate": 48000,
                    "channels": 2,
                },
                "bytes": audio_bytes,
            },
        ],
        "producer_generation": 0,
    }
    return json.dumps({"producers": [producer], "consumers": []}).encode()


def _ready_preflight(_root: Path) -> MacOSMediaPreflight:
    return MacOSMediaPreflight(
        code="ready",
        app_identity_ready=True,
        launchd_owner_count=1,
        listener_owned_by_launchd=True,
        local_network_state="available",
    )


class _Response(io.BytesIO):
    status = 200

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        self.close()


class _Opener:
    def __init__(self, payloads: list[bytes]):
        self.payloads = payloads
        self.requests = []

    def open(self, request, *, timeout: float):
        self.requests.append((request, timeout))
        return _Response(self.payloads.pop(0))


def test_collector_rejects_failed_preflight_before_config_or_http(
    tmp_path: Path,
) -> None:
    opener = _Opener([])
    failed = MacOSMediaPreflight(
        code="app_identity_invalid",
        app_identity_ready=False,
        launchd_owner_count=0,
        listener_owned_by_launchd=False,
        local_network_state="unknown",
    )

    with pytest.raises(XiaomiMediaDiagnosticError, match="xiaomi_media_unavailable"):
        collect_snapshot(
            tmp_path,
            opener=opener,
            preflight=lambda _root: failed,
            sleeper=lambda _seconds: None,
            interval_seconds=0.0,
        )

    assert opener.requests == []
    assert list(tmp_path.iterdir()) == []


def test_collector_is_fixed_loopback_bounded_and_read_only(tmp_path: Path) -> None:
    root = tmp_path
    (root / "runtime").mkdir()
    config = root / "runtime/go2rtc.yaml"
    config.write_bytes(_config())
    opener = _Opener([_body(41, 100, 200), _body(41, 150, 250)])
    sleeps = []

    snapshot = collect_snapshot(
        root,
        opener=opener,
        preflight=_ready_preflight,
        sleeper=sleeps.append,
        interval_seconds=5.0,
    )

    assert snapshot.video_bytes_increased is True
    assert snapshot.audio_bytes_increased is True
    assert sleeps == [5.0]
    assert len(opener.requests) == 2
    assert all(
        item[0].full_url == "http://127.0.0.1:1984/api/streams?src=source"
        for item in opener.requests
    )
    assert all(
        item[0].method == "GET" and item[1] <= 5.0
        for item in opener.requests
    )
    assert config.read_bytes() == _config()
    assert list(root.rglob("*")) == [root / "runtime", config]


def test_collector_rejects_an_oversize_http_body(tmp_path: Path) -> None:
    (tmp_path / "runtime").mkdir()
    (tmp_path / "runtime/go2rtc.yaml").write_bytes(_config())
    opener = _Opener([b"x" * 1_048_577])

    with pytest.raises(XiaomiMediaDiagnosticError, match="xiaomi_media_unavailable"):
        collect_snapshot(
            tmp_path,
            opener=opener,
            preflight=_ready_preflight,
            sleeper=lambda _seconds: None,
            interval_seconds=0.0,
        )


def test_report_contains_only_approved_aggregate_fields() -> None:
    snapshot = XiaomiMediaSnapshot(
        configured_transport="auto",
        producer_count=1,
        negotiated_protocol="cs2+tcp",
        producer_generation=0,
        consumer_count=2,
        video_media_ready=True,
        camera_audio_media_ready=True,
        speaker_media_ready=True,
        video_bytes_increased=True,
        audio_bytes_increased=True,
        producer_replaced=False,
    )

    output = format_report(snapshot)

    assert output == (
        "result=PASS",
        "operation=xiaomi-media-diagnostic",
        "configured_transport=auto",
        "producer_count=1",
        "negotiated_protocol=cs2+tcp",
        "producer_generation=0",
        "consumer_count=2",
        "video_media_ready=true",
        "camera_audio_media_ready=true",
        "speaker_media_ready=true",
        "video_bytes_increased=true",
        "audio_bytes_increased=true",
        "producer_replaced=false",
    )
    combined = "\n".join(output)
    for secret in ("private", "xiaomi:", "address", "uri", "did", "id="):
        assert secret not in combined.lower()


def test_report_fails_when_either_media_counter_does_not_advance() -> None:
    snapshot = XiaomiMediaSnapshot(
        configured_transport="auto",
        producer_count=1,
        negotiated_protocol="cs2+udp",
        producer_generation=0,
        consumer_count=0,
        video_media_ready=True,
        camera_audio_media_ready=True,
        speaker_media_ready=True,
        video_bytes_increased=True,
        audio_bytes_increased=False,
        producer_replaced=False,
    )

    assert format_report(snapshot)[0] == "result=FAIL"
