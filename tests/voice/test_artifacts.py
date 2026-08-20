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
    voice_artifact_specs,
)
from tools.voice_models import install_voice_artifact


def canonical_manifest(spec: VoiceArtifactSpec, files: dict[str, bytes]) -> bytes:
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


def spec_and_files(artifact_id: str, payload: bytes = b"synthetic voice model") -> tuple[VoiceArtifactSpec, dict[str, bytes]]:
    provisional = next(
        spec
        for spec in voice_artifact_specs(settings_for_manifest(artifact_id, "0" * 64))
        if spec.artifact_id == artifact_id
    )
    files = {name: payload + name.encode("ascii") for name in provisional.required_files}
    manifest = canonical_manifest(provisional, files)
    manifest_sha256 = hashlib.sha256(manifest).hexdigest()
    spec = next(
        candidate
        for candidate in voice_artifact_specs(settings_for_manifest(artifact_id, manifest_sha256))
        if candidate.artifact_id == artifact_id
    )
    return spec, files


def write_bundle(path: Path, spec: VoiceArtifactSpec, files: dict[str, bytes]) -> None:
    path.mkdir(parents=True, exist_ok=True)
    for name, payload in files.items():
        target = path / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(payload)
    (path / "manifest.json").write_bytes(canonical_manifest(spec, files))


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
    assert specs[1].source_revision == "31243bad24cc746f07d4c8bfdd2d974872cb1803"
    assert specs[2].source_revision == "31243bad24cc746f07d4c8bfdd2d974872cb1803"
    assert specs[3].source_revision == "0f99f2d0ebe89ac095bcc5903c4dd8f72b367286"
    assert all(len(spec.source_revision) == 40 for spec in specs)
    assert all(spec.spdx_license in {"MIT", "Apache-2.0"} for spec in specs)
    assert all(
        spec.bundle_relative_path
        == Path("runtime/models/voice-care") / spec.artifact_id / spec.manifest_sha256
        for spec in specs
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
