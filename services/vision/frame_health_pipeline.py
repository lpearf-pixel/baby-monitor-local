from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
from typing import Protocol
from uuid import uuid4

from services.storage.visual_health import (
    StoredVisualHealthIncident,
    VisualHealthStore,
)
from services.vision.frame_health import FrameHealthCode, FrameHealthTransition


class VisualHealthNotificationResult(Protocol):
    delivered: bool


class VisualHealthNotifier(Protocol):
    def notify(
        self,
        incident: StoredVisualHealthIncident,
        transition_kind: str,
    ) -> VisualHealthNotificationResult: ...


def _local_now() -> datetime:
    return datetime.now().astimezone()


class VisualFrameHealthPipeline:
    def __init__(
        self,
        *,
        store: VisualHealthStore,
        open_incident: StoredVisualHealthIncident | None,
        notifier: VisualHealthNotifier | None,
        clock: Callable[[], datetime],
    ) -> None:
        self._store = store
        self._open_incident = open_incident
        self._notifier = notifier
        self._clock = clock
        self._last_wall_time = (
            open_incident.updated_at if open_incident is not None else None
        )

    @classmethod
    def restore(
        cls,
        *,
        store: VisualHealthStore,
        notifier: VisualHealthNotifier | None = None,
        clock: Callable[[], datetime] = _local_now,
    ) -> "VisualFrameHealthPipeline":
        pipeline = cls(
            store=store,
            open_incident=store.load_open(),
            notifier=notifier,
            clock=clock,
        )
        if pipeline._open_incident is not None:
            pipeline._deliver_pending(pipeline._open_incident)
        return pipeline

    def handle(self, transition: FrameHealthTransition) -> None:
        if transition.code is FrameHealthCode.RECONNECT_REQUIRED:
            return
        if transition.code in {
            FrameHealthCode.SOURCE_OFFLINE,
            FrameHealthCode.FRAME_FROZEN,
        }:
            if self._open_incident is not None:
                self._deliver_pending(self._open_incident)
                return
            now = self._next_time()
            incident = StoredVisualHealthIncident(
                incident_id=str(uuid4()),
                code=transition.code.value,
                state="open",
                opened_at=now,
                updated_at=now,
                duration_seconds=transition.duration_seconds,
            )
            self._store.save(incident)
            self._open_incident = incident
            self._deliver_pending(incident)
            return
        if transition.code is FrameHealthCode.RECOVERED:
            if self._open_incident is None:
                return
            now = self._next_time()
            incident = self._open_incident.model_copy(
                update={
                    "state": "recovered",
                    "updated_at": now,
                    "recovered_at": now,
                    "duration_seconds": transition.duration_seconds,
                }
            )
            incident = StoredVisualHealthIncident.model_validate(incident)
            self._store.save(incident)
            self._open_incident = None
            self._deliver_pending(incident)

    def _next_time(self) -> datetime:
        value = self._clock()
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("wall clock must be timezone-aware")
        if self._last_wall_time is not None and value < self._last_wall_time:
            raise ValueError("wall clock cannot decrease")
        self._last_wall_time = value
        return value

    def _deliver_pending(self, incident: StoredVisualHealthIncident) -> None:
        if self._notifier is None:
            return
        transition_kind = "recovered" if incident.state == "recovered" else "opened"
        already_delivered = (
            incident.recovered_notified
            if transition_kind == "recovered"
            else incident.opened_notified
        )
        if already_delivered:
            return
        result = self._notifier.notify(incident, transition_kind)
        if not bool(getattr(result, "delivered", False)):
            return
        field = (
            "recovered_notified"
            if transition_kind == "recovered"
            else "opened_notified"
        )
        delivered = incident.model_copy(update={field: True})
        self._store.save(delivered)
        if delivered.state == "open":
            self._open_incident = delivered
