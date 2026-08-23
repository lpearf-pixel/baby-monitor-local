"""Fail-closed local speaker verification for one explicitly claimed profile."""

from __future__ import annotations

import math
import re
from collections.abc import Callable
from dataclasses import dataclass
from typing import Literal, TypeAlias
from uuid import UUID

import numpy as np


SAMPLE_RATE_HZ = 16_000
SAMPLE_WIDTH_BYTES = 2
EMBEDDING_DIMENSIONS = 192
MIN_PCM_SECONDS = 0.8
MAX_PCM_SECONDS = 8.0
MIN_SIGNAL_DBFS = -45.0
MIN_SNR_DB = 8.0
MAX_OVERLAP_PROBABILITY = 0.10
_MODEL_VERSION = re.compile(r"^[A-Za-z0-9._-]{1,64}$")

SpeakerState: TypeAlias = Literal[
    "verified", "uncertain", "mismatch", "not_enrolled"
]
EmbeddingRunner: TypeAlias = Callable[[np.ndarray], "EmbeddingObservation"]


@dataclass(frozen=True)
class EmbeddingObservation:
    embedding: tuple[float, ...]
    speech_seconds: float
    snr_db: float
    overlap_probability: float


@dataclass(frozen=True)
class VoiceProfile:
    profile_id: str
    model_version: str
    embedding: tuple[float, ...]
    accept_threshold: float
    uncertain_threshold: float
    enrollment_quality: Literal["accepted"]

    def __post_init__(self) -> None:
        try:
            canonical_id = str(UUID(self.profile_id))
            vector = _normalized_embedding(self.embedding)
        except Exception:
            raise ValueError("voice_profile_invalid") from None
        if (
            canonical_id != self.profile_id
            or _MODEL_VERSION.fullmatch(self.model_version) is None
            or vector != self.embedding
            or not 0.50 <= self.uncertain_threshold < self.accept_threshold <= 0.95
            or self.enrollment_quality != "accepted"
        ):
            raise ValueError("voice_profile_invalid")


@dataclass(frozen=True)
class SpeakerVerification:
    state: SpeakerState
    reason: str


class SpeakerVerifier:
    """Compare one utterance only with the explicit claimed enrolled profile."""

    def __init__(
        self,
        *,
        runner: EmbeddingRunner,
        profile: VoiceProfile | None,
        claimed_profile_id: str | None,
        model_version: str,
    ) -> None:
        self._runner = runner
        self._profile = profile
        self._claim = claimed_profile_id
        self._model_version = model_version

    def verify(self, pcm: bytes) -> SpeakerVerification:
        profile = self._profile
        if profile is None or profile.model_version != self._model_version:
            return _result("not_enrolled")
        if self._claim is None:
            return _result("uncertain")
        if self._claim != profile.profile_id:
            return _result("mismatch")
        try:
            samples = _validated_pcm(pcm)
            observation = self._runner(samples)
            candidate = _validated_observation(observation)
        except Exception:
            return _result("uncertain")
        if (
            observation.speech_seconds < MIN_PCM_SECONDS
            or observation.snr_db < MIN_SNR_DB
            or observation.overlap_probability > MAX_OVERLAP_PROBABILITY
        ):
            return _result("uncertain")
        similarity = float(np.dot(np.asarray(profile.embedding), np.asarray(candidate)))
        if not math.isfinite(similarity):
            return _result("uncertain")
        if similarity >= profile.accept_threshold:
            return _result("verified")
        if similarity < profile.uncertain_threshold:
            return _result("mismatch")
        return _result("uncertain")


def _validated_pcm(pcm: bytes) -> np.ndarray:
    if (
        type(pcm) is not bytes
        or len(pcm) % SAMPLE_WIDTH_BYTES
        or not int(MIN_PCM_SECONDS * SAMPLE_RATE_HZ * SAMPLE_WIDTH_BYTES)
        <= len(pcm)
        <= int(MAX_PCM_SECONDS * SAMPLE_RATE_HZ * SAMPLE_WIDTH_BYTES)
    ):
        raise ValueError("voice_pcm_invalid")
    samples = np.frombuffer(pcm, dtype="<i2").astype(np.float32) / 32_768.0
    rms = float(np.sqrt(np.mean(np.square(samples), dtype=np.float64)))
    dbfs = 20.0 * math.log10(max(rms, 1.0 / 32_768.0))
    if not math.isfinite(dbfs) or dbfs < MIN_SIGNAL_DBFS:
        raise ValueError("voice_pcm_invalid")
    return samples


def _validated_observation(observation: EmbeddingObservation) -> tuple[float, ...]:
    if not isinstance(observation, EmbeddingObservation):
        raise ValueError("voice_model_unavailable")
    metrics = (
        observation.speech_seconds,
        observation.snr_db,
        observation.overlap_probability,
    )
    if (
        any(
            type(value) not in {int, float} or not math.isfinite(float(value))
            for value in metrics
        )
        or observation.speech_seconds < 0.0
        or not 0.0 <= observation.overlap_probability <= 1.0
    ):
        raise ValueError("voice_model_unavailable")
    return _normalized_embedding(observation.embedding)


def _normalized_embedding(raw: object) -> tuple[float, ...]:
    if type(raw) is not tuple or len(raw) != EMBEDDING_DIMENSIONS:
        raise ValueError("voice_model_unavailable")
    values = np.asarray(raw, dtype=np.float64)
    if values.shape != (EMBEDDING_DIMENSIONS,) or not np.isfinite(values).all():
        raise ValueError("voice_model_unavailable")
    norm = float(np.linalg.norm(values))
    if not math.isfinite(norm) or not 0.999 <= norm <= 1.001:
        raise ValueError("voice_model_unavailable")
    return tuple(float(value) for value in values)


def _result(state: SpeakerState) -> SpeakerVerification:
    return SpeakerVerification(state=state, reason=f"speaker_{state}")


__all__ = [
    "EMBEDDING_DIMENSIONS",
    "EmbeddingObservation",
    "SpeakerState",
    "SpeakerVerification",
    "SpeakerVerifier",
    "VoiceProfile",
]
