from __future__ import annotations

from dataclasses import dataclass

from packages.contracts.vision import (
    AdultPresence,
    BabyVisibility,
    BedState,
    FaceVisibility,
    ImageQuality,
    ModelRisk,
    Posture,
    RiskResolutionCause,
    VisualReview,
    VisualRiskKind,
    VisualSemanticConflict,
)


MINIMUM_CONFIDENCE = 0.70


@dataclass(frozen=True)
class RiskEvidence:
    candidate: bool
    safe: bool
    resolution_cause: RiskResolutionCause | None = None


@dataclass(frozen=True)
class CanonicalVisualEvidence:
    face: RiskEvidence
    prone: RiskEvidence
    outside: RiskEvidence
    semantic_conflicts: tuple[VisualSemanticConflict, ...]

    def for_risk(self, risk_kind: VisualRiskKind) -> RiskEvidence:
        return {
            VisualRiskKind.FACE_NOT_VISIBLE: self.face,
            VisualRiskKind.PRONE_CANDIDATE: self.prone,
            VisualRiskKind.OUTSIDE_CANDIDATE: self.outside,
        }[risk_kind]


def canonicalize_visual_review(review: VisualReview) -> CanonicalVisualEvidence:
    subject_attributable = (
        review.baby_visibility in {BabyVisibility.VISIBLE, BabyVisibility.PARTIAL}
        and review.bed_state is BedState.INSIDE
    )
    usable_confident = (
        review.image_quality is ImageQuality.USABLE
        and review.confidence >= MINIMUM_CONFIDENCE
    )
    face_candidate = (
        subject_attributable
        and usable_confident
        and review.face_visibility is FaceVisibility.NOT_VISIBLE
        and review.risk is ModelRisk.HIGH
    )
    face_explicit_safe = (
        subject_attributable
        and usable_confident
        and review.face_visibility is FaceVisibility.CLEAR
        and review.adult_presence is AdultPresence.ABSENT
    )
    subject_outside = (
        usable_confident
        and review.baby_visibility is BabyVisibility.NOT_VISIBLE
        and review.bed_state is BedState.OUTSIDE_CANDIDATE
    )
    conflicts = (
        (VisualSemanticConflict.FACE_WITHOUT_SUBJECT,)
        if review.face_visibility is FaceVisibility.NOT_VISIBLE
        and not subject_attributable
        else ()
    )
    generic_safe = (
        usable_confident and review.adult_presence is AdultPresence.ABSENT
    )

    prone_safe = generic_safe and review.posture in {
        Posture.SUPINE,
        Posture.SIDE,
        Posture.UPRIGHT,
    }
    outside_safe = generic_safe and review.bed_state is BedState.INSIDE
    return CanonicalVisualEvidence(
        face=RiskEvidence(
            candidate=face_candidate,
            safe=face_explicit_safe or subject_outside,
            resolution_cause=(
                RiskResolutionCause.SUBJECT_OUTSIDE
                if subject_outside
                else RiskResolutionCause.EXPLICIT_SAFE
                if face_explicit_safe
                else None
            ),
        ),
        prone=RiskEvidence(
            candidate=(
                review.posture is Posture.PRONE_CANDIDATE
                and review.risk is ModelRisk.HIGH
            ),
            safe=prone_safe,
            resolution_cause=(
                RiskResolutionCause.EXPLICIT_SAFE if prone_safe else None
            ),
        ),
        outside=RiskEvidence(
            candidate=review.bed_state is BedState.OUTSIDE_CANDIDATE,
            safe=outside_safe,
            resolution_cause=(
                RiskResolutionCause.EXPLICIT_SAFE if outside_safe else None
            ),
        ),
        semantic_conflicts=conflicts,
    )
