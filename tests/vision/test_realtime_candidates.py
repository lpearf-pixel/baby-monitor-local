from __future__ import annotations

import pytest

from packages.contracts.vision import (
    RealtimeCandidateKind,
    RealtimeCandidateTransitionKind,
    RealtimeObservation,
    RiskTransitionKind,
    SceneQuality,
    VisualRiskKind,
    VisualRiskState,
)
from services.vision.risk_state import VisualRiskStateMachine


def observation(**changes: object) -> RealtimeObservation:
    payload: dict[str, object] = {
        "motion_ratio": 0.0,
        "scene_quality": "usable",
        "pose_count": 1,
        "face_count": 1,
        "bed_subject_track": "inside",
        "adult_track": "absent",
        "head_face_state": "visible",
        "processing_ms": 10.0,
    }
    payload.update(changes)
    return RealtimeObservation.model_validate(payload)


def candidate_module():
    from services.vision import realtime_candidates

    return realtime_candidates


def warm(machine: object) -> None:
    machine.evaluate(observation(), monotonic_now=0.0)
    machine.evaluate(observation(), monotonic_now=10.0)


def opened(transitions: tuple[object, ...]) -> set[RealtimeCandidateKind]:
    return {
        transition.candidate_kind
        for transition in transitions
        if transition.transition_kind is RealtimeCandidateTransitionKind.WATCH_OPENED
    }


def test_startup_suppresses_semantic_and_motion_candidates() -> None:
    module = candidate_module()
    machine = module.RealtimeCandidateStateMachine()

    assert machine.evaluate(
        observation(
            motion_ratio=0.4,
            face_count=0,
            head_face_state="temporarily_missing",
            bed_subject_track="missing",
        ),
        monotonic_now=0.0,
    ) == ()
    assert machine.evaluate(
        observation(
            motion_ratio=0.4,
            face_count=0,
            head_face_state="temporarily_missing",
            bed_subject_track="missing",
        ),
        monotonic_now=9.9,
    ) == ()


def test_significant_motion_opens_after_point_six_and_clears_after_two_seconds() -> None:
    module = candidate_module()
    machine = module.RealtimeCandidateStateMachine()
    warm(machine)

    machine.evaluate(observation(motion_ratio=0.2), monotonic_now=10.1)
    transition = machine.evaluate(observation(motion_ratio=0.2), monotonic_now=10.7)
    assert opened(transition) == {RealtimeCandidateKind.SIGNIFICANT_BED_MOTION}

    machine.evaluate(observation(), monotonic_now=11.0)
    cleared = machine.evaluate(observation(), monotonic_now=13.0)
    assert cleared[0].transition_kind is RealtimeCandidateTransitionKind.CANDIDATE_CLEARED
    assert cleared[0].candidate_kind is RealtimeCandidateKind.SIGNIFICANT_BED_MOTION


def test_face_obstruction_requires_recent_visible_face_and_usable_tracking() -> None:
    module = candidate_module()
    machine = module.RealtimeCandidateStateMachine()
    warm(machine)
    missing = observation(
        face_count=0,
        head_face_state="temporarily_missing",
    )

    machine.evaluate(missing, monotonic_now=10.1)
    transition = machine.evaluate(missing, monotonic_now=11.6)

    assert RealtimeCandidateKind.POSSIBLE_FACE_OBSTRUCTION in opened(transition)

    no_history = module.RealtimeCandidateStateMachine()
    no_history.evaluate(missing, monotonic_now=0.0)
    no_history.evaluate(missing, monotonic_now=10.0)
    no_history.evaluate(missing, monotonic_now=12.0)
    assert no_history.evaluate(missing, monotonic_now=14.0) == ()


def test_exit_requires_inside_history_motion_and_no_recent_adult() -> None:
    module = candidate_module()
    machine = module.RealtimeCandidateStateMachine()
    warm(machine)
    exiting = observation(
        motion_ratio=0.2,
        pose_count=0,
        face_count=0,
        bed_subject_track="missing",
        head_face_state="uncertain",
    )

    machine.evaluate(exiting, monotonic_now=10.1)
    transition = machine.evaluate(exiting, monotonic_now=11.1)
    assert RealtimeCandidateKind.POSSIBLE_EXIT in opened(transition)

    suppressed = module.RealtimeCandidateStateMachine()
    warm(suppressed)
    adult = observation(
        pose_count=2,
        adult_track="intersecting_bed",
    )
    suppressed.evaluate(adult, monotonic_now=10.1)
    suppressed.evaluate(adult, monotonic_now=10.7)
    suppressed.evaluate(exiting, monotonic_now=11.0)
    assert RealtimeCandidateKind.POSSIBLE_EXIT not in opened(
        suppressed.evaluate(exiting, monotonic_now=12.5)
    )


def test_rollover_proxy_and_adult_intervention_are_watch_only() -> None:
    module = candidate_module()
    machine = module.RealtimeCandidateStateMachine()
    warm(machine)
    changed = observation(
        motion_ratio=0.2,
        face_count=0,
        head_face_state="temporarily_missing",
    )
    adult = observation(pose_count=2, adult_track="intersecting_bed")

    machine.evaluate(changed, monotonic_now=10.1)
    rollover = machine.evaluate(changed, monotonic_now=11.1)
    machine.evaluate(adult, monotonic_now=12.0)
    intervention = machine.evaluate(adult, monotonic_now=12.6)

    assert RealtimeCandidateKind.POSSIBLE_ROLLOVER_OR_PRONE in opened(rollover)
    assert RealtimeCandidateKind.ADULT_INTERVENTION in opened(intervention)
    forbidden = {RiskTransitionKind.ALERT_OPENED.value, RiskTransitionKind.RECOVERED.value}
    assert not ({item.transition_kind.value for item in rollover + intervention} & forbidden)


def test_camera_obstruction_works_during_warmup_and_requires_two_seconds() -> None:
    module = candidate_module()
    machine = module.RealtimeCandidateStateMachine()
    obstructed = observation(
        scene_quality=SceneQuality.FLAT,
        pose_count=None,
        face_count=None,
        bed_subject_track="uncertain",
        adult_track="uncertain",
        head_face_state="uncertain",
    )

    assert machine.evaluate(obstructed, monotonic_now=0.0) == ()
    transition = machine.evaluate(obstructed, monotonic_now=2.0)

    assert opened(transition) == {RealtimeCandidateKind.CAMERA_OBSTRUCTED}


def test_persistent_blur_can_open_camera_obstruction_after_infrared_grace() -> None:
    module = candidate_module()
    machine = module.RealtimeCandidateStateMachine()
    blurred = observation(scene_quality="blurred")

    assert machine.evaluate(blurred, monotonic_now=0.0) == ()
    transition = machine.evaluate(blurred, monotonic_now=2.0)

    assert opened(transition) == {RealtimeCandidateKind.CAMERA_OBSTRUCTED}


def test_uncertain_or_model_unavailable_input_cannot_open_semantic_candidate() -> None:
    module = candidate_module()
    machine = module.RealtimeCandidateStateMachine()
    warm(machine)
    uncertain = observation(
        motion_ratio=0.4,
        scene_quality="uncertain",
        pose_count=None,
        face_count=None,
        bed_subject_track="uncertain",
        adult_track="uncertain",
        head_face_state="uncertain",
    )

    machine.evaluate(uncertain, monotonic_now=10.1)
    assert machine.evaluate(uncertain, monotonic_now=20.0) == ()


def test_time_rollback_is_rejected_and_risk_machine_is_untouched() -> None:
    module = candidate_module()
    machine = module.RealtimeCandidateStateMachine()
    machine.evaluate(observation(), monotonic_now=1.0)

    with pytest.raises(ValueError, match="monotonic"):
        machine.evaluate(observation(), monotonic_now=0.9)

    risk = VisualRiskStateMachine()
    assert all(
        risk.state_for(kind) is VisualRiskState.NORMAL
        for kind in VisualRiskKind
    )
