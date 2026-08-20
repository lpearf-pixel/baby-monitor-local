from __future__ import annotations

import subprocess

import pytest

from packages.contracts.audio import AudioFailureReason
from packages.contracts.settings import AudioSettings
from services.audio.source import BoundedPcmBuffer, FixedAudioDecoder


def test_pcm_buffer_keeps_only_aligned_configured_duration() -> None:
    buffer = BoundedPcmBuffer(
        sample_rate_hz=4,
        channels=1,
        sample_width_bytes=2,
        buffer_seconds=2,
    )

    buffer.append(bytes(range(12)))
    buffer.append(bytes(range(12, 24)))

    assert buffer.capacity_bytes == 16
    assert buffer.size_bytes == 16
    assert buffer.latest(1_000) == bytes(range(16, 24))


def test_pcm_buffer_rejects_partial_samples_and_invalid_window() -> None:
    buffer = BoundedPcmBuffer(4, 1, 2, 2)

    with pytest.raises(ValueError, match="aligned"):
        buffer.append(b"x")
    with pytest.raises(ValueError, match="duration"):
        buffer.latest(3_000)


class FakeStdout:
    def __init__(self, chunks: list[bytes | BaseException]) -> None:
        self.chunks = chunks
        self.closed = False

    def read(self, _size: int) -> bytes:
        item = self.chunks.pop(0)
        if isinstance(item, BaseException):
            raise item
        return item

    def close(self) -> None:
        self.closed = True


class FakeProcess:
    def __init__(self, chunks: list[bytes | BaseException], code: int | None = None) -> None:
        self.stdout = FakeStdout(chunks)
        self.code = code
        self.terminated = False
        self.killed = False
        self.wait_calls: list[float] = []

    def poll(self) -> int | None:
        return self.code

    def terminate(self) -> None:
        self.terminated = True

    def kill(self) -> None:
        self.killed = True

    def wait(self, timeout: float) -> int:
        self.wait_calls.append(timeout)
        return 0


def test_decoder_uses_fixed_loopback_audio_only_command() -> None:
    calls: list[tuple[tuple[str, ...], dict[str, object]]] = []

    def opener(command: tuple[str, ...], **kwargs: object) -> FakeProcess:
        calls.append((command, kwargs))
        return FakeProcess([b"\x00\x01"])

    decoder = FixedAudioDecoder(AudioSettings(), opener=opener)
    result = decoder.read(2)

    assert result.pcm == b"\x00\x01"
    assert result.failure_reason is None
    command, kwargs = calls[0]
    assert command[0] == "ffmpeg"
    assert "rtsp://127.0.0.1:8554/audio_analysis" in command
    assert command[command.index("-timeout") + 1] == "5000000"
    assert "-rw_timeout" not in command
    assert command[-1] == "pipe:1"
    assert kwargs["stderr"] is subprocess.DEVNULL


@pytest.mark.parametrize(
    ("process", "reason"),
    [
        (FakeProcess([b""], code=1), AudioFailureReason.DECODER_FAILED),
        (FakeProcess([b""], code=None), AudioFailureReason.AUDIO_STALE),
        (
            FakeProcess([OSError("private source detail")]),
            AudioFailureReason.DECODER_FAILED,
        ),
    ],
)
def test_decoder_failures_return_only_closed_reasons(
    process: FakeProcess, reason: AudioFailureReason
) -> None:
    decoder = FixedAudioDecoder(
        AudioSettings(), opener=lambda *_args, **_kwargs: process
    )

    result = decoder.read(2)

    assert result.pcm == b""
    assert result.failure_reason is reason


def test_decoder_start_failure_is_source_unavailable() -> None:
    def fail(*_args: object, **_kwargs: object) -> FakeProcess:
        raise OSError("private command detail")

    result = FixedAudioDecoder(AudioSettings(), opener=fail).read(2)

    assert result.failure_reason is AudioFailureReason.AUDIO_SOURCE_UNAVAILABLE


def test_decoder_rejects_malformed_partial_pcm_sample() -> None:
    decoder = FixedAudioDecoder(
        AudioSettings(), opener=lambda *_args, **_kwargs: FakeProcess([b"x"])
    )

    result = decoder.read(2)

    assert result.pcm == b""
    assert result.failure_reason is AudioFailureReason.DECODER_FAILED


def test_decoder_close_terminates_child_and_is_idempotent() -> None:
    process = FakeProcess([b"\x00\x01"])
    decoder = FixedAudioDecoder(
        AudioSettings(), opener=lambda *_args, **_kwargs: process
    )
    decoder.read(2)

    decoder.close()
    decoder.close()

    assert process.stdout.closed is True
    assert process.terminated is True
    assert process.killed is False
    assert process.wait_calls == [2.0]
