from __future__ import annotations

import subprocess
from dataclasses import dataclass

import pytest

from packages.contracts.audio import AudioFailureReason
from packages.contracts.settings import AudioSettings
from packages.contracts.stream import AudioHealth, StreamHealth, VideoHealth
from services.audio.feasibility import (
    AUDIO_ANALYSIS_URL,
    SOURCE_URL,
    AudioFeasibilityError,
    inspect_audio_media,
    receive_audio_window,
    verify_synthetic_opus,
)
from services.audio.source import DecoderRead


class MediaProbe:
    def __init__(self, results: dict[str, StreamHealth]) -> None:
        self.results = results
        self.sources: list[str] = []

    def probe(self, source: str) -> StreamHealth:
        self.sources.append(source)
        return self.results[source]


def stream_health(*, video: bool, audio: bool = True) -> StreamHealth:
    return StreamHealth(
        healthy=video,
        video=(
            VideoHealth(codec="hevc", width=2560, height=1440, fps=15)
            if video
            else None
        ),
        audio=(
            AudioHealth(codec="opus", sample_rate=16_000, channels=1)
            if audio
            else None
        ),
    )


def test_media_inspection_requires_source_and_alias_opus_contract() -> None:
    probe = MediaProbe(
        {
            SOURCE_URL: stream_health(video=True),
            AUDIO_ANALYSIS_URL: stream_health(video=False),
        }
    )

    result = inspect_audio_media(probe=probe)

    assert probe.sources == [SOURCE_URL, AUDIO_ANALYSIS_URL]
    assert result.source_video_codec == "hevc"
    assert result.source_audio_codec == "opus"
    assert result.alias_audio_codec == "opus"
    assert result.sample_rate_hz == 16_000
    assert result.channels == 1
    assert SOURCE_URL not in repr(result)
    assert AUDIO_ANALYSIS_URL not in repr(result)


def test_media_inspection_fails_closed_when_alias_contract_is_wrong() -> None:
    probe = MediaProbe(
        {
            SOURCE_URL: stream_health(video=True),
            AUDIO_ANALYSIS_URL: StreamHealth(
                healthy=False,
                video=None,
                audio=AudioHealth(codec="aac", sample_rate=48_000, channels=2),
            ),
        }
    )

    with pytest.raises(AudioFeasibilityError, match="audio_alias_unsupported"):
        inspect_audio_media(probe=probe)


def test_media_inspection_accepts_supported_xiaomi_opus_clock_and_channels() -> None:
    inbound = AudioHealth(codec="opus", sample_rate=48_000, channels=2)
    probe = MediaProbe(
        {
            SOURCE_URL: StreamHealth(
                healthy=True,
                video=VideoHealth(
                    codec="hevc", width=2560, height=1440, fps=20
                ),
                audio=inbound,
            ),
            AUDIO_ANALYSIS_URL: StreamHealth(
                healthy=False,
                video=None,
                audio=inbound,
            ),
        }
    )

    result = inspect_audio_media(probe=probe)

    assert result.sample_rate_hz == 48_000
    assert result.channels == 2


class Decoder:
    def __init__(self, reads: list[DecoderRead]) -> None:
        self.reads = reads
        self.closed = False

    def read(self, _max_bytes: int) -> DecoderRead:
        return self.reads.pop(0)

    def close(self) -> None:
        self.closed = True


def test_receive_window_discards_pcm_and_always_closes_decoder() -> None:
    decoder = Decoder([DecoderRead(b"\x00\x00" * 16_000)])

    result = receive_audio_window(
        duration_seconds=1,
        settings=AudioSettings(),
        decoder_factory=lambda _settings: decoder,
    )

    assert result.decoded_seconds == 1.0
    assert result.decoded_bytes == 32_000
    assert result.chunk_count == 1
    assert decoder.closed is True
    assert not hasattr(result, "pcm")


def test_receive_window_maps_decoder_failure_to_stable_closed_reason() -> None:
    decoder = Decoder(
        [DecoderRead(b"", AudioFailureReason.AUDIO_SOURCE_UNAVAILABLE)]
    )

    with pytest.raises(AudioFeasibilityError, match="audio_decode_unavailable"):
        receive_audio_window(
            duration_seconds=1,
            settings=AudioSettings(),
            decoder_factory=lambda _settings: decoder,
        )

    assert decoder.closed is True


@dataclass
class Completed:
    returncode: int = 0
    stdout: bytes = b""
    stderr: bytes = b""


def test_synthetic_opus_round_trip_is_memory_only_and_uses_pcm_contract() -> None:
    calls: list[tuple[list[str], dict[str, object]]] = []

    def runner(command: list[str], **kwargs: object) -> Completed:
        calls.append((command, kwargs))
        if len(calls) == 1:
            return Completed(stdout=b"synthetic-opus")
        return Completed(stdout=b"\x00\x00" * 16_000)

    result = verify_synthetic_opus(runner=runner)

    assert result.opus_bytes == len(b"synthetic-opus")
    assert result.pcm_bytes == 32_000
    assert result.decoded_seconds == 1.0
    assert "libopus" in calls[0][0]
    assert calls[0][1]["capture_output"] is True
    assert calls[1][1]["input"] == b"synthetic-opus"
    assert calls[1][0][calls[1][0].index("-i") - 1] != "opus"
    assert calls[1][0][-1] == "pipe:1"
    assert all("/" not in argument for command, _ in calls for argument in command)


def test_synthetic_opus_failure_does_not_expose_ffmpeg_stderr() -> None:
    def runner(_command: list[str], **_kwargs: object) -> Completed:
        return Completed(returncode=1, stderr=b"private diagnostic")

    with pytest.raises(AudioFeasibilityError) as exc_info:
        verify_synthetic_opus(runner=runner)

    assert str(exc_info.value) == "synthetic_opus_failed"
    assert "private" not in str(exc_info.value)
