from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class VisionContract(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


def _require_aware(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("datetime must be timezone-aware")
    return value


class BabyVisibility(StrEnum):
    VISIBLE = "visible"
    PARTIAL = "partial"
    NOT_VISIBLE = "not_visible"
    UNCERTAIN = "uncertain"


class FaceVisibility(StrEnum):
    CLEAR = "clear"
    PARTIAL = "partial"
    NOT_VISIBLE = "not_visible"
    UNCERTAIN = "uncertain"


class Posture(StrEnum):
    SUPINE = "supine"
    SIDE = "side"
    PRONE_CANDIDATE = "prone_candidate"
    UPRIGHT = "upright"
    UNCERTAIN = "uncertain"


class BedState(StrEnum):
    INSIDE = "inside"
    OUTSIDE_CANDIDATE = "outside_candidate"
    UNCERTAIN = "uncertain"


class AdultPresence(StrEnum):
    PRESENT = "present"
    ABSENT = "absent"
    UNCERTAIN = "uncertain"


class ImageQuality(StrEnum):
    USABLE = "usable"
    DARK = "dark"
    BLURRED = "blurred"
    OCCLUDED = "occluded"
    UNCERTAIN = "uncertain"


class ModelRisk(StrEnum):
    NONE = "none"
    WATCH = "watch"
    HIGH = "high"
    UNCERTAIN = "uncertain"


class VisualReasonCode(StrEnum):
    FACE_NOT_VISIBLE = "face_not_visible"
    PRONE_CANDIDATE = "prone_candidate"
    OUTSIDE_CANDIDATE = "outside_candidate"
    ADULT_INTERVENTION = "adult_intervention"
    POOR_IMAGE = "poor_image"


class SceneQuality(StrEnum):
    USABLE = "usable"
    DARK = "dark"
    FLAT = "flat"
    BLURRED = "blurred"
    UNCERTAIN = "uncertain"


class BedSubjectTrack(StrEnum):
    INSIDE = "inside"
    BOUNDARY = "boundary"
    MISSING = "missing"
    UNCERTAIN = "uncertain"


class AdultTrack(StrEnum):
    ABSENT = "absent"
    INTERSECTING_BED = "intersecting_bed"
    UNCERTAIN = "uncertain"


class HeadFaceState(StrEnum):
    VISIBLE = "visible"
    TEMPORARILY_MISSING = "temporarily_missing"
    UNCERTAIN = "uncertain"


class RealtimeCandidateKind(StrEnum):
    SIGNIFICANT_BED_MOTION = "significant_bed_motion"
    POSSIBLE_ROLLOVER_OR_PRONE = "possible_rollover_or_prone"
    POSSIBLE_FACE_OBSTRUCTION = "possible_face_obstruction"
    POSSIBLE_EXIT = "possible_exit"
    ADULT_INTERVENTION = "adult_intervention"
    CAMERA_OBSTRUCTED = "camera_obstructed"


class RealtimeCandidateTransitionKind(StrEnum):
    WATCH_OPENED = "watch_opened"
    CANDIDATE_CLEARED = "candidate_cleared"


class NormalizedPoint(VisionContract):
    x: float = Field(ge=0, le=1)
    y: float = Field(ge=0, le=1)


class NormalizedPolygon(VisionContract):
    points: tuple[NormalizedPoint, ...] = Field(min_length=3)

    @model_validator(mode="after")
    def require_distinct_non_zero_area(self) -> "NormalizedPolygon":
        if len(set(self.points)) < 3:
            raise ValueError("polygon requires at least three distinct points")
        double_area = sum(
            first.x * second.y - second.x * first.y
            for first, second in zip(
                self.points,
                (*self.points[1:], self.points[0]),
                strict=True,
            )
        )
        if abs(double_area) <= 1e-9:
            raise ValueError("polygon requires non-zero area")
        return self


class VisualRiskKind(StrEnum):
    FACE_NOT_VISIBLE = "face_not_visible"
    PRONE_CANDIDATE = "prone_candidate"
    OUTSIDE_CANDIDATE = "outside_candidate"


class VisualRiskState(StrEnum):
    NORMAL = "normal"
    WATCH = "watch"
    ALERT = "alert"


class RiskTransitionKind(StrEnum):
    WATCH_STARTED = "watch_started"
    WATCH_CLEARED = "watch_cleared"
    ALERT_OPENED = "alert_opened"
    RECOVERED = "recovered"
    ADULT_INTERVENTION = "adult_intervention"


class VisualReview(VisionContract):
    schema_version: Literal[1] = 1
    baby_visibility: BabyVisibility
    face_visibility: FaceVisibility
    posture: Posture
    bed_state: BedState
    adult_presence: AdultPresence
    image_quality: ImageQuality
    risk: ModelRisk
    reason_codes: tuple[VisualReasonCode, ...] = Field(max_length=5)
    confidence: float = Field(ge=0, le=1)

    @field_validator("reason_codes")
    @classmethod
    def require_unique_reason_codes(
        cls, value: tuple[VisualReasonCode, ...]
    ) -> tuple[VisualReasonCode, ...]:
        if len(set(value)) != len(value):
            raise ValueError("reason_codes must be unique")
        return value


class RiskTransition(VisionContract):
    transition_kind: RiskTransitionKind
    risk_kind: VisualRiskKind | None
    previous_state: VisualRiskState
    current_state: VisualRiskState
    observed_at: datetime
    confidence: float | None = Field(default=None, ge=0, le=1)
    rule_version: Literal["visual-risk-v1"] = "visual-risk-v1"
    notify: bool

    _aware_observed_at = field_validator("observed_at")(_require_aware)


class RiskSnapshot(VisionContract):
    schema_version: Literal[1] = 1
    snapshot_at: datetime
    open_risks: frozenset[VisualRiskKind] = frozenset()

    _aware_snapshot_at = field_validator("snapshot_at")(_require_aware)


class RealtimeObservation(VisionContract):
    motion_ratio: float = Field(ge=0, le=1, allow_inf_nan=False)
    scene_quality: SceneQuality
    pose_count: int | None = Field(default=None, ge=0)
    face_count: int | None = Field(default=None, ge=0)
    bed_subject_track: BedSubjectTrack
    adult_track: AdultTrack
    head_face_state: HeadFaceState
    processing_ms: float = Field(ge=0, allow_inf_nan=False)


class RealtimeCandidateTransition(VisionContract):
    transition_kind: RealtimeCandidateTransitionKind
    candidate_kind: RealtimeCandidateKind
    monotonic_at: float = Field(ge=0, allow_inf_nan=False)
    rule_version: Literal["realtime-visual-v1"] = "realtime-visual-v1"
