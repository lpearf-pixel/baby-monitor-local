from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from services.notifications.ntfy import NotificationResult
from services.storage.visual_health import VisualHealthStore
from services.vision.frame_health import (
    FrameHealthCode,
    FrameHealthState,
    FrameHealthTransition,
)
from services.vision.frame_health_pipeline import VisualFrameHealthPipeline


NOW = datetime(2026, 8, 8, 18, 0, tzinfo=timezone(timedelta(hours=8)))


class RecordingNotifier:
    def __init__(self, delivered: list[bool]) -> None:
        self._delivered = iter(delivered)
        self.calls: list[tuple[str, str]] = []

    def notify(self, incident: object, transition_kind: str) -> NotificationResult:
        code = str(getattr(incident, "code"))
        self.calls.append((code, transition_kind))
        delivered = next(self._delivered)
        return NotificationResult(
            delivered=delivered,
            code="ok" if delivered else "ntfy_unavailable",
            attempts=1 if delivered else 3,
        )


def transition(code: FrameHealthCode, duration: float) -> FrameHealthTransition:
    return FrameHealthTransition(
        state=(
            FrameHealthState.HEALTHY
            if code is FrameHealthCode.RECOVERED
            else FrameHealthState.DEGRADED
        ),
        code=code,
        duration_seconds=duration,
    )


def clock(*values: datetime):
    moments = iter(values)
    return lambda: next(moments)


def test_open_survives_restart_without_duplicate_incident_or_notification(
    tmp_path: Path,
) -> None:
    store = VisualHealthStore(tmp_path / "visual-health.sqlite3")
    store.migrate()
    notifier = RecordingNotifier([True])
    first = VisualFrameHealthPipeline.restore(
        store=store,
        notifier=notifier,
        clock=clock(NOW),
    )
    opened = transition(FrameHealthCode.SOURCE_OFFLINE, 60.0)

    first.handle(opened)
    assert first.open_code is FrameHealthCode.SOURCE_OFFLINE
    restored = VisualFrameHealthPipeline.restore(
        store=store,
        notifier=notifier,
        clock=clock(NOW + timedelta(seconds=120)),
    )
    restored.handle(opened)
    assert restored.open_code is FrameHealthCode.SOURCE_OFFLINE

    incidents = store.incidents()
    assert len(incidents) == 1
    assert incidents[0].state == "open"
    assert incidents[0].opened_notified is True
    assert notifier.calls == [("source_offline", "opened")]


def test_failed_open_notification_remains_pending_and_retries_after_restart(
    tmp_path: Path,
) -> None:
    store = VisualHealthStore(tmp_path / "visual-health.sqlite3")
    store.migrate()
    notifier = RecordingNotifier([False, True])
    pipeline = VisualFrameHealthPipeline.restore(
        store=store,
        notifier=notifier,
        clock=clock(NOW),
    )

    pipeline.handle(transition(FrameHealthCode.FRAME_FROZEN, 61.0))
    assert store.load_open().opened_notified is False  # type: ignore[union-attr]

    VisualFrameHealthPipeline.restore(
        store=store,
        notifier=notifier,
        clock=clock(NOW + timedelta(seconds=1)),
    )

    assert store.load_open().opened_notified is True  # type: ignore[union-attr]
    assert notifier.calls == [
        ("frame_frozen", "opened"),
        ("frame_frozen", "opened"),
    ]


def test_recovery_updates_and_notifies_the_existing_incident_once(
    tmp_path: Path,
) -> None:
    store = VisualHealthStore(tmp_path / "visual-health.sqlite3")
    store.migrate()
    notifier = RecordingNotifier([True, True])
    pipeline = VisualFrameHealthPipeline.restore(
        store=store,
        notifier=notifier,
        clock=clock(NOW, NOW + timedelta(seconds=90)),
    )

    pipeline.handle(transition(FrameHealthCode.SOURCE_OFFLINE, 60.0))
    pipeline.handle(transition(FrameHealthCode.RECOVERED, 20.0))
    assert pipeline.open_code is None
    pipeline.handle(transition(FrameHealthCode.RECOVERED, 30.0))

    incidents = store.incidents()
    assert len(incidents) == 1
    assert incidents[0].state == "recovered"
    assert incidents[0].recovered_at == NOW + timedelta(seconds=90)
    assert incidents[0].recovered_notified is True
    assert notifier.calls == [
        ("source_offline", "opened"),
        ("source_offline", "recovered"),
    ]


def test_internal_reconnect_transition_is_never_persisted(tmp_path: Path) -> None:
    store = VisualHealthStore(tmp_path / "visual-health.sqlite3")
    store.migrate()
    pipeline = VisualFrameHealthPipeline.restore(
        store=store,
        clock=clock(),
    )

    pipeline.handle(transition(FrameHealthCode.RECONNECT_REQUIRED, 60.0))

    assert store.incidents() == ()


def test_pipeline_rejects_decreasing_wall_clock_before_state_mutation(
    tmp_path: Path,
) -> None:
    store = VisualHealthStore(tmp_path / "visual-health.sqlite3")
    store.migrate()
    pipeline = VisualFrameHealthPipeline.restore(
        store=store,
        clock=clock(NOW, NOW - timedelta(seconds=1)),
    )
    pipeline.handle(transition(FrameHealthCode.SOURCE_OFFLINE, 60.0))

    with pytest.raises(ValueError, match="cannot decrease"):
        pipeline.handle(transition(FrameHealthCode.RECOVERED, 20.0))

    assert store.load_open() is not None
