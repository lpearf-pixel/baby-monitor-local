from __future__ import annotations

from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from packages.contracts.vision import (
    FaceVisibility,
    RiskSnapshot,
    RiskTransition,
    RiskTransitionKind,
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
