from __future__ import annotations

import yaml

from packages.contracts.settings import StreamSettings


def build_go2rtc_config(source_expression: str, settings: StreamSettings) -> str:
    """Render a loopback-only go2rtc config with one external camera producer."""

    if not source_expression or not source_expression.strip():
        raise ValueError("source_expression must not be empty")

    host = settings.go2rtc_api_host
    analysis = (
        "ffmpeg:source"
        f"#video=h264"
        f"#width={settings.analysis_width}"
        f"#height={settings.analysis_height}"
        f"#fps={settings.analysis_fps}"
    )
    config = {
        "api": {"listen": f"{host}:{settings.go2rtc_api_port}"},
        "rtsp": {"listen": f"{host}:8554"},
        "webrtc": {"listen": f"{host}:8555"},
        "streams": {
            "source": source_expression,
            "analysis": analysis,
            "live": "source",
        },
    }
    return yaml.safe_dump(config, sort_keys=False, allow_unicode=True)
