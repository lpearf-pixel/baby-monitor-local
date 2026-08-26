from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from packages.contracts.settings import VoiceCareSettings


def enabled_settings() -> VoiceCareSettings:
    return VoiceCareSettings(
        enabled=True,
        silero_vad_manifest_sha256="1" * 64,
        whisper_base_manifest_sha256="2" * 64,
        whisper_small_manifest_sha256="3" * 64,
        paraformer_zh_manifest_sha256="5" * 64,
        speechbrain_ecapa_manifest_sha256="4" * 64,
    )


def test_voice_defaults_are_disabled_and_bounded() -> None:
    settings = VoiceCareSettings()

    assert settings.enabled is False
    assert settings.listen_only_enabled is False
    assert settings.camera_reply_enabled is False
    assert settings.stream_name == "audio_analysis"
    assert settings.max_utterance_ms == 8_000
    assert settings.pre_roll_ms == 500
    assert settings.terminal_silence_ms == 800
    assert settings.outbox_max_intents == 128
    assert settings.outbox_retention_seconds == 1_800


def test_enabled_voice_rejects_missing_artifact_manifest_digests() -> None:
    with pytest.raises(ValueError, match="VOICE_ARTIFACT_DIGEST_REQUIRED"):
        VoiceCareSettings(enabled=True)


def test_enabled_voice_accepts_all_pinned_manifest_digests() -> None:
    settings = enabled_settings()

    assert settings.silero_vad_manifest_sha256 == "1" * 64
    assert settings.paraformer_zh_manifest_sha256 == "5" * 64


def test_full_care_and_listen_only_modes_are_mutually_exclusive() -> None:
    with pytest.raises(ValueError, match="VOICE_MODE_CONFLICT"):
        VoiceCareSettings(
            enabled=True,
            listen_only_enabled=True,
            silero_vad_manifest_sha256="1" * 64,
            whisper_base_manifest_sha256="2" * 64,
            whisper_small_manifest_sha256="3" * 64,
            paraformer_zh_manifest_sha256="5" * 64,
            speechbrain_ecapa_manifest_sha256="4" * 64,
        )


def test_listen_only_requires_only_the_selected_runtime_digests() -> None:
    settings = VoiceCareSettings(
        listen_only_enabled=True,
        silero_vad_manifest_sha256="1" * 64,
        paraformer_zh_manifest_sha256="5" * 64,
    )

    assert settings.listen_only_enabled is True
    assert settings.whisper_base_manifest_sha256 is None
    assert settings.speechbrain_ecapa_manifest_sha256 is None


def test_listen_only_rejects_a_missing_selected_runtime_digest() -> None:
    with pytest.raises(ValueError, match="VOICE_LISTEN_ONLY_ARTIFACT_DIGEST_REQUIRED"):
        VoiceCareSettings(
            listen_only_enabled=True,
            silero_vad_manifest_sha256="1" * 64,
        )


def test_camera_reply_example_is_disabled() -> None:
    payload = yaml.safe_load(Path("config/settings.example.yaml").read_text())

    assert payload["voice_care"]["camera_reply_enabled"] is False


@pytest.mark.parametrize(
    ("enabled", "listen_only_enabled"), [(False, False), (True, False)]
)
def test_camera_reply_requires_exclusive_listen_only_mode(
    enabled: bool, listen_only_enabled: bool
) -> None:
    values = {
        "enabled": enabled,
        "listen_only_enabled": listen_only_enabled,
        "camera_reply_enabled": True,
        "silero_vad_manifest_sha256": "1" * 64,
        "paraformer_zh_manifest_sha256": "5" * 64,
    }
    if enabled:
        values.update(
            {
                "whisper_base_manifest_sha256": "2" * 64,
                "whisper_small_manifest_sha256": "3" * 64,
                "speechbrain_ecapa_manifest_sha256": "4" * 64,
            }
        )
    with pytest.raises(ValueError, match="VOICE_CAMERA_REPLY_MODE_REQUIRED"):
        VoiceCareSettings(**values)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("stream_name", "analysis"),
        ("max_utterance_ms", 7_000),
        ("pre_roll_ms", 600),
        ("terminal_silence_ms", 900),
        ("outbox_max_intents", 64),
        ("outbox_retention_seconds", 1_000),
    ],
)
def test_voice_fixed_fields_reject_replacement(field: str, value: object) -> None:
    with pytest.raises(ValueError, match=field):
        VoiceCareSettings.model_validate({field: value})
