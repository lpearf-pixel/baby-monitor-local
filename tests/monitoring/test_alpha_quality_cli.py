from __future__ import annotations

import subprocess
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

import yaml


ROOT = Path(__file__).resolve().parents[2]
CLI = ROOT / "tools" / "alpha_quality.py"


def jpeg(width: int, height: int) -> bytes:
    return (
        b"\xff\xd8"
        b"\xff\xc0"
        b"\x00\x11"
        b"\x08"
        + height.to_bytes(2, "big")
        + width.to_bytes(2, "big")
        + b"\x03\x01\x11\x00\x02\x11\x00\x03\x11\x00"
        + b"\xff\xd9"
    )


class ProbeHandler(BaseHTTPRequestHandler):
    config_path: Path

    def log_message(self, _format: str, *_args: object) -> None:
        return None

    def do_GET(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler contract
        parsed = urlsplit(self.path)
        query = parse_qs(parsed.query)
        if parsed.path == "/api/streams" and not parsed.query:
            self._send_json(b'{"source": {"producers": []}}')
            return
        if parsed.path == "/api/streams" and parsed.query == "src=source&video":
            self._send_json(
                b'{"producers": [{"protocol": "cs2+udp", '
                b'"medias": ["video, recvonly, H265"], '
                b'"bytes_recv": 50000}], "consumers": []}'
            )
            return
        if parsed.path == "/api/frame.jpeg":
            if query.get("src") == ["live"]:
                self._send_jpeg((1280, 720))
                return
            source = yaml.safe_load(self.config_path.read_text(encoding="utf-8"))[
                "streams"
            ]["source"]
            subtype = dict(parse_qs(urlsplit(source).query))["subtype"][0]
            dimensions = {"2": (864, 480), "3": (2560, 1440)}[subtype]
            self._send_jpeg(dimensions)
            return
        if parsed.path == "/api/stream.mjpeg" and query.get("src") == ["live"]:
            self.send_response(200)
            self.send_header("Content-Type", "multipart/x-mixed-replace")
            self.end_headers()
            self.wfile.write(jpeg(1280, 720))
            return
        if parsed.path == "/healthz":
            self._send_json(b'{"status": "ok"}')
            return
        self.send_response(404)
        self.end_headers()

    def _send_jpeg(self, dimensions: tuple[int, int]) -> None:
        self.send_response(200)
        self.send_header("Content-Type", "image/jpeg")
        self.end_headers()
        self.wfile.write(jpeg(*dimensions))

    def _send_json(self, payload: bytes) -> None:
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(payload)


def start_probe_server(config_path: Path) -> tuple[ThreadingHTTPServer, threading.Thread]:
    handler = type("ConfiguredProbeHandler", (ProbeHandler,), {"config_path": config_path})
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, thread


def run_cli(*args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(CLI), *args],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )


def test_help_lists_source_health_check() -> None:
    result = run_cli("--help")

    assert result.returncode == 0
    assert "check" in result.stdout
    assert "--base-url" in run_cli("check", "--help").stdout
    assert "--dashboard-url" in run_cli("check", "--help").stdout
    probe_help = run_cli("probe-subtypes", "--help").stdout
    assert "--candidates" in probe_help
    assert "--restart-command" in probe_help
    apply_help = run_cli("apply-subtype", "--help").stdout
    assert "--subtype" in apply_help
    assert "--minimum-width" in apply_help
    assert "--minimum-height" in apply_help


def test_info_prints_only_derived_quality_fields(tmp_path: Path) -> None:
    config = tmp_path / "go2rtc.yaml"
    config.write_text(
        yaml.safe_dump(
            {
                "xiaomi": {"123": "V1:super-secret"},
                "streams": {
                    "source": (
                        "xiaomi://123:cn@192.0.2.10?did=456"
                        "&model=example.camera&subtype=hd"
                    ),
                    "live": (
                        "ffmpeg:source#video=mjpeg#width=1280"
                        "#height=720#raw=-r 10"
                    ),
                    "source_compat": (
                        "ffmpeg:source#video=h264#hardware=videotoolbox"
                        "#width=2560#height=1440#bitrate=6M"
                    ),
                },
            }
        ),
        encoding="utf-8",
    )

    result = run_cli("info", "--config", str(config))

    assert result.returncode == 0
    assert result.stdout.splitlines() == [
        "source_quality=hd",
        "transport=auto",
        "live_width=1280",
        "live_height=720",
        "live_fps=10",
        "compat_profile=videotoolbox-1440p-6M",
    ]
    combined = result.stdout + result.stderr
    assert "xiaomi://" not in combined
    assert "V1:" not in combined
    assert "192.0.2.10" not in combined
    assert "did=456" not in combined


def test_check_prints_normalized_source_codec_without_media_details(
    tmp_path: Path,
) -> None:
    config = tmp_path / "go2rtc.yaml"
    config.write_text(
        yaml.safe_dump(
            {
                "streams": {
                    "source": "xiaomi://fixture?subtype=3",
                    "live": "fixture",
                }
            }
        ),
        encoding="utf-8",
    )
    server, thread = start_probe_server(config)
    try:
        result = run_cli(
            "check",
            "--base-url",
            f"http://127.0.0.1:{server.server_port}",
            "--dashboard-url",
            f"http://127.0.0.1:{server.server_port}",
        )
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)

    assert result.returncode == 0
    assert result.stdout.splitlines() == [
        "result=PASS",
        "protocol=cs2+udp",
        "source_codec=H265",
        "bytes_received=50000",
        "source_dimensions=2560x1440",
        "live_dimensions=1280x720",
    ]
    assert "video, recvonly" not in result.stdout
    assert "xiaomi://" not in result.stdout + result.stderr


def test_apply_hd_reports_backup_without_printing_config(tmp_path: Path) -> None:
    config = tmp_path / "go2rtc.yaml"
    backups = tmp_path / "backups"
    config.write_text(
        yaml.safe_dump(
            {
                "xiaomi": {"123": "V1:super-secret"},
                "streams": {
                    "source": (
                        "xiaomi://123:cn@192.0.2.10?did=456"
                        "&model=example.camera&transport=tcp"
                    ),
                    "live": "old",
                },
            }
        ),
        encoding="utf-8",
    )

    result = run_cli(
        "apply-hd",
        "--config",
        str(config),
        "--backups",
        str(backups),
    )

    assert result.returncode == 0
    assert "backup=" in result.stdout
    combined = result.stdout + result.stderr
    assert "xiaomi://" not in combined
    assert "V1:" not in combined
    assert "192.0.2.10" not in combined


def test_apply_gauge_stream_reports_backup_without_printing_config(tmp_path: Path) -> None:
    config = tmp_path / "go2rtc.yaml"
    backups = tmp_path / "backups"
    config.write_text(
        "streams:\n  source: xiaomi://device:cn@192.0.2.10?subtype=3\n",
        encoding="utf-8",
    )

    result = run_cli(
        "apply-gauge-stream",
        "--config",
        str(config),
        "--backups",
        str(backups),
    )

    assert result.returncode == 0
    assert "backup=" in result.stdout
    assert "xiaomi://" not in result.stdout + result.stderr


def test_cli_returns_code_two_for_missing_source(tmp_path: Path) -> None:
    config = tmp_path / "go2rtc.yaml"
    config.write_text("streams: {live: old}\n", encoding="utf-8")

    result = run_cli("info", "--config", str(config))

    assert result.returncode == 2
    assert result.stderr.strip() == "SOURCE_NOT_CONFIGURED"


def test_probe_subtypes_prints_derived_results_and_restores_config(
    tmp_path: Path,
) -> None:
    config = tmp_path / "go2rtc.yaml"
    original_text = yaml.safe_dump(
        {
            "xiaomi": {"123": "V1:super-secret"},
            "streams": {
                "source": (
                    "xiaomi://123:cn@192.0.2.10?did=456&subtype=hd"
                    "&vendor_hint=keep"
                ),
                "live": "old",
            },
        },
        sort_keys=False,
    )
    config.write_text(original_text, encoding="utf-8")
    restart_script = tmp_path / "restart.py"
    restart_script.write_text(
        "print('xiaomi://must-not-leak did=456 192.0.2.10')\n",
        encoding="utf-8",
    )
    server, thread = start_probe_server(config)
    try:
        result = run_cli(
            "probe-subtypes",
            "--config",
            str(config),
            "--backups",
            str(tmp_path / "backups"),
            "--base-url",
            f"http://127.0.0.1:{server.server_port}",
            "--candidates",
            "2",
            "3",
            "--restart-command",
            f"{sys.executable} {restart_script}",
        )
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)

    assert result.returncode == 0
    assert result.stdout.splitlines() == [
        (
            "subtype=2 result=PASS protocol=cs2+udp "
            "bytes_received=50000 source_dimensions=864x480"
        ),
        (
            "subtype=3 result=PASS protocol=cs2+udp "
            "bytes_received=50000 source_dimensions=2560x1440"
        ),
        "recommended_subtype=3",
        "original_config_restored=true",
    ]
    assert config.read_text(encoding="utf-8") == original_text
    combined = result.stdout + result.stderr
    assert "xiaomi://" not in combined
    assert "V1:" not in combined
    assert "did=" not in combined
    assert "192.0.2.10" not in combined


def test_probe_rejects_malformed_config_without_leaking_content(
    tmp_path: Path,
) -> None:
    config = tmp_path / "go2rtc.yaml"
    config.write_text(
        'streams:\n  source: "xiaomi://123:cn@192.0.2.10?did=456\n',
        encoding="utf-8",
    )

    result = run_cli(
        "probe-subtypes",
        "--config",
        str(config),
        "--backups",
        str(tmp_path / "backups"),
        "--base-url",
        "http://127.0.0.1:1984",
        "--candidates",
        "0",
        "--restart-command",
        f"{sys.executable} -c pass",
    )

    assert result.returncode == 2
    assert result.stderr.strip() == "SOURCE_NOT_CONFIGURED"
    combined = result.stdout + result.stderr
    assert "xiaomi://" not in combined
    assert "did=" not in combined
    assert "192.0.2.10" not in combined


def test_apply_subtype_keeps_verified_native_hd_with_derived_output(
    tmp_path: Path,
) -> None:
    config = tmp_path / "go2rtc.yaml"
    original_text = yaml.safe_dump(
        {
            "xiaomi": {"123": "V1:super-secret"},
            "streams": {
                "source": (
                    "xiaomi://123:cn@192.0.2.10?did=456&subtype=hd"
                    "&vendor_hint=keep"
                ),
                "live": (
                    "ffmpeg:source#video=mjpeg#width=1280"
                    "#height=720#raw=-r 10"
                ),
            },
        },
        sort_keys=False,
    )
    config.write_text(original_text, encoding="utf-8")
    config.chmod(0o600)
    restart_script = tmp_path / "restart.py"
    restart_script.write_text(
        "print('xiaomi://must-not-leak did=456 192.0.2.10')\n",
        encoding="utf-8",
    )
    server, thread = start_probe_server(config)
    try:
        result = run_cli(
            "apply-subtype",
            "--config",
            str(config),
            "--backups",
            str(tmp_path / "backups"),
            "--base-url",
            f"http://127.0.0.1:{server.server_port}",
            "--dashboard-url",
            f"http://127.0.0.1:{server.server_port}",
            "--subtype",
            "3",
            "--minimum-width",
            "1920",
            "--minimum-height",
            "1080",
            "--restart-command",
            f"{sys.executable} {restart_script}",
        )
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)

    assert result.returncode == 0
    assert result.stdout.splitlines() == [
        "result=PASS",
        "applied_subtype=3",
        "protocol=cs2+udp",
        "bytes_received=50000",
        "source_dimensions=2560x1440",
        "live_dimensions=1280x720",
        "original_config_restored=false",
    ]
    source = yaml.safe_load(config.read_text(encoding="utf-8"))["streams"]["source"]
    assert "subtype=3" in source
    assert "vendor_hint=keep" in source
    assert config.stat().st_mode & 0o777 == 0o600
    combined = result.stdout + result.stderr
    assert "xiaomi://" not in combined
    assert "V1:" not in combined
    assert "did=" not in combined
    assert "192.0.2.10" not in combined


def test_apply_subtype_restores_config_when_source_is_not_native_hd(
    tmp_path: Path,
) -> None:
    config = tmp_path / "go2rtc.yaml"
    original_text = yaml.safe_dump(
        {
            "xiaomi": {"123": "V1:super-secret"},
            "streams": {
                "source": "xiaomi://123:cn@192.0.2.10?did=456&subtype=hd",
                "live": (
                    "ffmpeg:source#video=mjpeg#width=1280"
                    "#height=720#raw=-r 10"
                ),
            },
        },
        sort_keys=False,
    )
    config.write_text(original_text, encoding="utf-8")
    restart_script = tmp_path / "restart.py"
    restart_script.write_text("pass\n", encoding="utf-8")
    server, thread = start_probe_server(config)
    try:
        result = run_cli(
            "apply-subtype",
            "--config",
            str(config),
            "--backups",
            str(tmp_path / "backups"),
            "--base-url",
            f"http://127.0.0.1:{server.server_port}",
            "--dashboard-url",
            f"http://127.0.0.1:{server.server_port}",
            "--subtype",
            "2",
            "--minimum-width",
            "1920",
            "--minimum-height",
            "1080",
            "--restart-command",
            f"{sys.executable} {restart_script}",
        )
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)

    assert result.returncode == 2
    assert result.stdout.splitlines() == [
        "result=SOURCE_DIMENSIONS_TOO_LOW",
        "applied_subtype=2",
        "protocol=cs2+udp",
        "bytes_received=50000",
        "source_dimensions=864x480",
        "live_dimensions=1280x720",
        "original_config_restored=true",
    ]
    assert config.read_text(encoding="utf-8") == original_text
