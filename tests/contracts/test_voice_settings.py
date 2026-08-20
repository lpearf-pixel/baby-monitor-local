from __future__ import annotations

import pytest

from packages.contracts.settings import VoiceCareSettings


def test_voice_defaults_are_disabled_and_bounded() -> None:
    settings = VoiceCareSettings()

    assert settings.enabled is False
    assert settings.stream_name == "audio_analysis"
    assert settings.max_utterance_ms == 8_000
    assert settings.pre_roll_ms == 500
    assert settings.terminal_silence_ms == 800
    assert settings.outbox_max_intents == 128
    assert settings.outbox_retention_seconds == 1_800


def test_enabled_voice_rejects_missing_artifact_digests() -> None:
    with pytest.raises(ValueError, match="VOICE_ARTIFACT_DIGEST_REQUIRED"):
        VoiceCareSettings(enabled=True)
