import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from packages.contracts.settings import AudioSettings


def test_audio_defaults_are_fixed_private_and_memory_bounded() -> None:
    settings = AudioSettings()

    assert settings.enabled is False
    assert settings.stream_name == "audio_analysis"
    assert settings.sample_rate_hz == 16_000
    assert settings.channels == 1
    assert settings.sample_width_bytes == 2
    assert settings.buffer_seconds == 15
    assert settings.normal_seconds == 5
    assert settings.high_seconds == 10
    assert settings.repeat_seconds == 30
    assert settings.initial_noise_floor_dbfs == -60.0
    assert settings.loudness_gate_margin_db == 12.0
    assert settings.noise_floor_adaptation == 0.1
    assert settings.model_path == Path("runtime/models/cry-classifier.onnx")


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("stream_name", "rtsp://camera.example/private"),
        ("sample_rate_hz", 48_000),
        ("channels", 2),
        ("sample_width_bytes", 4),
        ("buffer_seconds", 60),
    ],
)
def test_audio_fixed_runtime_boundary_rejects_replacement(
    field: str, value: object
) -> None:
    with pytest.raises(ValidationError, match=field):
        AudioSettings.model_validate({field: value})


@pytest.mark.parametrize(
    "model_path",
    [Path("/private/model.onnx"), Path("../model.onnx")],
)
def test_audio_model_path_must_remain_relative_and_local(model_path: Path) -> None:
    with pytest.raises(ValidationError, match="model_path"):
        AudioSettings(model_path=model_path)


def test_audio_timing_must_remain_ordered_and_fit_memory_window() -> None:
    with pytest.raises(ValidationError, match="timing"):
        AudioSettings(normal_seconds=10, high_seconds=5)

    with pytest.raises(ValidationError, match="buffer"):
        AudioSettings(buffer_seconds=5, high_seconds=10)


def test_audio_settings_reject_unknown_fields() -> None:
    with pytest.raises(ValidationError):
        AudioSettings.model_validate({"source_url": "rtsp://private"})


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("initial_noise_floor_dbfs", 1),
        ("loudness_gate_margin_db", 0),
        ("noise_floor_adaptation", 1),
    ],
)
def test_audio_loudness_settings_are_bounded(field: str, value: float) -> None:
    with pytest.raises(ValidationError, match=field):
        AudioSettings.model_validate({field: value})


def test_exported_schema_and_example_expose_safe_audio_defaults() -> None:
    schema = json.loads(
        Path("config/settings.schema.json").read_text(encoding="utf-8")
    )

    assert schema["properties"]["audio"]["$ref"] == "#/$defs/AudioSettings"
    audio = schema["$defs"]["AudioSettings"]["properties"]
    assert audio["stream_name"]["const"] == "audio_analysis"
    assert audio["sample_rate_hz"]["const"] == 16_000
    assert audio["buffer_seconds"]["const"] == 15

    example = Path("config/settings.example.yaml").read_text(encoding="utf-8")
    assert "audio:\n  enabled: false\n" in example
    assert "  stream_name: audio_analysis\n" in example
    assert "runtime/models/cry-classifier.onnx" in example
