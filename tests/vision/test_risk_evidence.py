from __future__ import annotations

from packages.contracts.vision import (
    BabyVisibility,
    BedState,
    RiskResolutionCause,
    VisualReview,
    VisualRiskKind,
    VisualSemanticConflict,
)
from services.vision.risk_evidence import canonicalize_visual_review


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


def test_baby_present_face_occlusion_is_the_only_face_candidate() -> None:
    source = review(face_visibility="not_visible", risk="high")

    evidence = canonicalize_visual_review(source)

    assert evidence.face.candidate is True
    assert evidence.face.safe is False
    assert evidence.outside.candidate is False
    assert evidence.semantic_conflicts == ()
    assert source.baby_visibility is BabyVisibility.VISIBLE
    assert source.bed_state is BedState.INSIDE


def test_no_baby_outside_removes_face_candidate_but_keeps_outside() -> None:
    source = review(
        baby_visibility="not_visible",
        face_visibility="not_visible",
        bed_state="outside_candidate",
        risk="high",
    )

    evidence = canonicalize_visual_review(source)

    assert (evidence.face.candidate, evidence.face.safe) == (False, True)
    assert evidence.face.resolution_cause is RiskResolutionCause.SUBJECT_OUTSIDE
    assert evidence.outside.candidate is True
    assert evidence.semantic_conflicts == (
        VisualSemanticConflict.FACE_WITHOUT_SUBJECT,
    )


def test_adult_does_not_block_subject_outside_or_independent_outside() -> None:
    evidence = canonicalize_visual_review(
        review(
            baby_visibility="not_visible",
            face_visibility="not_visible",
            bed_state="outside_candidate",
            adult_presence="present",
            risk="high",
        )
    )

    assert (evidence.face.candidate, evidence.face.safe) == (False, True)
    assert evidence.face.resolution_cause is RiskResolutionCause.SUBJECT_OUTSIDE
    assert evidence.outside.candidate is True
    assert evidence.semantic_conflicts == (
        VisualSemanticConflict.FACE_WITHOUT_SUBJECT,
    )


def test_uncertain_subject_cannot_create_or_resolve_face_evidence() -> None:
    evidence = canonicalize_visual_review(
        review(
            baby_visibility="uncertain",
            face_visibility="not_visible",
            bed_state="uncertain",
            risk="high",
        )
    )

    assert (evidence.face.candidate, evidence.face.safe) == (False, False)
    assert evidence.face.resolution_cause is None
    assert evidence.outside.candidate is False
    assert evidence.semantic_conflicts == (
        VisualSemanticConflict.FACE_WITHOUT_SUBJECT,
    )


def test_explicit_face_clear_is_safe_only_for_attributable_baby() -> None:
    evidence = canonicalize_visual_review(review())

    assert (evidence.face.candidate, evidence.face.safe) == (False, True)
    assert evidence.face.resolution_cause is RiskResolutionCause.EXPLICIT_SAFE
    assert evidence.outside.candidate is False
    assert evidence.outside.safe is True
    assert evidence.semantic_conflicts == ()


def test_low_confidence_blocks_new_face_candidate_without_changing_outside() -> None:
    evidence = canonicalize_visual_review(
        review(face_visibility="not_visible", risk="high", confidence=0.69)
    )

    assert (evidence.face.candidate, evidence.face.safe) == (False, False)
    assert evidence.outside.candidate is False
    assert evidence.semantic_conflicts == ()


def test_unusable_or_low_confidence_outside_cannot_resolve_face() -> None:
    for overrides in (
        {"image_quality": "dark"},
        {"confidence": 0.69},
    ):
        evidence = canonicalize_visual_review(
            review(
                baby_visibility="not_visible",
                face_visibility="not_visible",
                bed_state="outside_candidate",
                risk="high",
                **overrides,
            )
        )

        assert (evidence.face.candidate, evidence.face.safe) == (False, False)
        assert evidence.face.resolution_cause is None
        assert evidence.outside.candidate is True
        assert evidence.semantic_conflicts == (
            VisualSemanticConflict.FACE_WITHOUT_SUBJECT,
        )


def test_for_risk_maps_every_closed_track() -> None:
    evidence = canonicalize_visual_review(review())

    assert evidence.for_risk(VisualRiskKind.FACE_NOT_VISIBLE) is evidence.face
    assert evidence.for_risk(VisualRiskKind.PRONE_CANDIDATE) is evidence.prone
    assert evidence.for_risk(VisualRiskKind.OUTSIDE_CANDIDATE) is evidence.outside
