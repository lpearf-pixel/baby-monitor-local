from __future__ import annotations

import hashlib
import json
import types
from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

from packages.contracts.settings import VoiceCareSettings
from services.voice.artifacts import VoiceArtifactSpec, voice_artifact_specs
from services.voice.asr import (
    BASELINE,
    CARE_BEAM10,
    CARE_HOTWORDS,
    NO_HOTWORDS,
    AsrEngine,
    _load_whisper_model_class,
)


def _whisper_spec_and_bundle(
    project_root: Path, artifact_id: str = "openai-whisper-base"
) -> tuple[VoiceArtifactSpec, Path]:
    provisional = next(
        spec
        for spec in voice_artifact_specs(
            VoiceCareSettings(
                whisper_base_manifest_sha256="0" * 64,
                whisper_small_manifest_sha256="0" * 64,
                silero_vad_manifest_sha256="0" * 64,
                speechbrain_ecapa_manifest_sha256="0" * 64,
            )
        )
        if spec.artifact_id == artifact_id
    )
    files = {name: name.encode("ascii") for name in provisional.required_files}
    payload = {
        "artifact_id": provisional.artifact_id,
        "files": {
            name: hashlib.sha256(contents).hexdigest()
            for name, contents in files.items()
        },
        "source_manifest_sha256": "a" * 64,
        "source_revision": provisional.source_revision,
        "spdx_license": provisional.spdx_license,
    }
    manifest = (json.dumps(payload, separators=(",", ":"), sort_keys=True) + "\n").encode(
        "ascii"
    )
    manifest_sha256 = hashlib.sha256(manifest).hexdigest()
    settings = VoiceCareSettings(
        whisper_base_manifest_sha256=(
            manifest_sha256 if artifact_id == "openai-whisper-base" else "0" * 64
        ),
        whisper_small_manifest_sha256=(
            manifest_sha256 if artifact_id == "openai-whisper-small" else "0" * 64
        ),
        silero_vad_manifest_sha256="0" * 64,
        speechbrain_ecapa_manifest_sha256="0" * 64,
    )
    spec = next(
        item for item in voice_artifact_specs(settings) if item.artifact_id == artifact_id
    )
    bundle = project_root / spec.bundle_relative_path
    bundle.mkdir(parents=True)
    for name, contents in files.items():
        (bundle / name).write_bytes(contents)
    (bundle / "manifest.json").write_bytes(manifest)
    return spec, bundle


class _Runner:
    def __init__(self, text: str = "小小，我要喂奶了", language: str = "zh") -> None:
        self.text = text
        self.language = language
        self.calls: list[tuple[np.ndarray, dict[str, object]]] = []

    def transcribe(self, samples: np.ndarray, **options: object):
        self.calls.append((samples, options))
        return iter((SimpleNamespace(text=self.text),)), SimpleNamespace(
            language=self.language
        )


@pytest.mark.parametrize(
    "artifact_id", ("openai-whisper-base", "openai-whisper-small")
)
def test_engine_uses_only_validated_absolute_local_whisper_and_chinese_transcribe(
    tmp_path: Path, artifact_id: str
) -> None:
    spec, bundle = _whisper_spec_and_bundle(tmp_path, artifact_id)
    runner = _Runner()
    factory_calls: list[dict[str, object]] = []

    def factory(**options: object) -> _Runner:
        factory_calls.append(options)
        return runner

    engine = AsrEngine(
        spec,
        project_root=tmp_path,
        runner_factory=factory,
        monotonic_ns=iter((1_000_000_000, 1_012_000_000)).__next__,
    )
    result = engine.transcribe(b"\x00\x80\xff\x7f")

    assert factory_calls == [
        {
            "model_path": bundle.resolve(),
            "device": "cpu",
            "compute_type": "int8",
            "local_files_only": True,
        }
    ]
    samples, options = runner.calls[0]
    assert samples.tolist() == pytest.approx([-1.0, 32767 / 32768])
    assert samples.dtype == np.float32
    assert options == {
        "language": "zh",
        "task": "transcribe",
        "beam_size": 5,
        "temperature": 0.0,
        "condition_on_previous_text": False,
        "vad_filter": False,
        "without_timestamps": True,
        "hotwords": "小小 喂奶 开始 喂完 继续 结束 爸爸 妈妈 口令",
    }
    assert result.text == "小小，我要喂奶了"
    assert result.language == "zh"
    assert result.duration_ms == 12


@pytest.mark.parametrize(
    ("profile", "beam_size", "hotwords"),
    (
        (BASELINE, 5, "小小 喂奶 开始 喂完 继续 结束 爸爸 妈妈 口令"),
        (NO_HOTWORDS, 5, None),
        (
            CARE_HOTWORDS,
            5,
            "小小 爸爸 妈妈 宝宝 喂奶 开始 结束 喝了 九十 毫升 配方奶 取消 这次 记录 今天 天气 不错",
        ),
        (
            CARE_BEAM10,
            10,
            "小小 爸爸 妈妈 宝宝 喂奶 开始 结束 喝了 九十 毫升 配方奶 取消 这次 记录 今天 天气 不错",
        ),
    ),
)
def test_engine_uses_only_closed_global_decode_profiles(
    tmp_path: Path, profile: object, beam_size: int, hotwords: str | None
) -> None:
    spec, _bundle = _whisper_spec_and_bundle(tmp_path)
    runner = _Runner()
    engine = AsrEngine(
        spec,
        project_root=tmp_path,
        runner_factory=lambda **_options: runner,
    )

    engine.for_profile(profile).transcribe(b"\0\0")

    options = runner.calls[0][1]
    assert options["beam_size"] == beam_size
    assert options.get("hotwords") == hotwords
    assert "initial_prompt" not in options
    assert "prefix" not in options


def test_engine_rejects_arbitrary_decode_profile(tmp_path: Path) -> None:
    spec, _bundle = _whisper_spec_and_bundle(tmp_path)
    engine = AsrEngine(
        spec,
        project_root=tmp_path,
        runner_factory=lambda **_options: _Runner(),
    )

    with pytest.raises(ValueError, match="^voice_model_unavailable$"):
        engine.for_profile("care_hotwords_beam20")


def test_engine_rejects_non_whisper_artifact_before_runner_creation(tmp_path: Path) -> None:
    settings = VoiceCareSettings(
        whisper_base_manifest_sha256="0" * 64,
        whisper_small_manifest_sha256="0" * 64,
        silero_vad_manifest_sha256="0" * 64,
        speechbrain_ecapa_manifest_sha256="0" * 64,
    )
    spec = voice_artifact_specs(settings)[0]
    created = False

    def factory(**_options: object) -> _Runner:
        nonlocal created
        created = True
        return _Runner()

    with pytest.raises(ValueError, match="^voice_model_unavailable$"):
        AsrEngine(spec, project_root=tmp_path, runner_factory=factory)

    assert created is False


def test_engine_maps_artifact_runner_and_language_failures_to_stable_unavailable(
    tmp_path: Path,
) -> None:
    spec, bundle = _whisper_spec_and_bundle(tmp_path)
    (bundle / "model.bin").write_bytes(b"changed")
    with pytest.raises(ValueError, match="^voice_model_unavailable$"):
        AsrEngine(spec, project_root=tmp_path, runner_factory=lambda **_options: _Runner())

    spec, _bundle = _whisper_spec_and_bundle(tmp_path / "runner")

    class BrokenRunner:
        def transcribe(self, _samples: np.ndarray, **_options: object):
            raise RuntimeError("sensitive runner detail")

    engine = AsrEngine(
        spec,
        project_root=tmp_path / "runner",
        runner_factory=lambda **_options: BrokenRunner(),
    )
    with pytest.raises(ValueError, match="^voice_model_unavailable$"):
        engine.transcribe(b"\0\0")

    spec, _bundle = _whisper_spec_and_bundle(tmp_path / "language")
    engine = AsrEngine(
        spec,
        project_root=tmp_path / "language",
        runner_factory=lambda **_options: _Runner(language="en"),
    )
    with pytest.raises(ValueError, match="^voice_model_unavailable$"):
        engine.transcribe(b"\0\0")


@pytest.mark.parametrize("pcm", [b"", b"\0", b"\0\0" * (16_000 * 8 + 1)])
def test_engine_rejects_empty_misaligned_or_over_eight_second_pcm(
    tmp_path: Path, pcm: bytes
) -> None:
    spec, _bundle = _whisper_spec_and_bundle(tmp_path)
    engine = AsrEngine(
        spec,
        project_root=tmp_path,
        runner_factory=lambda **_options: _Runner(),
    )

    with pytest.raises(ValueError, match="^voice_pcm_invalid$"):
        engine.transcribe(pcm)


def test_runtime_import_blocks_optional_torch_only_before_threads_start() -> None:
    modules: dict[str, object] = {}
    observed: list[object] = []
    model_class = lambda **_options: _Runner()

    def importer(name: str) -> object:
        assert name == "faster_whisper"
        observed.append(modules["torch"])
        return types.SimpleNamespace(WhisperModel=model_class)

    loaded = _load_whisper_model_class(
        importer=importer,
        modules=modules,
        active_count=lambda: 1,
    )

    assert loaded is model_class
    assert observed == [None]
    assert "torch" not in modules

    with pytest.raises(ValueError, match="^voice_model_unavailable$"):
        _load_whisper_model_class(
            importer=importer,
            modules={"torch": object()},
            active_count=lambda: 1,
        )
    with pytest.raises(ValueError, match="^voice_model_unavailable$"):
        _load_whisper_model_class(
            importer=importer,
            modules={},
            active_count=lambda: 2,
        )
