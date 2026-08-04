from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass
from typing import Any

import pytest
import yaml

from packages.contracts.settings import StreamSettings
from services.stream.go2rtc_config import build_go2rtc_config
from services.stream.probe import (
    ProbeExecutionError,
    ProbePayloadError,
    ProbeTimeoutError,
    StreamProbe,
)


@dataclass
class Completed:
    returncode: int = 0
    stdout: str = ""
    stderr: str = ""


def payload(*, audio: bool = True) -> str:
    streams: list[dict[str, Any]] = [
        {
            "codec_type": "video",
            "codec_name": "hevc",
            "width": 2560,
            "height": 1440,
            "avg_frame_rate": "15/1",
        }
    ]
    if audio:
        streams.append(
            {
                "codec_type": "audio",
                "codec_name": "opus",
                "sample_rate": "16000",
                "channels": 1,
            }
        )
    return json.dumps({"streams": streams, "format": {"duration": "42.5"}})


def test_probe_parses_hevc_video_and_audio_without_exposing_source() -> None:
    calls: list[tuple[list[str], dict[str, Any]]] = []

    def runner(command: list[str], **kwargs: Any) -> Completed:
        calls.append((command, kwargs))
        return Completed(stdout=payload())

    result = StreamProbe(runner=runner).probe("rtsp://user:secret@camera/live")

    assert result.healthy is True
    assert result.video.codec == "hevc"
    assert result.video.width == 2560
    assert result.video.height == 1440
    assert result.video.fps == 15.0
    assert result.audio is not None
    assert result.audio.codec == "opus"
    assert result.audio.sample_rate == 16000
    assert result.duration_seconds == 42.5
    assert "secret" not in result.model_dump_json()

    command, kwargs = calls[0]
    assert command[0] == "ffprobe"
    assert command[-1] == "rtsp://user:secret@camera/live"
    assert kwargs["shell"] is False
    assert kwargs["timeout"] == 10.0


def test_probe_accepts_video_only_stream() -> None:
    result = StreamProbe(runner=lambda *_args, **_kwargs: Completed(stdout=payload(audio=False))).probe(
        "rtsp://camera/live"
    )

    assert result.healthy is True
    assert result.audio is None


def test_probe_rejects_nonzero_ffprobe_exit() -> None:
    probe = StreamProbe(
        runner=lambda *_args, **_kwargs: Completed(returncode=1, stderr="connection refused")
    )

    with pytest.raises(ProbeExecutionError, match="connection refused"):
        probe.probe("rtsp://camera/live")


def test_probe_rejects_malformed_json() -> None:
    probe = StreamProbe(runner=lambda *_args, **_kwargs: Completed(stdout="{bad json"))

    with pytest.raises(ProbePayloadError, match="valid JSON"):
        probe.probe("rtsp://camera/live")


def test_probe_wraps_timeout_without_leaking_source() -> None:
    def runner(*_args: Any, **_kwargs: Any) -> Completed:
        raise subprocess.TimeoutExpired(cmd=["ffprobe"], timeout=10)

    with pytest.raises(ProbeTimeoutError) as exc_info:
        StreamProbe(runner=runner).probe("rtsp://user:secret@camera/live")

    assert "secret" not in str(exc_info.value)


def test_go2rtc_config_uses_one_external_upstream_for_three_logical_streams() -> None:
    settings = StreamSettings(
        go2rtc_api_host="127.0.0.1",
        go2rtc_api_port=1984,
        analysis_width=960,
        analysis_height=540,
        analysis_fps=5,
    )

    rendered = build_go2rtc_config("xiaomi:nursery-main", settings)
    config = yaml.safe_load(rendered)

    assert config["api"]["listen"] == "127.0.0.1:1984"
    assert config["rtsp"]["listen"] == "127.0.0.1:8554"
    assert config["webrtc"]["listen"] == "127.0.0.1:8555"
    assert set(config["streams"]) == {"source", "analysis", "live"}
    assert config["streams"]["source"] == "xiaomi:nursery-main"
    assert config["streams"]["live"] == "source"
    assert config["streams"]["analysis"].startswith("ffmpeg:source#")
    assert rendered.count("xiaomi:nursery-main") == 1
    assert "width=960" in config["streams"]["analysis"]
    assert "height=540" in config["streams"]["analysis"]
    assert "fps=5" in config["streams"]["analysis"]
