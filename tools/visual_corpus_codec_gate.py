from __future__ import annotations

import json
import os
import signal
import socket
import subprocess
import sys
import tempfile
import time
from collections.abc import Callable
from contextlib import AbstractContextManager
from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO, Literal, Protocol
from urllib.request import ProxyHandler, Request, build_opener


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

from packages.monitoring.go2rtc_build import (  # noqa: E402
    GO2RTC_COMMIT,
    read_metadata,
    sha256_file,
)
from services.stream.frame_source import (  # noqa: E402
    FrameSourceUnavailable,
    _validate_jpeg,
)


MAX_FRAME_BYTES = 16 * 1024 * 1024
DEFAULT_ATTEMPTS = 40
HTTP_TIMEOUT_SECONDS = 1.0
POLL_SECONDS = 0.25


@dataclass(frozen=True)
class CodecGateResult:
    status: Literal["PASS", "FAIL", "SKIP"]
    reason: str
    width: int = 0
    height: int = 0


class ProcessLike(Protocol):
    pid: int

    def poll(self) -> int | None: ...


ResponseOpener = Callable[[str, float], AbstractContextManager[BinaryIO]]
Spawn = Callable[..., ProcessLike]


def build_config(
    prepared: Path,
    *,
    api_port: int,
    rtsp_port: int,
    webrtc_port: int | None = None,
) -> str:
    ports = (api_port, rtsp_port, webrtc_port or rtsp_port + 1)
    if len(set(ports)) != 3 or any(not 1024 <= port <= 65535 for port in ports):
        raise ValueError("visual_corpus_codec_port_invalid")
    source = json.dumps(
        f"ffmpeg:{Path(prepared).absolute()}#video=copy",
        ensure_ascii=True,
    )
    return (
        "api:\n"
        f"  listen: \"127.0.0.1:{ports[0]}\"\n"
        "rtsp:\n"
        f"  listen: \"127.0.0.1:{ports[1]}\"\n"
        "webrtc:\n"
        f"  listen: \"127.0.0.1:{ports[2]}\"\n"
        "streams:\n"
        f"  corpus: {source}\n"
    )


def run_gate(
    *,
    binary: Path,
    prepared: Path,
    identity_check: Callable[[Path], bool] | None = None,
    spawn: Spawn = subprocess.Popen,
    opener: ResponseOpener | None = None,
    ports: tuple[int, int] | tuple[int, int, int] | None = None,
    terminate: Callable[[ProcessLike], None] | None = None,
    sleeper: Callable[[float], None] = time.sleep,
    attempts: int = DEFAULT_ATTEMPTS,
) -> CodecGateResult:
    binary = Path(binary)
    prepared = Path(prepared)
    if not binary.is_file() or not os.access(binary, os.X_OK):
        return CodecGateResult("SKIP", "visual_corpus_codec_binary_unavailable")
    if not prepared.is_file() or prepared.is_symlink():
        return CodecGateResult("SKIP", "visual_corpus_codec_media_unavailable")
    if (identity_check or _installed_identity_matches)(binary) is not True:
        return CodecGateResult("FAIL", "visual_corpus_codec_identity_mismatch")
    if attempts < 1 or attempts > DEFAULT_ATTEMPTS:
        return CodecGateResult("FAIL", "visual_corpus_codec_configuration_invalid")
    selected_ports = ports or _select_ports()
    if len(selected_ports) == 2:
        selected_ports = (*selected_ports, _select_port(exclude=set(selected_ports)))
    if len(set(selected_ports)) != 3:
        return CodecGateResult("SKIP", "visual_corpus_codec_bind_unavailable")
    open_response = opener or _default_opener
    stop_owned = terminate or _terminate_owned
    process: ProcessLike | None = None
    try:
        with tempfile.TemporaryDirectory(prefix="visual-corpus-go2rtc-") as temporary:
            config = Path(temporary) / "go2rtc.yaml"
            config.write_text(
                build_config(
                    prepared,
                    api_port=selected_ports[0],
                    rtsp_port=selected_ports[1],
                    webrtc_port=selected_ports[2],
                ),
                encoding="ascii",
            )
            config.chmod(0o600)
            process = spawn(
                (str(binary), "-config", str(config)),
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                start_new_session=True,
            )
            frame_url = (
                f"http://127.0.0.1:{selected_ports[0]}"
                "/api/frame.jpeg?src=corpus"
            )
            for _attempt in range(attempts):
                if process.poll() is not None:
                    return CodecGateResult(
                        "FAIL",
                        "visual_corpus_codec_process_failed",
                    )
                try:
                    with open_response(frame_url, HTTP_TIMEOUT_SECONDS) as response:
                        if getattr(response, "status", None) != 200:
                            raise OSError
                        payload = response.read(MAX_FRAME_BYTES + 1)
                    if len(payload) > MAX_FRAME_BYTES:
                        raise FrameSourceUnavailable("frame_invalid")
                    width, height = _validate_jpeg(payload)
                    return CodecGateResult("PASS", "ok", width, height)
                except (OSError, TimeoutError, FrameSourceUnavailable):
                    sleeper(POLL_SECONDS)
            return CodecGateResult("FAIL", "visual_corpus_codec_decode_failed")
    except (OSError, ValueError):
        return CodecGateResult("SKIP", "visual_corpus_codec_bind_unavailable")
    finally:
        if process is not None:
            stop_owned(process)


def main() -> int:
    binary = _installed_binary()
    prepared = _prepared_hevc_clip()
    result = run_gate(binary=binary, prepared=prepared)
    print(f"result={result.status}")
    print(f"reason={result.reason}")
    if result.status == "PASS":
        print(f"decoded_width={result.width}")
        print(f"decoded_height={result.height}")
        print("camera_accessed=false")
        print("production_service_touched=false")
    return 0 if result.status in {"PASS", "SKIP"} else 2


def _default_opener(url: str, timeout: float) -> AbstractContextManager[BinaryIO]:
    request = Request(url, headers={"Accept": "image/jpeg"})
    return build_opener(ProxyHandler({})).open(request, timeout=timeout)  # type: ignore[return-value]


def _installed_binary() -> Path:
    deployment_root = _deployment_root()
    raw = deployment_root / ".local/bin/go2rtc"
    app = deployment_root / ".local/Go2RTC.app/Contents/MacOS/go2rtc"
    return raw if raw.is_file() else app


def _prepared_hevc_clip() -> Path:
    candidates = tuple(
        sorted(
            (
                REPOSITORY_ROOT
                / "runtime/test-corpus/visual/prepared"
            ).glob("wide-01.xiaomi_source_hd.*.mkv")
        )
    )
    return candidates[0] if len(candidates) == 1 else Path("missing")


def _deployment_root() -> Path:
    try:
        completed = subprocess.run(
            ("git", "rev-parse", "--git-common-dir"),
            cwd=REPOSITORY_ROOT,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            timeout=5,
            check=False,
            text=True,
        )
        common = completed.stdout.strip()
        if completed.returncode != 0 or not common:
            return REPOSITORY_ROOT
        common_path = Path(common)
        if not common_path.is_absolute():
            common_path = REPOSITORY_ROOT / common_path
        return common_path.resolve().parent
    except (OSError, subprocess.TimeoutExpired):
        return REPOSITORY_ROOT


def _installed_identity_matches(binary: Path) -> bool:
    deployment_root = _deployment_root()
    metadata = read_metadata(deployment_root / "runtime/build/go2rtc.json")
    patch = REPOSITORY_ROOT / "patches/go2rtc-macos-hybrid-hd.patch"
    try:
        return bool(
            metadata is not None
            and metadata.upstream_commit == GO2RTC_COMMIT
            and metadata.patch_sha256 == sha256_file(patch)
            and metadata.binary_sha256 == sha256_file(binary)
        )
    except OSError:
        return False


def _select_ports() -> tuple[int, int, int]:
    selected: list[int] = []
    for _index in range(3):
        selected.append(_select_port(exclude=set(selected)))
    return tuple(selected)  # type: ignore[return-value]


def _select_port(*, exclude: set[int]) -> int:
    for _attempt in range(8):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as probe:
            probe.bind(("127.0.0.1", 0))
            port = int(probe.getsockname()[1])
        if port not in exclude:
            return port
    raise OSError("visual_corpus_codec_bind_unavailable")


def _terminate_owned(process: ProcessLike) -> None:
    if process.poll() is not None:
        return
    try:
        os.killpg(process.pid, signal.SIGTERM)
    except OSError:
        return
    wait = getattr(process, "wait", None)
    if not callable(wait):
        return
    try:
        wait(timeout=2)
        return
    except (OSError, subprocess.TimeoutExpired):
        pass
    try:
        os.killpg(process.pid, signal.SIGKILL)
    except OSError:
        return
    try:
        wait(timeout=2)
    except (OSError, subprocess.TimeoutExpired):
        return


if __name__ == "__main__":
    raise SystemExit(main())
