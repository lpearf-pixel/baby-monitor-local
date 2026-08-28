from __future__ import annotations

from contextlib import contextmanager
from io import BytesIO
from pathlib import Path

from PIL import Image


def module():
    from tools import visual_corpus_codec_gate

    return visual_corpus_codec_gate


def jpeg() -> bytes:
    output = BytesIO()
    Image.new("RGB", (64, 36), (10, 20, 30)).save(output, format="JPEG")
    return output.getvalue()


def test_generated_config_is_loopback_local_file_only(tmp_path: Path) -> None:
    media = tmp_path / "wide-01.xiaomi_source_hd.0123456789abcdef.mkv"
    config = module().build_config(media, api_port=31001, rtsp_port=31002)

    assert 'listen: "127.0.0.1:31001"' in config
    assert 'listen: "127.0.0.1:31002"' in config
    assert "ffmpeg:" in config
    assert str(media) in config
    assert not any(
        token in config.lower()
        for token in ("xiaomi:", "miss:", "cs2:", "password", "token", "0.0.0.0")
    )


class Response:
    status = 200

    def __init__(self, payload: bytes) -> None:
        self.payload = payload

    def read(self, size: int = -1) -> bytes:
        return self.payload[:size]

    def __enter__(self):
        return self

    def __exit__(self, *_args: object) -> None:
        return None


class Process:
    pid = 4321

    def __init__(self) -> None:
        self.terminated = False

    def poll(self):
        return None


def executable(path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"binary")
    path.chmod(0o700)
    return path


def media(path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"hevc")
    path.chmod(0o600)
    return path


def test_gate_starts_owned_binary_decodes_frame_and_tears_down(tmp_path: Path) -> None:
    binary = executable(tmp_path / "Go2RTC.app/Contents/MacOS/go2rtc")
    prepared = media(
        tmp_path / "wide-01.xiaomi_source_hd.0123456789abcdef.mkv"
    )
    process = Process()
    observed: dict[str, object] = {}

    def spawn(argv, **kwargs):
        observed["argv"] = tuple(argv)
        observed["config"] = Path(argv[2]).read_text(encoding="ascii")
        observed["kwargs"] = kwargs
        return process

    @contextmanager
    def open_response(url: str, _timeout: float):
        observed.setdefault("urls", []).append(url)
        yield Response(jpeg())

    result = module().run_gate(
        binary=binary,
        prepared=prepared,
        identity_check=lambda _binary: True,
        spawn=spawn,
        opener=open_response,
        ports=(31001, 31002, 31003),
        terminate=lambda owned: setattr(owned, "terminated", True),
        sleeper=lambda _seconds: None,
    )

    assert result.status == "PASS"
    assert result.reason == "ok"
    assert result.width == 64
    assert result.height == 36
    assert observed["argv"][0] == str(binary)
    assert observed["argv"][1] == "-config"
    assert "127.0.0.1:31001" in observed["config"]
    assert process.terminated is True


def test_identity_mismatch_fails_before_start(tmp_path: Path) -> None:
    calls: list[object] = []
    result = module().run_gate(
        binary=executable(tmp_path / "go2rtc"),
        prepared=media(tmp_path / "wide-01.xiaomi_source_hd.abc.mkv"),
        identity_check=lambda _binary: False,
        spawn=lambda *_args, **_kwargs: calls.append("spawn"),
        ports=(31001, 31002, 31003),
    )

    assert result.status == "FAIL"
    assert result.reason == "visual_corpus_codec_identity_mismatch"
    assert calls == []


def test_missing_binary_or_media_is_precise_skip(tmp_path: Path) -> None:
    missing_binary = module().run_gate(
        binary=tmp_path / "missing-go2rtc",
        prepared=media(tmp_path / "clip.mkv"),
        ports=(31001, 31002),
    )
    missing_media = module().run_gate(
        binary=executable(tmp_path / "go2rtc"),
        prepared=tmp_path / "missing.mkv",
        ports=(31001, 31002),
    )

    assert (missing_binary.status, missing_binary.reason) == (
        "SKIP",
        "visual_corpus_codec_binary_unavailable",
    )
    assert (missing_media.status, missing_media.reason) == (
        "SKIP",
        "visual_corpus_codec_media_unavailable",
    )


def test_decode_timeout_tears_down_only_owned_process(tmp_path: Path) -> None:
    process = Process()

    @contextmanager
    def unavailable(_url: str, _timeout: float):
        raise OSError("private endpoint")
        yield

    result = module().run_gate(
        binary=executable(tmp_path / "go2rtc"),
        prepared=media(tmp_path / "wide-01.xiaomi_source_hd.abc.mkv"),
        identity_check=lambda _binary: True,
        spawn=lambda *_args, **_kwargs: process,
        opener=unavailable,
        ports=(31001, 31002, 31003),
        terminate=lambda owned: setattr(owned, "terminated", True),
        sleeper=lambda _seconds: None,
        attempts=2,
    )

    assert result.status == "FAIL"
    assert result.reason == "visual_corpus_codec_decode_failed"
    assert process.terminated is True
