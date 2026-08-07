"""Validated cross-service contracts."""

from packages.contracts.vision import (
    AdultTrack,
    BedSubjectTrack,
    HeadFaceState,
    NormalizedPoint,
    NormalizedPolygon,
    RealtimeCandidateKind,
    RealtimeCandidateTransition,
    RealtimeCandidateTransitionKind,
    RealtimeObservation,
    RiskSnapshot,
    RiskTransition,
    RiskTransitionKind,
    SceneQuality,
    VisualReview,
    VisualRiskKind,
    VisualRiskState,
)

__all__ = [
    "AdultTrack",
    "BedSubjectTrack",
    "HeadFaceState",
    "NormalizedPoint",
    "NormalizedPolygon",
    "RealtimeCandidateKind",
    "RealtimeCandidateTransition",
    "RealtimeCandidateTransitionKind",
    "RealtimeObservation",
    "RiskSnapshot",
    "RiskTransition",
    "RiskTransitionKind",
    "SceneQuality",
    "VisualReview",
    "VisualRiskKind",
    "VisualRiskState",
]
