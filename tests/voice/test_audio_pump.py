from __future__ import annotations

import threading

from packages.contracts.audio import AudioFailureReason
from services.audio.source import DecoderRead
from services.voice.audio_pump import ExactFrameAudioPump


FRAME_BYTES = 3_200


class Decoder:
    def __init__(self, reads: list[DecoderRead]) -> None:
        self.reads = reads
        self.requests: list[tuple[int, float | None]] = []
        self.closed = False

    def read(
        self, max_bytes: int, *, timeout_seconds: float | None = None
    ) -> DecoderRead:
        self.requests.append((max_bytes, timeout_seconds))
        return self.reads.pop(0)

    def close(self) -> None:
        self.closed = True


def test_partial_reads_form_one_exact_frame_without_loss() -> None:
    decoder = Decoder([DecoderRead(b"a" * 1_000), DecoderRead(b"b" * 2_200)])
    pump = ExactFrameAudioPump(decoder)

    result = pump.read_frame()

    assert result.pcm == b"a" * 1_000 + b"b" * 2_200
    assert result.failure_reason is None
    assert result.dropped is False
    assert decoder.requests == [(3_200, 1.0), (2_200, 1.0)]
    assert pump.buffered_bytes == 0


def test_warmup_discards_exactly_five_frames_before_ready() -> None:
    decoder = Decoder([DecoderRead(bytes([value]) * FRAME_BYTES) for value in range(6)])
    pump = ExactFrameAudioPump(decoder)

    assert pump.warm_up(threading.Event()) is True
    assert pump.read_frame().pcm == bytes([5]) * FRAME_BYTES
    assert len(decoder.requests) == 6


def test_duck_consumes_and_drops_input_then_resumes_with_empty_assembler() -> None:
    decoder = Decoder(
        [DecoderRead(b"a" * 1_000), DecoderRead(b"b" * 2_200), DecoderRead(b"c" * FRAME_BYTES)]
    )
    pump = ExactFrameAudioPump(decoder)

    pump.begin_duck()
    dropped = pump.read_frame()
    pump.end_duck()
    resumed = pump.read_frame()

    assert dropped.dropped is True
    assert dropped.pcm == b""
    assert pump.buffered_bytes == 0
    assert resumed.pcm == b"c" * FRAME_BYTES


def test_source_failure_clears_partial_pcm_and_is_bounded() -> None:
    decoder = Decoder(
        [
            DecoderRead(b"a" * 1_000),
            DecoderRead(b"", AudioFailureReason.AUDIO_STALE),
            DecoderRead(b"b" * FRAME_BYTES),
        ]
    )
    pump = ExactFrameAudioPump(decoder)

    failed = pump.read_frame()
    recovered = pump.read_frame()

    assert failed.failure_reason is AudioFailureReason.AUDIO_STALE
    assert failed.pcm == b""
    assert pump.buffered_bytes == 0
    assert recovered.pcm == b"b" * FRAME_BYTES


def test_cancelled_warmup_and_close_settle_only_owned_decoder() -> None:
    decoder = Decoder([])
    pump = ExactFrameAudioPump(decoder)
    cancelled = threading.Event()
    cancelled.set()

    assert pump.warm_up(cancelled) is False
    pump.close()
    pump.close()

    assert decoder.closed is True


def test_decoder_cannot_overfill_the_fixed_frame_assembler() -> None:
    decoder = Decoder([DecoderRead(b"x" * (FRAME_BYTES + 2))])
    pump = ExactFrameAudioPump(decoder)

    result = pump.read_frame()

    assert result.pcm == b""
    assert result.failure_reason is AudioFailureReason.DECODER_FAILED
    assert pump.buffered_bytes == 0
