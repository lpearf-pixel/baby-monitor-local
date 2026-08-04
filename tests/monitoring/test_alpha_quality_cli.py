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
            source = yaml.safe_load(self.config_path.read_text(encoding="utf-8"))[
                "streams"
            ]["source"]
            subtype = dict(parse_qs(urlsplit(source).query))["subtype"][0]
            dimensions = {"2": (864, 480), "3": (2560, 1440)}[subtype]
            self.send_response(200)
            self.send_header("Content-Type", "image/jpeg")
            self.end_headers()
            self.wfile.write(jpeg(*dimensions))
            return
        self.send_response(404)
        self.end_headers()

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
    ]
    combined = result.stdout + result.stderr
    assert "xiaomi://" not in combined
    assert "V1:" not in combined
    assert "192.0.2.10" not in combined
    assert "did=456" not in combined


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
