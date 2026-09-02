from __future__ import annotations

import io
import sqlite3
from collections.abc import Iterable
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from packages.contracts.vision import (
    RiskResolutionCause,
    VisualReview,
    VisualRiskKind,
    VisualSemanticConflict,
)
from services.events.guardian_query import GuardianEventQueryService
from services.storage.visual_risk import VisualRiskEventStore
from services.vision.risk_evidence import canonicalize_visual_review
from services.vision.risk_event_pipeline import VisualRiskEventPipeline
from services.vision.risk_state import VisualRiskStateMachine


NOW = datetime(2026, 9, 2, 12, 0, tzinfo=UTC)


def review(**overrides: object) -> VisualReview:
    payload: dict[str, object] = {
        "baby_visibility": "visible",
        "face_visibility": "clear",
        "posture": "supine",
        "bed_state": "inside",
        "adult_presence": "absent",
        "image_quality": "usable",
        "risk": "none",
        "reason_codes": [],
        "confidence": 0.90,
    }
    payload.update(overrides)
    return VisualReview.model_validate(payload)


def face_hidden() -> VisualReview:
    return review(
        face_visibility="not_visible",
        risk="high",
        reason_codes=["face_not_visible"],
    )


def outside(*, adult: bool = False, risk: str = "watch") -> VisualReview:
    return review(
        baby_visibility="not_visible",
        face_visibility="not_visible",
        bed_state="outside_candidate",
        adult_presence="present" if adult else "absent",
        risk=risk,
        reason_codes=(
            ["face_not_visible", "outside_candidate", "adult_intervention"]
            if adult
            else ["face_not_visible", "outside_candidate"]
        ),
    )


def run_reviews(
    database: Path,
    samples: Iterable[tuple[int, VisualReview]],
) -> tuple[
    VisualRiskEventStore,
    tuple[object, ...],
    frozenset[VisualSemanticConflict],
    str,
]:
    store = VisualRiskEventStore(database)
    store.migrate()
    stream = io.StringIO()
    next_id = iter(range(1, 20))
    pipeline = VisualRiskEventPipeline(
        store=store,
        stream=stream,
        event_id_factory=lambda: f"event-{next(next_id)}",
    )
    machine = VisualRiskStateMachine()
    transitions: list[object] = []
    conflicts: set[VisualSemanticConflict] = set()
    for seconds, item in samples:
        conflicts.update(canonicalize_visual_review(item).semantic_conflicts)
        current = machine.evaluate(item, NOW + timedelta(seconds=seconds))
        transitions.extend(current)
        for transition in current:
            pipeline.handle(transition)
    return store, tuple(transitions), frozenset(conflicts), stream.getvalue()


def stored_counts(database: Path) -> tuple[int, tuple[str, ...]]:
    with sqlite3.connect(database) as connection:
        intervention_count = connection.execute(
            "SELECT count(*) FROM visual_interventions"
        ).fetchone()[0]
        stages = tuple(
            row[0]
            for row in connection.execute(
                "SELECT stage FROM visual_risk_notifications ORDER BY queued_at, stage"
            ).fetchall()
        )
    return int(intervention_count), stages


def assert_projection_is_media_free(database: Path) -> tuple[object, ...]:
    result = GuardianEventQueryService(database).recent_events()
    payload = result.model_dump_json()
    for forbidden in ("evidence_key", "snapshot", "clip", "path", "media"):
        assert forbidden not in payload
    return result.events


def test_safe_baby_creates_no_event_or_notification(tmp_path: Path) -> None:
    database = tmp_path / "events.sqlite3"
    store, transitions, conflicts, _log = run_reviews(database, [(0, review())])

    assert transitions == ()
    assert conflicts == frozenset()
    assert store.list_events() == ()
    assert stored_counts(database) == (0, ())
    assert assert_projection_is_media_free(database) == ()


def test_face_occlusion_and_explicit_clear_share_one_recovered_event(
    tmp_path: Path,
) -> None:
    database = tmp_path / "events.sqlite3"
    store, transitions, conflicts, _log = run_reviews(
        database,
        [(0, face_hidden()), (10, face_hidden()), (20, review()), (30, review())],
    )

    assert conflicts == frozenset()
    assert [(item.transition_kind.value, item.risk_kind.value) for item in transitions] == [
        ("watch_started", "face_not_visible"),
        ("alert_opened", "face_not_visible"),
        ("recovered", "face_not_visible"),
    ]
    recovered = transitions[-1]
    assert recovered.resolution_cause is RiskResolutionCause.EXPLICIT_SAFE
    assert recovered.notify is True
    assert [(item.risk_kind.value, item.state) for item in store.list_events()] == [
        ("face_not_visible", "recovered")
    ]
    assert stored_counts(database) == (
        0,
        ("risk_opened", "risk_recovered"),
    )
    projected = assert_projection_is_media_free(database)
    assert [(item.risk_kind, item.state) for item in projected] == [
        (VisualRiskKind.FACE_NOT_VISIBLE, "recovered")
    ]


@pytest.mark.parametrize("adult", [False, True])
def test_empty_or_adult_only_bed_creates_outside_but_zero_face_output(
    tmp_path: Path,
    adult: bool,
) -> None:
    database = tmp_path / "events.sqlite3"
    store, transitions, conflicts, _log = run_reviews(
        database,
        [(0, outside(adult=adult)), (10, outside(adult=adult))],
    )

    risk_kinds = [item.risk_kind for item in transitions if item.risk_kind is not None]
    assert VisualRiskKind.FACE_NOT_VISIBLE not in risk_kinds
    assert conflicts == frozenset({VisualSemanticConflict.FACE_WITHOUT_SUBJECT})
    assert [(item.risk_kind.value, item.state) for item in store.list_events()] == [
        ("outside_candidate", "open")
    ]
    intervention_count, stages = stored_counts(database)
    assert intervention_count == int(adult)
    assert stages == ("risk_opened",)
    projected = assert_projection_is_media_free(database)
    assert [(item.risk_kind, item.state) for item in projected] == [
        (VisualRiskKind.OUTSIDE_CANDIDATE, "open")
    ]


def test_legacy_conflict_is_unique_and_preserves_outside_event(tmp_path: Path) -> None:
    database = tmp_path / "events.sqlite3"
    store, transitions, conflicts, _log = run_reviews(
        database,
        [(0, outside(risk="high")), (10, outside(risk="high"))],
    )

    assert conflicts == frozenset({VisualSemanticConflict.FACE_WITHOUT_SUBJECT})
    assert all(
        item.risk_kind is not VisualRiskKind.FACE_NOT_VISIBLE for item in transitions
    )
    assert [(item.risk_kind.value, item.state) for item in store.list_events()] == [
        ("outside_candidate", "open")
    ]
    assert stored_counts(database) == (0, ("risk_opened",))
    assert len(assert_projection_is_media_free(database)) == 1


def test_face_then_outside_recovers_without_face_recovery_notification(
    tmp_path: Path,
) -> None:
    database = tmp_path / "events.sqlite3"
    store, transitions, conflicts, log = run_reviews(
        database,
        [
            (0, face_hidden()),
            (10, face_hidden()),
            (20, outside()),
            (30, outside()),
        ],
    )

    face_recovery = next(
        item
        for item in transitions
        if item.transition_kind.value == "recovered"
        and item.risk_kind is VisualRiskKind.FACE_NOT_VISIBLE
    )
    assert face_recovery.resolution_cause is RiskResolutionCause.SUBJECT_OUTSIDE
    assert face_recovery.notify is False
    assert conflicts == frozenset({VisualSemanticConflict.FACE_WITHOUT_SUBJECT})
    assert {(item.risk_kind.value, item.state) for item in store.list_events()} == {
        ("face_not_visible", "recovered"),
        ("outside_candidate", "open"),
    }
    assert stored_counts(database) == (
        0,
        ("risk_opened", "risk_opened"),
    )
    assert '"resolution_cause":"subject_outside"' in log
    projected = assert_projection_is_media_free(database)
    assert {(item.risk_kind, item.state) for item in projected} == {
        (VisualRiskKind.FACE_NOT_VISIBLE, "recovered"),
        (VisualRiskKind.OUTSIDE_CANDIDATE, "open"),
    }
