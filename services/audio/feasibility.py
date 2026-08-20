from __future__ import annotations

import subprocess
from collections.abc import Callable
from dataclasses import dataclass
from typing import Protocol

from packages.contracts.audio import AudioFailureReason
from packages.contracts.settings import AudioSettings
from packages.contracts.stream import StreamHealth
from services.audio.source import DecoderRead, FixedAudioDecoder
from services.stream.probe import StreamProbe, StreamProbeError


SOURCE_URL = "rtsp://127.0.0.1:8554/source"
AUDIO_ANALYSIS_URL = "rtsp://127.0.0.1:8554/audio_analysis"

_REASON_CODES = frozenset(
    {
        "source_media_unavailable",
        "source_audio_unsupported",
        "audio_alias_unsupported",
        "audio_decode_unavailable",
        "audio_decode_stalled",
        "audio_decode_failed",
        "synthetic_opus_failed",
        "internal_error",
    }
)


class AudioFeasibilityError(RuntimeError):
    def __init__(self, reason: str) -> None:
        super().__init__(reason if reason in _REASON_CODES else "internal_error")


class MediaProbe(Protocol):
    def probe(self, source: str) -> StreamHealth: ...


class AudioDecoder(Protocol):
    def read(self, max_bytes: int) -> DecoderRead: ...

    def close(self) -> None: ...


@dataclass(frozen=True)
class AudioMediaResult:
    source_video_codec: str
    source_audio_codec: str
    alias_audio_codec: str
    sample_rate_hz: int
    channels: int


@dataclass(frozen=True)
class AudioReceiveResult:
    decoded_seconds: float
    decoded_bytes: int
    chunk_count: int


@dataclass(frozen=True)
class SyntheticOpusResult:
    opus_bytes: int
    pcm_bytes: int
    decoded_seconds: float


def inspect_audio_media(*, probe: MediaProbe | None = None) -> AudioMediaResult:
    active_probe = probe or StreamProbe(timeout_seconds=10)
    try:
        source = active_probe.probe(SOURCE_URL)
        alias = active_probe.probe(AUDIO_ANALYSIS_URL)
    except StreamProbeError as exc:
        raise AudioFeasibilityError("source_media_unavailable") from exc

    if source.video is None or source.video.codec.lower() not in {"hevc", "h265"}:
        raise AudioFeasibilityError("source_media_unavailable")

    def supported_opus(audio: object) -> bool:
        return bool(
            audio is not None
            and getattr(audio, "codec", "").lower() == "opus"
            and getattr(audio, "sample_rate", None)
            in {8_000, 12_000, 16_000, 24_000, 48_000}
            and getattr(audio, "channels", None) in {1, 2}
        )

    if not supported_opus(source.audio):
        raise AudioFeasibilityError("source_audio_unsupported")
    if not supported_opus(alias.audio):
        raise AudioFeasibilityError("audio_alias_unsupported")

    assert source.audio is not None
    assert alias.audio is not None

    return AudioMediaResult(
        source_video_codec=source.video.codec.lower(),
        source_audio_codec=source.audio.codec.lower(),
        alias_audio_codec=alias.audio.codec.lower(),
        sample_rate_hz=alias.audio.sample_rate,
        channels=alias.audio.channels,
    )


DecoderFactory = Callable[[AudioSettings], AudioDecoder]


def receive_audio_window(
    *,
    duration_seconds: int,
    settings: AudioSettings | None = None,
    decoder_factory: DecoderFactory = FixedAudioDecoder,
) -> AudioReceiveResult:
    if duration_seconds < 1 or duration_seconds > 600:
        raise ValueError("duration_seconds must be between 1 and 600")
    active_settings = settings or AudioSettings()
    bytes_per_second = (
        active_settings.sample_rate_hz
        * active_settings.channels
        * active_settings.sample_width_bytes
    )
    target_bytes = bytes_per_second * duration_seconds
    decoded_bytes = 0
    chunk_count = 0
    decoder = decoder_factory(active_settings)
    try:
        while decoded_bytes < target_bytes:
            read = decoder.read(min(bytes_per_second, target_bytes - decoded_bytes))
            if read.failure_reason is not None:
                if read.failure_reason is AudioFailureReason.AUDIO_SOURCE_UNAVAILABLE:
                    reason = "audio_decode_unavailable"
                elif read.failure_reason is AudioFailureReason.AUDIO_STALE:
                    reason = "audio_decode_stalled"
                else:
                    reason = "audio_decode_failed"
                raise AudioFeasibilityError(reason)
            if not read.pcm:
                raise AudioFeasibilityError("audio_decode_stalled")
            decoded_bytes += len(read.pcm)
            chunk_count += 1
    finally:
        decoder.close()

    return AudioReceiveResult(
        decoded_seconds=decoded_bytes / bytes_per_second,
        decoded_bytes=decoded_bytes,
        chunk_count=chunk_count,
    )


BinaryRunner = Callable[..., subprocess.CompletedProcess[bytes]]


def verify_synthetic_opus(
    *, runner: BinaryRunner = subprocess.run
) -> SyntheticOpusResult:
    encode_command = [
        "ffmpeg",
        "-nostdin",
        "-hide_banner",
        "-loglevel",
        "error",
        "-f",
        "lavfi",
        "-i",
        "sine=frequency=440:sample_rate=16000:duration=1",
        "-ac",
        "1",
        "-c:a",
        "libopus",
        "-f",
        "opus",
        "pipe:1",
    ]
    decode_command = [
        "ffmpeg",
        "-nostdin",
        "-hide_banner",
        "-loglevel",
        "error",
        "-i",
        "pipe:0",
        "-map",
        "0:a:0",
        "-vn",
        "-ac",
        "1",
        "-ar",
        "16000",
        "-f",
        "s16le",
        "pipe:1",
    ]
    try:
        encoded = runner(
            encode_command,
            capture_output=True,
            check=False,
            timeout=10,
            shell=False,
        )
        if encoded.returncode != 0 or not encoded.stdout:
            raise AudioFeasibilityError("synthetic_opus_failed")
        decoded = runner(
            decode_command,
            input=encoded.stdout,
            capture_output=True,
            check=False,
            timeout=10,
            shell=False,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        raise AudioFeasibilityError("synthetic_opus_failed") from exc

    pcm_bytes = len(decoded.stdout)
    if decoded.returncode != 0 or pcm_bytes < 28_800 or pcm_bytes % 2:
        raise AudioFeasibilityError("synthetic_opus_failed")
    return SyntheticOpusResult(
        opus_bytes=len(encoded.stdout),
        pcm_bytes=pcm_bytes,
        decoded_seconds=pcm_bytes / 32_000,
    )
