from __future__ import annotations

import hashlib
import json
from dataclasses import replace
from pathlib import Path

import pytest

from packages.contracts.settings import VoiceCareSettings
from services.voice.artifacts import (
    VOICE_ARTIFACT_IDS,
    VoiceArtifactSpec,
    validate_voice_artifact,
    voice_artifact_spec,
    voice_artifact_specs,
)
from tools.voice_models import collect_voice_artifact, convert_whisper_bundle, install_voice_artifact


WHISPER_TRANSFORMERS_SOURCE_FILES = (
    "added_tokens.json",
    "config.json",
    "generation_config.json",
    "merges.txt",
    "model.safetensors",
    "normalizer.json",
    "preprocessor_config.json",
    "special_tokens_map.json",
    "tokenizer.json",
    "tokenizer_config.json",
    "vocab.json",
)
WHISPER_FASTER_WHISPER_RUNTIME_FILES = (
    "config.json",
    "model.bin",
    "preprocessor_config.json",
    "tokenizer.json",
    "vocabulary.json",
)


@pytest.fixture
def converter_environment(tmp_path: Path) -> Path:
    executable_dir = tmp_path / "runtime/voice-converter-venv/bin"
    executable_dir.mkdir(parents=True)
    python = executable_dir / "python"
    python.write_text("#!/bin/sh\nexit 0\n", encoding="ascii")
    python.chmod(0o700)
    (executable_dir.parent / "pyvenv.cfg").write_text(
        "include-system-site-packages = false\n", encoding="ascii"
    )
    return python


def canonical_manifest(
    spec: VoiceArtifactSpec,
    files: dict[str, bytes],
    source_manifest_sha256: str = "a" * 64,
) -> bytes:
    return (
        json.dumps(
            {
                "artifact_id": spec.artifact_id,
                "files": {
                    name: hashlib.sha256(payload).hexdigest()
                    for name, payload in sorted(files.items())
                },
                "source_manifest_sha256": source_manifest_sha256,
                "source_revision": spec.source_revision,
                "spdx_license": spec.spdx_license,
            },
            separators=(",", ":"),
            sort_keys=True,
        )
        + "\n"
    ).encode("ascii")


def settings_for_manifest(artifact_id: str, manifest_sha256: str) -> VoiceCareSettings:
    fields = {
        "silero_vad_manifest_sha256": "0" * 64,
        "whisper_base_manifest_sha256": "0" * 64,
        "whisper_small_manifest_sha256": "0" * 64,
        "speechbrain_ecapa_manifest_sha256": "0" * 64,
    }
    field = {
        "silero-vad-v6.2": "silero_vad_manifest_sha256",
        "openai-whisper-base": "whisper_base_manifest_sha256",
        "openai-whisper-small": "whisper_small_manifest_sha256",
        "speechbrain-ecapa-voxceleb": "speechbrain_ecapa_manifest_sha256",
    }[artifact_id]
    fields[field] = manifest_sha256
    return VoiceCareSettings(enabled=True, **fields)


def spec_for_runtime(
    provisional: VoiceArtifactSpec,
    files: dict[str, bytes],
    source_manifest_sha256: str,
) -> VoiceArtifactSpec:
    manifest_sha256 = hashlib.sha256(
        canonical_manifest(provisional, files, source_manifest_sha256)
    ).hexdigest()
    return next(
        candidate
        for candidate in voice_artifact_specs(
            settings_for_manifest(provisional.artifact_id, manifest_sha256)
        )
        if candidate.artifact_id == provisional.artifact_id
    )


def spec_and_files(artifact_id: str, payload: bytes = b"synthetic voice model") -> tuple[VoiceArtifactSpec, dict[str, bytes]]:
    provisional = next(
        spec
        for spec in voice_artifact_specs(settings_for_manifest(artifact_id, "0" * 64))
        if spec.artifact_id == artifact_id
    )
    files = {name: payload + name.encode("ascii") for name in provisional.required_files}
    spec = spec_for_runtime(provisional, files, "a" * 64)
    return spec, files


def write_bundle(
    path: Path,
    spec: VoiceArtifactSpec,
    files: dict[str, bytes],
    source_manifest_sha256: str = "a" * 64,
) -> None:
    path.mkdir(parents=True, exist_ok=True)
    for name, payload in files.items():
        target = path / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(payload)
    (path / "manifest.json").write_bytes(
        canonical_manifest(spec, files, source_manifest_sha256)
    )


def test_registry_is_closed_and_uses_full_immutable_provenance() -> None:
    settings = VoiceCareSettings(
        enabled=True,
        silero_vad_manifest_sha256="1" * 64,
        whisper_base_manifest_sha256="2" * 64,
        whisper_small_manifest_sha256="3" * 64,
        speechbrain_ecapa_manifest_sha256="4" * 64,
    )
    specs = voice_artifact_specs(settings)

    assert tuple(spec.artifact_id for spec in specs) == VOICE_ARTIFACT_IDS
    assert specs[0].source_revision == "be95df9152c0d7618fa1edfeb296fc3dae32376f"
    assert specs[1].upstream_project == "https://huggingface.co/openai/whisper-base"
    assert specs[1].source_revision == "e37978b90ca9030d5170a5c07aadb050351a65bb"
    assert specs[2].upstream_project == "https://huggingface.co/openai/whisper-small"
    assert specs[2].source_revision == "973afd24965f72e36ca33b3055d56a652f456b4d"
    assert specs[3].source_revision == "0f99f2d0ebe89ac095bcc5903c4dd8f72b367286"
    assert all(len(spec.source_revision) == 40 for spec in specs)
    assert all(spec.spdx_license in {"MIT", "Apache-2.0"} for spec in specs)
    for spec in specs[1:3]:
        assert spec.spdx_license == "Apache-2.0"
        assert spec.source_files == WHISPER_TRANSFORMERS_SOURCE_FILES
        assert spec.required_files == WHISPER_FASTER_WHISPER_RUNTIME_FILES
        assert "model.pt" not in spec.source_files
        assert "vocabulary.txt" not in spec.required_files
    assert all(
        spec.bundle_relative_path
        == Path("runtime/models/voice-care") / spec.artifact_id / spec.manifest_sha256
        for spec in specs
    )


def test_single_artifact_selection_requires_only_its_own_digest() -> None:
    settings = VoiceCareSettings(
        enabled=False,
        speechbrain_ecapa_manifest_sha256="4" * 64,
    )

    spec = voice_artifact_spec(settings, "speechbrain-ecapa-voxceleb")

    assert spec.artifact_id == "speechbrain-ecapa-voxceleb"
    assert spec.manifest_sha256 == "4" * 64
    with pytest.raises(ValueError, match="^VOICE_ARTIFACT_DIGEST_REQUIRED$"):
        voice_artifact_spec(settings, "openai-whisper-base")


@pytest.mark.parametrize("artifact_id", ("openai-whisper-base", "openai-whisper-small"))
def test_whisper_converter_uses_validated_transformers_bundle_and_runtime_assets(
    tmp_path: Path, artifact_id: str, converter_environment: Path
) -> None:
    provisional, _runtime_files = spec_and_files(artifact_id)
    source_files = {
        name: b"synthetic source " + name.encode("ascii")
        for name in WHISPER_TRANSFORMERS_SOURCE_FILES
    }
    source, source_manifest, source_manifest_sha256 = write_source(
        tmp_path, provisional, source_files
    )
    output_files = {
        name: b"converted " + name.encode("ascii")
        for name in WHISPER_FASTER_WHISPER_RUNTIME_FILES
    }
    spec = spec_for_runtime(provisional, output_files, source_manifest_sha256)
    commands: list[tuple[str, ...]] = []

    def converter(command: tuple[str, ...], *, check: bool) -> None:
        assert check is True
        commands.append(command)
        output = Path(command[command.index("--output_dir") + 1])
        output.mkdir()
        for name, payload in output_files.items():
            (output / name).write_bytes(payload)

    result = convert_whisper_bundle(
        spec,
        source_dir=source,
        source_manifest=source_manifest,
        source_manifest_sha256=source_manifest_sha256,
        project_root=tmp_path,
        runner=converter,
    )

    assert len(commands) == 1
    command = commands[0]
    assert command[:4] == (
        str(converter_environment),
        str(Path(convert_whisper_bundle.__code__.co_filename).with_name("voice_whisper_converter.py")),
        "--expected-prefix",
        str(converter_environment.parent.parent),
    )
    assert command[4:6] == (
        "--model",
        str(source.resolve()),
    )
    assert command[6] == "--output_dir"
    assert Path(command[7]).name == "bundle"
    assert command[8:] == (
        "--copy_files",
        "tokenizer.json",
        "preprocessor_config.json",
    )
    assert result == tmp_path / spec.bundle_relative_path
    assert validate_voice_artifact(spec, tmp_path) == result


def test_whisper_converter_fails_closed_when_isolated_environment_is_missing(
    tmp_path: Path,
) -> None:
    provisional, _runtime_files = spec_and_files("openai-whisper-base")
    source_files = {
        name: b"synthetic source " + name.encode("ascii")
        for name in WHISPER_TRANSFORMERS_SOURCE_FILES
    }
    source, source_manifest, source_manifest_sha256 = write_source(
        tmp_path, provisional, source_files
    )

    with pytest.raises(ValueError, match="^VOICE_CONVERTER_UNAVAILABLE$"):
        convert_whisper_bundle(
            provisional,
            source_dir=source,
            source_manifest=source_manifest,
            source_manifest_sha256=source_manifest_sha256,
            project_root=tmp_path,
        )


def test_whisper_converter_rejects_system_site_packages(
    tmp_path: Path, converter_environment: Path
) -> None:
    (converter_environment.parent.parent / "pyvenv.cfg").write_text(
        "include-system-site-packages = true\n", encoding="ascii"
    )
    provisional, _runtime_files = spec_and_files("openai-whisper-base")
    source_files = {
        name: b"synthetic source " + name.encode("ascii")
        for name in WHISPER_TRANSFORMERS_SOURCE_FILES
    }
    source, source_manifest, source_manifest_sha256 = write_source(
        tmp_path, provisional, source_files
    )

    with pytest.raises(ValueError, match="^VOICE_CONVERTER_UNAVAILABLE$"):
        convert_whisper_bundle(
            provisional,
            source_dir=source,
            source_manifest=source_manifest,
            source_manifest_sha256=source_manifest_sha256,
            project_root=tmp_path,
        )


def test_valid_bundle_returns_absolute_fixed_runtime_directory(tmp_path: Path) -> None:
    spec, files = spec_and_files("silero-vad-v6.2")
    bundle = tmp_path / spec.bundle_relative_path
    write_bundle(bundle, spec, files)

    result = validate_voice_artifact(spec, tmp_path)

    assert result == bundle.resolve()
    assert result.is_absolute()


@pytest.mark.parametrize("runtime_path", [Path("runtime/models/x"), Path("tracked/model")])
def test_runtime_prefix_is_fixed_at_spec_and_validation_boundaries(
    tmp_path: Path, runtime_path: Path
) -> None:
    spec, _files = spec_and_files("silero-vad-v6.2")

    with pytest.raises(ValueError, match="VOICE_ARTIFACT_INVALID"):
        replace(spec, bundle_relative_path=runtime_path)
    with pytest.raises(ValueError, match="VOICE_ARTIFACT_INVALID"):
        validate_voice_artifact(replace(spec, bundle_relative_path=runtime_path), tmp_path)


def test_bundle_rejects_manifest_provenance_license_and_required_file_errors(
    tmp_path: Path,
) -> None:
    spec, files = spec_and_files("silero-vad-v6.2")
    bundle = tmp_path / spec.bundle_relative_path
    write_bundle(bundle, spec, files)

    manifest = json.loads((bundle / "manifest.json").read_text(encoding="ascii"))
    manifest["spdx_license"] = "Apache-2.0"
    (bundle / "manifest.json").write_text(
        json.dumps(manifest, separators=(",", ":"), sort_keys=True) + "\n",
        encoding="ascii",
    )
    with pytest.raises(ValueError, match="VOICE_ARTIFACT_INVALID"):
        validate_voice_artifact(spec, tmp_path)

    write_bundle(bundle, spec, files)
    (bundle / spec.required_files[0]).unlink()
    with pytest.raises(ValueError, match="VOICE_ARTIFACT_INVALID"):
        validate_voice_artifact(spec, tmp_path)


def test_bundle_rejects_extra_and_symlink_files(tmp_path: Path) -> None:
    spec, files = spec_and_files("silero-vad-v6.2")
    bundle = tmp_path / spec.bundle_relative_path
    write_bundle(bundle, spec, files)
    (bundle / "unexpected.bin").write_bytes(b"extra")

    with pytest.raises(ValueError, match="VOICE_ARTIFACT_INVALID"):
        validate_voice_artifact(spec, tmp_path)

    (bundle / "unexpected.bin").unlink()
    required = bundle / spec.required_files[0]
    payload = required.read_bytes()
    required.unlink()
    outside = tmp_path / "outside.bin"
    outside.write_bytes(payload)
    required.symlink_to(outside)
    with pytest.raises(ValueError, match="VOICE_ARTIFACT_INVALID"):
        validate_voice_artifact(spec, tmp_path)


def test_installer_renames_only_valid_complete_bundle_and_preserves_prior_bundle(
    tmp_path: Path,
) -> None:
    previous_spec, previous_files = spec_and_files("silero-vad-v6.2", b"previous")
    previous_source = tmp_path / "previous-source"
    write_bundle(previous_source, previous_spec, previous_files)
    previous = install_voice_artifact(
        previous_spec, source_bundle=previous_source, project_root=tmp_path
    )

    next_spec, next_files = spec_and_files("silero-vad-v6.2", b"next")
    next_source = tmp_path / "next-source"
    write_bundle(next_source, next_spec, next_files)
    (next_source / "unexpected.bin").write_bytes(b"extra")
    with pytest.raises(ValueError, match="VOICE_ARTIFACT_INVALID"):
        install_voice_artifact(next_spec, source_bundle=next_source, project_root=tmp_path)

    assert validate_voice_artifact(previous_spec, tmp_path) == previous
    assert not (tmp_path / next_spec.bundle_relative_path).exists()


def test_installer_rejects_symlinked_runtime_prefix_before_staging(tmp_path: Path) -> None:
    spec, files = spec_and_files("silero-vad-v6.2")
    source = tmp_path / "source"
    write_bundle(source, spec, files)
    outside = tmp_path.parent / "outside-voice-runtime"
    outside.mkdir()
    (tmp_path / "runtime").symlink_to(outside, target_is_directory=True)

    with pytest.raises(ValueError, match="VOICE_ARTIFACT_INVALID"):
        install_voice_artifact(spec, source_bundle=source, project_root=tmp_path)

    assert not (outside / "models").exists()


def canonical_source_manifest(spec: VoiceArtifactSpec, files: dict[str, bytes]) -> bytes:
    return (
        json.dumps(
            {
                "artifact_id": spec.artifact_id,
                "files": {
                    name: hashlib.sha256(payload).hexdigest()
                    for name, payload in sorted(files.items())
                },
                "source_revision": spec.source_revision,
                "spdx_license": spec.spdx_license,
                "upstream_project": spec.upstream_project,
            },
            separators=(",", ":"),
            sort_keys=True,
        )
        + "\n"
    ).encode("ascii")


def write_source(
    root: Path, spec: VoiceArtifactSpec, files: dict[str, bytes]
) -> tuple[Path, Path, str]:
    source = root / "source"
    source.mkdir()
    for name, payload in files.items():
        (source / name).write_bytes(payload)
    manifest = root / "source-manifest.json"
    manifest_bytes = canonical_source_manifest(spec, files)
    manifest.write_bytes(manifest_bytes)
    return source, manifest, hashlib.sha256(manifest_bytes).hexdigest()


@pytest.mark.parametrize(
    "artifact_id",
    (
        "silero-vad-v6.2",
        "openai-whisper-base",
        "openai-whisper-small",
        "speechbrain-ecapa-voxceleb",
    ),
)
def test_closed_acquisition_requires_verified_source_manifest_without_network(
    tmp_path: Path, artifact_id: str, converter_environment: Path
) -> None:
    provisional, _runtime_files = spec_and_files(artifact_id)
    source_files = {
        name: b"synthetic source " + name.encode("ascii")
        for name in provisional.source_files
    }
    source, source_manifest, source_manifest_sha256 = write_source(
        tmp_path, provisional, source_files
    )
    output_files = {
        name: (
            source_files[name]
            if provisional.acquisition == "collect"
            else b"converted " + name.encode("ascii")
        )
        for name in provisional.required_files
    }
    spec = spec_for_runtime(provisional, output_files, source_manifest_sha256)
    expected = {"calls": 0}

    def converter(command: tuple[str, ...], *, check: bool) -> None:
        expected["calls"] += 1
        output = Path(command[command.index("--output_dir") + 1])
        output.mkdir()
        for name in provisional.required_files:
            (output / name).write_bytes(output_files[name])

    if provisional.acquisition == "collect":
        result = collect_voice_artifact(
            spec,
            source_dir=source,
            source_manifest=source_manifest,
            source_manifest_sha256=source_manifest_sha256,
            project_root=tmp_path,
        )
        assert expected["calls"] == 0
    else:
        result = convert_whisper_bundle(
            spec,
            source_dir=source,
            source_manifest=source_manifest,
            source_manifest_sha256=source_manifest_sha256,
            project_root=tmp_path,
            runner=converter,
        )
        assert expected["calls"] == 1
    assert result == tmp_path / spec.bundle_relative_path
    assert validate_voice_artifact(spec, tmp_path) == result


def test_acquisition_rejects_bad_source_digest_license_layout_and_converter_failure(
    tmp_path: Path,
    converter_environment: Path,
) -> None:
    provisional, _runtime_files = spec_and_files("openai-whisper-base")
    spec = provisional
    source_files = {name: b"source " + name.encode("ascii") for name in spec.source_files}
    source, source_manifest, source_manifest_sha256 = write_source(
        tmp_path, spec, source_files
    )
    with pytest.raises(ValueError, match="VOICE_ARTIFACT_INVALID"):
        convert_whisper_bundle(
            spec,
            source_dir=source,
            source_manifest=source_manifest,
            source_manifest_sha256="0" * 64,
            project_root=tmp_path,
            runner=lambda *_args, **_kwargs: pytest.fail("converter must not run"),
        )

    manifest = json.loads(source_manifest.read_text(encoding="ascii"))
    manifest["spdx_license"] = "MIT"
    source_manifest.write_text(
        json.dumps(manifest, separators=(",", ":"), sort_keys=True) + "\n",
        encoding="ascii",
    )
    with pytest.raises(ValueError, match="VOICE_ARTIFACT_INVALID"):
        convert_whisper_bundle(
            spec,
            source_dir=source,
            source_manifest=source_manifest,
            source_manifest_sha256=hashlib.sha256(source_manifest.read_bytes()).hexdigest(),
            project_root=tmp_path,
            runner=lambda *_args, **_kwargs: pytest.fail("converter must not run"),
        )

    source_manifest.write_bytes(canonical_source_manifest(spec, source_files))
    source_manifest_sha256 = hashlib.sha256(source_manifest.read_bytes()).hexdigest()
    (source / "extra.bin").write_bytes(b"extra")
    with pytest.raises(ValueError, match="VOICE_ARTIFACT_INVALID"):
        convert_whisper_bundle(
            spec,
            source_dir=source,
            source_manifest=source_manifest,
            source_manifest_sha256=source_manifest_sha256,
            project_root=tmp_path,
            runner=lambda *_args, **_kwargs: pytest.fail("converter must not run"),
        )
    (source / "extra.bin").unlink()

    with pytest.raises(RuntimeError, match="converter failed"):
        convert_whisper_bundle(
            spec,
            source_dir=source,
            source_manifest=source_manifest,
            source_manifest_sha256=source_manifest_sha256,
            project_root=tmp_path,
            runner=lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("converter failed")),
        )
    assert not (tmp_path / spec.bundle_relative_path).exists()
