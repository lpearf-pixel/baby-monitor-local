from __future__ import annotations

import json
import os
from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from typing import Protocol

from packages.contracts.audio import (
    AudioFailureReason,
    AudioObservation,
    AudioObservationState,
)
from packages.contracts.settings import AudioSettings
from services.audio.source import DecoderRead
from services.audio.state import AudioStateMachine, AudioStateTransition


class Decoder(Protocol):
    def read(self, max_bytes: int) -> DecoderRead: ...

    def close(self) -> None: ...


class LoudnessGate(Protocol):
    def observe(self, pcm: bytes, *, observed_at: datetime) -> AudioObservation: ...


class Classifier(Protocol):
    def classify(
        self, pcm: bytes, source: AudioObservation
    ) -> AudioObservation: ...


class EventSink(Protocol):
    def handle(self, transition: AudioStateTransition) -> object: ...


class StopEvent(Protocol):
    def is_set(self) -> bool: ...

    def wait(self, timeout: float) -> bool: ...


class AudioStatusWriter:
    def __init__(self, path: Path) -> None:
        self._path = Path(path)

    def write(self, observation: AudioObservation) -> None:
        payload = {
            "schema_version": 1,
            "checked_at": observation.observed_at.isoformat(),
            "worker_state": (
                "degraded"
                if observation.state is AudioObservationState.UNAVAILABLE
                else "healthy"
            ),
            "observation_state": observation.state.value,
            "failure_reason": (
                observation.failure_reason.value
                if observation.failure_reason is not None
                else None
            ),
        }
        self._path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self._path.with_name(f".{self._path.name}.{os.getpid()}.tmp")
        try:
            temporary.write_text(
                json.dumps(payload, ensure_ascii=True, sort_keys=True) + "\n",
                encoding="ascii",
            )
            os.chmod(temporary, 0o600)
            os.replace(temporary, self._path)
        finally:
            try:
                temporary.unlink()
            except FileNotFoundError:
                pass


class AudioWorker:
    def __init__(
        self,
        *,
        settings: AudioSettings,
        decoder: Decoder,
        gate: LoudnessGate,
        classifier: Classifier,
        state_machine: AudioStateMachine,
        event_sink: EventSink,
        status_writer: AudioStatusWriter,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._settings = settings
        self._decoder = decoder
        self._gate = gate
        self._classifier = classifier
        self._state_machine = state_machine
        self._event_sink = event_sink
        self._status_writer = status_writer
        self._clock = clock or (lambda: datetime.now().astimezone())
        self._window_bytes = (
            settings.sample_rate_hz
            * settings.channels
            * settings.sample_width_bytes
            * settings.window_ms
            // 1_000
        )

    def step(self) -> None:
        observed_at = self._clock()
        read = self._decoder.read(self._window_bytes)
        if read.failure_reason is not None:
            observation = AudioObservation(
                observed_at=observed_at,
                state=AudioObservationState.UNAVAILABLE,
                duration_ms=0,
                failure_reason=read.failure_reason,
            )
        else:
            observation = self._gate.observe(read.pcm, observed_at=observed_at)
            if observation.state is AudioObservationState.SOUND:
                observation = self._classifier.classify(read.pcm, observation)
        snapshot = self._state_machine.snapshot()
        transition = self._state_machine.observe(observation)
        if transition is not None:
            try:
                self._event_sink.handle(transition)
            except Exception:
                self._state_machine = AudioStateMachine.from_snapshot(
                    self._settings, snapshot
                )
                observation = AudioObservation(
                    observed_at=observed_at,
                    state=AudioObservationState.UNAVAILABLE,
                    duration_ms=0,
                    failure_reason=AudioFailureReason.INTERNAL_ERROR,
                )
        self._status_writer.write(observation)

    def run(self, stop_event: StopEvent) -> None:
        stride_seconds = self._settings.stride_ms / 1_000
        try:
            while not stop_event.is_set():
                self.step()
                stop_event.wait(stride_seconds)
        finally:
            self._decoder.close()
