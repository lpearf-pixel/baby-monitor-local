from __future__ import annotations

import importlib
from collections import deque
from datetime import UTC, datetime, timedelta
from io import BytesIO
from pathlib import Path

import pytest
from PIL import Image


NOW = datetime(2026, 8, 28, 12, 0, tzinfo=UTC)


def source_module():
    return importlib.import_module("services.stream.file_frame_source")


def jpeg(color: str = "red", *, size: tuple[int, int] = (64, 48)) -> bytes:
    output = BytesIO()
    Image.new("RGB", size, color).save(output, format="JPEG")
    return output.getvalue()


class FakeDecoder:
    def __init__(
        self,
        chunks: list[bytes | BaseException],
        *,
        returncode: int = 0,
    ) -> None:
        self.chunks = deque(chunks)
        self.returncode = returncode
        self.exhausted = False
        self.terminated = False
        self.killed = False
        self.closed = False
        self.read_timeouts: list[float] = []
        self.wait_timeouts: list[float] = []

    def read(self, size: int, *, timeout_seconds: float) -> bytes:
        self.read_timeouts.append(timeout_seconds)
        if not self.chunks:
            self.exhausted = True
            return b""
        item = self.chunks.popleft()
        if isinstance(item, BaseException):
            raise item
        if len(item) > size:
            self.chunks.appendleft(item[size:])
            return item[:size]
        return item

    def poll(self) -> int | None:
        return self.returncode if self.exhausted else None

    def wait(self, *, timeout_seconds: float) -> int:
        self.wait_timeouts.append(timeout_seconds)
        self.exhausted = True
        return self.returncode

    def terminate(self) -> None:
        self.terminated = True

    def kill(self) -> None:
        self.killed = True

    def close(self) -> None:
        self.closed = True


class RecordingFactory:
    def __init__(self, decoder: FakeDecoder) -> None:
        self.decoder = decoder
        self.argv: list[tuple[str, ...]] = []

    def __call__(self, argv: tuple[str, ...]):
        self.argv.append(argv)
        return self.decoder


def media_file(tmp_path: Path) -> Path:
    path = tmp_path / "prepared.mkv"
    path.write_bytes(b"fixture")
    return path


def test_decoder_uses_fixed_video_only_mjpeg_argv(tmp_path: Path) -> None:
    module = source_module()
    decoder = FakeDecoder([jpeg()])
    factory = RecordingFactory(decoder)

    frames = tuple(
        module.FfmpegFileFrameSource(
            media_file(tmp_path),
            fps=5,
            decoder_factory=factory,
        ).iter_frames(started_at=NOW)
    )

    assert len(frames) == 1
    assert factory.argv == [
        (
            "ffmpeg",
            "-nostdin",
            "-hide_banner",
            "-loglevel",
            "error",
            "-i",
            str(tmp_path / "prepared.mkv"),
            "-map",
            "0:v:0",
            "-an",
            "-vf",
            "fps=5",
            "-fps_mode",
            "cfr",
            "-c:v",
            "mjpeg",
            "-f",
            "image2pipe",
            "pipe:1",
        )
    ]


def test_split_jpegs_use_deterministic_media_timestamps(tmp_path: Path) -> None:
    module = source_module()
    payload = jpeg("red") + jpeg("green") + jpeg("blue")
    decoder = FakeDecoder([payload[:37], payload[37:911], payload[911:]])

    frames = tuple(
        module.FfmpegFileFrameSource(
            media_file(tmp_path),
            fps=5,
            decoder_factory=RecordingFactory(decoder),
        ).iter_frames(started_at=NOW, pace=False)
    )

    assert [frame.captured_at for frame in frames] == [
        NOW,
        NOW + timedelta(milliseconds=200),
        NOW + timedelta(milliseconds=400),
    ]
    assert {(frame.width, frame.height) for frame in frames} == {(64, 48)}
    assert decoder.closed is True
    assert decoder.terminated is False


def test_pacing_never_changes_media_timestamps(tmp_path: Path) -> None:
    module = source_module()
    decoder = FakeDecoder([jpeg("red") + jpeg("blue")])
    ticks = iter([10.0, 10.0, 10.05])
    sleeps: list[float] = []
    source = module.FfmpegFileFrameSource(
        media_file(tmp_path),
        fps=5,
        decoder_factory=RecordingFactory(decoder),
        monotonic=lambda: next(ticks),
        sleep=sleeps.append,
    )

    frames = tuple(source.iter_frames(started_at=NOW, pace=True))

    assert [frame.captured_at for frame in frames] == [
        NOW,
        NOW + timedelta(milliseconds=200),
    ]
    assert sleeps == [pytest.approx(0.15)]


def test_naive_or_unsupported_inputs_fail_before_launch(tmp_path: Path) -> None:
    module = source_module()
    factory = RecordingFactory(FakeDecoder([jpeg()]))

    with pytest.raises(ValueError, match="fps"):
        module.FfmpegFileFrameSource(
            media_file(tmp_path), fps=2, decoder_factory=factory
        )
    source = module.FfmpegFileFrameSource(
        media_file(tmp_path), fps=1, decoder_factory=factory
    )
    with pytest.raises(ValueError, match="timezone-aware"):
        tuple(source.iter_frames(started_at=datetime(2026, 8, 28)))

    assert factory.argv == []


@pytest.mark.parametrize(
    ("chunks", "returncode", "reason"),
    [
        ([b"not-a-jpeg"], 0, "file_frame_invalid"),
        ([b"\xff\xd8partial"], 0, "file_frame_invalid"),
        ([], 0, "file_decoder_empty"),
        ([jpeg()], 7, "file_decoder_failed"),
    ],
)
def test_malformed_early_eof_or_nonzero_exit_fails_closed(
    tmp_path: Path,
    chunks: list[bytes],
    returncode: int,
    reason: str,
) -> None:
    module = source_module()
    decoder = FakeDecoder(chunks, returncode=returncode)

    with pytest.raises(module.FileFrameSourceUnavailable, match=f"^{reason}$"):
        tuple(
            module.FfmpegFileFrameSource(
                media_file(tmp_path),
                fps=5,
                decoder_factory=RecordingFactory(decoder),
            ).iter_frames(started_at=NOW)
        )

    assert decoder.closed is True


def test_oversized_unterminated_frame_is_bounded_and_child_is_reaped(
    tmp_path: Path,
) -> None:
    module = source_module()
    decoder = FakeDecoder([b"\xff\xd8" + b"x" * module.MAX_FILE_FRAME_BYTES])

    with pytest.raises(
        module.FileFrameSourceUnavailable,
        match="^file_frame_too_large$",
    ):
        tuple(
            module.FfmpegFileFrameSource(
                media_file(tmp_path),
                fps=5,
                decoder_factory=RecordingFactory(decoder),
            ).iter_frames(started_at=NOW)
        )

    assert decoder.terminated is True
    assert decoder.closed is True


def test_read_timeout_terminates_and_redacts_underlying_error(tmp_path: Path) -> None:
    module = source_module()
    decoder = FakeDecoder([TimeoutError("/private/family/video")])

    with pytest.raises(module.FileFrameSourceUnavailable) as failure:
        tuple(
            module.FfmpegFileFrameSource(
                media_file(tmp_path),
                fps=5,
                decoder_factory=RecordingFactory(decoder),
            ).iter_frames(started_at=NOW)
        )

    assert str(failure.value) == "file_decoder_timeout"
    assert "/private" not in str(failure.value)
    assert decoder.terminated is True
    assert decoder.closed is True


def test_closing_iterator_terminates_the_single_decoder(tmp_path: Path) -> None:
    module = source_module()
    decoder = FakeDecoder([jpeg(), jpeg("blue")])
    source = module.FfmpegFileFrameSource(
        media_file(tmp_path),
        fps=5,
        decoder_factory=RecordingFactory(decoder),
    )
    iterator = source.iter_frames(started_at=NOW)

    assert next(iterator).width == 64
    iterator.close()

    assert decoder.terminated is True
    assert decoder.closed is True
