from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from threading import Event

import pytest

from services.storage.visual_risk import VisualRiskEventStore
from packages.contracts.vision import VisualRiskKind


NOW = datetime(2026, 9, 2, tzinfo=timezone.utc)


def test_notification_store_delegates_and_records_decision(tmp_path: Path) -> None:
    from services.offline_application_sinks import RecordingNotificationStore

    actual = VisualRiskEventStore(tmp_path / "events.sqlite3")
    actual.migrate()
    event = actual.open_event(
        event_id="event-1", risk_kind=VisualRiskKind.FACE_NOT_VISIBLE, opened_at=NOW,
        confidence=0.9, rule_version="visual-risk-v1",
    )
    recording = RecordingNotificationStore(actual)
    notification = recording.queue_notification(
        notification_id="notification-1", event_id=event.event_id,
        stage="risk_opened", queued_at=NOW,
    )

    assert notification.notification_id == "notification-1"
    assert recording.load_open() == actual.load_open()
    assert recording.queued[0].event_id == event.event_id
    assert recording.queued[0].stage == "risk_opened"


@pytest.mark.parametrize(
    ("behavior", "success", "state"),
    [("success", True, "succeeded"), ("timeout", False, "timed_out"),
     ("failure", False, "failed")],
)
def test_reply_sink_has_one_bounded_terminal_lifecycle(
    behavior: str, success: bool, state: str
) -> None:
    from services.offline_application_sinks import RecordingReplySink

    identifiers = iter(["reply-1", "reply-2"])
    sink = RecordingReplySink(behavior=behavior, id_factory=lambda: next(identifiers))
    assert sink.speak_code("listen_only_ready", Event()) is success
    assert sink.residual_sessions == 0
    assert sink.recorded[0].reply_id == "reply-1"
    assert sink.recorded[0].started_count == 1
    assert sink.recorded[0].terminal_count == 1
    assert sink.recorded[0].terminal_state == state
    assert sink.recorded[0].generated_byte_count > 0
    sink.close()
    assert sink.residual_sessions == 0


def test_reply_sink_closes_cancelled_and_rejects_use_after_close() -> None:
    from services.offline_application_sinks import RecordingReplySink

    cancelled = Event()
    cancelled.set()
    sink = RecordingReplySink(behavior="success", id_factory=lambda: "reply-1")
    assert sink.speak_code("listen_only_ready", cancelled) is False
    assert sink.recorded[0].terminal_state == "cancelled"
    sink.close()
    with pytest.raises(RuntimeError, match="reply_sink_closed"):
        sink.speak_code("listen_only_ready", Event())


def test_sink_source_has_no_real_adapter_imports() -> None:
    source = (Path(__file__).parents[2] / "services/offline_application_sinks.py").read_text()
    lowered = source.lower()
    for forbidden in ("camera_reply", "xiaomi", "go2rtc", "notification_dispatch", "baby_care"):
        assert forbidden not in lowered
