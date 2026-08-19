from __future__ import annotations

import math

import numpy as np
import pytest

from packages.contracts.audio import AudioObservationState
from packages.contracts.settings import AudioSettings
from services.audio.features import DynamicLoudnessGate, pcm_loudness_dbfs


def pcm_at_level(dbfs: float, *, samples: int = 16_000) -> bytes:
    peak = 10 ** (dbfs / 20) * math.sqrt(2)
    phase = np.arange(samples, dtype=np.float64)
    signal = np.sin(2 * math.pi * 440 * phase / 16_000) * peak
    return np.rint(signal * 32_767).astype("<i2").tobytes()


def test_pcm_loudness_reports_hand_checked_rms_level() -> None:
    assert pcm_loudness_dbfs(pcm_at_level(-23.0)) == pytest.approx(-23.0, abs=0.05)


def test_silence_has_finite_bounded_loudness() -> None:
    assert pcm_loudness_dbfs(bytes(32_000)) == -120.0


def test_quiet_background_updates_noise_floor_without_opening_gate() -> None:
    gate = DynamicLoudnessGate(
        settings=AudioSettings(initial_noise_floor_dbfs=-60.0)
    )

    first = gate.observe(pcm_at_level(-55.0))
    second = gate.observe(pcm_at_level(-50.0))

    assert first.state is AudioObservationState.QUIET
    assert second.state is AudioObservationState.QUIET
    assert -60.0 < second.noise_floor_dbfs < -50.0


def test_loud_episode_does_not_raise_learned_noise_floor() -> None:
    gate = DynamicLoudnessGate(
        settings=AudioSettings(initial_noise_floor_dbfs=-55.0)
    )
    quiet = gate.observe(pcm_at_level(-52.0))

    loud = gate.observe(pcm_at_level(-20.0))

    assert loud.state is AudioObservationState.SOUND
    assert loud.noise_floor_dbfs == quiet.noise_floor_dbfs


def test_tone_can_only_be_sound_before_cry_classifier() -> None:
    gate = DynamicLoudnessGate(
        settings=AudioSettings(initial_noise_floor_dbfs=-55.0)
    )

    observation = gate.observe(pcm_at_level(-18.0))

    assert observation.state is AudioObservationState.SOUND
    assert observation.cry_confidence is None


def test_gate_uses_centralized_margin_setting() -> None:
    settings = AudioSettings(loudness_gate_margin_db=20.0)
    gate = DynamicLoudnessGate(settings=settings)

    observation = gate.observe(pcm_at_level(-45.0))

    assert observation.state is AudioObservationState.QUIET
