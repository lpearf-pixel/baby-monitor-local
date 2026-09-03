from __future__ import annotations

import io
import os
import sqlite3
from collections import Counter
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path

from packages.contracts.offline_application_rehearsal import (
    ApplicationScenarioResultV1,
    RehearsalScenarioV1,
    RehearsalSuiteV1,
)
from packages.contracts.vision import VisualRiskKind
from services.events.guardian_query import GuardianEventQueryService
from services.offline_application_sinks import RecordingNotificationStore
from services.storage.visual_risk import VisualRiskEventStore
from services.vision.risk_evidence import canonicalize_visual_review
from services.vision.risk_event_pipeline import VisualRiskEventPipeline
from services.vision.risk_state import VisualRiskStateMachine


EPOCH = datetime(2026, 9, 2, tzinfo=UTC)


def _prepare_root(path: Path) -> Path:
    root = Path(path)
    root.mkdir(mode=0o700, parents=True, exist_ok=False)
    os.chmod(root, 0o700)
    return root


def _guardian_counts(
    transitions: tuple[object, ...],
    conflicts: set[object],
    store: VisualRiskEventStore,
    notifications: RecordingNotificationStore,
    database: Path,
) -> dict[str, int]:
    counts: Counter[str] = Counter()
    for transition in transitions:
        risk = transition.risk_kind.value if transition.risk_kind is not None else "none"
        counts[f"transition.{transition.transition_kind.value}.{risk}"] += 1
        if transition.resolution_cause is not None:
            counts[f"resolution.{transition.resolution_cause.value}"] += 1
    for conflict in conflicts:
        counts[f"semantic_conflict.{conflict.value}"] += 1
    events = store.list_events()
    for event in events:
        counts[f"event.{event.risk_kind.value}.{event.state}"] += 1
    projected = GuardianEventQueryService(database).recent_events().events
    counts["dashboard.event"] = len(projected)
    counts["dashboard.open"] = sum(item.state == "open" for item in projected)
    for notification in notifications.queued:
        counts[f"notification.{notification.stage}"] += 1
    if not notifications.queued:
        counts["notification.total"] = 0
    with sqlite3.connect(database) as connection:
        counts["intervention.total"] = int(connection.execute(
            "SELECT count(*) FROM visual_interventions"
        ).fetchone()[0])
    face_transitions = sum(
        transition.risk_kind is VisualRiskKind.FACE_NOT_VISIBLE
        for transition in transitions
    )
    face_events = sum(event.risk_kind is VisualRiskKind.FACE_NOT_VISIBLE for event in events)
    face_notifications = sum(
        any(event.event_id == item.event_id and event.risk_kind is VisualRiskKind.FACE_NOT_VISIBLE for event in events)
        for item in notifications.queued
    )
    counts["face.output"] = face_transitions + face_events + face_notifications
    return dict(counts)


def run_application_oracle_scenario(
    scenario: RehearsalScenarioV1,
    scenario_root: Path,
    *,
    event_id_factory: Callable[[], str],
    notification_id_factory: Callable[[], str],
) -> ApplicationScenarioResultV1:
    if scenario.lane not in {"application_oracle", "joined_application"}:
        raise ValueError("application_oracle_lane_invalid")
    root = _prepare_root(scenario_root)
    database = root / "guardian.sqlite3"
    actual = VisualRiskEventStore(database)
    actual.migrate()
    recording = RecordingNotificationStore(actual, id_factory=notification_id_factory)
    pipeline = VisualRiskEventPipeline(
        store=recording,
        stream=io.StringIO(),
        event_id_factory=event_id_factory,
    )
    machine = VisualRiskStateMachine()
    transitions: list[object] = []
    conflicts: set[object] = set()
    for step in scenario.steps:
        if step.visual_review is None:
            continue
        conflicts.update(canonicalize_visual_review(step.visual_review).semantic_conflicts)
        current = machine.evaluate(
            step.visual_review,
            EPOCH + timedelta(milliseconds=step.offset_ms),
        )
        transitions.extend(current)
        for transition in current:
            pipeline.handle(transition)
    counts = _guardian_counts(tuple(transitions), conflicts, actual, recording, database)
    selected = {key: counts.get(key, 0) for key in scenario.expected_counts}
    events = actual.list_events()
    passed = selected == scenario.expected_counts
    return ApplicationScenarioResultV1(
        scenario_id=scenario.scenario_id,
        lane=scenario.lane,
        status="PASS" if passed else "FAIL",
        reason="ok" if passed else "application_oracle_mismatch",
        counts=selected,
        event_ids=tuple(event.event_id for event in events),
    )


class OfflineApplicationRehearsalRunner:
    def __init__(self, root: Path) -> None:
        self._root = Path(root)

    def run_functional_pack(
        self, suite: RehearsalSuiteV1
    ) -> tuple[ApplicationScenarioResultV1, ...]:
        event_number = iter(range(1, 10_000))
        notification_number = iter(range(1, 10_000))
        return tuple(
            run_application_oracle_scenario(
                scenario,
                self._root / scenario.scenario_id,
                event_id_factory=lambda: f"event-{next(event_number):08d}",
                notification_id_factory=lambda: f"notification-{next(notification_number):08d}",
            )
            for scenario in suite.scenarios
            if scenario.lane == "application_oracle"
        )


__all__ = ["OfflineApplicationRehearsalRunner", "run_application_oracle_scenario"]
