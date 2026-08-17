from __future__ import annotations

from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class AudioObservationState(StrEnum):
    QUIET = "quiet"
    SOUND = "sound"
    CRY_CANDIDATE = "cry_candidate"
    UNAVAILABLE = "unavailable"


class AudioFailureReason(StrEnum):
    AUDIO_SOURCE_UNAVAILABLE = "audio_source_unavailable"
    AUDIO_TRACK_UNSUPPORTED = "audio_track_unsupported"
    AUDIO_STALE = "audio_stale"
    DECODER_FAILED = "decoder_failed"
    MODEL_MISSING = "model_missing"
    MODEL_INVALID = "model_invalid"
    MODEL_FAILED = "model_failed"
    INTERNAL_ERROR = "internal_error"


class AudioObservation(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    observed_at: datetime
    state: AudioObservationState
    duration_ms: int = Field(ge=0, le=15_000)
    loudness_dbfs: float | None = Field(default=None, ge=-120, le=0)
    noise_floor_dbfs: float | None = Field(default=None, ge=-120, le=0)
    cry_confidence: float | None = Field(default=None, ge=0, le=1)
    failure_reason: AudioFailureReason | None = None

    @field_validator("observed_at")
    @classmethod
    def require_aware_time(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("observed_at must be timezone-aware")
        return value

    @model_validator(mode="after")
    def require_fields_matching_state(self) -> "AudioObservation":
        if self.state is AudioObservationState.UNAVAILABLE:
            if self.failure_reason is None:
                raise ValueError("unavailable observation requires a failure reason")
            if any(
                value is not None
                for value in (
                    self.loudness_dbfs,
                    self.noise_floor_dbfs,
                    self.cry_confidence,
                )
            ):
                raise ValueError("unavailable observation cannot contain measurements")
            return self

        if self.failure_reason is not None:
            raise ValueError("available observation cannot contain a failure reason")
        if self.loudness_dbfs is None or self.noise_floor_dbfs is None:
            raise ValueError("available observation requires loudness and noise floor")
        if self.state is AudioObservationState.CRY_CANDIDATE:
            if self.cry_confidence is None:
                raise ValueError("cry candidate requires confidence")
        elif self.cry_confidence is not None:
            raise ValueError("non-cry observation cannot contain cry confidence")
        return self
