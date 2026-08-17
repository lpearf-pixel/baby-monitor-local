from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

from packages.contracts.audio import (
    AudioFailureReason,
    AudioObservation,
    AudioObservationState,
)
from packages.contracts.settings import AudioSettings
from services.audio.source import DecoderRead
from services.audio.state import AudioStateMachine
from services.audio.worker import AudioStatusWriter, AudioWorker


NOW = datetime(2026, 8, 17, 14, tzinfo=UTC)


class Decoder:
    def __init__(self, result: DecoderRead) -> None:
        self.result = result

    def read(self, _max_bytes: int) -> DecoderRead:
        return self.result


class Gate:
    def __init__(self, result: AudioObservation) -> None:
        self.result = result

    def observe(self, _pcm: bytes, *, observed_at: datetime) -> AudioObservation:
        return self.result.model_copy(update={"observed_at": observed_at})


class Classifier:
    def __init__(self, result: AudioObservation) -> None:
        self.result = result
        self.calls = 0

    def classify(self, _pcm: bytes, source: AudioObservation) -> AudioObservation:
        self.calls += 1
        return self.result.model_copy(update={"observed_at": source.observed_at})


class Sink:
    def __init__(self) -> None:
        self.transitions = []

    def handle(self, transition) -> None:
        self.transitions.append(transition)


class FailingSink:
    def handle(self, _transition) -> None:
        raise OSError("private database path")


def available(state: AudioObservationState) -> AudioObservation:
    return AudioObservation(
        observed_at=NOW,
        state=state,
        duration_ms=1_000,
        loudness_dbfs=-20,
        noise_floor_dbfs=-50,
        cry_confidence=0.9 if state is AudioObservationState.CRY_CANDIDATE else None,
    )


def test_worker_failure_publishes_closed_status_without_positive_event(
    tmp_path: Path,
) -> None:
    writer = AudioStatusWriter(tmp_path / "status.json")
    sink = Sink()
    worker = AudioWorker(
        settings=AudioSettings(),
        decoder=Decoder(DecoderRead(b"", AudioFailureReason.AUDIO_STALE)),
        gate=Gate(available(AudioObservationState.QUIET)),
        classifier=Classifier(available(AudioObservationState.CRY_CANDIDATE)),
        state_machine=AudioStateMachine(AudioSettings()),
        event_sink=sink,
        status_writer=writer,
        clock=lambda: NOW,
    )

    worker.step()

    payload = json.loads((tmp_path / "status.json").read_text())
    assert payload == {
        "checked_at": NOW.isoformat(),
        "failure_reason": "audio_stale",
        "observation_state": "unavailable",
        "schema_version": 1,
        "worker_state": "degraded",
    }
    assert sink.transitions == []


def test_worker_runs_classifier_only_for_loud_sound_and_emits_transition(
    tmp_path: Path,
) -> None:
    settings = AudioSettings(normal_seconds=1, high_seconds=2)
    cry = available(AudioObservationState.CRY_CANDIDATE)
    classifier = Classifier(cry)
    sink = Sink()
    worker = AudioWorker(
        settings=settings,
        decoder=Decoder(DecoderRead(b"\x00\x00" * 16_000)),
        gate=Gate(available(AudioObservationState.SOUND)),
        classifier=classifier,
        state_machine=AudioStateMachine(settings),
        event_sink=sink,
        status_writer=AudioStatusWriter(tmp_path / "status.json"),
        clock=lambda: NOW,
    )

    worker.step()
    worker._clock = lambda: NOW.replace(second=1)
    worker.step()

    assert classifier.calls == 2
    assert len(sink.transitions) == 1
    payload = json.loads((tmp_path / "status.json").read_text())
    assert payload["worker_state"] == "healthy"
    assert payload["observation_state"] == "cry_candidate"
    assert "pcm" not in payload
    assert "path" not in payload


def test_quiet_window_skips_classifier(tmp_path: Path) -> None:
    classifier = Classifier(available(AudioObservationState.CRY_CANDIDATE))
    worker = AudioWorker(
        settings=AudioSettings(),
        decoder=Decoder(DecoderRead(b"\x00\x00" * 16_000)),
        gate=Gate(available(AudioObservationState.QUIET)),
        classifier=classifier,
        state_machine=AudioStateMachine(AudioSettings()),
        event_sink=Sink(),
        status_writer=AudioStatusWriter(tmp_path / "status.json"),
        clock=lambda: NOW,
    )

    worker.step()

    assert classifier.calls == 0


def test_event_persistence_failure_rolls_back_and_publishes_closed_status(
    tmp_path: Path,
) -> None:
    settings = AudioSettings(normal_seconds=1, high_seconds=2)
    worker = AudioWorker(
        settings=settings,
        decoder=Decoder(DecoderRead(b"\x00\x00" * 16_000)),
        gate=Gate(available(AudioObservationState.SOUND)),
        classifier=Classifier(available(AudioObservationState.CRY_CANDIDATE)),
        state_machine=AudioStateMachine(settings),
        event_sink=FailingSink(),
        status_writer=AudioStatusWriter(tmp_path / "status.json"),
        clock=lambda: NOW,
    )
    worker.step()
    worker._clock = lambda: NOW.replace(second=1)

    worker.step()

    payload = json.loads((tmp_path / "status.json").read_text())
    assert payload["worker_state"] == "degraded"
    assert payload["failure_reason"] == "internal_error"
