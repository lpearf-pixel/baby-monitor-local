from __future__ import annotations

import io
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

from packages.contracts.vision import (
    RiskResolutionCause,
    RiskTransition,
    RiskTransitionKind,
    VisualRiskKind,
    VisualRiskState,
)
from services.storage.visual_risk import VisualRiskEventStore
from services.vision.risk_event_pipeline import VisualRiskEventPipeline


NOW = datetime(2026, 8, 11, 12, 0, tzinfo=UTC)


def transition(
    transition_kind: RiskTransitionKind,
    *,
    risk_kind: VisualRiskKind | None = VisualRiskKind.FACE_NOT_VISIBLE,
    observed_at: datetime = NOW,
    notify: bool | None = None,
    resolution_cause: RiskResolutionCause | None = None,
) -> RiskTransition:
    states = {
        RiskTransitionKind.WATCH_STARTED: (
            VisualRiskState.NORMAL,
            VisualRiskState.WATCH,
        ),
        RiskTransitionKind.WATCH_CLEARED: (
            VisualRiskState.WATCH,
            VisualRiskState.NORMAL,
        ),
        RiskTransitionKind.ALERT_OPENED: (
            VisualRiskState.WATCH,
            VisualRiskState.ALERT,
        ),
        RiskTransitionKind.RECOVERED: (
            VisualRiskState.ALERT,
            VisualRiskState.NORMAL,
        ),
        RiskTransitionKind.ADULT_INTERVENTION: (
            VisualRiskState.ALERT,
            VisualRiskState.ALERT,
        ),
    }
    previous, current = states[transition_kind]
    if resolution_cause is None and transition_kind in {
        RiskTransitionKind.WATCH_CLEARED,
        RiskTransitionKind.RECOVERED,
    }:
        resolution_cause = RiskResolutionCause.EXPLICIT_SAFE
    return RiskTransition(
        transition_kind=transition_kind,
        risk_kind=(
            None
            if transition_kind is RiskTransitionKind.ADULT_INTERVENTION
            else risk_kind
        ),
        previous_state=previous,
        current_state=current,
        observed_at=observed_at,
        confidence=0.88,
        notify=(
            transition_kind
            in {RiskTransitionKind.ALERT_OPENED, RiskTransitionKind.RECOVERED}
            if notify is None
            else notify
        ),
        resolution_cause=resolution_cause,
    )


def decoded_lines(stream: io.StringIO) -> list[dict[str, object]]:
    return [json.loads(line) for line in stream.getvalue().splitlines()]


def test_alert_open_and_recovery_share_one_persisted_event_id(
    tmp_path: Path,
) -> None:
    store = VisualRiskEventStore(tmp_path / "events.sqlite3")
    store.migrate()
    stream = io.StringIO()
    pipeline = VisualRiskEventPipeline(
        store=store,
        stream=stream,
        event_id_factory=lambda: "event-face",
    )

    opened = transition(RiskTransitionKind.ALERT_OPENED)
    pipeline.handle(opened)
    pipeline.handle(opened)
    pipeline.handle(
        transition(
            RiskTransitionKind.RECOVERED,
            observed_at=NOW + timedelta(seconds=10),
        )
    )

    events = store.list_events()
    assert len(events) == 1
    assert events[0].event_id == "event-face"
    assert events[0].state == "recovered"
    assert [line["code"] for line in decoded_lines(stream)] == [
        "guardian.transition_observed",
        "guardian.event_opened",
        "guardian.notification_queued",
        "guardian.transition_observed",
        "guardian.event_opened",
        "guardian.transition_observed",
        "guardian.event_recovered",
        "guardian.notification_queued",
    ]
    assert decoded_lines(stream)[1]["result"] == "created"
    assert decoded_lines(stream)[4]["result"] == "existing"
    opened_notification = store.next_pending_notification(NOW)
    assert opened_notification is not None
    assert opened_notification.event_id == "event-face"
    assert opened_notification.stage == "risk_opened"
    store.record_notification_result(
        notification_id=opened_notification.notification_id,
        attempted_at=NOW + timedelta(seconds=11),
        result_code="ok",
    )
    recovered_notification = store.next_pending_notification(
        NOW + timedelta(seconds=11)
    )
    assert recovered_notification is not None
    assert recovered_notification.stage == "risk_recovered"


def test_subject_outside_recovery_persists_without_notification(
    tmp_path: Path,
) -> None:
    store = VisualRiskEventStore(tmp_path / "events.sqlite3")
    store.migrate()
    stream = io.StringIO()
    pipeline = VisualRiskEventPipeline(
        store=store,
        stream=stream,
        event_id_factory=lambda: "event-face",
    )
    pipeline.handle(transition(RiskTransitionKind.ALERT_OPENED))
    opened = store.next_pending_notification(NOW)
    assert opened is not None
    store.record_notification_result(
        notification_id=opened.notification_id,
        attempted_at=NOW + timedelta(seconds=1),
        result_code="ok",
    )

    pipeline.handle(
        transition(
            RiskTransitionKind.RECOVERED,
            observed_at=NOW + timedelta(seconds=10),
            notify=False,
            resolution_cause=RiskResolutionCause.SUBJECT_OUTSIDE,
        )
    )

    events = store.list_events()
    assert len(events) == 1
    assert events[0].event_id == "event-face"
    assert events[0].state == "recovered"
    assert store.next_pending_notification(NOW + timedelta(seconds=10)) is None
    lines = decoded_lines(stream)
    recovered_lines = [
        line
        for line in lines
        if line.get("transition_kind") == RiskTransitionKind.RECOVERED.value
    ]
    assert recovered_lines
    assert {
        line.get("resolution_cause") for line in recovered_lines
    } == {RiskResolutionCause.SUBJECT_OUTSIDE.value}
    assert "Traceback" not in stream.getvalue()
    assert "/" not in "".join(
        str(line.get("event_id", "")) for line in recovered_lines
    )


def test_persist_defensively_respects_non_notifying_recovery(
    tmp_path: Path,
) -> None:
    store = VisualRiskEventStore(tmp_path / "events.sqlite3")
    store.migrate()
    store.open_event(
        event_id="event-face",
        risk_kind=VisualRiskKind.FACE_NOT_VISIBLE,
        opened_at=NOW,
        confidence=0.88,
        rule_version="visual-risk-v1",
    )
    pipeline = VisualRiskEventPipeline(store=store, stream=io.StringIO())

    pipeline._persist(
        transition(
            RiskTransitionKind.RECOVERED,
            observed_at=NOW + timedelta(seconds=10),
            notify=False,
            resolution_cause=RiskResolutionCause.SUBJECT_OUTSIDE,
        )
    )

    assert store.list_events()[0].state == "recovered"
    assert store.next_pending_notification(NOW + timedelta(seconds=10)) is None


def test_watch_transitions_are_logged_without_creating_long_term_events(
    tmp_path: Path,
) -> None:
    store = VisualRiskEventStore(tmp_path / "events.sqlite3")
    store.migrate()
    stream = io.StringIO()
    pipeline = VisualRiskEventPipeline(store=store, stream=stream)

    pipeline.handle(transition(RiskTransitionKind.WATCH_STARTED))
    pipeline.handle(
        transition(
            RiskTransitionKind.WATCH_CLEARED,
            observed_at=NOW + timedelta(seconds=10),
        )
    )

    assert store.list_events() == ()
    assert [line["transition_kind"] for line in decoded_lines(stream)] == [
        "watch_started",
        "watch_cleared",
    ]


def test_recovery_without_open_event_is_ignored_and_does_not_invent_history(
    tmp_path: Path,
) -> None:
    store = VisualRiskEventStore(tmp_path / "events.sqlite3")
    store.migrate()
    stream = io.StringIO()
    pipeline = VisualRiskEventPipeline(store=store, stream=stream)

    pipeline.handle(transition(RiskTransitionKind.RECOVERED))

    assert store.list_events() == ()
    assert decoded_lines(stream)[-1] == {
        "code": "guardian.transition_ignored",
        "component": "baby_guardian",
        "observed_at": NOW.isoformat(),
        "result": "no_open_event",
        "resolution_cause": "explicit_safe",
        "risk_kind": "face_not_visible",
        "rule_version": "visual-risk-v1",
        "schema_version": 1,
        "transition_kind": "recovered",
    }


def test_adult_intervention_is_idempotent_and_retained_without_open_risk(
    tmp_path: Path,
) -> None:
    store = VisualRiskEventStore(tmp_path / "events.sqlite3")
    store.migrate()
    stream = io.StringIO()
    pipeline = VisualRiskEventPipeline(store=store, stream=stream)
    adult = transition(
        RiskTransitionKind.ADULT_INTERVENTION,
        risk_kind=None,
    )

    pipeline.handle(adult)
    pipeline.handle(adult)

    intervention_lines = [
        line
        for line in decoded_lines(stream)
        if line["code"] == "guardian.intervention_recorded"
    ]
    assert len(intervention_lines) == 2
    assert intervention_lines[0]["intervention_id"] == intervention_lines[1][
        "intervention_id"
    ]
    assert intervention_lines[0]["linked_event_count"] == 0
    assert store.next_pending_notification(NOW) is None


def test_linked_adult_intervention_queues_once_per_event(tmp_path: Path) -> None:
    store = VisualRiskEventStore(tmp_path / "events.sqlite3")
    store.migrate()
    pipeline = VisualRiskEventPipeline(
        store=store,
        stream=io.StringIO(),
        event_id_factory=lambda: "event-face",
    )
    pipeline.handle(transition(RiskTransitionKind.ALERT_OPENED))
    opened = store.next_pending_notification(NOW)
    assert opened is not None
    store.record_notification_result(
        notification_id=opened.notification_id,
        attempted_at=NOW,
        result_code="ok",
    )
    adult = transition(
        RiskTransitionKind.ADULT_INTERVENTION,
        risk_kind=None,
        observed_at=NOW + timedelta(seconds=5),
    )

    pipeline.handle(adult)
    pipeline.handle(adult)

    pending = store.next_pending_notification(NOW + timedelta(seconds=5))
    assert pending is not None
    assert pending.event_id == "event-face"
    assert pending.stage == "adult_intervention"
    assert pending.intervention_id is not None
    store.record_notification_result(
        notification_id=pending.notification_id,
        attempted_at=NOW + timedelta(seconds=6),
        result_code="ok",
    )
    assert store.next_pending_notification(NOW + timedelta(seconds=6)) is None


def test_restore_snapshot_contains_only_currently_open_risks(tmp_path: Path) -> None:
    store = VisualRiskEventStore(tmp_path / "events.sqlite3")
    store.migrate()
    store.open_event(
        event_id="event-face",
        risk_kind=VisualRiskKind.FACE_NOT_VISIBLE,
        opened_at=NOW,
        confidence=0.82,
        rule_version="visual-risk-v1",
    )
    store.open_event(
        event_id="event-prone",
        risk_kind=VisualRiskKind.PRONE_CANDIDATE,
        opened_at=NOW,
        confidence=0.84,
        rule_version="visual-risk-v1",
    )
    store.recover_event(
        risk_kind=VisualRiskKind.PRONE_CANDIDATE,
        recovered_at=NOW + timedelta(seconds=10),
        confidence=0.91,
        rule_version="visual-risk-v1",
    )
    pipeline = VisualRiskEventPipeline(store=store, stream=io.StringIO())

    snapshot = pipeline.restore_snapshot(NOW + timedelta(seconds=20))

    assert snapshot.open_risks == frozenset({VisualRiskKind.FACE_NOT_VISIBLE})


class SensitiveFailingStore:
    def load_open(self) -> tuple[object, ...]:
        raise RuntimeError("token at /private/family/events.sqlite3")

    def open_event(self, **_kwargs: object) -> None:
        raise RuntimeError("token at /private/family/events.sqlite3")


class BrokenStream:
    def write(self, _value: str) -> int:
        raise OSError("/private/family/visual.log")

    def flush(self) -> None:
        raise OSError("/private/family/visual.log")


def test_persistence_failure_is_redacted_and_does_not_escape() -> None:
    stream = io.StringIO()
    pipeline = VisualRiskEventPipeline(
        store=SensitiveFailingStore(),
        stream=stream,
        event_id_factory=lambda: "event-face",
    )

    pipeline.handle(transition(RiskTransitionKind.ALERT_OPENED))
    snapshot = pipeline.restore_snapshot(NOW)

    serialized = stream.getvalue()
    assert snapshot.open_risks == frozenset()
    assert "guardian.persistence_failed" in serialized
    assert "guardian.restore_failed" in serialized
    assert "token" not in serialized
    assert "/private" not in serialized


def test_broken_log_stream_never_changes_persistence_result(tmp_path: Path) -> None:
    store = VisualRiskEventStore(tmp_path / "events.sqlite3")
    store.migrate()
    pipeline = VisualRiskEventPipeline(
        store=store,
        stream=BrokenStream(),
        event_id_factory=lambda: "event-face",
    )

    pipeline.handle(transition(RiskTransitionKind.ALERT_OPENED))

    assert store.load_open()[0].event_id == "event-face"


def test_new_event_callback_runs_once_after_persistence(tmp_path: Path) -> None:
    store = VisualRiskEventStore(tmp_path / "events.sqlite3")
    store.migrate()
    received: list[tuple[object, RiskTransition]] = []
    pipeline = VisualRiskEventPipeline(
        store=store,
        stream=io.StringIO(),
        event_id_factory=lambda: "event-face",
        on_event_opened=lambda event, item: received.append((event, item)),
    )
    opened = transition(RiskTransitionKind.ALERT_OPENED)

    pipeline.handle(opened)
    pipeline.handle(opened)

    assert len(received) == 1
    assert received[0][0].event_id == "event-face"
    assert received[0][1] == opened


def test_new_event_initializes_evidence_before_notification_becomes_pending(
    tmp_path: Path,
) -> None:
    store = VisualRiskEventStore(tmp_path / "events.sqlite3")
    store.migrate()
    real_queue = store.queue_notification

    def start_evidence(event: object, _transition: RiskTransition) -> None:
        store.begin_evidence(
            event_id=event.event_id,
            started_at=NOW,
            capture_deadline=NOW + timedelta(seconds=30),
            snapshot_key=None,
            frame_count=0,
        )

    def require_evidence_before_queue(**kwargs: object):
        assert store.get_evidence(str(kwargs["event_id"])) is not None
        return real_queue(**kwargs)

    store.queue_notification = require_evidence_before_queue  # type: ignore[method-assign]
    pipeline = VisualRiskEventPipeline(
        store=store,
        stream=io.StringIO(),
        event_id_factory=lambda: "event-face",
        on_event_opened=start_evidence,
    )

    pipeline.handle(transition(RiskTransitionKind.ALERT_OPENED))

    pending = store.next_pending_notification(NOW)
    assert pending is not None
    assert pending.event_id == "event-face"


def test_new_event_callback_failure_is_redacted_and_does_not_rollback(
    tmp_path: Path,
) -> None:
    store = VisualRiskEventStore(tmp_path / "events.sqlite3")
    store.migrate()
    stream = io.StringIO()

    def fail(_event: object, _transition: RiskTransition) -> None:
        raise RuntimeError("token at /private/family/evidence")

    pipeline = VisualRiskEventPipeline(
        store=store,
        stream=stream,
        event_id_factory=lambda: "event-face",
        on_event_opened=fail,
    )

    pipeline.handle(transition(RiskTransitionKind.ALERT_OPENED))

    assert store.load_open()[0].event_id == "event-face"
    serialized = stream.getvalue()
    assert "guardian.evidence_failed" in serialized
    assert "callback_failed" in serialized
    assert "token" not in serialized
    assert "/private" not in serialized


def test_notification_queue_failure_is_redacted_and_does_not_rollback(
    tmp_path: Path,
) -> None:
    store = VisualRiskEventStore(tmp_path / "events.sqlite3")
    store.migrate()
    stream = io.StringIO()

    def fail(**_kwargs: object) -> None:
        raise RuntimeError("token at /private/family/outbox")

    store.queue_notification = fail  # type: ignore[method-assign]
    pipeline = VisualRiskEventPipeline(
        store=store,
        stream=stream,
        event_id_factory=lambda: "event-face",
    )

    pipeline.handle(transition(RiskTransitionKind.ALERT_OPENED))

    assert store.load_open()[0].event_id == "event-face"
    serialized = stream.getvalue()
    assert "guardian.notification_queue_failed" in serialized
    assert "queue_failed" in serialized
    assert "token" not in serialized
    assert "/private" not in serialized
