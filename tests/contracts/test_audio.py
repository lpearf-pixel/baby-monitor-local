from __future__ import annotations

from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from packages.contracts.audio import (
    AudioFailureReason,
    AudioObservation,
    AudioObservationState,
)


NOW = datetime(2026, 8, 17, 12, tzinfo=timezone.utc)


def test_cry_observation_contains_only_bounded_scalar_results() -> None:
    observation = AudioObservation(
        observed_at=NOW,
        state=AudioObservationState.CRY_CANDIDATE,
        duration_ms=1_000,
        loudness_dbfs=-18.5,
        noise_floor_dbfs=-42.0,
        cry_confidence=0.82,
    )

    assert observation.failure_reason is None
    assert "samples" not in observation.model_dump()
    assert "source" not in observation.model_dump()


def test_unavailable_observation_requires_closed_failure_reason() -> None:
    observation = AudioObservation(
        observed_at=NOW,
        state=AudioObservationState.UNAVAILABLE,
        duration_ms=0,
        failure_reason=AudioFailureReason.AUDIO_SOURCE_UNAVAILABLE,
    )

    assert observation.cry_confidence is None

    with pytest.raises(ValidationError):
        AudioObservation(
            observed_at=NOW,
            state=AudioObservationState.UNAVAILABLE,
            duration_ms=0,
            failure_reason="private decoder exception",
        )


def test_available_and_unavailable_fields_cannot_be_mixed() -> None:
    with pytest.raises(ValidationError, match="failure reason"):
        AudioObservation(
            observed_at=NOW,
            state=AudioObservationState.QUIET,
            duration_ms=1_000,
            loudness_dbfs=-60,
            noise_floor_dbfs=-55,
            failure_reason=AudioFailureReason.DECODER_FAILED,
        )

    with pytest.raises(ValidationError, match="unavailable"):
        AudioObservation(
            observed_at=NOW,
            state=AudioObservationState.UNAVAILABLE,
            duration_ms=0,
        )


def test_observation_rejects_naive_time_and_unknown_or_sample_fields() -> None:
    with pytest.raises(ValidationError, match="timezone-aware"):
        AudioObservation(
            observed_at=datetime(2026, 8, 17, 12),
            state=AudioObservationState.SOUND,
            duration_ms=500,
            loudness_dbfs=-20,
            noise_floor_dbfs=-45,
        )

    with pytest.raises(ValidationError):
        AudioObservation.model_validate(
            {
                "observed_at": NOW,
                "state": "sound",
                "duration_ms": 500,
                "loudness_dbfs": -20,
                "noise_floor_dbfs": -45,
                "samples": [1, 2, 3],
            }
        )
