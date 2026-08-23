from __future__ import annotations

from collections.abc import Callable

import numpy as np
import pytest

from services.voice.speaker import (
    EmbeddingObservation,
    SpeakerVerifier,
    VoiceProfile,
)


PROFILE_ID = "11111111-1111-4111-8111-111111111111"
OTHER_PROFILE_ID = "22222222-2222-4222-8222-222222222222"
MODEL_VERSION = "speechbrain-ecapa-v1"


def embedding(first: float, second: float = 0.0) -> tuple[float, ...]:
    values = np.zeros(192, dtype=np.float32)
    values[0] = first
    values[1] = second
    values /= np.linalg.norm(values)
    return tuple(float(value) for value in values)


def pcm(seconds: float = 1.25, amplitude: int = 4_000) -> bytes:
    return np.full(int(16_000 * seconds), amplitude, dtype="<i2").tobytes()


def profile() -> VoiceProfile:
    return VoiceProfile(
        profile_id=PROFILE_ID,
        model_version=MODEL_VERSION,
        embedding=embedding(1.0),
        accept_threshold=0.80,
        uncertain_threshold=0.55,
        enrollment_quality="accepted",
    )


class Runner:
    def __init__(self, observation: EmbeddingObservation | Exception) -> None:
        self.observation = observation
        self.calls = 0

    def __call__(self, samples: np.ndarray) -> EmbeddingObservation:
        self.calls += 1
        assert samples.dtype == np.float32
        if isinstance(self.observation, Exception):
            raise self.observation
        return self.observation


def observation(
    vector: tuple[float, ...], *, speech_seconds: float = 1.2,
    snr_db: float = 18.0, overlap_probability: float = 0.0,
) -> EmbeddingObservation:
    return EmbeddingObservation(
        embedding=vector,
        speech_seconds=speech_seconds,
        snr_db=snr_db,
        overlap_probability=overlap_probability,
    )


def verifier(
    result: EmbeddingObservation | Exception,
    *, claimed_profile_id: str | None = PROFILE_ID,
    enrolled_profile: VoiceProfile | None = None,
) -> tuple[SpeakerVerifier, Runner]:
    runner = Runner(result)
    return (
        SpeakerVerifier(
            runner=runner,
            profile=profile() if enrolled_profile is None else enrolled_profile,
            claimed_profile_id=claimed_profile_id,
            model_version=MODEL_VERSION,
        ),
        runner,
    )


def test_verified_uncertain_and_mismatch_are_closed_states() -> None:
    verified, _ = verifier(observation(embedding(1.0)))
    uncertain, _ = verifier(observation(embedding(0.70, 0.714)))
    mismatch, _ = verifier(observation(embedding(0.10, 0.995)))

    verified_result = verified.verify(pcm())
    assert verified_result.state == "verified"
    assert set(vars(verified_result)) == {"state", "reason"}
    assert "audio" not in repr(verified_result)
    assert "transcript" not in repr(verified_result)
    assert uncertain.verify(pcm()).state == "uncertain"
    assert mismatch.verify(pcm()).state == "mismatch"


def test_not_enrolled_and_claim_conflict_do_not_run_the_model() -> None:
    no_profile_runner = Runner(observation(embedding(1.0)))
    no_profile = SpeakerVerifier(
        runner=no_profile_runner,
        profile=None,
        claimed_profile_id=PROFILE_ID,
        model_version=MODEL_VERSION,
    )
    conflict, conflict_runner = verifier(
        observation(embedding(1.0)), claimed_profile_id=OTHER_PROFILE_ID
    )

    assert no_profile.verify(pcm()).state == "not_enrolled"
    assert conflict.verify(pcm()).state == "mismatch"
    assert no_profile_runner.calls == conflict_runner.calls == 0


@pytest.mark.parametrize(
    "change",
    [
        lambda value: observation(value, speech_seconds=0.4),
        lambda value: observation(value, snr_db=4.0),
        lambda value: observation(value, overlap_probability=0.2),
    ],
)
def test_short_noisy_or_overlapping_audio_is_uncertain(
    change: Callable[[tuple[float, ...]], EmbeddingObservation],
) -> None:
    candidate, _ = verifier(change(embedding(1.0)))
    assert candidate.verify(pcm()).state == "uncertain"


@pytest.mark.parametrize("candidate", [b"", b"\0", pcm(8.01), pcm(amplitude=0)])
def test_invalid_or_quiet_pcm_and_model_failure_are_uncertain(candidate: bytes) -> None:
    checked, _ = verifier(observation(embedding(1.0)))
    assert checked.verify(candidate).state == "uncertain"
    broken, _ = verifier(RuntimeError("private model detail"))
    result = broken.verify(pcm())
    assert result.state == "uncertain"
    assert "private" not in result.reason
