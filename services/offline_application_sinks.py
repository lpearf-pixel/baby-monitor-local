from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from threading import Event
from typing import Literal

from services.storage.visual_risk import (
    NotificationStage,
    StoredVisualRiskNotification,
    VisualRiskEventStore,
)


@dataclass(frozen=True)
class RecordedNotification:
    notification_id: str
    event_id: str
    stage: Literal["risk_opened", "risk_recovered", "adult_intervention"]
    intervention_id: str | None


@dataclass(frozen=True)
class RecordedReply:
    reply_id: str
    response_code: str
    generated_byte_count: int
    started_count: Literal[1]
    terminal_count: Literal[1]
    terminal_state: Literal["succeeded", "timed_out", "failed", "cancelled"]


class RecordingNotificationStore:
    def __init__(
        self,
        store: VisualRiskEventStore,
        *,
        id_factory: Callable[[], str] | None = None,
    ) -> None:
        self._store = store
        self._id_factory = id_factory
        self._queued: list[RecordedNotification] = []

    @property
    def queued(self) -> tuple[RecordedNotification, ...]:
        return tuple(self._queued)

    def __getattr__(self, name: str):
        return getattr(self._store, name)

    def queue_notification(
        self,
        *,
        notification_id: str,
        event_id: str,
        stage: NotificationStage,
        queued_at: datetime,
        intervention_id: str | None = None,
    ) -> StoredVisualRiskNotification:
        value = self._store.queue_notification(
            notification_id=(self._id_factory() if self._id_factory else notification_id),
            event_id=event_id,
            stage=stage,
            queued_at=queued_at,
            intervention_id=intervention_id,
        )
        self._queued.append(
            RecordedNotification(
                notification_id=value.notification_id,
                event_id=value.event_id,
                stage=value.stage,
                intervention_id=value.intervention_id,
            )
        )
        return value


class RecordingReplySink:
    def __init__(
        self,
        *,
        behavior: Literal["success", "timeout", "failure"],
        id_factory: Callable[[], str],
    ) -> None:
        self._behavior = behavior
        self._id_factory = id_factory
        self._recorded: list[RecordedReply] = []
        self._ids: set[str] = set()
        self._active = False
        self._closed = False

    @property
    def recorded(self) -> tuple[RecordedReply, ...]:
        return tuple(self._recorded)

    @property
    def residual_sessions(self) -> int:
        return int(self._active)

    def speak_code(self, code: str, cancelled: Event) -> bool:
        if self._closed:
            raise RuntimeError("reply_sink_closed")
        if self._active:
            raise RuntimeError("reply_session_active")
        reply_id = self._id_factory()
        if reply_id in self._ids:
            raise RuntimeError("reply_id_duplicate")
        self._ids.add(reply_id)
        self._active = True
        try:
            if cancelled.is_set():
                terminal_state = "cancelled"
                success = False
            elif self._behavior == "success":
                terminal_state = "succeeded"
                success = True
            elif self._behavior == "timeout":
                terminal_state = "timed_out"
                success = False
            else:
                terminal_state = "failed"
                success = False
            self._recorded.append(
                RecordedReply(
                    reply_id=reply_id,
                    response_code=code,
                    generated_byte_count=min(len(code.encode("ascii")), 4096),
                    started_count=1,
                    terminal_count=1,
                    terminal_state=terminal_state,
                )
            )
            return success
        finally:
            self._active = False

    def close(self) -> None:
        self._active = False
        self._closed = True


__all__ = [
    "RecordedNotification", "RecordedReply", "RecordingNotificationStore",
    "RecordingReplySink",
]
