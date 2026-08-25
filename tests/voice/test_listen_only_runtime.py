from __future__ import annotations

import threading
from datetime import UTC, datetime

from packages.contracts.audio import AudioFailureReason
from services.voice.audio_pump import PumpFrame
from services.voice.capture import UtteranceResult
from services.voice.listen_only import ListenOnlyOutcome
from services.voice.listen_only_runtime import ListenOnlyVoiceWorker, PlaybackDucker
from services.voice.vad import VadResult


class Pump:
    def __init__(self, frames: list[PumpFrame]) -> None:
        self.frames = frames
        self.ducked = False
        self.closed = False
        self.read_count = 0

    def warm_up(self, _cancelled) -> bool:
        return True

    def read_frame(self) -> PumpFrame:
        self.read_count += 1
        return self.frames.pop(0) if self.frames else PumpFrame(b"", dropped=True)

    def begin_duck(self) -> None:
        self.ducked = True

    def end_duck(self) -> None:
        self.ducked = False

    def close(self) -> None:
        self.closed = True


class Vad:
    def __init__(self, result: VadResult) -> None:
        self.result = result
        self.reset_count = 0
        self.closed = False

    def observe(self, _frame: bytes) -> VadResult:
        return self.result

    def reset(self) -> None:
        self.reset_count += 1

    def close(self) -> None:
        self.closed = True


class Collector:
    def __init__(self, result: UtteranceResult | None) -> None:
        self.result = result
        self.reset_count = 0
        self.closed = False

    def push(self, _frame: bytes, _vad: VadResult):
        result, self.result = self.result, None
        return result

    def reset(self) -> None:
        self.reset_count += 1

    def close(self) -> None:
        self.closed = True


class Controller:
    def __init__(self, outcome: ListenOnlyOutcome) -> None:
        self.outcome = outcome
        self.started: list[int] = []
        self.handled: list[bytes] = []
        self.reset_count = 0

    def expire(self, _now_ns: int) -> ListenOnlyOutcome:
        return ListenOnlyOutcome("listen_only_idle", None, "idle")

    def on_speech_started(self, now_ns: int) -> bool:
        self.started.append(now_ns)
        return True

    def handle(self, pcm: bytes, _cancelled) -> ListenOnlyOutcome:
        self.handled.append(pcm)
        return self.outcome

    def reset(self) -> None:
        self.reset_count += 1


class Status:
    def __init__(self) -> None:
        self.values: list[dict[str, object]] = []

    def write(self, **value: object) -> None:
        self.values.append(value)


class AsrCloser:
    def __init__(self) -> None:
        self.closed = False

    def close(self) -> None:
        self.closed = True


def test_worker_routes_one_completed_utterance_to_listen_only_controller() -> None:
    pump = Pump([PumpFrame(b"p" * 3_200)])
    vad = Vad(VadResult(True, 0.9))
    collector = Collector(UtteranceResult(b"u" * 32_000, "terminal_silence"))
    controller = Controller(
        ListenOnlyOutcome("listen_only_acknowledged", "listen_only_received", "idle")
    )
    status = Status()
    worker = ListenOnlyVoiceWorker(
        pump=pump,
        vad=vad,
        collector=collector,
        controller=controller,
        asr_closer=AsrCloser(),
        status_writer=status,
        clock=lambda: datetime(2026, 8, 25, tzinfo=UTC),
        monotonic_ns=iter((1_000_000_000, 1_080_000_000)).__next__,
    )

    worker.step(threading.Event())

    assert controller.started == [1_000_000_000]
    assert controller.handled == [b"u" * 32_000]
    assert vad.reset_count == 1
    assert status.values[-1] == {
        "mode": "listen_only",
        "worker_state": "healthy",
        "reason": "listen_only_acknowledged",
        "processed_count": 1,
        "last_latency_ms": 80,
    }


def test_worker_source_failure_resets_only_voice_state_and_fails_closed() -> None:
    pump = Pump([PumpFrame(b"", AudioFailureReason.AUDIO_STALE)])
    vad = Vad(VadResult(False, 0.0))
    collector = Collector(None)
    controller = Controller(ListenOnlyOutcome("listen_only_idle", None, "idle"))
    status = Status()
    worker = ListenOnlyVoiceWorker(
        pump=pump,
        vad=vad,
        collector=collector,
        controller=controller,
        asr_closer=AsrCloser(),
        status_writer=status,
    )

    worker.step(threading.Event())

    assert vad.reset_count == 1
    assert collector.reset_count == 1
    assert controller.reset_count == 1
    assert status.values[-1]["reason"] == "voice_audio_unavailable"


def test_playback_ducker_drains_audio_and_resets_capture_state() -> None:
    pump = Pump([PumpFrame(b"", dropped=True)] * 100)
    vad = Vad(VadResult(False, 0.0))
    collector = Collector(None)
    ducker = PlaybackDucker(pump=pump, vad=vad, collector=collector)

    ducker.pause()
    assert pump.ducked is True
    assert threading.Event().wait(0.02) is False
    ducker.resume()

    assert pump.read_count > 0
    assert pump.ducked is False
    assert vad.reset_count >= 2
    assert collector.reset_count >= 2


def test_worker_close_settles_all_owned_voice_resources() -> None:
    pump = Pump([])
    vad = Vad(VadResult(False, 0.0))
    collector = Collector(None)
    controller = Controller(ListenOnlyOutcome("listen_only_idle", None, "idle"))
    asr = AsrCloser()
    worker = ListenOnlyVoiceWorker(
        pump=pump,
        vad=vad,
        collector=collector,
        controller=controller,
        asr_closer=asr,
        status_writer=Status(),
    )

    worker.close()
    worker.close()

    assert pump.closed is True
    assert vad.closed is True
    assert collector.closed is True
    assert asr.closed is True
