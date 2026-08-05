from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from pydantic import ValidationError

from packages.contracts import events


NOW = datetime(2026, 8, 5, 12, 0, tzinfo=UTC)


def available_payload() -> dict[str, object]:
    return {
        "schema_version": 1,
        "reading_id": "reading-1",
        "source_kind": events.EnvironmentSourceKind.WS2021_GAUGE,
        "captured_at": NOW,
        "fresh_until": NOW + timedelta(seconds=90),
        "state": events.ReadingState.AVAILABLE,
        "temperature_c": 22.0,
        "humidity_rh": 48.0,
        "confidence": 0.9,
        "confidence_state": events.ConfidenceState.HIGH,
        "failure_reason": None,
        "calibration_version": "calibration-1",
        "sample_count": 5,
        "valid_temperature_samples": 5,
        "valid_humidity_samples": 5,
    }


@pytest.mark.parametrize("missing_field", ["temperature_c", "humidity_rh"])
def test_available_reading_requires_both_values(missing_field: str) -> None:
    payload = available_payload()
    payload[missing_field] = None

    with pytest.raises(ValidationError, match="both temperature and humidity"):
        events.EnvironmentReading.model_validate(payload)


def test_available_reading_rejects_failure_reason() -> None:
    payload = available_payload()
    payload["failure_reason"] = events.ReadingFailureReason.GLARE

    with pytest.raises(ValidationError, match="must not contain a failure reason"):
        events.EnvironmentReading.model_validate(payload)


def test_unavailable_factory_clears_values_and_uses_closed_reason() -> None:
    reading = events.EnvironmentReading.unavailable(
        reading_id="reading-2",
        source_kind=events.EnvironmentSourceKind.WS2021_GAUGE,
        captured_at=NOW,
        failure_reason=events.ReadingFailureReason.TOO_DARK,
        calibration_version="calibration-1",
        sample_count=5,
        valid_temperature_samples=0,
        valid_humidity_samples=0,
    )

    assert reading.state is events.ReadingState.UNAVAILABLE
    assert reading.temperature_c is None
    assert reading.humidity_rh is None
    assert reading.fresh_until == NOW + timedelta(seconds=90)
    assert reading.failure_reason is events.ReadingFailureReason.TOO_DARK


def test_unavailable_reading_rejects_free_text_reason() -> None:
    with pytest.raises(ValidationError):
        events.EnvironmentReading.unavailable(
            reading_id="reading-2",
            source_kind=events.EnvironmentSourceKind.WS2021_GAUGE,
            captured_at=NOW,
            failure_reason="needle failed beside /private/home/image.jpg",
            calibration_version="calibration-1",
            sample_count=0,
        )


def test_ws2021_reading_requires_calibration_version() -> None:
    payload = available_payload()
    payload["calibration_version"] = None

    with pytest.raises(ValidationError, match="calibration_version"):
        events.EnvironmentReading.model_validate(payload)


def test_reading_rejects_naive_or_reversed_freshness() -> None:
    payload = available_payload()
    payload["fresh_until"] = NOW
    with pytest.raises(ValidationError, match="later than captured_at"):
        events.EnvironmentReading.model_validate(payload)

    payload = available_payload()
    payload["captured_at"] = NOW.replace(tzinfo=None)
    with pytest.raises(ValidationError, match="timezone-aware"):
        events.EnvironmentReading.model_validate(payload)


def test_available_factory_enforces_minimum_confidence() -> None:
    with pytest.raises(ValueError, match="minimum confidence"):
        events.EnvironmentReading.available(
            reading_id="reading-3",
            source_kind=events.EnvironmentSourceKind.WS2021_GAUGE,
            captured_at=NOW,
            temperature_c=22.0,
            humidity_rh=48.0,
            confidence=0.74,
            calibration_version="calibration-1",
            sample_count=5,
            valid_temperature_samples=5,
            valid_humidity_samples=5,
            minimum_confidence=0.75,
        )


def test_reading_rejects_extra_fields_and_impossible_sample_counts() -> None:
    payload = available_payload()
    payload["frame_path"] = "/private/family/frame.jpg"
    with pytest.raises(ValidationError, match="Extra inputs"):
        events.EnvironmentReading.model_validate(payload)

    payload = available_payload()
    payload["valid_temperature_samples"] = 6
    with pytest.raises(ValidationError, match="cannot exceed sample_count"):
        events.EnvironmentReading.model_validate(payload)
