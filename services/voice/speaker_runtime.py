"""Conservative local ECAPA quality adapter for adult speaker enrollment."""

from __future__ import annotations

import math
from typing import Protocol

import numpy as np

from services.voice.artifacts import VoiceArtifactSpec
from services.voice.ecapa import EcapaEmbedding
from services.voice.speaker import EmbeddingObservation


SAMPLE_RATE_HZ = 16_000
FRAME_SAMPLES = 320
MIN_ACTIVE_SECONDS = 1.6
MAX_UTTERANCE_SECONDS = 8.0
UNAVAILABLE_REASON = "voice_model_unavailable"


class _EmbeddingProcess(Protocol):
    def embed(self, pcm: bytes) -> EcapaEmbedding: ...

    def close(self) -> None: ...


class EcapaObservationRunner:
    """Create one closed speaker observation from full and temporal embeddings."""

    def __init__(
        self,
        *,
        process: _EmbeddingProcess,
        supervised_single_speaker: bool = False,
    ) -> None:
        if type(supervised_single_speaker) is not bool:
            raise ValueError(UNAVAILABLE_REASON)
        self._process = process
        self._supervised_single_speaker = supervised_single_speaker
        self._closed = False

    def __call__(self, samples: np.ndarray) -> EmbeddingObservation:
        try:
            checked = _validated_samples(samples)
            speech_seconds, snr_db = _signal_quality(checked)
            full = _embedding(self._process.embed(_pcm_bytes(checked)))
            return EmbeddingObservation(
                embedding=full,
                speech_seconds=speech_seconds,
                snr_db=snr_db,
                overlap_probability=(
                    0.0 if self._supervised_single_speaker else 1.0
                ),
            )
        except Exception:
            raise ValueError(UNAVAILABLE_REASON) from None

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        self._process.close()


def ecapa_model_version(artifact: VoiceArtifactSpec) -> str:
    if artifact.artifact_id != "speechbrain-ecapa-voxceleb":
        raise ValueError(UNAVAILABLE_REASON)
    return f"speechbrain-ecapa-{artifact.manifest_sha256[:16]}"


def _validated_samples(samples: np.ndarray) -> np.ndarray:
    if (
        type(samples) is not np.ndarray
        or samples.dtype != np.float32
        or samples.ndim != 1
        or not int(MIN_ACTIVE_SECONDS * SAMPLE_RATE_HZ)
        <= samples.size
        <= int(MAX_UTTERANCE_SECONDS * SAMPLE_RATE_HZ)
        or not np.isfinite(samples).all()
        or float(np.max(np.abs(samples))) > 1.0
    ):
        raise ValueError(UNAVAILABLE_REASON)
    return samples


def _signal_quality(samples: np.ndarray) -> tuple[float, float]:
    frame_count = samples.size // FRAME_SAMPLES
    frames = samples[: frame_count * FRAME_SAMPLES].reshape(
        frame_count, FRAME_SAMPLES
    )
    rms = np.sqrt(np.mean(np.square(frames), axis=1, dtype=np.float64))
    dbfs = 20.0 * np.log10(np.maximum(rms, 1.0 / 32_768.0))
    noise_dbfs = float(np.percentile(dbfs, 20))
    signal_dbfs = float(np.percentile(dbfs, 80))
    snr_db = signal_dbfs - noise_dbfs
    active = dbfs >= noise_dbfs + 6.0
    active_indices = np.flatnonzero(active)
    speech_seconds = float(active_indices.size * FRAME_SAMPLES / SAMPLE_RATE_HZ)
    if (
        not math.isfinite(snr_db)
        or snr_db < 0.0
        or speech_seconds < MIN_ACTIVE_SECONDS
        or active_indices.size == 0
    ):
        raise ValueError(UNAVAILABLE_REASON)
    return speech_seconds, min(snr_db, 120.0)


def _pcm_bytes(samples: np.ndarray) -> bytes:
    converted = np.rint(samples.astype(np.float64) * 32_767.0).astype("<i2")
    return converted.tobytes()


def _embedding(result: EcapaEmbedding) -> tuple[float, ...]:
    if (
        not isinstance(result, EcapaEmbedding)
        or type(result.embedding) is not tuple
        or len(result.embedding) != 192
        or any(
            type(value) not in {int, float} or not math.isfinite(float(value))
            for value in result.embedding
        )
    ):
        raise ValueError(UNAVAILABLE_REASON)
    values = np.asarray(result.embedding, dtype=np.float64)
    norm = float(np.linalg.norm(values))
    if not math.isfinite(norm) or not 0.999 <= norm <= 1.001:
        raise ValueError(UNAVAILABLE_REASON)
    return tuple(float(value) for value in values)


__all__ = ["EcapaObservationRunner", "ecapa_model_version"]
