from __future__ import annotations

from datetime import datetime
from typing import Any, Literal, Protocol, Self
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from packages.contracts.events import EnvironmentReading, ReadingState


class StateModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


def _aware(value: datetime | None) -> datetime | None:
    if value is not None and (value.tzinfo is None or value.utcoffset() is None):
        raise ValueError("datetime must be timezone-aware")
    return value


class EnvironmentStatePolicy(StateModel):
    policy_version: str = "environment-v1"
    temperature_low_c: float = 18
    temperature_high_c: float = 26
    temperature_critical_low_c: float = 15
    temperature_critical_high_c: float = 30
    humidity_low_rh: float = 35
    humidity_high_rh: float = 60
    humidity_critical_low_rh: float = 25
    humidity_critical_high_rh: float = 75
    normal_sustained_seconds: int = Field(default=300, gt=0)
    recovery_sustained_seconds: int = Field(default=300, gt=0)
    unreadable_seconds: int = Field(default=600, gt=0)
    critical_confirmations: int = Field(default=2, ge=2)
    critical_min_span_seconds: int = Field(default=60, gt=0)

    @model_validator(mode="after")
    def require_nested_thresholds(self) -> Self:
        if not (
            self.temperature_critical_low_c
            < self.temperature_low_c
            < self.temperature_high_c
            < self.temperature_critical_high_c
        ):
            raise ValueError("temperature thresholds must be strictly nested")
        if not (
            self.humidity_critical_low_rh
            < self.humidity_low_rh
            < self.humidity_high_rh
            < self.humidity_critical_high_rh
        ):
            raise ValueError("humidity thresholds must be strictly nested")
        return self


class EnvironmentIncident(StateModel):
    incident_id: str = Field(min_length=1)
    kind: Literal["range", "unreadable"]
    state: Literal["open", "recovered"]
    severity: Literal["normal", "critical"]
    opened_at: datetime
    updated_at: datetime
    recovered_at: datetime | None = None
    reasons: tuple[str, ...]
    opening_reading_id: str | None = None
    data_available: bool

    _aware_opened_at = field_validator("opened_at")(_aware)
    _aware_updated_at = field_validator("updated_at")(_aware)
    _aware_recovered_at = field_validator("recovered_at")(_aware)


class EnvironmentTransition(StateModel):
    kind: Literal["opened", "escalated", "recovered", "reasons_changed"]
    occurred_at: datetime
    incident: EnvironmentIncident
    reading_id: str | None = None

    _aware_occurred_at = field_validator("occurred_at")(_aware)


class EnvironmentStateSnapshot(StateModel):
    schema_version: Literal[1] = 1
    range_incident: EnvironmentIncident | None = None
    unreadable_incident: EnvironmentIncident | None = None
    last_record_at: datetime | None = None

    _aware_last_record_at = field_validator("last_record_at")(_aware)


class EnvironmentStateMachine:
    def __init__(self, policy: EnvironmentStatePolicy) -> None:
        self._policy = policy
        self._range_incident: EnvironmentIncident | None = None
        self._unreadable_incident: EnvironmentIncident | None = None
        self._last_record_at: datetime | None = None
        self._range_pending_since: datetime | None = None
        self._range_recovery_since: datetime | None = None
        self._critical_since: datetime | None = None
        self._critical_count = 0
        self._critical_reasons: tuple[str, ...] = ()
        self._unreadable_since: datetime | None = None
        self._unreadable_reason = "reading_unavailable"
        self._unreadable_recovery_count = 0

    @classmethod
    def restore(
        cls,
        policy: EnvironmentStatePolicy,
        snapshot: EnvironmentStateSnapshot | dict[str, Any],
    ) -> "EnvironmentStateMachine":
        validated = EnvironmentStateSnapshot.model_validate(snapshot)
        machine = cls(policy)
        machine._range_incident = validated.range_incident
        machine._unreadable_incident = validated.unreadable_incident
        machine._last_record_at = validated.last_record_at
        return machine

    def snapshot(self) -> EnvironmentStateSnapshot:
        return EnvironmentStateSnapshot(
            range_incident=self._range_incident,
            unreadable_incident=self._unreadable_incident,
            last_record_at=self._last_record_at,
        )

    def open_incidents(self) -> tuple[EnvironmentIncident, ...]:
        return tuple(
            incident
            for incident in (self._range_incident, self._unreadable_incident)
            if incident is not None
        )

    def consume(
        self,
        reading: EnvironmentReading,
    ) -> tuple[EnvironmentTransition, ...]:
        self._last_record_at = reading.captured_at
        if reading.state is ReadingState.UNAVAILABLE:
            return self._consume_unavailable(reading)

        transitions: list[EnvironmentTransition] = []
        unreadable_recovery = self._consume_valid_for_unreadable(reading)
        if unreadable_recovery is not None:
            transitions.append(unreadable_recovery)
        transitions.extend(self._consume_available_range(reading))
        return tuple(transitions)

    def observe_missing_record(
        self,
        now: datetime,
    ) -> tuple[EnvironmentTransition, ...]:
        _aware(now)
        if self._unreadable_incident is not None:
            return ()
        since = self._last_record_at
        if since is None:
            if self._unreadable_since is None:
                self._unreadable_since = now
                self._unreadable_reason = "no_new_reading"
                return ()
            since = self._unreadable_since
        if (now - since).total_seconds() < self._policy.unreadable_seconds:
            return ()
        return (self._open_unreadable(now, "no_new_reading", reading_id=None),)

    def _consume_unavailable(
        self,
        reading: EnvironmentReading,
    ) -> tuple[EnvironmentTransition, ...]:
        self._range_pending_since = None
        self._range_recovery_since = None
        self._reset_critical()
        self._unreadable_recovery_count = 0
        if self._range_incident is not None and self._range_incident.data_available:
            self._range_incident = self._range_incident.model_copy(
                update={"data_available": False, "updated_at": reading.captured_at}
            )

        if self._unreadable_incident is not None:
            return ()
        if self._unreadable_since is None:
            self._unreadable_since = reading.captured_at
            self._unreadable_reason = (
                reading.failure_reason.value
                if reading.failure_reason is not None
                else "reading_unavailable"
            )
            return ()
        if (
            reading.captured_at - self._unreadable_since
        ).total_seconds() < self._policy.unreadable_seconds:
            return ()
        return (
            self._open_unreadable(
                reading.captured_at,
                self._unreadable_reason,
                reading_id=reading.reading_id,
            ),
        )

    def _open_unreadable(
        self,
        occurred_at: datetime,
        reason: str,
        *,
        reading_id: str | None,
    ) -> EnvironmentTransition:
        opened_at = self._unreadable_since or self._last_record_at or occurred_at
        incident = EnvironmentIncident(
            incident_id=str(uuid4()),
            kind="unreadable",
            state="open",
            severity="normal",
            opened_at=opened_at,
            updated_at=occurred_at,
            reasons=(reason,),
            opening_reading_id=reading_id,
            data_available=False,
        )
        self._unreadable_incident = incident
        self._unreadable_since = None
        return EnvironmentTransition(
            kind="opened",
            occurred_at=occurred_at,
            incident=incident,
            reading_id=reading_id,
        )

    def _consume_valid_for_unreadable(
        self,
        reading: EnvironmentReading,
    ) -> EnvironmentTransition | None:
        self._unreadable_since = None
        if self._unreadable_incident is None:
            self._unreadable_recovery_count = 0
            return None
        self._unreadable_recovery_count += 1
        if self._unreadable_recovery_count < 2:
            return None
        recovered = self._unreadable_incident.model_copy(
            update={
                "state": "recovered",
                "updated_at": reading.captured_at,
                "recovered_at": reading.captured_at,
                "data_available": True,
            }
        )
        self._unreadable_incident = None
        self._unreadable_recovery_count = 0
        return EnvironmentTransition(
            kind="recovered",
            occurred_at=reading.captured_at,
            incident=recovered,
            reading_id=reading.reading_id,
        )

    def _consume_available_range(
        self,
        reading: EnvironmentReading,
    ) -> list[EnvironmentTransition]:
        reasons = self._range_reasons(reading)
        critical_reasons = self._critical_reasons_for(reading)
        transitions: list[EnvironmentTransition] = []

        if self._range_incident is not None and not self._range_incident.data_available:
            self._range_incident = self._range_incident.model_copy(
                update={"data_available": True, "updated_at": reading.captured_at}
            )

        if reasons:
            self._range_recovery_since = None
            if self._range_pending_since is None:
                self._range_pending_since = reading.captured_at
            if critical_reasons:
                critical_transition = self._advance_critical(
                    reading, reasons, critical_reasons
                )
                if critical_transition is not None:
                    transitions.append(critical_transition)
            else:
                self._reset_critical()

            if self._range_incident is None and not transitions:
                elapsed = (
                    reading.captured_at - self._range_pending_since
                ).total_seconds()
                if elapsed >= self._policy.normal_sustained_seconds:
                    incident = EnvironmentIncident(
                        incident_id=str(uuid4()),
                        kind="range",
                        state="open",
                        severity="normal",
                        opened_at=self._range_pending_since,
                        updated_at=reading.captured_at,
                        reasons=reasons,
                        opening_reading_id=reading.reading_id,
                        data_available=True,
                    )
                    self._range_incident = incident
                    self._range_pending_since = None
                    transitions.append(
                        EnvironmentTransition(
                            kind="opened",
                            occurred_at=reading.captured_at,
                            incident=incident,
                            reading_id=reading.reading_id,
                        )
                    )

            if self._range_incident is not None:
                current_reasons = self._range_incident.reasons
                if reasons != current_reasons:
                    updated = self._range_incident.model_copy(
                        update={"reasons": reasons, "updated_at": reading.captured_at}
                    )
                    self._range_incident = updated
                    transitions.append(
                        EnvironmentTransition(
                            kind="reasons_changed",
                            occurred_at=reading.captured_at,
                            incident=updated,
                            reading_id=reading.reading_id,
                        )
                    )
            return transitions

        self._range_pending_since = None
        self._reset_critical()
        if self._range_incident is None:
            self._range_recovery_since = None
            return transitions
        if self._range_recovery_since is None:
            self._range_recovery_since = reading.captured_at
            return transitions
        if (
            reading.captured_at - self._range_recovery_since
        ).total_seconds() < self._policy.recovery_sustained_seconds:
            return transitions
        recovered = self._range_incident.model_copy(
            update={
                "state": "recovered",
                "updated_at": reading.captured_at,
                "recovered_at": reading.captured_at,
                "reasons": (),
                "data_available": True,
            }
        )
        self._range_incident = None
        self._range_recovery_since = None
        transitions.append(
            EnvironmentTransition(
                kind="recovered",
                occurred_at=reading.captured_at,
                incident=recovered,
                reading_id=reading.reading_id,
            )
        )
        return transitions

    def _advance_critical(
        self,
        reading: EnvironmentReading,
        reasons: tuple[str, ...],
        critical_reasons: tuple[str, ...],
    ) -> EnvironmentTransition | None:
        if critical_reasons != self._critical_reasons:
            self._critical_since = reading.captured_at
            self._critical_count = 1
            self._critical_reasons = critical_reasons
            return None
        self._critical_count += 1
        assert self._critical_since is not None
        span = (reading.captured_at - self._critical_since).total_seconds()
        if (
            self._critical_count < self._policy.critical_confirmations
            or span < self._policy.critical_min_span_seconds
        ):
            return None
        if self._range_incident is None:
            incident = EnvironmentIncident(
                incident_id=str(uuid4()),
                kind="range",
                state="open",
                severity="critical",
                opened_at=self._critical_since,
                updated_at=reading.captured_at,
                reasons=reasons,
                opening_reading_id=reading.reading_id,
                data_available=True,
            )
            self._range_incident = incident
            self._range_pending_since = None
            kind: Literal["opened", "escalated"] = "opened"
        elif self._range_incident.severity == "normal":
            incident = self._range_incident.model_copy(
                update={
                    "severity": "critical",
                    "updated_at": reading.captured_at,
                    "reasons": reasons,
                }
            )
            self._range_incident = incident
            kind = "escalated"
        else:
            return None
        return EnvironmentTransition(
            kind=kind,
            occurred_at=reading.captured_at,
            incident=incident,
            reading_id=reading.reading_id,
        )

    def _reset_critical(self) -> None:
        self._critical_since = None
        self._critical_count = 0
        self._critical_reasons = ()

    def _range_reasons(self, reading: EnvironmentReading) -> tuple[str, ...]:
        assert reading.temperature_c is not None
        assert reading.humidity_rh is not None
        reasons: list[str] = []
        if reading.temperature_c < self._policy.temperature_low_c:
            reasons.append("temperature_low")
        if reading.temperature_c > self._policy.temperature_high_c:
            reasons.append("temperature_high")
        if reading.humidity_rh < self._policy.humidity_low_rh:
            reasons.append("humidity_low")
        if reading.humidity_rh > self._policy.humidity_high_rh:
            reasons.append("humidity_high")
        return tuple(reasons)

    def _critical_reasons_for(
        self,
        reading: EnvironmentReading,
    ) -> tuple[str, ...]:
        assert reading.temperature_c is not None
        assert reading.humidity_rh is not None
        reasons: list[str] = []
        if reading.temperature_c < self._policy.temperature_critical_low_c:
            reasons.append("temperature_critical_low")
        if reading.temperature_c > self._policy.temperature_critical_high_c:
            reasons.append("temperature_critical_high")
        if reading.humidity_rh < self._policy.humidity_critical_low_rh:
            reasons.append("humidity_critical_low")
        if reading.humidity_rh > self._policy.humidity_critical_high_rh:
            reasons.append("humidity_critical_high")
        return tuple(reasons)


class EnvironmentReadingStore(Protocol):
    def latest(self) -> EnvironmentReading | None: ...

    def latest_available(self) -> EnvironmentReading | None: ...


class EnvironmentSnapshot(StateModel):
    generated_at: datetime
    policy_version: str
    current_reading: EnvironmentReading | None
    current_available: bool
    temperature_c: float | None = None
    humidity_rh: float | None = None
    last_valid_reading: EnvironmentReading | None
    open_incidents: tuple[EnvironmentIncident, ...]
    control_eligibility: Literal["ineligible"] = "ineligible"
    control_ineligibility_reasons: tuple[
        Literal["optical_source_only", "actuator_api_disabled"], ...
    ] = ("optical_source_only", "actuator_api_disabled")

    _aware_generated_at = field_validator("generated_at")(_aware)


class EnvironmentSnapshotProvider:
    def __init__(
        self,
        *,
        store: EnvironmentReadingStore,
        state_machine: EnvironmentStateMachine,
    ) -> None:
        self._store = store
        self._state_machine = state_machine

    def current(self, now: datetime) -> EnvironmentSnapshot:
        _aware(now)
        current = self._store.latest()
        current_available = bool(
            current is not None
            and current.state is ReadingState.AVAILABLE
            and current.fresh_until >= now
        )
        return EnvironmentSnapshot(
            generated_at=now,
            policy_version=self._state_machine._policy.policy_version,
            current_reading=current,
            current_available=current_available,
            temperature_c=(
                current.temperature_c if current_available and current is not None else None
            ),
            humidity_rh=(
                current.humidity_rh if current_available and current is not None else None
            ),
            last_valid_reading=self._store.latest_available(),
            open_incidents=self._state_machine.open_incidents(),
        )
