from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from services.voice.artifacts import VoiceArtifactSpec, validate_voice_artifact
from tools.voice_models import install_voice_artifact


def spec_for(path: Path, payload: bytes) -> VoiceArtifactSpec:
    return VoiceArtifactSpec(
        artifact_id="test-artifact",
        runtime_path=path,
        upstream_project="https://example.invalid/test-artifact",
        source_revision="0123456789abcdef",
        spdx_license="MIT",
        sha256=hashlib.sha256(payload).hexdigest(),
    )


def test_valid_artifact_returns_absolute_contained_path(tmp_path: Path) -> None:
    artifact = tmp_path / "runtime" / "models" / "artifact.bin"
    artifact.parent.mkdir(parents=True)
    payload = b"synthetic voice model"
    artifact.write_bytes(payload)

    result = validate_voice_artifact(
        spec_for(Path("runtime/models/artifact.bin"), payload), tmp_path
    )

    assert result == artifact.resolve()
    assert result.is_absolute()


def test_artifact_digest_mismatch_fails_before_runner_creation(tmp_path: Path) -> None:
    artifact = tmp_path / "runtime" / "models" / "artifact.bin"
    artifact.parent.mkdir(parents=True)
    artifact.write_bytes(b"unexpected")

    with pytest.raises(ValueError, match="VOICE_ARTIFACT_INVALID"):
        validate_voice_artifact(
            spec_for(Path("runtime/models/artifact.bin"), b"expected"), tmp_path
        )


def test_artifact_symlink_is_rejected_even_when_target_is_inside_root(tmp_path: Path) -> None:
    target = tmp_path / "runtime" / "models" / "target.bin"
    target.parent.mkdir(parents=True)
    payload = b"synthetic voice model"
    target.write_bytes(payload)
    linked = tmp_path / "runtime" / "models" / "artifact.bin"
    linked.symlink_to(target)

    with pytest.raises(ValueError, match="VOICE_ARTIFACT_INVALID"):
        validate_voice_artifact(
            spec_for(Path("runtime/models/artifact.bin"), payload), tmp_path
        )


def test_artifact_path_must_be_relative_and_contained(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="VOICE_ARTIFACT_INVALID"):
        validate_voice_artifact(spec_for(Path("../artifact.bin"), b"expected"), tmp_path)


def test_explicit_installer_validates_before_atomic_local_placement(
    tmp_path: Path,
) -> None:
    source = tmp_path / "source.bin"
    payload = b"synthetic voice model"
    source.write_bytes(payload)

    installed = install_voice_artifact(
        spec_for(Path("runtime/models/artifact.bin"), payload),
        source=source,
        project_root=tmp_path,
    )

    assert installed == tmp_path / "runtime" / "models" / "artifact.bin"
    assert installed.read_bytes() == payload


def test_explicit_installer_rejects_symlinked_destination_before_write(
    tmp_path: Path,
) -> None:
    source = tmp_path / "source.bin"
    payload = b"synthetic voice model"
    source.write_bytes(payload)
    outside = tmp_path.parent / "outside-runtime"
    outside.mkdir()
    (tmp_path / "runtime").symlink_to(outside, target_is_directory=True)

    with pytest.raises(ValueError, match="VOICE_ARTIFACT_INVALID"):
        install_voice_artifact(
            spec_for(Path("runtime/models/artifact.bin"), payload),
            source=source,
            project_root=tmp_path,
        )

    assert not (outside / "models" / "artifact.bin").exists()
