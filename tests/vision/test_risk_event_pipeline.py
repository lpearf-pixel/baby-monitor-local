from __future__ import annotations

import io
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

from packages.contracts.vision import (
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
        notify=transition_kind
        in {RiskTransitionKind.ALERT_OPENED, RiskTransitionKind.RECOVERED},
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
        "guardian.transition_observed",
        "guardian.event_opened",
        "guardian.transition_observed",
        "guardian.event_recovered",
    ]
    assert decoded_lines(stream)[1]["result"] == "created"
    assert decoded_lines(stream)[3]["result"] == "existing"


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
