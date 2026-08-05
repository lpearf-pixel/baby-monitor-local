from __future__ import annotations

from datetime import UTC, datetime, timedelta
import importlib

from packages.contracts.events import (
    EnvironmentReading,
    EnvironmentSourceKind,
    ReadingFailureReason,
)


NOW = datetime(2026, 8, 5, 12, 0, tzinfo=UTC)


def state_module():
    return importlib.import_module("services.events.environment_state")


def available(captured_at: datetime) -> EnvironmentReading:
    return EnvironmentReading.available(
        reading_id=f"available-{captured_at.timestamp()}",
        source_kind=EnvironmentSourceKind.WS2021_GAUGE,
        captured_at=captured_at,
        temperature_c=22,
        humidity_rh=48,
        confidence=0.9,
        calibration_version="calibration-1",
        sample_count=5,
        valid_temperature_samples=5,
        valid_humidity_samples=5,
    )


def unavailable(captured_at: datetime) -> EnvironmentReading:
    return EnvironmentReading.unavailable(
        reading_id=f"unavailable-{captured_at.timestamp()}",
        source_kind=EnvironmentSourceKind.WS2021_GAUGE,
        captured_at=captured_at,
        failure_reason=ReadingFailureReason.GLARE,
        calibration_version="calibration-1",
        sample_count=5,
    )


class FakeStore:
    def __init__(
        self,
        *,
        current: EnvironmentReading | None,
        last_valid: EnvironmentReading | None,
    ) -> None:
        self.current = current
        self.last_valid = last_valid

    def latest(self) -> EnvironmentReading | None:
        return self.current

    def latest_available(self) -> EnvironmentReading | None:
        return self.last_valid


def test_stale_reading_is_not_exposed_as_current_values() -> None:
    module = state_module()
    old = available(NOW - timedelta(minutes=5))
    provider = module.EnvironmentSnapshotProvider(
        store=FakeStore(current=old, last_valid=old),
        state_machine=module.EnvironmentStateMachine(
            module.EnvironmentStatePolicy()
        ),
    )

    snapshot = provider.current(NOW)

    assert snapshot.current_reading == old
    assert snapshot.current_available is False
    assert snapshot.temperature_c is None
    assert snapshot.humidity_rh is None
    assert snapshot.last_valid_reading == old


def test_unavailable_latest_does_not_fall_back_to_old_current_values() -> None:
    module = state_module()
    old = available(NOW - timedelta(minutes=1))
    current = unavailable(NOW)
    provider = module.EnvironmentSnapshotProvider(
        store=FakeStore(current=current, last_valid=old),
        state_machine=module.EnvironmentStateMachine(
            module.EnvironmentStatePolicy()
        ),
    )

    snapshot = provider.current(NOW)

    assert snapshot.current_reading == current
    assert snapshot.current_available is False
    assert snapshot.temperature_c is None
    assert snapshot.last_valid_reading == old


def test_fresh_available_reading_is_exposed_with_fixed_ineligible_policy() -> None:
    module = state_module()
    reading = available(NOW)
    provider = module.EnvironmentSnapshotProvider(
        store=FakeStore(current=reading, last_valid=reading),
        state_machine=module.EnvironmentStateMachine(
            module.EnvironmentStatePolicy()
        ),
    )

    snapshot = provider.current(NOW)

    assert snapshot.current_available is True
    assert snapshot.temperature_c == 22
    assert snapshot.humidity_rh == 48
    assert snapshot.control_eligibility == "ineligible"
    assert snapshot.control_ineligibility_reasons == (
        "optical_source_only",
        "actuator_api_disabled",
    )
