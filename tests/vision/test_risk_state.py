from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from packages.contracts.vision import (
    AdultPresence,
    BedState,
    FaceVisibility,
    ImageQuality,
    ModelRisk,
    Posture,
    RiskResolutionCause,
    RiskTransitionKind,
    VisualReview,
    VisualRiskKind,
    VisualRiskState,
)
from services.vision.risk_state import VisualRiskStateMachine


NOW = datetime(2026, 8, 5, 12, 0, tzinfo=timezone.utc)


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
        "confidence": 0.9,
    }
    payload.update(overrides)
    return VisualReview.model_validate(payload)


def face_hidden(*, confidence: float = 0.82) -> VisualReview:
    return review(
        face_visibility="not_visible",
        risk="high",
        reason_codes=["face_not_visible"],
        confidence=confidence,
    )


def prone(*, confidence: float = 0.82) -> VisualReview:
    return review(
        posture="prone_candidate",
        risk="high",
        reason_codes=["prone_candidate"],
        confidence=confidence,
    )


def outside(*, confidence: float = 0.82) -> VisualReview:
    return review(
        baby_visibility="not_visible",
        face_visibility="not_visible",
        bed_state="outside_candidate",
        risk="watch",
        reason_codes=["outside_candidate"],
        confidence=confidence,
    )


def kinds(transitions: tuple[object, ...]) -> list[RiskTransitionKind]:
    return [item.transition_kind for item in transitions]  # type: ignore[attr-defined]


def test_face_candidate_requires_two_valid_reviews_spanning_ten_seconds() -> None:
    machine = VisualRiskStateMachine()

    first = machine.evaluate(face_hidden(confidence=0.82), NOW)
    second = machine.evaluate(face_hidden(confidence=0.85), NOW + timedelta(seconds=10))

    assert kinds(first) == [RiskTransitionKind.WATCH_STARTED]
    assert kinds(second) == [RiskTransitionKind.ALERT_OPENED]
    assert second[0].risk_kind is VisualRiskKind.FACE_NOT_VISIBLE
    assert second[0].notify is True


@pytest.mark.parametrize(
    ("candidate", "risk_kind"),
    [
        (prone, VisualRiskKind.PRONE_CANDIDATE),
        (outside, VisualRiskKind.OUTSIDE_CANDIDATE),
    ],
)
def test_each_non_face_candidate_has_an_independent_confirmation_track(
    candidate: object,
    risk_kind: VisualRiskKind,
) -> None:
    machine = VisualRiskStateMachine()

    machine.evaluate(candidate(), NOW)  # type: ignore[operator]
    transitions = machine.evaluate(  # type: ignore[operator]
        candidate(), NOW + timedelta(seconds=10)
    )

    assert len(transitions) == 1
    assert transitions[0].transition_kind is RiskTransitionKind.ALERT_OPENED
    assert transitions[0].risk_kind is risk_kind


def test_two_candidates_less_than_ten_seconds_apart_do_not_open_alert() -> None:
    machine = VisualRiskStateMachine()

    machine.evaluate(face_hidden(), NOW)
    too_soon = machine.evaluate(face_hidden(), NOW + timedelta(seconds=9))
    on_time = machine.evaluate(face_hidden(), NOW + timedelta(seconds=10))

    assert too_soon == ()
    assert kinds(on_time) == [RiskTransitionKind.ALERT_OPENED]


def test_low_confidence_candidates_remain_watch_without_accumulating() -> None:
    machine = VisualRiskStateMachine()

    first = machine.evaluate(face_hidden(confidence=0.69), NOW)
    second = machine.evaluate(
        face_hidden(confidence=0.69), NOW + timedelta(seconds=30)
    )

    assert first == ()
    assert second == ()
    assert machine.state_for(VisualRiskKind.FACE_NOT_VISIBLE) is VisualRiskState.NORMAL


def test_alert_requires_two_explicit_safe_reviews_to_recover() -> None:
    machine = VisualRiskStateMachine()
    machine.evaluate(face_hidden(), NOW)
    machine.evaluate(face_hidden(), NOW + timedelta(seconds=10))

    first_safe = machine.evaluate(review(), NOW + timedelta(seconds=20))
    recovered = machine.evaluate(review(), NOW + timedelta(seconds=30))

    assert first_safe == ()
    assert kinds(recovered) == [RiskTransitionKind.RECOVERED]
    assert recovered[0].previous_state is VisualRiskState.ALERT
    assert recovered[0].current_state is VisualRiskState.NORMAL
    assert recovered[0].notify is True
    assert recovered[0].resolution_cause is RiskResolutionCause.EXPLICIT_SAFE


def test_repeated_candidate_does_not_duplicate_an_open_alert() -> None:
    machine = VisualRiskStateMachine()
    machine.evaluate(face_hidden(), NOW)
    machine.evaluate(face_hidden(), NOW + timedelta(seconds=10))

    repeated = machine.evaluate(face_hidden(), NOW + timedelta(seconds=20))

    assert repeated == ()


def test_adult_intervention_is_recorded_once_without_recovering_alert() -> None:
    machine = VisualRiskStateMachine()
    machine.evaluate(face_hidden(), NOW)
    machine.evaluate(face_hidden(), NOW + timedelta(seconds=10))
    intervention = review(
        face_visibility="not_visible",
        adult_presence="present",
        risk="high",
        reason_codes=["face_not_visible", "adult_intervention"],
        confidence=0.9,
    )

    first = machine.evaluate(intervention, NOW + timedelta(seconds=20))
    repeated = machine.evaluate(intervention, NOW + timedelta(seconds=30))
    explicit_safe_but_adult_present = machine.evaluate(
        review(adult_presence="present"), NOW + timedelta(seconds=40)
    )

    assert kinds(first) == [RiskTransitionKind.ADULT_INTERVENTION]
    assert first[0].risk_kind is None
    assert first[0].notify is False
    assert repeated == ()
    assert explicit_safe_but_adult_present == ()
    assert machine.state_for(VisualRiskKind.FACE_NOT_VISIBLE) is VisualRiskState.ALERT


def test_no_baby_combination_keeps_prone_and_outside_independent_from_face() -> None:
    machine = VisualRiskStateMachine()
    combined = review(
        baby_visibility="not_visible",
        face_visibility="not_visible",
        posture="prone_candidate",
        bed_state="outside_candidate",
        risk="high",
        reason_codes=[
            "face_not_visible",
            "prone_candidate",
            "outside_candidate",
        ],
        confidence=0.9,
    )

    first = machine.evaluate(combined, NOW)
    second = machine.evaluate(combined, NOW + timedelta(seconds=10))

    assert {item.risk_kind for item in first} == {
        VisualRiskKind.PRONE_CANDIDATE,
        VisualRiskKind.OUTSIDE_CANDIDATE,
    }
    assert {item.transition_kind for item in first} == {
        RiskTransitionKind.WATCH_STARTED
    }
    assert {item.risk_kind for item in second} == {
        VisualRiskKind.PRONE_CANDIDATE,
        VisualRiskKind.OUTSIDE_CANDIDATE,
    }
    assert {item.transition_kind for item in second} == {
        RiskTransitionKind.ALERT_OPENED
    }
    assert machine.state_for(VisualRiskKind.FACE_NOT_VISIBLE) is VisualRiskState.NORMAL


def test_empty_bed_opens_only_the_outside_track() -> None:
    machine = VisualRiskStateMachine()
    absent = outside()

    first = machine.evaluate(absent, NOW)
    second = machine.evaluate(absent, NOW + timedelta(seconds=10))

    assert [(item.transition_kind, item.risk_kind) for item in first] == [
        (RiskTransitionKind.WATCH_STARTED, VisualRiskKind.OUTSIDE_CANDIDATE)
    ]
    assert [(item.transition_kind, item.risk_kind) for item in second] == [
        (RiskTransitionKind.ALERT_OPENED, VisualRiskKind.OUTSIDE_CANDIDATE)
    ]
    assert machine.state_for(VisualRiskKind.FACE_NOT_VISIBLE) is VisualRiskState.NORMAL


def test_adult_only_outside_emits_one_intervention_and_no_face_output() -> None:
    machine = VisualRiskStateMachine()
    adult_only = outside().model_copy(update={"adult_presence": AdultPresence.PRESENT})

    first = machine.evaluate(adult_only, NOW)
    second = machine.evaluate(adult_only, NOW + timedelta(seconds=10))

    assert [(item.transition_kind, item.risk_kind) for item in first] == [
        (RiskTransitionKind.ADULT_INTERVENTION, None),
        (RiskTransitionKind.WATCH_STARTED, VisualRiskKind.OUTSIDE_CANDIDATE),
    ]
    assert [(item.transition_kind, item.risk_kind) for item in second] == [
        (RiskTransitionKind.ALERT_OPENED, VisualRiskKind.OUTSIDE_CANDIDATE)
    ]
    assert machine.state_for(VisualRiskKind.FACE_NOT_VISIBLE) is VisualRiskState.NORMAL


def test_uncertain_subject_does_not_create_face_or_outside_recovery_evidence() -> None:
    machine = VisualRiskStateMachine()
    uncertain = review(
        baby_visibility="uncertain",
        face_visibility="not_visible",
        bed_state="uncertain",
        risk="high",
    )

    assert machine.evaluate(uncertain, NOW) == ()
    assert machine.evaluate(uncertain, NOW + timedelta(seconds=10)) == ()
    assert machine.state_for(VisualRiskKind.FACE_NOT_VISIBLE) is VisualRiskState.NORMAL


def test_confirmed_subject_outside_recovers_face_without_notification() -> None:
    machine = VisualRiskStateMachine()
    machine.evaluate(face_hidden(), NOW)
    machine.evaluate(face_hidden(), NOW + timedelta(seconds=10))

    first = machine.evaluate(outside(), NOW + timedelta(seconds=20))
    second = machine.evaluate(outside(), NOW + timedelta(seconds=30))

    assert [(item.transition_kind, item.risk_kind) for item in first] == [
        (RiskTransitionKind.WATCH_STARTED, VisualRiskKind.OUTSIDE_CANDIDATE)
    ]
    assert [(item.transition_kind, item.risk_kind) for item in second] == [
        (RiskTransitionKind.RECOVERED, VisualRiskKind.FACE_NOT_VISIBLE),
        (RiskTransitionKind.ALERT_OPENED, VisualRiskKind.OUTSIDE_CANDIDATE),
    ]
    recovered = second[0]
    assert recovered.resolution_cause is RiskResolutionCause.SUBJECT_OUTSIDE
    assert recovered.notify is False


@pytest.mark.parametrize(
    ("first_safe", "second_safe", "expected_cause", "expected_notify"),
    [
        (review(), outside(), RiskResolutionCause.SUBJECT_OUTSIDE, False),
        (outside(), review(), RiskResolutionCause.EXPLICIT_SAFE, True),
    ],
)
def test_face_recovery_requires_two_reviews_with_the_same_resolution_cause(
    first_safe: VisualReview,
    second_safe: VisualReview,
    expected_cause: RiskResolutionCause,
    expected_notify: bool,
) -> None:
    machine = VisualRiskStateMachine()
    machine.evaluate(face_hidden(), NOW)
    machine.evaluate(face_hidden(), NOW + timedelta(seconds=10))

    first = machine.evaluate(first_safe, NOW + timedelta(seconds=20))
    assert all(
        item.risk_kind is not VisualRiskKind.FACE_NOT_VISIBLE
        for item in first
    )
    mixed = machine.evaluate(second_safe, NOW + timedelta(seconds=30))

    assert all(
        item.transition_kind is not RiskTransitionKind.RECOVERED
        for item in mixed
    )
    assert machine.state_for(VisualRiskKind.FACE_NOT_VISIBLE) is VisualRiskState.ALERT

    recovered = machine.evaluate(second_safe, NOW + timedelta(seconds=40))
    face_recovery = next(
        item
        for item in recovered
        if item.transition_kind is RiskTransitionKind.RECOVERED
    )
    assert face_recovery.resolution_cause is expected_cause
    assert face_recovery.notify is expected_notify


def test_confirmed_subject_outside_clears_face_watch_without_notification() -> None:
    machine = VisualRiskStateMachine()
    machine.evaluate(face_hidden(), NOW)

    machine.evaluate(outside(), NOW + timedelta(seconds=5))
    transitions = machine.evaluate(outside(), NOW + timedelta(seconds=15))

    face_clear = next(
        item
        for item in transitions
        if item.risk_kind is VisualRiskKind.FACE_NOT_VISIBLE
    )
    assert face_clear.transition_kind is RiskTransitionKind.WATCH_CLEARED
    assert face_clear.resolution_cause is RiskResolutionCause.SUBJECT_OUTSIDE
    assert face_clear.notify is False


def test_uncertain_review_resets_subject_outside_recovery_confirmation() -> None:
    machine = VisualRiskStateMachine()
    machine.evaluate(face_hidden(), NOW)
    machine.evaluate(face_hidden(), NOW + timedelta(seconds=10))
    machine.evaluate(outside(), NOW + timedelta(seconds=20))
    machine.evaluate(
        review(
            baby_visibility="uncertain",
            face_visibility="uncertain",
            bed_state="uncertain",
            risk="uncertain",
        ),
        NOW + timedelta(seconds=25),
    )

    not_yet = machine.evaluate(outside(), NOW + timedelta(seconds=30))
    recovered = machine.evaluate(outside(), NOW + timedelta(seconds=40))

    assert all(
        item.transition_kind is not RiskTransitionKind.RECOVERED
        for item in not_yet
    )
    assert next(
        item
        for item in recovered
        if item.transition_kind is RiskTransitionKind.RECOVERED
    ).resolution_cause is RiskResolutionCause.SUBJECT_OUTSIDE


def test_uncertain_or_poor_image_is_not_safe_recovery_evidence() -> None:
    machine = VisualRiskStateMachine()
    machine.evaluate(face_hidden(), NOW)
    machine.evaluate(face_hidden(), NOW + timedelta(seconds=10))

    uncertain = machine.evaluate(
        review(
            face_visibility="uncertain",
            image_quality="blurred",
            risk="uncertain",
            reason_codes=["poor_image"],
            confidence=0.2,
        ),
        NOW + timedelta(seconds=20),
    )

    assert uncertain == ()
    assert machine.state_for(VisualRiskKind.FACE_NOT_VISIBLE) is VisualRiskState.ALERT


def test_uncertain_adult_presence_is_not_safe_recovery_evidence() -> None:
    machine = VisualRiskStateMachine()
    machine.evaluate(face_hidden(), NOW)
    machine.evaluate(face_hidden(), NOW + timedelta(seconds=10))

    uncertain_adult = machine.evaluate(
        review(adult_presence="uncertain"), NOW + timedelta(seconds=20)
    )
    first_explicitly_safe = machine.evaluate(
        review(adult_presence="absent"), NOW + timedelta(seconds=30)
    )

    assert uncertain_adult == ()
    assert first_explicitly_safe == ()
    assert machine.state_for(VisualRiskKind.FACE_NOT_VISIBLE) is VisualRiskState.ALERT


def test_watch_clears_only_after_two_safe_reviews_spanning_ten_seconds() -> None:
    machine = VisualRiskStateMachine()
    machine.evaluate(face_hidden(), NOW)

    first_safe = machine.evaluate(review(), NOW + timedelta(seconds=5))
    cleared = machine.evaluate(review(), NOW + timedelta(seconds=15))

    assert first_safe == ()
    assert kinds(cleared) == [RiskTransitionKind.WATCH_CLEARED]
    assert cleared[0].notify is False
    assert cleared[0].resolution_cause is RiskResolutionCause.EXPLICIT_SAFE


def test_timestamp_rollback_is_rejected_before_state_changes() -> None:
    machine = VisualRiskStateMachine()
    machine.evaluate(face_hidden(), NOW + timedelta(seconds=10))

    with pytest.raises(ValueError, match="monotonic"):
        machine.evaluate(face_hidden(), NOW)

    assert machine.state_for(VisualRiskKind.FACE_NOT_VISIBLE) is VisualRiskState.WATCH


def test_safe_enums_used_by_recovery_are_explicit() -> None:
    safe = review()

    assert safe.face_visibility is FaceVisibility.CLEAR
    assert safe.posture is Posture.SUPINE
    assert safe.bed_state is BedState.INSIDE
    assert safe.adult_presence is AdultPresence.ABSENT
    assert safe.image_quality is ImageQuality.USABLE
    assert safe.risk is ModelRisk.NONE


def test_restart_preserves_open_alert_but_discards_partial_recovery() -> None:
    machine = VisualRiskStateMachine()
    machine.evaluate(face_hidden(), NOW)
    machine.evaluate(face_hidden(), NOW + timedelta(seconds=10))
    machine.evaluate(review(), NOW + timedelta(seconds=20))

    snapshot = machine.snapshot(NOW + timedelta(seconds=21))
    restored = VisualRiskStateMachine.from_snapshot(snapshot)
    first_safe_after_restart = restored.evaluate(
        review(), NOW + timedelta(seconds=30)
    )
    recovered = restored.evaluate(review(), NOW + timedelta(seconds=40))

    assert snapshot.open_risks == frozenset({VisualRiskKind.FACE_NOT_VISIBLE})
    assert (
        restored.state_for(VisualRiskKind.FACE_NOT_VISIBLE)
        is VisualRiskState.NORMAL
    )
    assert first_safe_after_restart == ()
    assert kinds(recovered) == [RiskTransitionKind.RECOVERED]


def test_restart_discards_watch_and_pending_candidate_evidence() -> None:
    machine = VisualRiskStateMachine()
    machine.evaluate(face_hidden(), NOW)

    snapshot = machine.snapshot(NOW + timedelta(seconds=1))
    restored = VisualRiskStateMachine.from_snapshot(snapshot)
    first_after_restart = restored.evaluate(
        face_hidden(), NOW + timedelta(seconds=10)
    )

    assert snapshot.open_risks == frozenset()
    assert kinds(first_after_restart) == [RiskTransitionKind.WATCH_STARTED]
    assert (
        restored.state_for(VisualRiskKind.FACE_NOT_VISIBLE)
        is VisualRiskState.WATCH
    )


def test_restored_snapshot_time_is_the_new_monotonic_floor() -> None:
    machine = VisualRiskStateMachine()
    snapshot = machine.snapshot(NOW + timedelta(seconds=20))
    restored = VisualRiskStateMachine.from_snapshot(snapshot)

    with pytest.raises(ValueError, match="monotonic"):
        restored.evaluate(review(), NOW + timedelta(seconds=19))
