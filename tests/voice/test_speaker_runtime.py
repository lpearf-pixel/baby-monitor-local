from __future__ import annotations

import numpy as np
import pytest

from packages.contracts.settings import VoiceCareSettings
from services.voice.artifacts import voice_artifact_spec
from services.voice.ecapa import EcapaEmbedding
from services.voice.speaker_runtime import EcapaObservationRunner, ecapa_model_version


def embedding(first: float, second: float = 0.0) -> tuple[float, ...]:
    values = np.zeros(192, dtype=np.float64)
    values[0] = first
    values[1] = second
    values /= np.linalg.norm(values)
    return tuple(float(value) for value in values)


def utterance() -> np.ndarray:
    quiet = np.full(int(16_000 * 0.4), 0.001, dtype=np.float32)
    time = np.arange(int(16_000 * 2.4), dtype=np.float32) / 16_000
    speech = (0.20 * np.sin(2 * np.pi * 220 * time)).astype(np.float32)
    return np.concatenate((quiet, speech, quiet))


class Process:
    def __init__(self, results: tuple[EcapaEmbedding, ...]) -> None:
        self._results = iter(results)
        self.calls: list[bytes] = []
        self.close_calls = 0

    def embed(self, pcm: bytes) -> EcapaEmbedding:
        self.calls.append(pcm)
        return next(self._results)

    def close(self) -> None:
        self.close_calls += 1


def result(vector: tuple[float, ...]) -> EcapaEmbedding:
    return EcapaEmbedding(vector, 10)


def test_unsupervised_runtime_fails_closed_when_overlap_is_not_measured() -> None:
    process = Process((result(embedding(1.0)),))
    runner = EcapaObservationRunner(process=process)

    observed = runner(utterance())

    assert observed.embedding == embedding(1.0)
    assert observed.speech_seconds >= 1.6
    assert observed.snr_db >= 8.0
    assert observed.overlap_probability == 1.0
    assert len(process.calls) == 1
    assert len(process.calls[0]) == len(utterance()) * 2


def test_explicit_human_supervision_allows_single_speaker_enrollment_observation() -> None:
    process = Process((result(embedding(1.0)),))

    observed = EcapaObservationRunner(
        process=process, supervised_single_speaker=True
    )(utterance())

    assert observed.overlap_probability == 0.0
    assert len(process.calls) == 1


@pytest.mark.parametrize(
    "samples",
    (
        np.zeros(int(16_000 * 3.2), dtype=np.float32),
        np.ones(int(16_000 * 1.59), dtype=np.float32) * 0.2,
        np.ones(int(16_000 * 3.2), dtype=np.float64) * 0.2,
    ),
)
def test_quiet_short_or_wrong_dtype_input_fails_closed(samples: np.ndarray) -> None:
    same = result(embedding(1.0))
    process = Process((same, same, same, same))

    with pytest.raises(ValueError, match="^voice_model_unavailable$"):
        EcapaObservationRunner(process=process)(samples)


def test_close_is_idempotent() -> None:
    process = Process(())
    runner = EcapaObservationRunner(process=process)

    runner.close()
    runner.close()

    assert process.close_calls == 1


def test_model_version_is_bounded_and_derived_from_verified_manifest() -> None:
    artifact = voice_artifact_spec(
        VoiceCareSettings(speechbrain_ecapa_manifest_sha256="a" * 64),
        "speechbrain-ecapa-voxceleb",
    )

    assert ecapa_model_version(artifact) == "speechbrain-ecapa-aaaaaaaaaaaaaaaa"
