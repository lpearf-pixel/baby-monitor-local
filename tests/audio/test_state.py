from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from packages.contracts.audio import (
    AudioFailureReason,
    AudioObservation,
    AudioObservationState,
)
from packages.contracts.events import EventSeverity
from packages.contracts.settings import AudioSettings
from services.audio.state import (
    AudioAlertState,
    AudioStateSnapshot,
    AudioStateMachine,
    AudioTransitionKind,
)


START = datetime(2026, 8, 17, 12, tzinfo=UTC)


def observation(
    seconds: float,
    state: AudioObservationState,
) -> AudioObservation:
    if state is AudioObservationState.UNAVAILABLE:
        return AudioObservation(
            observed_at=START + timedelta(seconds=seconds),
            state=state,
            duration_ms=0,
            failure_reason=AudioFailureReason.AUDIO_SOURCE_UNAVAILABLE,
        )
    return AudioObservation(
        observed_at=START + timedelta(seconds=seconds),
        state=state,
        duration_ms=1_000,
        loudness_dbfs=-20,
        noise_floor_dbfs=-50,
        cry_confidence=0.9 if state is AudioObservationState.CRY_CANDIDATE else None,
    )


def test_continuous_cry_opens_normal_then_escalates_high() -> None:
    machine = AudioStateMachine(AudioSettings())

    assert machine.observe(observation(0, AudioObservationState.CRY_CANDIDATE)) is None
    assert machine.state is AudioAlertState.CANDIDATE
    normal = machine.observe(observation(5, AudioObservationState.CRY_CANDIDATE))
    high = machine.observe(observation(10, AudioObservationState.CRY_CANDIDATE))

    assert normal is not None
    assert normal.kind is AudioTransitionKind.OPENED
    assert normal.severity is EventSeverity.NORMAL
    assert high is not None
    assert high.kind is AudioTransitionKind.ESCALATED
    assert high.severity is EventSeverity.HIGH


def test_non_cry_before_threshold_clears_short_candidate() -> None:
    machine = AudioStateMachine(AudioSettings())
    machine.observe(observation(0, AudioObservationState.CRY_CANDIDATE))

    transition = machine.observe(observation(4, AudioObservationState.QUIET))

    assert transition is None
    assert machine.state is AudioAlertState.IDLE


def test_alert_recovers_only_after_sustained_available_non_cry() -> None:
    machine = AudioStateMachine(AudioSettings())
    machine.observe(observation(0, AudioObservationState.CRY_CANDIDATE))
    machine.observe(observation(5, AudioObservationState.CRY_CANDIDATE))

    assert machine.observe(observation(6, AudioObservationState.QUIET)) is None
    recovered = machine.observe(observation(11, AudioObservationState.SOUND))

    assert recovered is not None
    assert recovered.kind is AudioTransitionKind.RECOVERED
    assert recovered.severity is EventSeverity.INFO
    assert machine.state is AudioAlertState.IDLE


def test_unavailable_freezes_alert_and_cannot_count_toward_recovery() -> None:
    machine = AudioStateMachine(AudioSettings())
    machine.observe(observation(0, AudioObservationState.CRY_CANDIDATE))
    machine.observe(observation(5, AudioObservationState.CRY_CANDIDATE))
    machine.observe(observation(6, AudioObservationState.QUIET))

    assert machine.observe(observation(20, AudioObservationState.UNAVAILABLE)) is None
    assert machine.observe(observation(21, AudioObservationState.QUIET)) is None
    recovered = machine.observe(observation(26, AudioObservationState.QUIET))

    assert recovered is not None
    assert recovered.kind is AudioTransitionKind.RECOVERED


def test_repeat_within_window_merges_as_high_escalation() -> None:
    machine = AudioStateMachine(AudioSettings())
    machine.observe(observation(0, AudioObservationState.CRY_CANDIDATE))
    machine.observe(observation(5, AudioObservationState.CRY_CANDIDATE))
    machine.observe(observation(6, AudioObservationState.QUIET))
    machine.observe(observation(11, AudioObservationState.QUIET))

    merged = machine.observe(observation(20, AudioObservationState.CRY_CANDIDATE))

    assert merged is not None
    assert merged.kind is AudioTransitionKind.MERGED_ESCALATION
    assert merged.severity is EventSeverity.HIGH
    assert machine.state is AudioAlertState.HIGH


def test_repeat_after_window_starts_a_new_short_candidate() -> None:
    machine = AudioStateMachine(AudioSettings())
    machine.observe(observation(0, AudioObservationState.CRY_CANDIDATE))
    machine.observe(observation(5, AudioObservationState.CRY_CANDIDATE))
    machine.observe(observation(6, AudioObservationState.QUIET))
    machine.observe(observation(11, AudioObservationState.QUIET))

    transition = machine.observe(observation(42, AudioObservationState.CRY_CANDIDATE))

    assert transition is None
    assert machine.state is AudioAlertState.CANDIDATE


def test_duplicate_timestamp_is_idempotent_and_older_time_is_rejected() -> None:
    machine = AudioStateMachine(AudioSettings())
    first = observation(0, AudioObservationState.CRY_CANDIDATE)
    machine.observe(first)

    assert machine.observe(first) is None
    with pytest.raises(ValueError, match="observation time moved backwards"):
        machine.observe(observation(-1, AudioObservationState.CRY_CANDIDATE))
    assert machine.state is AudioAlertState.CANDIDATE


def test_cry_interrupts_recovery_timer() -> None:
    machine = AudioStateMachine(AudioSettings())
    machine.observe(observation(0, AudioObservationState.CRY_CANDIDATE))
    machine.observe(observation(5, AudioObservationState.CRY_CANDIDATE))
    machine.observe(observation(6, AudioObservationState.QUIET))
    machine.observe(observation(9, AudioObservationState.QUIET))
    machine.observe(observation(10, AudioObservationState.CRY_CANDIDATE))

    assert machine.observe(observation(11, AudioObservationState.QUIET)) is None
    recovered = machine.observe(observation(16, AudioObservationState.QUIET))

    assert recovered is not None
    assert recovered.kind is AudioTransitionKind.RECOVERED


def test_restart_restores_open_severity_without_stale_timing_progress() -> None:
    restored = AudioStateMachine.from_snapshot(
        AudioSettings(), AudioStateSnapshot(state=AudioAlertState.HIGH)
    )

    assert restored.state is AudioAlertState.HIGH
    assert restored.observe(observation(20, AudioObservationState.UNAVAILABLE)) is None
    assert restored.observe(observation(21, AudioObservationState.QUIET)) is None
    recovered = restored.observe(observation(26, AudioObservationState.QUIET))

    assert recovered is not None
    assert recovered.kind is AudioTransitionKind.RECOVERED
