from __future__ import annotations

from datetime import UTC, datetime, timedelta
import importlib

from packages.contracts.events import (
    EnvironmentReading,
    EnvironmentSourceKind,
    ReadingFailureReason,
)


BASE = datetime(2026, 8, 5, 12, 0, tzinfo=UTC)


def state_module():
    return importlib.import_module("services.events.environment_state")


def reading_at(
    seconds: int,
    *,
    temperature: float = 22,
    humidity: float = 48,
) -> EnvironmentReading:
    captured_at = BASE + timedelta(seconds=seconds)
    return EnvironmentReading.available(
        reading_id=f"reading-{seconds}-{temperature}-{humidity}",
        source_kind=EnvironmentSourceKind.WS2021_GAUGE,
        captured_at=captured_at,
        temperature_c=temperature,
        humidity_rh=humidity,
        confidence=0.9,
        calibration_version="calibration-1",
        sample_count=5,
        valid_temperature_samples=5,
        valid_humidity_samples=5,
    )


def unavailable_at(seconds: int) -> EnvironmentReading:
    return EnvironmentReading.unavailable(
        reading_id=f"unavailable-{seconds}",
        source_kind=EnvironmentSourceKind.WS2021_GAUGE,
        captured_at=BASE + timedelta(seconds=seconds),
        failure_reason=ReadingFailureReason.TOO_DARK,
        calibration_version="calibration-1",
        sample_count=5,
    )


def test_range_incident_opens_only_after_five_continuous_minutes() -> None:
    module = state_module()
    machine = module.EnvironmentStateMachine(module.EnvironmentStatePolicy())

    assert machine.consume(reading_at(0, temperature=27)) == ()
    assert machine.consume(reading_at(299, temperature=27)) == ()
    transitions = machine.consume(reading_at(300, temperature=27))

    assert len(transitions) == 1
    assert transitions[0].kind == "opened"
    assert transitions[0].incident.kind == "range"
    assert transitions[0].incident.severity == "normal"
    assert transitions[0].incident.reasons == ("temperature_high",)


def test_unavailable_sample_interrupts_pending_range_timer() -> None:
    module = state_module()
    machine = module.EnvironmentStateMachine(module.EnvironmentStatePolicy())

    assert machine.consume(reading_at(0, temperature=27)) == ()
    assert machine.consume(unavailable_at(250)) == ()
    assert machine.consume(reading_at(600, temperature=27)) == ()
    assert machine.consume(reading_at(899, temperature=27)) == ()
    assert machine.consume(reading_at(900, temperature=27))[0].kind == "opened"


def test_two_critical_samples_require_at_least_sixty_seconds() -> None:
    module = state_module()
    machine = module.EnvironmentStateMachine(module.EnvironmentStatePolicy())

    assert machine.consume(reading_at(0, temperature=31)) == ()
    assert machine.consume(reading_at(59, temperature=31)) == ()
    transitions = machine.consume(reading_at(60, temperature=31))

    assert len(transitions) == 1
    assert transitions[0].kind == "opened"
    assert transitions[0].incident.severity == "critical"


def test_open_range_incident_escalates_once_after_two_confirmations() -> None:
    module = state_module()
    machine = module.EnvironmentStateMachine(module.EnvironmentStatePolicy())
    machine.consume(reading_at(0, temperature=27))
    opened = machine.consume(reading_at(300, temperature=27))
    assert opened[0].kind == "opened"

    assert machine.consume(reading_at(360, temperature=31)) == ()
    escalated = machine.consume(reading_at(420, temperature=31))
    assert escalated[0].kind == "escalated"
    assert escalated[0].incident.severity == "critical"
    assert machine.consume(reading_at(480, temperature=31)) == ()


def test_range_recovery_requires_five_continuous_minutes() -> None:
    module = state_module()
    machine = module.EnvironmentStateMachine(module.EnvironmentStatePolicy())
    machine.consume(reading_at(0, temperature=27))
    machine.consume(reading_at(300, temperature=27))

    assert machine.consume(reading_at(360)) == ()
    assert machine.consume(reading_at(659)) == ()
    recovered = machine.consume(reading_at(660))

    assert recovered[0].kind == "recovered"
    assert recovered[0].incident.state == "recovered"
    assert machine.consume(reading_at(720)) == ()


def test_unreadable_opens_after_ten_minutes_and_recovers_after_two_valid() -> None:
    module = state_module()
    machine = module.EnvironmentStateMachine(module.EnvironmentStatePolicy())

    assert machine.consume(unavailable_at(0)) == ()
    assert machine.consume(unavailable_at(599)) == ()
    opened = machine.consume(unavailable_at(600))
    assert opened[0].kind == "opened"
    assert opened[0].incident.kind == "unreadable"

    assert machine.consume(reading_at(660)) == ()
    recovered = machine.consume(reading_at(720))
    assert recovered[0].kind == "recovered"
    assert recovered[0].incident.kind == "unreadable"


def test_missing_new_records_uses_same_unreadable_incident() -> None:
    module = state_module()
    machine = module.EnvironmentStateMachine(module.EnvironmentStatePolicy())
    machine.consume(reading_at(0))

    assert machine.observe_missing_record(BASE + timedelta(seconds=599)) == ()
    opened = machine.observe_missing_record(BASE + timedelta(seconds=600))

    assert opened[0].kind == "opened"
    assert opened[0].incident.kind == "unreadable"
    assert opened[0].incident.reasons == ("no_new_reading",)
    assert machine.observe_missing_record(BASE + timedelta(seconds=700)) == ()


def test_restart_preserves_open_incident_but_resets_incomplete_recovery_timer() -> None:
    module = state_module()
    machine = module.EnvironmentStateMachine(module.EnvironmentStatePolicy())
    machine.consume(reading_at(0, temperature=27))
    machine.consume(reading_at(300, temperature=27))
    machine.consume(reading_at(360))

    restored = module.EnvironmentStateMachine.restore(
        module.EnvironmentStatePolicy(), machine.snapshot()
    )

    assert restored.consume(reading_at(600)) == ()
    assert restored.consume(reading_at(899)) == ()
    recovered = restored.consume(reading_at(900))
    assert recovered[0].kind == "recovered"


def test_reason_change_is_audit_transition_without_reopening() -> None:
    module = state_module()
    machine = module.EnvironmentStateMachine(module.EnvironmentStatePolicy())
    machine.consume(reading_at(0, temperature=27))
    opened = machine.consume(reading_at(300, temperature=27))

    changed = machine.consume(reading_at(360, temperature=27, humidity=70))

    assert changed[0].kind == "reasons_changed"
    assert changed[0].incident.incident_id == opened[0].incident.incident_id
    assert changed[0].incident.reasons == ("temperature_high", "humidity_high")
