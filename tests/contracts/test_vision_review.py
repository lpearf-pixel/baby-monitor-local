from __future__ import annotations

from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from packages.contracts.vision import (
    AdultTrack,
    BedSubjectTrack,
    FaceVisibility,
    HeadFaceState,
    RealtimeCandidateKind,
    RealtimeCandidateTransition,
    RealtimeCandidateTransitionKind,
    RealtimeObservation,
    RiskResolutionCause,
    RiskSnapshot,
    RiskTransition,
    RiskTransitionKind,
    SceneQuality,
    VisualReview,
    VisualRiskKind,
    VisualRiskState,
)


NOW = datetime(2026, 8, 5, 12, 0, tzinfo=timezone.utc)


def valid_review_payload() -> dict[str, object]:
    return {
        "schema_version": 1,
        "baby_visibility": "visible",
        "face_visibility": "not_visible",
        "posture": "supine",
        "bed_state": "inside",
        "adult_presence": "absent",
        "image_quality": "usable",
        "risk": "high",
        "reason_codes": ["face_not_visible"],
        "confidence": 0.82,
    }


def test_valid_visual_review_parses_into_typed_immutable_contract() -> None:
    review = VisualReview.model_validate(valid_review_payload())

    assert review.face_visibility is FaceVisibility.NOT_VISIBLE
    with pytest.raises(ValidationError, match="frozen"):
        review.confidence = 0.5


def test_visual_review_rejects_unknown_model_fields() -> None:
    payload = valid_review_payload()
    payload["free_text"] = "probably unsafe"

    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        VisualReview.model_validate(payload)


@pytest.mark.parametrize(
    "reason_codes",
    [
        ["face_not_visible", "face_not_visible"],
        [
            "face_not_visible",
            "prone_candidate",
            "outside_candidate",
            "adult_intervention",
            "poor_image",
            "face_not_visible",
        ],
    ],
)
def test_visual_review_rejects_duplicate_or_oversized_reason_codes(
    reason_codes: list[str],
) -> None:
    payload = valid_review_payload()
    payload["reason_codes"] = reason_codes

    with pytest.raises(ValidationError):
        VisualReview.model_validate(payload)


@pytest.mark.parametrize("confidence", [-0.01, 1.01])
def test_visual_review_rejects_confidence_outside_probability_range(
    confidence: float,
) -> None:
    payload = valid_review_payload()
    payload["confidence"] = confidence

    with pytest.raises(ValidationError):
        VisualReview.model_validate(payload)


def test_transition_rejects_naive_observation_time() -> None:
    with pytest.raises(ValidationError, match="timezone-aware"):
        RiskTransition(
            transition_kind=RiskTransitionKind.ALERT_OPENED,
            risk_kind=VisualRiskKind.FACE_NOT_VISIBLE,
            previous_state=VisualRiskState.WATCH,
            current_state=VisualRiskState.ALERT,
            observed_at=datetime(2026, 8, 5, 12, 0),
            confidence=0.82,
            notify=True,
        )


@pytest.mark.parametrize(
    ("transition_kind", "risk_kind", "notify", "resolution_cause"),
    [
        (
            RiskTransitionKind.WATCH_CLEARED,
            VisualRiskKind.PRONE_CANDIDATE,
            False,
            RiskResolutionCause.EXPLICIT_SAFE,
        ),
        (
            RiskTransitionKind.RECOVERED,
            VisualRiskKind.FACE_NOT_VISIBLE,
            True,
            RiskResolutionCause.EXPLICIT_SAFE,
        ),
        (
            RiskTransitionKind.RECOVERED,
            VisualRiskKind.FACE_NOT_VISIBLE,
            False,
            RiskResolutionCause.SUBJECT_OUTSIDE,
        ),
    ],
)
def test_resolution_transition_accepts_only_closed_valid_causes(
    transition_kind: RiskTransitionKind,
    risk_kind: VisualRiskKind,
    notify: bool,
    resolution_cause: RiskResolutionCause,
) -> None:
    transition = RiskTransition(
        transition_kind=transition_kind,
        risk_kind=risk_kind,
        previous_state=VisualRiskState.WATCH,
        current_state=VisualRiskState.NORMAL,
        observed_at=NOW,
        confidence=0.82,
        notify=notify,
        resolution_cause=resolution_cause,
    )

    assert transition.resolution_cause is resolution_cause


@pytest.mark.parametrize(
    "overrides",
    [
        {
            "transition_kind": RiskTransitionKind.ALERT_OPENED,
            "risk_kind": VisualRiskKind.FACE_NOT_VISIBLE,
            "previous_state": VisualRiskState.WATCH,
            "current_state": VisualRiskState.ALERT,
            "notify": True,
            "resolution_cause": RiskResolutionCause.EXPLICIT_SAFE,
        },
        {
            "transition_kind": RiskTransitionKind.RECOVERED,
            "risk_kind": VisualRiskKind.FACE_NOT_VISIBLE,
            "previous_state": VisualRiskState.ALERT,
            "current_state": VisualRiskState.NORMAL,
            "notify": True,
            "resolution_cause": None,
        },
        {
            "transition_kind": RiskTransitionKind.RECOVERED,
            "risk_kind": VisualRiskKind.OUTSIDE_CANDIDATE,
            "previous_state": VisualRiskState.ALERT,
            "current_state": VisualRiskState.NORMAL,
            "notify": False,
            "resolution_cause": RiskResolutionCause.SUBJECT_OUTSIDE,
        },
        {
            "transition_kind": RiskTransitionKind.RECOVERED,
            "risk_kind": VisualRiskKind.FACE_NOT_VISIBLE,
            "previous_state": VisualRiskState.ALERT,
            "current_state": VisualRiskState.NORMAL,
            "notify": True,
            "resolution_cause": RiskResolutionCause.SUBJECT_OUTSIDE,
        },
        {
            "transition_kind": RiskTransitionKind.ADULT_INTERVENTION,
            "risk_kind": None,
            "previous_state": VisualRiskState.NORMAL,
            "current_state": VisualRiskState.NORMAL,
            "notify": False,
            "resolution_cause": RiskResolutionCause.EXPLICIT_SAFE,
        },
    ],
)
def test_transition_rejects_invalid_resolution_cause_combinations(
    overrides: dict[str, object],
) -> None:
    with pytest.raises(ValidationError):
        RiskTransition(
            observed_at=NOW,
            confidence=0.82,
            **overrides,
        )


def test_snapshot_rejects_naive_snapshot_time() -> None:
    with pytest.raises(ValidationError, match="timezone-aware"):
        RiskSnapshot(
            snapshot_at=datetime(2026, 8, 5, 12, 0),
            open_risks=frozenset({VisualRiskKind.FACE_NOT_VISIBLE}),
        )


def test_snapshot_round_trips_only_typed_open_risks() -> None:
    snapshot = RiskSnapshot(
        snapshot_at=NOW,
        open_risks=frozenset(
            {VisualRiskKind.FACE_NOT_VISIBLE, VisualRiskKind.PRONE_CANDIDATE}
        ),
    )

    restored = RiskSnapshot.model_validate_json(snapshot.model_dump_json())

    assert restored == snapshot


def valid_realtime_observation_payload() -> dict[str, object]:
    return {
        "motion_ratio": 0.2,
        "scene_quality": "usable",
        "pose_count": 1,
        "face_count": 1,
        "bed_subject_track": "inside",
        "adult_track": "absent",
        "head_face_state": "visible",
        "processing_ms": 12.5,
    }


def test_realtime_observation_is_strict_bounded_and_model_optional() -> None:
    observation = RealtimeObservation.model_validate(
        valid_realtime_observation_payload()
    )

    assert observation.scene_quality is SceneQuality.USABLE
    assert observation.bed_subject_track is BedSubjectTrack.INSIDE
    assert observation.adult_track is AdultTrack.ABSENT
    assert observation.head_face_state is HeadFaceState.VISIBLE

    unavailable = valid_realtime_observation_payload()
    unavailable["pose_count"] = None
    unavailable["face_count"] = None
    assert RealtimeObservation.model_validate(unavailable).pose_count is None


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("motion_ratio", -0.01),
        ("motion_ratio", 1.01),
        ("pose_count", -1),
        ("face_count", -1),
        ("processing_ms", -0.01),
        ("processing_ms", float("nan")),
        ("processing_ms", float("inf")),
        ("scene_quality", "occluded"),
    ],
)
def test_realtime_observation_rejects_invalid_values(
    field: str,
    value: object,
) -> None:
    payload = valid_realtime_observation_payload()
    payload[field] = value

    with pytest.raises(ValidationError):
        RealtimeObservation.model_validate(payload)


def test_realtime_observation_rejects_extra_model_output() -> None:
    payload = valid_realtime_observation_payload()
    payload["keypoints"] = [[0.2, 0.3]]

    with pytest.raises(ValidationError, match="Extra inputs are not permitted"):
        RealtimeObservation.model_validate(payload)


def test_realtime_transition_cannot_represent_alert_or_recovery() -> None:
    transition = RealtimeCandidateTransition(
        transition_kind=RealtimeCandidateTransitionKind.WATCH_OPENED,
        candidate_kind=RealtimeCandidateKind.POSSIBLE_FACE_OBSTRUCTION,
        monotonic_at=12.5,
    )

    assert transition.rule_version == "realtime-visual-v1"
    assert {kind.value for kind in RealtimeCandidateTransitionKind} == {
        "watch_opened",
        "candidate_cleared",
    }
    assert "alert_opened" not in {kind.value for kind in RealtimeCandidateTransitionKind}
    assert "recovered" not in {kind.value for kind in RealtimeCandidateTransitionKind}

    with pytest.raises(ValidationError):
        RealtimeCandidateTransition.model_validate(
            {
                "transition_kind": "alert_opened",
                "candidate_kind": "possible_face_obstruction",
                "monotonic_at": 12.5,
            }
        )
