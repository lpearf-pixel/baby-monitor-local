from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class StreamContract(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class VideoHealth(StreamContract):
    codec: str = Field(min_length=1)
    width: int = Field(gt=0)
    height: int = Field(gt=0)
    fps: float = Field(ge=0)


class AudioHealth(StreamContract):
    codec: str = Field(min_length=1)
    sample_rate: int | None = Field(default=None, gt=0)
    channels: int | None = Field(default=None, gt=0)


class StreamHealth(StreamContract):
    healthy: bool
    video: VideoHealth | None
    audio: AudioHealth | None = None
    duration_seconds: float | None = Field(default=None, ge=0)
