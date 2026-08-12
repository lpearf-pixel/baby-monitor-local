from __future__ import annotations

import hashlib
import json
import sys
from collections.abc import Callable
from datetime import datetime
from typing import TextIO
from uuid import uuid4

from packages.contracts.vision import (
    RiskSnapshot,
    RiskTransition,
    RiskTransitionKind,
)
from services.storage.visual_risk import (
    NotificationStage,
    StoredVisualRiskEvent,
    VisualRiskEventStore,
)


class _GuardianJsonLog:
    def __init__(self, stream: TextIO) -> None:
        self._stream = stream

    def emit(
        self,
        code: str,
        *,
        observed_at: datetime,
        transition: RiskTransition | None = None,
        event_id: str | None = None,
        intervention_id: str | None = None,
        state: str | None = None,
        result: str | None = None,
        linked_event_count: int | None = None,
        notification_id: str | None = None,
        notification_stage: str | None = None,
    ) -> None:
        payload: dict[str, object] = {
            "schema_version": 1,
            "component": "baby_guardian",
            "code": code,
            "observed_at": observed_at.isoformat(),
        }
        if transition is not None:
            payload["transition_kind"] = transition.transition_kind.value
            payload["rule_version"] = transition.rule_version
            if transition.risk_kind is not None:
                payload["risk_kind"] = transition.risk_kind.value
        if event_id is not None:
            payload["event_id"] = event_id
        if intervention_id is not None:
            payload["intervention_id"] = intervention_id
        if state is not None:
            payload["state"] = state
        if result is not None:
            payload["result"] = result
        if linked_event_count is not None:
            payload["linked_event_count"] = linked_event_count
        if notification_id is not None:
            payload["notification_id"] = notification_id
        if notification_stage is not None:
            payload["notification_stage"] = notification_stage
        try:
            self._stream.write(
                json.dumps(
                    payload,
                    ensure_ascii=True,
                    sort_keys=True,
                    separators=(",", ":"),
                )
                + "\n"
            )
            self._stream.flush()
        except Exception:
            return


class VisualRiskEventPipeline:
    def __init__(
        self,
        *,
        store: VisualRiskEventStore,
        stream: TextIO = sys.stderr,
        event_id_factory: Callable[[], str] | None = None,
        on_event_opened: Callable[
            [StoredVisualRiskEvent, RiskTransition], None
        ]
        | None = None,
    ) -> None:
        self._store = store
        self._log = _GuardianJsonLog(stream)
        self._event_id_factory = event_id_factory or (lambda: str(uuid4()))
        self._on_event_opened = on_event_opened or (
            lambda _event, _transition: None
        )

    def restore_snapshot(self, snapshot_at: datetime) -> RiskSnapshot:
        empty = RiskSnapshot(snapshot_at=snapshot_at)
        try:
            open_events = self._store.load_open()
        except Exception:
            self._log.emit(
                "guardian.restore_failed",
                observed_at=snapshot_at,
                result="persistence_unavailable",
            )
            return empty
        snapshot = RiskSnapshot(
            snapshot_at=snapshot_at,
            open_risks=frozenset(event.risk_kind for event in open_events),
        )
        if snapshot.open_risks:
            self._log.emit(
                "guardian.restore_completed",
                observed_at=snapshot_at,
                result="restored",
                linked_event_count=len(snapshot.open_risks),
            )
        return snapshot

    def handle(self, transition: RiskTransition) -> None:
        self._log.emit(
            "guardian.transition_observed",
            observed_at=transition.observed_at,
            transition=transition,
            state=transition.current_state.value,
        )
        try:
            self._persist(transition)
        except Exception:
            self._log.emit(
                "guardian.persistence_failed",
                observed_at=transition.observed_at,
                transition=transition,
                result="write_failed",
            )

    def _persist(self, transition: RiskTransition) -> None:
        if transition.transition_kind in {
            RiskTransitionKind.WATCH_STARTED,
            RiskTransitionKind.WATCH_CLEARED,
        }:
            return
        if transition.transition_kind is RiskTransitionKind.ALERT_OPENED:
            if transition.risk_kind is None or transition.confidence is None:
                raise ValueError("alert transition requires risk and confidence")
            existing = next(
                (
                    event
                    for event in self._store.load_open()
                    if event.risk_kind is transition.risk_kind
                ),
                None,
            )
            proposed_id = self._event_id_factory()
            event = self._store.open_event(
                event_id=proposed_id,
                risk_kind=transition.risk_kind,
                opened_at=transition.observed_at,
                confidence=transition.confidence,
                rule_version=transition.rule_version,
            )
            self._log.emit(
                "guardian.event_opened",
                observed_at=transition.observed_at,
                transition=transition,
                event_id=event.event_id,
                state=event.state,
                result="existing" if existing is not None else "created",
            )
            if existing is None:
                try:
                    self._on_event_opened(event, transition)
                except Exception:
                    self._log.emit(
                        "guardian.evidence_failed",
                        observed_at=transition.observed_at,
                        transition=transition,
                        event_id=event.event_id,
                        state="failed",
                        result="callback_failed",
                    )
                self._queue_notification(
                    event=event,
                    stage="risk_opened",
                    queued_at=transition.observed_at,
                    transition=transition,
                )
            return
        if transition.transition_kind is RiskTransitionKind.RECOVERED:
            if transition.risk_kind is None or transition.confidence is None:
                raise ValueError("recovery transition requires risk and confidence")
            event = self._store.recover_event(
                risk_kind=transition.risk_kind,
                recovered_at=transition.observed_at,
                confidence=transition.confidence,
                rule_version=transition.rule_version,
            )
            if event is None:
                self._log.emit(
                    "guardian.transition_ignored",
                    observed_at=transition.observed_at,
                    transition=transition,
                    result="no_open_event",
                )
                return
            self._log.emit(
                "guardian.event_recovered",
                observed_at=transition.observed_at,
                transition=transition,
                event_id=event.event_id,
                state=event.state,
                result="recovered",
            )
            self._queue_notification(
                event=event,
                stage="risk_recovered",
                queued_at=transition.observed_at,
                transition=transition,
            )
            return
        if transition.transition_kind is RiskTransitionKind.ADULT_INTERVENTION:
            if transition.confidence is None:
                raise ValueError("adult intervention requires confidence")
            intervention_id = self._intervention_id(transition)
            intervention = self._store.record_intervention(
                intervention_id=intervention_id,
                observed_at=transition.observed_at,
                confidence=transition.confidence,
                rule_version=transition.rule_version,
            )
            linked_event_ids = self._store.intervention_event_ids(
                intervention.intervention_id
            )
            self._log.emit(
                "guardian.intervention_recorded",
                observed_at=transition.observed_at,
                transition=transition,
                intervention_id=intervention.intervention_id,
                result="recorded",
                linked_event_count=len(linked_event_ids),
            )
            open_events = {
                event.event_id: event for event in self._store.load_open()
            }
            for event_id in linked_event_ids:
                event = open_events.get(event_id)
                if event is not None:
                    self._queue_notification(
                        event=event,
                        stage="adult_intervention",
                        queued_at=transition.observed_at,
                        transition=transition,
                        intervention_id=intervention.intervention_id,
                    )

    def _queue_notification(
        self,
        *,
        event: StoredVisualRiskEvent,
        stage: NotificationStage,
        queued_at: datetime,
        transition: RiskTransition,
        intervention_id: str | None = None,
    ) -> None:
        notification_id = self._notification_id(
            event.event_id,
            stage,
            intervention_id,
        )
        try:
            notification = self._store.queue_notification(
                notification_id=notification_id,
                event_id=event.event_id,
                stage=stage,
                queued_at=queued_at,
                intervention_id=intervention_id,
            )
        except Exception:
            self._log.emit(
                "guardian.notification_queue_failed",
                observed_at=queued_at,
                transition=transition,
                event_id=event.event_id,
                notification_id=notification_id,
                notification_stage=stage,
                result="queue_failed",
            )
            return
        self._log.emit(
            "guardian.notification_queued",
            observed_at=queued_at,
            transition=transition,
            event_id=event.event_id,
            notification_id=notification.notification_id,
            notification_stage=notification.stage,
            state=notification.state,
            result="queued",
        )

    @staticmethod
    def _notification_id(
        event_id: str,
        stage: NotificationStage,
        intervention_id: str | None,
    ) -> str:
        material = "|".join(
            (event_id, stage, intervention_id or "")
        ).encode("utf-8")
        return f"notification-{hashlib.sha256(material).hexdigest()}"

    @staticmethod
    def _intervention_id(transition: RiskTransition) -> str:
        material = "|".join(
            (
                transition.transition_kind.value,
                transition.rule_version,
                transition.observed_at.isoformat(),
            )
        ).encode("ascii")
        return f"intervention-{hashlib.sha256(material).hexdigest()}"
