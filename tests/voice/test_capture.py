from __future__ import annotations

import math

import pytest

from packages.contracts.settings import VoiceCareSettings
from services.voice import capture
from services.voice.capture import UtteranceCollector
from services.voice.vad import VadResult


SAMPLE_RATE_HZ = 16_000
BYTES_PER_SAMPLE = 2
FRAME_100MS = b"\x01\x00" * 1_600


class SnapshotBytearray(bytearray):
    """Records bytes at the moment production calls ``clear``."""

    def __init__(self) -> None:
        super().__init__()
        self.clear_snapshots: list[bytes] = []

    def clear(self) -> None:
        self.clear_snapshots.append(bytes(self))
        super().clear()


def inspectable_collector(monkeypatch: pytest.MonkeyPatch) -> UtteranceCollector:
    monkeypatch.setattr(capture, "PcmBuffer", SnapshotBytearray)
    return UtteranceCollector(VoiceCareSettings())


def test_collector_closes_at_eight_seconds_and_discards_after_take() -> None:
    collector = UtteranceCollector(VoiceCareSettings())

    result = None
    for _ in range(80):
        result = collector.push(
            FRAME_100MS, VadResult(speech=True, probability=0.9)
        )

    assert result is not None
    assert result.reason == "max_duration"
    assert len(result.pcm) == 8 * SAMPLE_RATE_HZ * BYTES_PER_SAMPLE
    assert collector.buffered_bytes == 0


def test_collector_includes_exact_five_hundred_ms_pre_roll() -> None:
    collector = UtteranceCollector(VoiceCareSettings())
    frames = [bytes([index, 0]) * 1_600 for index in range(1, 8)]

    for frame in frames[:5]:
        assert collector.push(frame, VadResult(speech=False, probability=0.1)) is None
    assert collector.push(frames[5], VadResult(speech=True, probability=0.9)) is None
    result = collector.push(frames[6], VadResult(speech=False, probability=0.1))

    assert result is None
    assert collector.buffered_bytes == 7 * len(FRAME_100MS)
    assert collector.reset() is None

    # A terminal silence closure exposes the same pre-roll before the first speech frame.
    for frame in frames[:5]:
        collector.push(frame, VadResult(speech=False, probability=0.1))
    collector.push(frames[5], VadResult(speech=True, probability=0.9))
    terminal = None
    for _ in range(8):
        terminal = collector.push(
            frames[6], VadResult(speech=False, probability=0.1)
        )

    assert terminal is not None
    assert terminal.reason == "terminal_silence"
    assert terminal.pcm[: 5 * len(FRAME_100MS)] == b"".join(frames[:5])


def test_collector_closes_after_exact_eight_hundred_ms_terminal_silence() -> None:
    collector = UtteranceCollector(VoiceCareSettings())

    assert collector.push(FRAME_100MS, VadResult(speech=True, probability=0.9)) is None
    for _ in range(7):
        assert collector.push(
            FRAME_100MS, VadResult(speech=False, probability=0.1)
        ) is None
    result = collector.push(FRAME_100MS, VadResult(speech=False, probability=0.1))

    assert result is not None
    assert result.reason == "terminal_silence"
    assert len(result.pcm) == 9 * len(FRAME_100MS)
    assert collector.buffered_bytes == 0


def test_collector_rejects_malformed_or_timing_inexact_frames_fail_closed() -> None:
    collector = UtteranceCollector(VoiceCareSettings())

    with pytest.raises(ValueError, match="frame aligned"):
        collector.push(b"x", VadResult(speech=True, probability=0.9))
    with pytest.raises(ValueError, match="timing"):
        collector.push(b"\x00\x00" * 480, VadResult(speech=True, probability=0.9))

    assert collector.buffered_bytes == 0


def test_collector_validation_error_zeroizes_active_buffer_before_clear(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    collector = inspectable_collector(monkeypatch)
    collector.push(FRAME_100MS, VadResult(speech=True, probability=0.9))
    utterance = collector._utterance

    with pytest.raises(ValueError, match="finite"):
        collector.push(FRAME_100MS, VadResult(speech=True, probability=math.nan))

    assert collector.buffered_bytes == 0
    assert utterance.clear_snapshots == [b"\x00" * len(FRAME_100MS)]


def test_collector_reset_zeroizes_pre_roll_before_clear(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    collector = inspectable_collector(monkeypatch)
    collector.push(FRAME_100MS, VadResult(speech=False, probability=0.1))
    pre_roll = collector._pre_roll
    collector.reset()

    assert collector.buffered_bytes == 0
    assert pre_roll.clear_snapshots == [b"\x00" * len(FRAME_100MS)]


def test_collector_close_zeroizes_active_buffer_before_clear(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    collector = inspectable_collector(monkeypatch)

    collector.push(FRAME_100MS, VadResult(speech=True, probability=0.9))
    utterance = collector._utterance
    collector.close()

    assert collector.buffered_bytes == 0
    assert utterance.clear_snapshots == [b"\x00" * len(FRAME_100MS)]
    with pytest.raises(RuntimeError, match="closed"):
        collector.push(FRAME_100MS, VadResult(speech=True, probability=0.9))


def test_collector_terminal_take_zeroizes_internal_buffer_and_keeps_pcm_copy(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    collector = inspectable_collector(monkeypatch)
    collector.push(FRAME_100MS, VadResult(speech=True, probability=0.9))
    utterance = collector._utterance

    result = None
    for _ in range(8):
        result = collector.push(FRAME_100MS, VadResult(speech=False, probability=0.1))

    assert result is not None
    assert result.pcm == FRAME_100MS * 9
    assert utterance.clear_snapshots == [b"\x00" * len(result.pcm)]
