from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

from packages.contracts.audio import AudioObservation, AudioObservationState
from packages.contracts.events import EventSeverity
from packages.contracts.settings import AudioSettings


AUDIO_RULE_VERSION = "audio-cry-v1"


class AudioAlertState(StrEnum):
    IDLE = "idle"
    CANDIDATE = "candidate"
    NORMAL = "normal"
    HIGH = "high"


class AudioTransitionKind(StrEnum):
    OPENED = "opened"
    ESCALATED = "escalated"
    MERGED_ESCALATION = "merged_escalation"
    RECOVERED = "recovered"


@dataclass(frozen=True, slots=True)
class AudioStateTransition:
    kind: AudioTransitionKind
    previous_state: AudioAlertState
    current_state: AudioAlertState
    severity: EventSeverity
    occurred_at: datetime
    confidence: float | None = None
    rule_version: str = AUDIO_RULE_VERSION


@dataclass(frozen=True, slots=True)
class AudioStateSnapshot:
    state: AudioAlertState

    def __post_init__(self) -> None:
        if self.state is AudioAlertState.CANDIDATE:
            raise ValueError("short candidate state is not restart-safe")


class AudioStateMachine:
    def __init__(self, settings: AudioSettings) -> None:
        self._settings = settings
        self.state = AudioAlertState.IDLE
        self._last_observation: AudioObservation | None = None
        self._cry_seconds = 0.0
        self._non_cry_seconds = 0.0
        self._last_recovered_at: datetime | None = None

    @classmethod
    def from_snapshot(
        cls,
        settings: AudioSettings,
        snapshot: AudioStateSnapshot,
    ) -> "AudioStateMachine":
        machine = cls(settings)
        machine.state = snapshot.state
        return machine

    def snapshot(self) -> AudioStateSnapshot:
        state = self.state
        if state is AudioAlertState.CANDIDATE:
            state = AudioAlertState.IDLE
        return AudioStateSnapshot(state=state)

    def observe(self, observation: AudioObservation) -> AudioStateTransition | None:
        previous = self._last_observation
        if previous is not None:
            if observation.observed_at < previous.observed_at:
                raise ValueError("observation time moved backwards")
            if observation.observed_at == previous.observed_at:
                if observation == previous:
                    return None
                raise ValueError("conflicting observation at duplicate time")

        elapsed = 0.0
        if previous is not None and previous.state is not AudioObservationState.UNAVAILABLE:
            elapsed = (observation.observed_at - previous.observed_at).total_seconds()
        self._last_observation = observation

        if observation.state is AudioObservationState.UNAVAILABLE:
            return None
        if observation.state is AudioObservationState.CRY_CANDIDATE:
            return self._observe_cry(observation, previous, elapsed)
        return self._observe_non_cry(observation, previous, elapsed)

    def _observe_cry(
        self,
        observation: AudioObservation,
        previous: AudioObservation | None,
        elapsed: float,
    ) -> AudioStateTransition | None:
        self._non_cry_seconds = 0.0
        if self.state is AudioAlertState.IDLE:
            if self._is_repeat(observation.observed_at):
                old_state = self.state
                self.state = AudioAlertState.HIGH
                self._cry_seconds = 0.0
                return self._transition(
                    AudioTransitionKind.MERGED_ESCALATION,
                    old_state,
                    EventSeverity.HIGH,
                    observation.observed_at,
                    observation.cry_confidence,
                )
            self.state = AudioAlertState.CANDIDATE
            self._cry_seconds = 0.0
            return None

        if previous is not None and previous.state is AudioObservationState.CRY_CANDIDATE:
            self._cry_seconds += elapsed
        else:
            self._cry_seconds = 0.0

        if (
            self.state is AudioAlertState.CANDIDATE
            and self._cry_seconds >= self._settings.normal_seconds
        ):
            old_state = self.state
            self.state = AudioAlertState.NORMAL
            return self._transition(
                AudioTransitionKind.OPENED,
                old_state,
                EventSeverity.NORMAL,
                observation.observed_at,
                observation.cry_confidence,
            )
        if (
            self.state is AudioAlertState.NORMAL
            and self._cry_seconds >= self._settings.high_seconds
        ):
            old_state = self.state
            self.state = AudioAlertState.HIGH
            return self._transition(
                AudioTransitionKind.ESCALATED,
                old_state,
                EventSeverity.HIGH,
                observation.observed_at,
                observation.cry_confidence,
            )
        return None

    def _observe_non_cry(
        self,
        observation: AudioObservation,
        previous: AudioObservation | None,
        elapsed: float,
    ) -> AudioStateTransition | None:
        self._cry_seconds = 0.0
        if self.state is AudioAlertState.CANDIDATE:
            self.state = AudioAlertState.IDLE
            self._non_cry_seconds = 0.0
            return None
        if self.state is AudioAlertState.IDLE:
            self._non_cry_seconds = 0.0
            return None

        if previous is not None and previous.state in {
            AudioObservationState.QUIET,
            AudioObservationState.SOUND,
        }:
            self._non_cry_seconds += elapsed
        else:
            self._non_cry_seconds = 0.0
        if self._non_cry_seconds < self._settings.recovery_seconds:
            return None

        old_state = self.state
        self.state = AudioAlertState.IDLE
        self._non_cry_seconds = 0.0
        self._last_recovered_at = observation.observed_at
        return self._transition(
            AudioTransitionKind.RECOVERED,
            old_state,
            EventSeverity.INFO,
            observation.observed_at,
            None,
        )

    def _is_repeat(self, observed_at: datetime) -> bool:
        if self._last_recovered_at is None:
            return False
        elapsed = (observed_at - self._last_recovered_at).total_seconds()
        return elapsed <= self._settings.repeat_seconds

    def _transition(
        self,
        kind: AudioTransitionKind,
        previous_state: AudioAlertState,
        severity: EventSeverity,
        occurred_at: datetime,
        confidence: float | None,
    ) -> AudioStateTransition:
        return AudioStateTransition(
            kind=kind,
            previous_state=previous_state,
            current_state=self.state,
            severity=severity,
            occurred_at=occurred_at,
            confidence=confidence,
        )
