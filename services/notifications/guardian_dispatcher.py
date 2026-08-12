from __future__ import annotations

import json
import sys
from collections.abc import Callable
from datetime import datetime, timedelta
from typing import Protocol, TextIO

from services.notifications.ntfy import NotificationResult
from services.storage.visual_risk import (
    StoredVisualRiskEvent,
    StoredVisualRiskNotification,
    VisualRiskEventStore,
)


class GuardianNotifier(Protocol):
    def notify(
        self,
        notification: StoredVisualRiskNotification,
        event: StoredVisualRiskEvent,
        evidence_state: str,
    ) -> NotificationResult: ...


class StopEvent(Protocol):
    def is_set(self) -> bool: ...

    def wait(self, timeout: float) -> bool: ...


class _DispatchLog:
    def __init__(self, stream: TextIO) -> None:
        self._stream = stream

    def emit(
        self,
        code: str,
        *,
        observed_at: datetime,
        notification: StoredVisualRiskNotification | None = None,
        result: str,
    ) -> None:
        payload: dict[str, object] = {
            "schema_version": 1,
            "component": "baby_guardian",
            "code": code,
            "observed_at": observed_at.isoformat(),
            "result": result,
        }
        if notification is not None:
            payload.update(
                {
                    "notification_id": notification.notification_id,
                    "event_id": notification.event_id,
                    "notification_stage": notification.stage,
                    "state": notification.state,
                    "dispatch_count": notification.dispatch_count,
                }
            )
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


class GuardianNotificationDispatcher:
    def __init__(
        self,
        *,
        store: VisualRiskEventStore,
        notifier: GuardianNotifier,
        stream: TextIO = sys.stderr,
        clock: Callable[[], datetime] | None = None,
        poll_seconds: float = 1,
    ) -> None:
        if not 0 < poll_seconds <= 10:
            raise ValueError("poll_seconds must be between 0 and 10")
        self._store = store
        self._notifier = notifier
        self._log = _DispatchLog(stream)
        self._clock = clock or (lambda: datetime.now().astimezone())
        self._poll_seconds = poll_seconds

    def dispatch_once(self, now: datetime) -> bool:
        try:
            pending = self._store.next_pending_notification(now)
        except Exception:
            self._log.emit(
                "guardian.notification_dispatch_failed",
                observed_at=now,
                result="persistence_unavailable",
            )
            return False
        if pending is None:
            return False
        try:
            event = self._store.get_event(pending.event_id)
            evidence = self._store.get_evidence(pending.event_id)
        except Exception:
            self._log.emit(
                "guardian.notification_dispatch_failed",
                observed_at=now,
                notification=pending,
                result="persistence_unavailable",
            )
            return False
        if event is None:
            delivery = NotificationResult(
                delivered=False,
                code="payload_rejected",
                attempts=0,
            )
        else:
            try:
                delivery = self._notifier.notify(
                    pending,
                    event,
                    evidence.state if evidence is not None else "unavailable",
                )
            except Exception:
                delivery = NotificationResult(
                    delivered=False,
                    code="ntfy_unavailable",
                    attempts=0,
                )
        safe_result = (
            delivery.code
            if delivery.code
            in {"ok", "payload_rejected", "ntfy_rejected", "ntfy_unavailable"}
            else "payload_rejected"
        )
        retry_delays = (5, 30, 300)
        retry_at = now + timedelta(
            seconds=retry_delays[min(pending.dispatch_count, 2)]
        )
        try:
            stored = self._store.record_notification_result(
                notification_id=pending.notification_id,
                attempted_at=now,
                result_code=safe_result,
                retry_at=retry_at if safe_result == "ntfy_unavailable" else None,
            )
        except Exception:
            self._log.emit(
                "guardian.notification_dispatch_failed",
                observed_at=now,
                notification=pending,
                result="persistence_unavailable",
            )
            return True
        if stored.state == "delivered":
            code = "guardian.notification_delivered"
        elif stored.state == "pending":
            code = "guardian.notification_retry_scheduled"
        else:
            code = "guardian.notification_rejected"
        self._log.emit(
            code,
            observed_at=now,
            notification=stored,
            result=stored.result_code or "unknown",
        )
        return True

    def run(self, stop_event: StopEvent) -> None:
        while not stop_event.is_set():
            worked = self.dispatch_once(self._clock())
            if not worked:
                stop_event.wait(self._poll_seconds)
