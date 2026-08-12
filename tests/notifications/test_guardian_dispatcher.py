from __future__ import annotations

import io
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from threading import Event

from packages.contracts.vision import VisualRiskKind
from services.notifications.guardian_dispatcher import GuardianNotificationDispatcher
from services.notifications.ntfy import NotificationResult
from services.storage.visual_risk import VisualRiskEventStore


NOW = datetime(2026, 8, 11, 12, 0, tzinfo=UTC)


class RecordingNotifier:
    def __init__(self, outcomes: list[NotificationResult | Exception]) -> None:
        self.outcomes = outcomes
        self.calls: list[tuple[object, object, str]] = []

    def notify(
        self,
        notification: object,
        event: object,
        evidence_state: str,
    ) -> NotificationResult:
        self.calls.append((notification, event, evidence_state))
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


def prepared_store(tmp_path: Path) -> tuple[VisualRiskEventStore, str]:
    store = VisualRiskEventStore(tmp_path / "events.sqlite3")
    store.migrate()
    store.open_event(
        event_id="event-face",
        risk_kind=VisualRiskKind.FACE_NOT_VISIBLE,
        opened_at=NOW,
        confidence=0.82,
        rule_version="visual-risk-v1",
    )
    notification = store.queue_notification(
        notification_id="notification-open",
        event_id="event-face",
        stage="risk_opened",
        queued_at=NOW,
    )
    return store, notification.notification_id


def result(code: str, *, delivered: bool = False) -> NotificationResult:
    return NotificationResult(
        delivered=delivered,
        code=code,
        attempts=1 if code != "payload_rejected" else 0,
    )


def test_dispatch_delivers_pending_notification_with_evidence_fallback(
    tmp_path: Path,
) -> None:
    store, notification_id = prepared_store(tmp_path)
    notifier = RecordingNotifier([result("ok", delivered=True)])
    stream = io.StringIO()
    dispatcher = GuardianNotificationDispatcher(
        store=store,
        notifier=notifier,
        stream=stream,
    )

    assert dispatcher.dispatch_once(NOW) is True

    stored = store.get_notification(notification_id)
    assert stored is not None
    assert stored.state == "delivered"
    assert stored.result_code == "ok"
    assert notifier.calls[0][2] == "unavailable"
    payload = json.loads(stream.getvalue())
    assert payload["code"] == "guardian.notification_delivered"
    assert payload["notification_id"] == notification_id
    assert payload["event_id"] == "event-face"


def test_permanent_rejection_does_not_retry(tmp_path: Path) -> None:
    store, notification_id = prepared_store(tmp_path)
    notifier = RecordingNotifier([result("ntfy_rejected")])
    dispatcher = GuardianNotificationDispatcher(
        store=store,
        notifier=notifier,
        stream=io.StringIO(),
    )

    assert dispatcher.dispatch_once(NOW) is True
    assert dispatcher.dispatch_once(NOW + timedelta(days=1)) is False

    stored = store.get_notification(notification_id)
    assert stored is not None
    assert stored.state == "rejected"
    assert stored.result_code == "ntfy_rejected"
    assert len(notifier.calls) == 1


def test_unavailable_delivery_uses_bounded_retry_schedule(tmp_path: Path) -> None:
    store, notification_id = prepared_store(tmp_path)
    notifier = RecordingNotifier(
        [
            result("ntfy_unavailable"),
            result("ntfy_unavailable"),
            result("ntfy_unavailable"),
        ]
    )
    dispatcher = GuardianNotificationDispatcher(
        store=store,
        notifier=notifier,
        stream=io.StringIO(),
    )

    assert dispatcher.dispatch_once(NOW) is True
    assert dispatcher.dispatch_once(NOW + timedelta(seconds=4)) is False
    assert dispatcher.dispatch_once(NOW + timedelta(seconds=5)) is True
    assert dispatcher.dispatch_once(NOW + timedelta(seconds=34)) is False
    assert dispatcher.dispatch_once(NOW + timedelta(seconds=35)) is True

    stored = store.get_notification(notification_id)
    assert stored is not None
    assert stored.state == "rejected"
    assert stored.result_code == "retry_exhausted"
    assert stored.dispatch_count == 3
    assert len(notifier.calls) == 3


def test_notifier_exception_is_redacted_and_treated_as_unavailable(
    tmp_path: Path,
) -> None:
    store, notification_id = prepared_store(tmp_path)
    notifier = RecordingNotifier(
        [RuntimeError("token at /private/family 192.168.1.5")]
    )
    stream = io.StringIO()
    dispatcher = GuardianNotificationDispatcher(
        store=store,
        notifier=notifier,
        stream=stream,
    )

    assert dispatcher.dispatch_once(NOW) is True

    stored = store.get_notification(notification_id)
    assert stored is not None
    assert stored.state == "pending"
    assert stored.result_code == "ntfy_unavailable"
    serialized = stream.getvalue()
    assert "guardian.notification_retry_scheduled" in serialized
    assert "token" not in serialized
    assert "/private" not in serialized
    assert "192.168" not in serialized


def test_empty_queue_and_pre_set_stop_event_do_no_work(tmp_path: Path) -> None:
    store = VisualRiskEventStore(tmp_path / "events.sqlite3")
    store.migrate()
    notifier = RecordingNotifier([])
    dispatcher = GuardianNotificationDispatcher(
        store=store,
        notifier=notifier,
        stream=io.StringIO(),
    )
    stopped = Event()
    stopped.set()

    assert dispatcher.dispatch_once(NOW) is False
    dispatcher.run(stopped)
    assert notifier.calls == []


class BrokenStream:
    def write(self, _value: str) -> int:
        raise OSError("/private/family/notify.log")

    def flush(self) -> None:
        raise OSError("/private/family/notify.log")


def test_broken_log_stream_does_not_change_delivery(tmp_path: Path) -> None:
    store, notification_id = prepared_store(tmp_path)
    dispatcher = GuardianNotificationDispatcher(
        store=store,
        notifier=RecordingNotifier([result("ok", delivered=True)]),
        stream=BrokenStream(),
    )

    assert dispatcher.dispatch_once(NOW) is True
    stored = store.get_notification(notification_id)
    assert stored is not None
    assert stored.state == "delivered"
