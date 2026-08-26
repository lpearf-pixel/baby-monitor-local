from __future__ import annotations

from pathlib import Path

import pytest

from packages.contracts.settings import VoiceCareSettings
from services.voice.live_enrollment import EnrollmentFailure, EnrollmentRunReport
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
            Coordinator(EnrollmentFailure("asr")),
            lambda: closed.append(True),
        ),
        input_fn=lambda _prompt: "",
        printer=output.append,
    )

    assert result == 1
    assert output == [
        "result=FAIL",
        "reason=voice_enrollment_failed",
        "failure_stage=asr",
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
        paraformer_zh_manifest_sha256="e" * 64,
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


def test_operator_build_uses_selected_paraformer_and_closes_both_models(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    artifacts: list[str] = []
    closed: list[str] = []
    class Paraformer:
        def close(self) -> None:
            closed.append("paraformer")

    paraformer = Paraformer()
    coordinator = object()

    monkeypatch.setattr(voice_enroll.platform, "system", lambda: "Darwin")
    monkeypatch.setattr(voice_enroll.platform, "machine", lambda: "x86_64")
    monkeypatch.setattr(voice_enroll, "_load_disabled_settings", lambda _root: object())
    monkeypatch.setattr(
        voice_enroll,
        "voice_artifact_spec",
        lambda _settings, artifact_id: artifacts.append(artifact_id) or artifact_id,
    )
    monkeypatch.setattr(
        voice_enroll,
        "ParaformerProcess",
        lambda artifact, *, project_root: paraformer,
        raising=False,
    )
    monkeypatch.setattr(voice_enroll, "keychain_for_runtime", lambda _root: object())
    monkeypatch.setattr(voice_enroll, "VoiceProfileStore", lambda *_args, **_kwargs: object())
    monkeypatch.setattr(voice_enroll, "VoiceProfileRegistry", lambda *_args, **_kwargs: object())
    monkeypatch.setattr(voice_enroll, "EcapaProcess", lambda *_args, **_kwargs: object())
    monkeypatch.setattr(
        voice_enroll,
        "EcapaObservationRunner",
        lambda **_kwargs: type("Runner", (), {"close": lambda self: closed.append("ecapa")})(),
    )
    monkeypatch.setattr(voice_enroll, "VoiceEnrollment", lambda **_kwargs: object())
    monkeypatch.setattr(voice_enroll, "ecapa_model_version", lambda _artifact: "ecapa-v1")
    monkeypatch.setattr(voice_enroll, "BoundedLivePcmCapture", lambda _settings: object())
    monkeypatch.setattr(voice_enroll, "EnrollmentChallengeSession", lambda: object())

    def build_coordinator(**kwargs: object) -> object:
        assert kwargs["asr"] is paraformer
        return coordinator

    monkeypatch.setattr(voice_enroll, "LiveEnrollmentCoordinator", build_coordinator)
    built, close = voice_enroll._build_operator("dad", tmp_path, lambda _prompt: "", print)
    close()

    assert built is coordinator
    assert artifacts == [
        "sherpa-onnx-paraformer-zh-2023-09-14",
        "speechbrain-ecapa-voxceleb",
    ]
    assert closed == ["ecapa", "paraformer"]


def test_operator_build_closes_paraformer_when_ecapa_start_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    closed: list[bool] = []

    class Paraformer:
        def close(self) -> None:
            closed.append(True)

    monkeypatch.setattr(voice_enroll.platform, "system", lambda: "Darwin")
    monkeypatch.setattr(voice_enroll.platform, "machine", lambda: "x86_64")
    monkeypatch.setattr(voice_enroll, "_load_disabled_settings", lambda _root: object())
    monkeypatch.setattr(
        voice_enroll,
        "voice_artifact_spec",
        lambda _settings, artifact_id: artifact_id,
    )
    monkeypatch.setattr(
        voice_enroll,
        "ParaformerProcess",
        lambda _artifact, *, project_root: Paraformer(),
    )
    monkeypatch.setattr(voice_enroll, "keychain_for_runtime", lambda _root: object())
    monkeypatch.setattr(voice_enroll, "VoiceProfileStore", lambda *_args, **_kwargs: object())
    monkeypatch.setattr(voice_enroll, "VoiceProfileRegistry", lambda *_args, **_kwargs: object())
    monkeypatch.setattr(
        voice_enroll,
        "EcapaProcess",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(ValueError("voice_model_unavailable")),
    )

    with pytest.raises(ValueError, match="^voice_model_unavailable$"):
        voice_enroll._build_operator("dad", tmp_path, lambda _prompt: "", print)

    assert closed == [True]


def test_enrollment_challenge_waits_for_local_countdown_before_capture() -> None:
    events: list[str] = []

    class Capture:
        def capture(self) -> bytes:
            events.append("capture")
            return b"pcm"

    result = voice_enroll._capture_after_countdown(
        "小小，我要说口令一二三四",
        capture=Capture(),
        input_fn=lambda prompt: events.append(prompt) or "",
        printer=events.append,
        sleeper=lambda seconds: events.append(f"sleep={seconds}"),
        cue=lambda: events.append("cue") or True,
    )

    assert result == b"pcm"
    assert events == [
        "challenge=小小，我要说口令一二三四",
        "press_enter_then_speak=",
        *[
            item
            for remaining in range(15, 0, -1)
            for item in (f"capture_starts_in_seconds={remaining}", "sleep=1.0")
        ],
        "cue",
        "capture_now=true",
        "capture",
    ]
