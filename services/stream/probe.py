from __future__ import annotations

import json
import subprocess
from collections.abc import Callable
from fractions import Fraction
from typing import Any, Protocol

from packages.contracts.stream import AudioHealth, StreamHealth, VideoHealth


class CompletedProcessLike(Protocol):
    returncode: int
    stdout: str
    stderr: str


Runner = Callable[..., CompletedProcessLike]


class StreamProbeError(RuntimeError):
    """Base class for stream probe failures."""


class ProbeExecutionError(StreamProbeError):
    """ffprobe executed but returned a non-zero exit code."""


class ProbePayloadError(StreamProbeError):
    """ffprobe output did not contain a usable JSON payload."""


class ProbeTimeoutError(StreamProbeError):
    """ffprobe exceeded the configured timeout."""


def _parse_float(value: Any) -> float | None:
    if value in (None, "", "N/A"):
        return None
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed >= 0 else None


def _parse_positive_int(value: Any) -> int | None:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return None
    return parsed if parsed > 0 else None


def _parse_rate(value: Any) -> float:
    if value in (None, "", "N/A", "0/0"):
        return 0.0
    try:
        return float(Fraction(str(value)))
    except (ValueError, ZeroDivisionError):
        return 0.0


def _safe_stderr(stderr: str) -> str:
    text = " ".join(stderr.strip().split())
    if not text:
        return "unknown ffprobe error"
    return text[-240:]


class StreamProbe:
    def __init__(
        self,
        *,
        executable: str = "ffprobe",
        timeout_seconds: float = 10.0,
        runner: Runner = subprocess.run,
    ) -> None:
        if timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")
        self._executable = executable
        self._timeout_seconds = timeout_seconds
        self._runner = runner

    def build_command(self, source: str) -> list[str]:
        if not source:
            raise ValueError("source must not be empty")
        return [
            self._executable,
            "-v",
            "error",
            "-show_streams",
            "-show_format",
            "-of",
            "json",
            source,
        ]

    def probe(self, source: str) -> StreamHealth:
        command = self.build_command(source)
        try:
            completed = self._runner(
                command,
                capture_output=True,
                text=True,
                timeout=self._timeout_seconds,
                check=False,
                shell=False,
            )
        except subprocess.TimeoutExpired as exc:
            raise ProbeTimeoutError(
                f"ffprobe timed out after {self._timeout_seconds:g} seconds"
            ) from exc

        if completed.returncode != 0:
            raise ProbeExecutionError(f"ffprobe failed: {_safe_stderr(completed.stderr)}")

        try:
            payload = json.loads(completed.stdout)
        except (TypeError, json.JSONDecodeError) as exc:
            raise ProbePayloadError("ffprobe did not return valid JSON") from exc

        if not isinstance(payload, dict):
            raise ProbePayloadError("ffprobe JSON root must be an object")
        raw_streams = payload.get("streams")
        if not isinstance(raw_streams, list):
            raise ProbePayloadError("ffprobe JSON must contain a streams array")

        video: VideoHealth | None = None
        audio: AudioHealth | None = None

        for raw in raw_streams:
            if not isinstance(raw, dict):
                continue
            codec_type = raw.get("codec_type")
            if codec_type == "video" and video is None:
                codec = str(raw.get("codec_name") or "").strip()
                width = _parse_positive_int(raw.get("width"))
                height = _parse_positive_int(raw.get("height"))
                if codec and width is not None and height is not None:
                    video = VideoHealth(
                        codec=codec,
                        width=width,
                        height=height,
                        fps=_parse_rate(raw.get("avg_frame_rate") or raw.get("r_frame_rate")),
                    )
            elif codec_type == "audio" and audio is None:
                codec = str(raw.get("codec_name") or "").strip()
                if codec:
                    audio = AudioHealth(
                        codec=codec,
                        sample_rate=_parse_positive_int(raw.get("sample_rate")),
                        channels=_parse_positive_int(raw.get("channels")),
                    )

        raw_format = payload.get("format")
        duration = (
            _parse_float(raw_format.get("duration"))
            if isinstance(raw_format, dict)
            else None
        )
        return StreamHealth(
            healthy=video is not None,
            video=video,
            audio=audio,
            duration_seconds=duration,
        )
