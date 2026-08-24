from __future__ import annotations

from pathlib import Path

import pytest

from packages.contracts.settings import VoiceCareSettings
from services.voice.live_enrollment import EnrollmentRunReport
from tools import voice_enroll


class Coordinator:
    def __init__(self, result: EnrollmentRunReport | BaseException) -> None:
        self.result = result

    def run(self) -> EnrollmentRunReport:
        if isinstance(self.result, BaseException):
            raise self.result
        return self.result


def test_operator_prints_only_public_prompt_and_aggregate_success(
    tmp_path: Path,
) -> None:
    output: list[str] = []
    closed: list[bool] = []

    def builder(
        role: str,
        project_root: Path,
        _input: object,
        printer: object,
    ) -> tuple[Coordinator, object]:
        assert role == "dad"
        assert project_root == tmp_path
        assert callable(printer)
        return (
            Coordinator(EnrollmentRunReport("dad", 3, "created", False)),
            lambda: closed.append(True),
        )

    result = voice_enroll.main(
        ["--role", "dad"],
        project_root=tmp_path,
        builder=builder,
        input_fn=lambda _prompt: "",
        printer=output.append,
    )

    assert result == 0
    assert output == [
        "result=PASS",
        "role=dad",
        "sample_count=3",
        "profile_state=created",
        "raw_audio_persisted=false",
    ]
    assert closed == [True]
    assert "11111111" not in "\n".join(output)


def test_operator_redacts_failure_and_closes_models(tmp_path: Path) -> None:
    output: list[str] = []
    closed: list[bool] = []

    result = voice_enroll.main(
        ["--role", "mom"],
        project_root=tmp_path,
        builder=lambda *_args: (
            Coordinator(RuntimeError("private transcript and profile path")),
            lambda: closed.append(True),
        ),
        input_fn=lambda _prompt: "",
        printer=output.append,
    )

    assert result == 1
    assert output == [
        "result=FAIL",
        "reason=voice_enrollment_failed",
        "raw_audio_persisted=false",
    ]
    assert closed == [True]
    assert "private" not in "\n".join(output)


def test_operator_closes_models_when_interrupted(tmp_path: Path) -> None:
    closed: list[bool] = []

    result = voice_enroll.main(
        ["--role", "dad"],
        project_root=tmp_path,
        builder=lambda *_args: (
            Coordinator(InterruptedError()),
            lambda: closed.append(True),
        ),
        input_fn=lambda _prompt: "",
        printer=lambda _line: None,
    )

    assert result == 1
    assert closed == [True]


def test_operator_settings_preflight_rejects_enabled_or_symlinked_runtime(
    tmp_path: Path,
) -> None:
    config = tmp_path / "runtime/config"
    config.mkdir(parents=True)
    enabled = VoiceCareSettings(
        enabled=True,
        silero_vad_manifest_sha256="a" * 64,
        whisper_base_manifest_sha256="b" * 64,
        whisper_small_manifest_sha256="c" * 64,
        speechbrain_ecapa_manifest_sha256="d" * 64,
    )
    (config / "voice-care-models.json").write_text(
        enabled.model_dump_json(), encoding="ascii"
    )

    with pytest.raises(ValueError, match="^voice_enrollment_failed$"):
        voice_enroll._load_disabled_settings(tmp_path)

    outside = tmp_path / "outside"
    outside.mkdir()
    (config / "voice-care-models.json").unlink()
    (tmp_path / "runtime/config").rmdir()
    (tmp_path / "runtime").rmdir()
    (tmp_path / "runtime").symlink_to(outside, target_is_directory=True)
    with pytest.raises(ValueError, match="^voice_enrollment_failed$"):
        voice_enroll._load_disabled_settings(tmp_path)

    assert list(outside.iterdir()) == []
