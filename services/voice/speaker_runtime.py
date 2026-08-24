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
WINDOW_SAMPLES = 12_800
MIN_ACTIVE_SECONDS = 1.6
MAX_UTTERANCE_SECONDS = 8.0
TEMPORAL_REFERENCE_COSINE = 0.75
UNAVAILABLE_REASON = "voice_model_unavailable"


class _EmbeddingProcess(Protocol):
    def embed(self, pcm: bytes) -> EcapaEmbedding: ...

    def close(self) -> None: ...


class EcapaObservationRunner:
    """Create one closed speaker observation from full and temporal embeddings."""

    def __init__(self, *, process: _EmbeddingProcess) -> None:
        self._process = process
        self._closed = False

    def __call__(self, samples: np.ndarray) -> EmbeddingObservation:
        try:
            checked = _validated_samples(samples)
            speech_seconds, snr_db, active_start, active_end = _signal_quality(
                checked
            )
            full = _embedding(self._process.embed(_pcm_bytes(checked)))
            windows = tuple(
                _embedding(self._process.embed(_pcm_bytes(window)))
                for window in _three_windows(checked, active_start, active_end)
            )
            return EmbeddingObservation(
                embedding=full,
                speech_seconds=speech_seconds,
                snr_db=snr_db,
                overlap_probability=_temporal_overlap_probability(windows),
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


def _signal_quality(samples: np.ndarray) -> tuple[float, float, int, int]:
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
    start = int(active_indices[0] * FRAME_SAMPLES)
    end = int((active_indices[-1] + 1) * FRAME_SAMPLES)
    if end - start < WINDOW_SAMPLES:
        raise ValueError(UNAVAILABLE_REASON)
    return speech_seconds, min(snr_db, 120.0), start, end


def _three_windows(
    samples: np.ndarray, active_start: int, active_end: int
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    last_start = active_end - WINDOW_SAMPLES
    middle_start = (active_start + last_start) // 2
    return tuple(
        samples[start : start + WINDOW_SAMPLES]
        for start in (active_start, middle_start, last_start)
    )  # type: ignore[return-value]


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


def _temporal_overlap_probability(
    windows: tuple[tuple[float, ...], ...]
) -> float:
    similarities = [
        float(np.dot(windows[left], windows[right]))
        for left, right in ((0, 1), (0, 2), (1, 2))
    ]
    minimum = min(similarities)
    if not math.isfinite(minimum):
        raise ValueError(UNAVAILABLE_REASON)
    return max(
        0.0,
        min(
            1.0,
            (TEMPORAL_REFERENCE_COSINE - minimum)
            / TEMPORAL_REFERENCE_COSINE,
        ),
    )


__all__ = ["EcapaObservationRunner", "ecapa_model_version"]
