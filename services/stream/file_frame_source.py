from __future__ import annotations

import os
import select
import signal
import stat
import subprocess
import time
from collections.abc import Callable, Iterator
from datetime import datetime, timedelta
from pathlib import Path
from typing import Literal, Protocol

from services.stream.frame_source import (
    CapturedFrame,
    FrameSourceUnavailable,
    _validate_jpeg,
)


MAX_FILE_FRAME_BYTES = 16 * 1024 * 1024
READ_CHUNK_BYTES = 64 * 1024
READ_TIMEOUT_SECONDS = 5.0
SETTLE_TIMEOUT_SECONDS = 2.0


class FileFrameSourceUnavailable(RuntimeError):
    """A stable, redacted file-replay failure."""


class DecoderProcess(Protocol):
    def read(self, size: int, *, timeout_seconds: float) -> bytes: ...

    def poll(self) -> int | None: ...

    def wait(self, *, timeout_seconds: float) -> int: ...

    def terminate(self) -> None: ...

    def kill(self) -> None: ...

    def close(self) -> None: ...


DecoderFactory = Callable[[tuple[str, ...]], DecoderProcess]


class _SubprocessDecoder:
    def __init__(self, argv: tuple[str, ...]) -> None:
        try:
            self._child = subprocess.Popen(
                argv,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                start_new_session=True,
            )
        except OSError as exc:
            raise FileFrameSourceUnavailable("file_decoder_unavailable") from exc
        if self._child.stdout is None:
            self._terminate_group(signal.SIGKILL)
            raise FileFrameSourceUnavailable("file_decoder_unavailable")

    def read(self, size: int, *, timeout_seconds: float) -> bytes:
        stdout = self._child.stdout
        if stdout is None:
            return b""
        try:
            readable, _, _ = select.select([stdout], [], [], timeout_seconds)
        except (OSError, ValueError) as exc:
            raise FileFrameSourceUnavailable("file_decoder_failed") from exc
        if not readable:
            raise TimeoutError
        try:
            return os.read(stdout.fileno(), size)
        except OSError as exc:
            raise FileFrameSourceUnavailable("file_decoder_failed") from exc

    def poll(self) -> int | None:
        return self._child.poll()

    def wait(self, *, timeout_seconds: float) -> int:
        try:
            return self._child.wait(timeout=timeout_seconds)
        except subprocess.TimeoutExpired as exc:
            raise TimeoutError from exc

    def terminate(self) -> None:
        self._terminate_group(signal.SIGTERM)

    def kill(self) -> None:
        self._terminate_group(signal.SIGKILL)

    def close(self) -> None:
        if self._child.stdout is not None:
            self._child.stdout.close()

    def _terminate_group(self, requested_signal: signal.Signals) -> None:
        if self._child.poll() is not None:
            return
        try:
            os.killpg(self._child.pid, requested_signal)
        except OSError:
            return


def _default_decoder_factory(argv: tuple[str, ...]) -> DecoderProcess:
    return _SubprocessDecoder(argv)


class FfmpegFileFrameSource:
    def __init__(
        self,
        path: Path,
        *,
        fps: Literal[1, 5, 10],
        decoder_factory: DecoderFactory = _default_decoder_factory,
        monotonic: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        if fps not in {1, 5, 10}:
            raise ValueError("fps must be one of 1, 5 or 10")
        candidate = Path(path)
        try:
            info = candidate.lstat()
        except OSError as exc:
            raise ValueError("media path must be a regular file") from exc
        if not stat.S_ISREG(info.st_mode):
            raise ValueError("media path must be a regular file")
        self._path = candidate
        self._fps = fps
        self._decoder_factory = decoder_factory
        self._monotonic = monotonic
        self._sleep = sleep

    def iter_frames(
        self,
        *,
        started_at: datetime,
        pace: bool = False,
    ) -> Iterator[CapturedFrame]:
        if started_at.tzinfo is None or started_at.utcoffset() is None:
            raise ValueError("started_at must be timezone-aware")
        decoder = self._launch()
        completed = False
        frame_index = 0
        buffer = bytearray()
        pacing_origin = self._monotonic() if pace else 0.0
        try:
            while True:
                frame = _pop_jpeg(buffer)
                if frame is not None:
                    try:
                        width, height = _validate_jpeg(frame)
                    except FrameSourceUnavailable as exc:
                        raise FileFrameSourceUnavailable("file_frame_invalid") from exc
                    if pace:
                        target = pacing_origin + frame_index / self._fps
                        remaining = target - self._monotonic()
                        if remaining > 0:
                            self._sleep(remaining)
                    yield CapturedFrame(
                        jpeg=frame,
                        captured_at=started_at
                        + timedelta(seconds=frame_index / self._fps),
                        width=width,
                        height=height,
                    )
                    frame_index += 1
                    continue

                try:
                    chunk = decoder.read(
                        READ_CHUNK_BYTES,
                        timeout_seconds=READ_TIMEOUT_SECONDS,
                    )
                except TimeoutError as exc:
                    raise FileFrameSourceUnavailable("file_decoder_timeout") from exc
                except FileFrameSourceUnavailable:
                    raise
                except Exception as exc:
                    raise FileFrameSourceUnavailable("file_decoder_failed") from exc
                if chunk:
                    buffer.extend(chunk)
                    if len(buffer) > MAX_FILE_FRAME_BYTES:
                        raise FileFrameSourceUnavailable("file_frame_too_large")
                    continue

                returncode = _wait_for_exit(decoder)
                completed = True
                if buffer:
                    raise FileFrameSourceUnavailable("file_frame_invalid")
                if returncode != 0:
                    raise FileFrameSourceUnavailable("file_decoder_failed")
                if frame_index == 0:
                    raise FileFrameSourceUnavailable("file_decoder_empty")
                return
        finally:
            if not completed and decoder.poll() is None:
                _terminate_decoder(decoder)
            decoder.close()

    def _launch(self) -> DecoderProcess:
        argv = (
            "ffmpeg",
            "-nostdin",
            "-hide_banner",
            "-loglevel",
            "error",
            "-i",
            str(self._path),
            "-map",
            "0:v:0",
            "-an",
            "-vf",
            f"fps={self._fps}",
            "-fps_mode",
            "cfr",
            "-c:v",
            "mjpeg",
            "-f",
            "image2pipe",
            "pipe:1",
        )
        try:
            return self._decoder_factory(argv)
        except FileFrameSourceUnavailable:
            raise
        except Exception as exc:
            raise FileFrameSourceUnavailable("file_decoder_unavailable") from exc


def _pop_jpeg(buffer: bytearray) -> bytes | None:
    if not buffer:
        return None
    if not buffer.startswith(b"\xff\xd8"):
        if len(buffer) >= 2:
            raise FileFrameSourceUnavailable("file_frame_invalid")
        return None
    end = buffer.find(b"\xff\xd9", 2)
    if end < 0:
        return None
    end += 2
    frame = bytes(buffer[:end])
    del buffer[:end]
    return frame


def _wait_for_exit(decoder: DecoderProcess) -> int:
    try:
        return decoder.wait(timeout_seconds=SETTLE_TIMEOUT_SECONDS)
    except TimeoutError as exc:
        raise FileFrameSourceUnavailable("file_decoder_timeout") from exc


def _terminate_decoder(decoder: DecoderProcess) -> None:
    decoder.terminate()
    try:
        decoder.wait(timeout_seconds=SETTLE_TIMEOUT_SECONDS)
        return
    except TimeoutError:
        decoder.kill()
    try:
        decoder.wait(timeout_seconds=SETTLE_TIMEOUT_SECONDS)
    except TimeoutError:
        return
