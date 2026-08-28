from __future__ import annotations

from enum import StrEnum
from typing import Literal
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from packages.contracts.vision import NormalizedPolygon


class VisualCorpusContract(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class CorpusReadiness(StrEnum):
    DESIGN_ONLY = "DESIGN_ONLY"
    PARTIAL = "PARTIAL"
    READY = "READY"


class SourceType(StrEnum):
    REAL = "REAL"
    PUBLIC_DATASET = "PUBLIC_DATASET"
    SYNTHETIC = "SYNTHETIC"


class DownloadMethod(StrEnum):
    DIRECT_HTTPS = "DIRECT_HTTPS"
    MANUAL = "MANUAL"
    APPLICATION_ONLY = "APPLICATION_ONLY"
    NOT_AVAILABLE = "NOT_AVAILABLE"


class CommercialUse(StrEnum):
    ALLOWED = "ALLOWED"
    PROHIBITED = "PROHIBITED"
    UNKNOWN = "UNKNOWN"


class Framing(StrEnum):
    CLOSE_UP = "close_up"
    MEDIUM = "medium"
    CRIB_WIDE = "crib_wide"
    ROOM_WIDE = "room_wide"


class SubjectScale(StrEnum):
    TINY = "tiny"
    SMALL = "small"
    MEDIUM = "medium"
    LARGE = "large"
    UNKNOWN = "unknown"


class CameraAngle(StrEnum):
    OVERHEAD = "overhead"
    HIGH_OBLIQUE = "high_oblique"
    EYE_LEVEL = "eye_level"
    UNKNOWN = "unknown"


class EnvironmentKind(StrEnum):
    CRIB = "crib"
    BED = "bed"
    PLAYMAT = "playmat"
    ROOM = "room"
    OTHER = "other"


class Lighting(StrEnum):
    DAY = "day"
    LOW_LIGHT = "low_light"
    NATIVE_IR = "native_ir"
    SIMULATED_IR = "simulated_ir"


class BabyVisibilityLabel(StrEnum):
    FULL = "full"
    PARTIAL = "partial"
    FACE_OCCLUDED = "face_occluded"
    MOSTLY_NOT_VISIBLE = "mostly_not_visible"
    NOT_VISIBLE = "not_visible"
    UNKNOWN = "unknown"


class MotionLabel(StrEnum):
    STILL = "still"
    MILD = "mild"
    ACTIVE = "active"
    ADULT_ENTERING = "adult_entering"
    UNKNOWN = "unknown"


class AdultVisibilityLabel(StrEnum):
    ABSENT = "absent"
    PARTIAL = "partial"
    PRESENT = "present"
    UNKNOWN = "unknown"


class ObjectState(StrEnum):
    EMPTY = "empty"
    BLANKET = "blanket"
    TOY = "toy"
    MIXED = "mixed"
    UNKNOWN = "unknown"


class WideContentRole(StrEnum):
    NONE = "none"
    INFANT_SMALL = "infant_small"
    EMPTY_OR_OBJECT_ONLY = "empty_or_object_only"
    ADULT_PRESENT_OR_ENTERING = "adult_present_or_entering"


class LabelProvenance(StrEnum):
    SOURCE_METADATA = "source_metadata"
    FRAME_REVIEW = "frame_review"
    DETERMINISTIC_RECIPE = "deterministic_recipe"


class ReviewState(StrEnum):
    UNREVIEWED = "unreviewed"
    REVIEWED = "reviewed"


class RecipeKind(StrEnum):
    SOURCE_SEGMENT = "SOURCE_SEGMENT"
    SIMULATED_IR = "SIMULATED_IR"
    LOW_CONTRAST = "LOW_CONTRAST"
    BOUNDED_OCCLUSION = "BOUNDED_OCCLUSION"
    SYNTHETIC_SCALE = "SYNTHETIC_SCALE"
    LOOP_TO_MINIMUM = "LOOP_TO_MINIMUM"


class ScenarioId(StrEnum):
    DAY_01 = "DAY-01"
    DAY_02 = "DAY-02"
    DAY_03 = "DAY-03"
    WIDE_01 = "WIDE-01"
    WIDE_02 = "WIDE-02"
    WIDE_03 = "WIDE-03"
    NIGHT_01 = "NIGHT-01"
    NIGHT_02 = "NIGHT-02"
    NIGHT_03 = "NIGHT-03"
    OCC_01 = "OCC-01"
    OCC_02 = "OCC-02"
    OCC_03 = "OCC-03"
    NEG_01 = "NEG-01"
    NEG_02 = "NEG-02"
    NEG_03 = "NEG-03"


class ReplayStatus(StrEnum):
    PASS = "PASS"
    FAIL = "FAIL"
    SKIP = "SKIP"


class ComparisonStatus(StrEnum):
    PASS = "PASS"
    REGRESSION = "REGRESSION"
    INCOMPARABLE = "INCOMPARABLE"
    FAILED = "FAILED"


class VisualCorpusSource(VisualCorpusContract):
    source_id: str = Field(pattern=r"^[a-z0-9][a-z0-9-]{2,63}$")
    name: str = Field(min_length=1, max_length=160)
    source_url: str = Field(min_length=1, max_length=2048)
    project_or_paper: str = Field(min_length=1, max_length=240)
    license: str = Field(min_length=1, max_length=120)
    download_method: DownloadMethod
    research_use_allowed: bool
    commercial_use: CommercialUse
    redistribution_allowed: bool
    github_allowed: bool
    privacy_notes: str = Field(min_length=1, max_length=500)
    local_only: bool
    expected_sha256: str | None = Field(
        default=None,
        pattern=r"^[0-9a-f]{64}$",
    )
    expected_bytes: int | None = Field(default=None, ge=1, le=128 * 1024 * 1024)
    source_page_sha1: str | None = Field(
        default=None,
        pattern=r"^[0-9a-f]{40}$",
    )

    @field_validator("source_url")
    @classmethod
    def require_https_url(cls, value: str) -> str:
        parsed = urlsplit(value)
        if (
            parsed.scheme != "https"
            or not parsed.hostname
            or parsed.username is not None
            or parsed.password is not None
            or parsed.fragment
        ):
            raise ValueError("source_url must be a public HTTPS URL")
        return value

    @model_validator(mode="after")
    def require_safe_distribution_claim(self) -> "VisualCorpusSource":
        if self.github_allowed and not self.redistribution_allowed:
            raise ValueError("github_allowed requires redistribution_allowed")
        if self.download_method is DownloadMethod.DIRECT_HTTPS and (
            self.expected_sha256 is None or self.expected_bytes is None
        ):
            raise ValueError("direct download requires size and checksum")
        return self


class NormalizationProfile(VisualCorpusContract):
    profile_id: Literal[
        "xiaomi_source_hd",
        "xiaomi_live",
        "analysis_realtime",
        "analysis_slow",
    ]
    width: int = Field(ge=1, le=4096)
    height: int = Field(ge=1, le=2160)
    fps: Literal[1, 5, 10]
    codec: Literal["hevc", "h264", "mjpeg"]


class ObjectiveLabels(VisualCorpusContract):
    framing: Framing
    subject_scale: SubjectScale
    subject_frame_area_ratio: float | None = Field(
        default=None,
        ge=0,
        le=1,
        allow_inf_nan=False,
    )
    camera_angle: CameraAngle
    environment: EnvironmentKind
    lighting: Lighting
    baby_visibility: BabyVisibilityLabel
    motion: MotionLabel
    adult_visibility: AdultVisibilityLabel
    object_state: ObjectState
    wide_content_role: WideContentRole = WideContentRole.NONE


class TemporalLabelSpan(VisualCorpusContract):
    start_ms: int = Field(ge=0)
    end_ms: int = Field(gt=0)
    labels: ObjectiveLabels

    @model_validator(mode="after")
    def require_positive_span(self) -> "TemporalLabelSpan":
        if self.end_ms <= self.start_ms:
            raise ValueError("temporal label span must be positive")
        return self


class PreparationRecipe(VisualCorpusContract):
    kind: RecipeKind


class VisualCorpusClip(VisualCorpusContract):
    clip_id: str = Field(pattern=r"^[A-Z]+-[0-9]{2}(?:-[A-Z0-9-]+)?$")
    source_id: str = Field(pattern=r"^[a-z0-9][a-z0-9-]{2,63}$")
    source_type: SourceType
    scenario_ids: tuple[ScenarioId, ...] = Field(min_length=1, max_length=5)
    start_ms: int = Field(ge=0)
    end_ms: int = Field(gt=0)
    parent_clip_id: str | None = Field(
        default=None,
        pattern=r"^[A-Z]+-[0-9]{2}(?:-[A-Z0-9-]+)?$",
    )
    recipe: PreparationRecipe
    labels: ObjectiveLabels
    temporal_labels: tuple[TemporalLabelSpan, ...] = Field(default=(), max_length=64)
    label_provenance: LabelProvenance
    label_confidence: float = Field(ge=0, le=1, allow_inf_nan=False)
    review_state: ReviewState
    analysis_region: NormalizedPolygon | None = None
    privacy_masks: tuple[NormalizedPolygon, ...] = Field(default=(), max_length=8)

    @model_validator(mode="after")
    def require_coherent_clip(self) -> "VisualCorpusClip":
        duration = self.end_ms - self.start_ms
        if not 10_000 <= duration <= 60_000:
            raise ValueError("clip duration must be between 10 and 60 seconds")
        if len(set(self.scenario_ids)) != len(self.scenario_ids):
            raise ValueError("scenario_ids must be unique")
        derived = self.recipe.kind is not RecipeKind.SOURCE_SEGMENT
        if derived and (self.source_type is not SourceType.SYNTHETIC or self.parent_clip_id is None):
            raise ValueError("derived clip requires synthetic source_type and parent_clip_id")
        if not derived and self.parent_clip_id is not None:
            raise ValueError("parent_clip_id is only valid for derived clips")
        for span in self.temporal_labels:
            if span.end_ms > duration:
                raise ValueError("temporal label span exceeds clip duration")
        return self


class VisualCorpusManifest(VisualCorpusContract):
    schema_version: Literal[1] = 1
    corpus_id: str = Field(pattern=r"^[a-z0-9][a-z0-9-]{2,79}$")
    readiness: CorpusReadiness
    sources: tuple[VisualCorpusSource, ...] = Field(default=(), max_length=32)
    profiles: tuple[NormalizationProfile, ...] = Field(min_length=1, max_length=4)
    clips: tuple[VisualCorpusClip, ...] = Field(default=(), max_length=20)

    @model_validator(mode="after")
    def require_unique_references(self) -> "VisualCorpusManifest":
        source_ids = [item.source_id for item in self.sources]
        if len(set(source_ids)) != len(source_ids):
            raise ValueError("source_id values must be unique")
        profile_ids = [item.profile_id for item in self.profiles]
        if len(set(profile_ids)) != len(profile_ids):
            raise ValueError("profile_id values must be unique")
        clip_ids = [item.clip_id for item in self.clips]
        if len(set(clip_ids)) != len(clip_ids):
            raise ValueError("clip_id values must be unique")
        source_id_set = set(source_ids)
        clip_id_set = set(clip_ids)
        for item in self.clips:
            if item.source_id not in source_id_set:
                raise ValueError("clip source_id is not declared")
            if item.parent_clip_id is not None and (
                item.parent_clip_id not in clip_id_set
                or item.parent_clip_id == item.clip_id
            ):
                raise ValueError("parent_clip_id is not a valid clip")
        return self


class ReplayResult(VisualCorpusContract):
    schema_version: Literal[1] = 1
    clip_id: str
    status: ReplayStatus
    reason: str = Field(pattern=r"^[a-z0-9_]+$")
    frames_total: int = Field(ge=0)
    frames_processed: int = Field(ge=0)
    frames_skipped: int = Field(ge=0)
    decode_errors: int = Field(ge=0)
    worker_errors: int = Field(ge=0)
    model_state: Literal["available", "degraded", "disabled", "unavailable"]
    observation_counts: dict[str, int] = Field(default_factory=dict)
    candidate_counts: dict[str, int] = Field(default_factory=dict)
    processing_p50_ms: float = Field(ge=0, allow_inf_nan=False)
    processing_p95_ms: float = Field(ge=0, allow_inf_nan=False)
    processing_max_ms: float = Field(ge=0, allow_inf_nan=False)
    pipeline_p50_ms: float = Field(ge=0, allow_inf_nan=False)
    pipeline_p95_ms: float = Field(ge=0, allow_inf_nan=False)
    pipeline_max_ms: float = Field(ge=0, allow_inf_nan=False)
    dropped_frames: int = Field(ge=0)
    queue_backlog_max: int = Field(ge=0)
    frame_observations_persisted: Literal[False] = False

    @field_validator("observation_counts", "candidate_counts")
    @classmethod
    def require_bounded_nonnegative_counts(cls, value: dict[str, int]) -> dict[str, int]:
        if len(value) > 128 or any(count < 0 for count in value.values()):
            raise ValueError("aggregate counts are invalid")
        return value

    @model_validator(mode="after")
    def require_frame_accounting(self) -> "ReplayResult":
        if self.frames_processed + self.frames_skipped != self.frames_total:
            raise ValueError("processed and skipped frames must equal total")
        return self


class ReplayResultSet(VisualCorpusContract):
    schema_version: Literal[1] = 1
    manifest_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    recipe_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    profile: str = Field(min_length=1, max_length=80)
    git_sha: str = Field(pattern=r"^[0-9a-f]{40}$")
    model_artifacts: tuple[str, ...] = Field(default=(), max_length=16)
    results: tuple[ReplayResult, ...] = Field(min_length=1, max_length=20)


class BaselineComparison(VisualCorpusContract):
    schema_version: Literal[1] = 1
    status: ComparisonStatus
    reason: str = Field(pattern=r"^[a-z0-9_]+$")
    compared_clips: int = Field(ge=0, le=20)
    regression_count: int = Field(ge=0)
    group_deltas: dict[str, float] = Field(default_factory=dict)
