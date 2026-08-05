from __future__ import annotations

from typing import Protocol

from packages.contracts.events import EnvironmentReading
from services.events.environment_state import (
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
    """Commits readings before deterministic state, incident and notification work."""

    def __init__(
        self,
        *,
        store: EnvironmentStore,
        state_machine: EnvironmentStateMachine,
        notifier: EnvironmentNotifier | None = None,
    ) -> None:
        self._store = store
        self._state_machine = state_machine
        self._notifier = notifier

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
    ) -> "EnvironmentPipelineSink":
        snapshot = store.load_state_snapshot()
        state_machine = (
            EnvironmentStateMachine.restore(policy, snapshot)
            if snapshot is not None
            else EnvironmentStateMachine(policy)
        )
        return cls(store=store, state_machine=state_machine, notifier=notifier)

    def append(self, reading: EnvironmentReading) -> None:
        self._store.append(reading)
        transitions = [
            *self._state_machine.observe_missing_record(reading.captured_at),
            *self._state_machine.consume(reading),
        ]
        for transition in transitions:
            self._persist_transition(transition)
        self._store.save_state_snapshot(
            self._state_machine.snapshot().model_dump(mode="json"),
            updated_at=reading.captured_at,
        )
        if self._notifier is not None:
            for transition in transitions:
                if transition.kind != "reasons_changed":
                    self._notifier.notify(transition, reading)

    def _persist_transition(self, transition: EnvironmentTransition) -> None:
        incident = transition.incident
        previous = self._store.incident(incident.incident_id)
        notified_levels = list(previous.notified_levels if previous is not None else ())
        marker = "recovered" if transition.kind == "recovered" else incident.severity
        if transition.kind != "reasons_changed" and marker not in notified_levels:
            notified_levels.append(marker)
        self._store.save_incident(
            StoredEnvironmentIncident(
                incident_id=incident.incident_id,
                kind=incident.kind,
                state=incident.state,
                severity=incident.severity,
                opened_at=incident.opened_at,
                updated_at=incident.updated_at,
                recovered_at=incident.recovered_at,
                reasons=incident.reasons,
                opening_reading_id=incident.opening_reading_id,
                notified_levels=tuple(notified_levels),
            )
        )
