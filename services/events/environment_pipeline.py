from __future__ import annotations

from datetime import datetime, timedelta
from typing import Protocol
from uuid import uuid4

from packages.contracts.events import (
    EnvironmentReading,
    EnvironmentSourceKind,
    ReadingFailureReason,
)
from services.events.environment_state import (
    EnvironmentIncident,
    EnvironmentStateMachine,
    EnvironmentStatePolicy,
    EnvironmentTransition,
)
from services.storage.environment import (
    EnvironmentStore,
    StoredEnvironmentIncident,
)


class EnvironmentNotifier(Protocol):
    def notify(
        self,
        transition: EnvironmentTransition,
        reading: EnvironmentReading,
    ) -> object: ...


class EnvironmentPipelineSink:
    """Atomically commits each reading with its deterministic incident state."""

    def __init__(
        self,
        *,
        store: EnvironmentStore,
        state_machine: EnvironmentStateMachine,
        notifier: EnvironmentNotifier | None = None,
        retention_days: int = 365,
    ) -> None:
        if retention_days <= 0:
            raise ValueError("retention_days must be positive")
        self._store = store
        self._state_machine = state_machine
        self._notifier = notifier
        self._retention_days = retention_days
        self._last_cleanup_at: datetime | None = None

    @property
    def state_machine(self) -> EnvironmentStateMachine:
        return self._state_machine

    @classmethod
    def restore(
        cls,
        *,
        store: EnvironmentStore,
        policy: EnvironmentStatePolicy,
        notifier: EnvironmentNotifier | None = None,
        retention_days: int = 365,
    ) -> "EnvironmentPipelineSink":
        snapshot = store.load_state_snapshot()
        state_machine = (
            EnvironmentStateMachine.restore(policy, snapshot)
            if snapshot is not None
            else EnvironmentStateMachine(policy)
        )
        return cls(
            store=store,
            state_machine=state_machine,
            notifier=notifier,
            retention_days=retention_days,
        )

    def append(self, reading: EnvironmentReading) -> None:
        before = self._state_machine.snapshot()
        transitions = (
            *self._state_machine.observe_missing_record(reading.captured_at),
            *self._state_machine.consume(reading),
        )
        incidents = self._incidents_for_commit(transitions)
        try:
            self._store.commit_pipeline(
                reading=reading,
                incidents=incidents,
                state_snapshot=self._state_machine.snapshot().model_dump(mode="json"),
                updated_at=reading.captured_at,
            )
        except Exception:
            self._state_machine = EnvironmentStateMachine.restore(
                self._state_machine.policy,
                before,
            )
            raise
        self._after_state_commit(reading, transitions)

    def process_stored(self, reading: EnvironmentReading) -> None:
        before = self._state_machine.snapshot()
        transitions = (
            *self._state_machine.observe_missing_record(reading.captured_at),
            *self._state_machine.consume(reading),
        )
        try:
            self._store.commit_state(
                incidents=self._incidents_for_commit(transitions),
                state_snapshot=self._state_machine.snapshot().model_dump(mode="json"),
                updated_at=reading.captured_at,
            )
        except Exception:
            self._state_machine = EnvironmentStateMachine.restore(
                self._state_machine.policy,
                before,
            )
            raise
        self._after_state_commit(reading, transitions)

    def _after_state_commit(
        self,
        reading: EnvironmentReading,
        transitions: tuple[EnvironmentTransition, ...],
    ) -> None:
        self._deliver_pending(
            reading,
            current_recovered_ids={
                transition.incident.incident_id
                for transition in transitions
                if transition.kind == "recovered"
            },
            only_incident_ids=None,
        )
        if (
            self._last_cleanup_at is None
            or reading.captured_at - self._last_cleanup_at >= timedelta(days=1)
        ):
            self._store.cleanup(
                now=reading.captured_at,
                retention_days=self._retention_days,
            )
            self._last_cleanup_at = reading.captured_at

    def check_missing(self, now: datetime) -> None:
        before = self._state_machine.snapshot()
        transitions = self._state_machine.observe_missing_record(now)
        if transitions:
            try:
                self._store.commit_state(
                    incidents=self._incidents_for_commit(transitions),
                    state_snapshot=self._state_machine.snapshot().model_dump(mode="json"),
                    updated_at=now,
                )
            except Exception:
                self._state_machine = EnvironmentStateMachine.restore(
                    self._state_machine.policy,
                    before,
                )
                raise
        missing_incident_ids = {
            incident.incident_id
            for incident in self._state_machine.open_incidents()
            if incident.kind == "unreadable" and "no_new_reading" in incident.reasons
        }
        if missing_incident_ids:
            self._deliver_pending(
                self._missing_notification_reading(now),
                current_recovered_ids=set(),
                only_incident_ids=missing_incident_ids,
            )

    def _incidents_for_commit(
        self,
        transitions: tuple[EnvironmentTransition, ...],
    ) -> tuple[StoredEnvironmentIncident, ...]:
        incidents: dict[str, EnvironmentIncident] = {
            item.incident_id: item for item in self._state_machine.open_incidents()
        }
        for transition in transitions:
            incidents[transition.incident.incident_id] = transition.incident
        return tuple(self._as_stored(item) for item in incidents.values())

    def _as_stored(self, incident: EnvironmentIncident) -> StoredEnvironmentIncident:
        previous = self._store.incident(incident.incident_id)
        return StoredEnvironmentIncident(
            incident_id=incident.incident_id,
            kind=incident.kind,
            state=incident.state,
            severity=incident.severity,
            opened_at=incident.opened_at,
            updated_at=incident.updated_at,
            recovered_at=incident.recovered_at,
            reasons=incident.reasons,
            opening_reading_id=incident.opening_reading_id,
            notified_levels=previous.notified_levels if previous is not None else (),
        )

    @staticmethod
    def _missing_notification_reading(now: datetime) -> EnvironmentReading:
        return EnvironmentReading.unavailable(
            reading_id=str(uuid4()),
            source_kind=EnvironmentSourceKind.WS2021_GAUGE,
            captured_at=now,
            failure_reason=ReadingFailureReason.INTERNAL_ERROR,
            calibration_version="watchdog",
            sample_count=0,
        )

    def _deliver_pending(
        self,
        reading: EnvironmentReading,
        *,
        current_recovered_ids: set[str],
        only_incident_ids: set[str] | None,
    ) -> None:
        if self._notifier is None:
            return
        recovered = [
            incident
            for incident_id in current_recovered_ids
            if (incident := self._store.incident(incident_id)) is not None
        ]
        open_incidents = list(self._store.open_incidents(limit=10))
        candidates = [*recovered, *open_incidents]
        unique_candidates: dict[str, StoredEnvironmentIncident] = {}
        for incident in candidates:
            if only_incident_ids is None or incident.incident_id in only_incident_ids:
                unique_candidates.setdefault(incident.incident_id, incident)
        candidates = list(unique_candidates.values())[:2]
        for stored in candidates:
            marker = "recovered" if stored.state == "recovered" else stored.severity
            if marker in stored.notified_levels:
                continue
            transition_kind = self._pending_transition_kind(stored)
            incident = EnvironmentIncident(
                incident_id=stored.incident_id,
                kind=stored.kind,
                state=stored.state,
                severity=stored.severity,
                opened_at=stored.opened_at,
                updated_at=stored.updated_at,
                recovered_at=stored.recovered_at,
                reasons=stored.reasons,
                opening_reading_id=stored.opening_reading_id,
                data_available=(
                    stored.kind == "range" or stored.state == "recovered"
                ),
            )
            result = self._notifier.notify(
                EnvironmentTransition(
                    kind=transition_kind,
                    occurred_at=stored.updated_at,
                    incident=incident,
                    reading_id=reading.reading_id,
                ),
                reading,
            )
            if bool(getattr(result, "delivered", False)):
                self._store.save_incident(
                    stored.model_copy(
                        update={"notified_levels": (*stored.notified_levels, marker)}
                    )
                )

    @staticmethod
    def _pending_transition_kind(
        incident: StoredEnvironmentIncident,
    ) -> str:
        if incident.state == "recovered":
            return "recovered"
        if incident.severity == "critical" and "normal" in incident.notified_levels:
            return "escalated"
        return "opened"
