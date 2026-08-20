from __future__ import annotations

import argparse
import shutil
import subprocess
import tempfile
import urllib.request
from pathlib import Path

from packages.contracts.settings import VoiceCareSettings
from services.voice.artifacts import (
    VoiceArtifactSpec,
    validate_voice_artifact,
    validate_voice_artifact_bundle,
    voice_artifact_specs,
    write_canonical_manifest,
)


def install_voice_artifact(
    spec: VoiceArtifactSpec, *, source_bundle: Path, project_root: Path
) -> Path:
    """Atomically install a complete validated bundle at its immutable digest path."""

    root = project_root.resolve(strict=True)
    destination = root / spec.bundle_relative_path
    if destination.exists() or destination.is_symlink():
        return validate_voice_artifact(spec, root)
    _reject_symlink_destination(root, spec.bundle_relative_path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    _reject_symlink_destination(root, spec.bundle_relative_path)
    staging = Path(tempfile.mkdtemp(dir=destination.parent, prefix=".staging-voice-"))
    try:
        staged_bundle = staging / "bundle"
        shutil.copytree(source_bundle, staged_bundle, symlinks=True)
        validate_voice_artifact_bundle(spec, staged_bundle)
        staged_bundle.rename(destination)
        return destination
    finally:
        shutil.rmtree(staging, ignore_errors=True)


def download_and_install_voice_artifact(
    spec: VoiceArtifactSpec, *, project_root: Path
) -> Path:
    """Download only the registry-bound provenance archive on explicit invocation."""

    with tempfile.TemporaryDirectory(prefix="voice-artifact-download-") as temporary:
        archive = Path(temporary) / "source.tar.gz"
        with urllib.request.urlopen(spec.source_url, timeout=60) as response, archive.open(
            "wb"
        ) as target:
            shutil.copyfileobj(response, target)
        unpacked = Path(temporary) / "unpacked"
        shutil.unpack_archive(str(archive), str(unpacked))
        children = tuple(unpacked.iterdir())
        source_bundle = children[0] if len(children) == 1 and children[0].is_dir() else unpacked
        return install_voice_artifact(spec, source_bundle=source_bundle, project_root=project_root)


def convert_whisper_bundle(
    spec: VoiceArtifactSpec, *, source_model: Path, project_root: Path
) -> Path:
    """Explicitly convert a local Whisper source into a complete CTranslate2 bundle."""

    if spec.artifact_id not in {"openai-whisper-base", "openai-whisper-small"}:
        raise ValueError("VOICE_ARTIFACT_INVALID")
    source = source_model.resolve(strict=True)
    if not source.is_dir() or source.is_symlink():
        raise ValueError("VOICE_ARTIFACT_INVALID")
    with tempfile.TemporaryDirectory(prefix="voice-whisper-convert-") as temporary:
        bundle = Path(temporary) / "bundle"
        subprocess.run(
            (
                "ct2-transformers-converter",
                "--model",
                str(source),
                "--output_dir",
                str(bundle),
                "--copy_files",
                "tokenizer.json",
                "vocabulary.txt",
            ),
            check=True,
        )
        write_canonical_manifest(spec, bundle)
        return install_voice_artifact(spec, source_bundle=bundle, project_root=project_root)


def main() -> int:
    parser = argparse.ArgumentParser(description="Install a pinned Voice Care model bundle")
    parser.add_argument("--settings", type=Path, required=True)
    parser.add_argument("--artifact", required=True)
    parser.add_argument("--operation", choices=("source", "download", "convert-whisper"), required=True)
    parser.add_argument("--source", type=Path)
    parser.add_argument("--project-root", type=Path, default=Path.cwd())
    arguments = parser.parse_args()
    settings = VoiceCareSettings.model_validate_json(arguments.settings.read_text("utf-8"))
    specs = {spec.artifact_id: spec for spec in voice_artifact_specs(settings)}
    spec = specs.get(arguments.artifact)
    if spec is None:
        parser.error("unknown Voice Care artifact")
    if arguments.operation == "download":
        download_and_install_voice_artifact(spec, project_root=arguments.project_root)
    elif arguments.operation == "convert-whisper":
        if arguments.source is None:
            parser.error("--source is required for convert-whisper")
        convert_whisper_bundle(spec, source_model=arguments.source, project_root=arguments.project_root)
    else:
        if arguments.source is None:
            parser.error("--source is required for source installation")
        install_voice_artifact(spec, source_bundle=arguments.source, project_root=arguments.project_root)
    return 0


def _reject_symlink_destination(root: Path, relative_path: Path) -> None:
    current = root
    for component in relative_path.parts:
        current = current / component
        if current.is_symlink():
            raise ValueError("VOICE_ARTIFACT_INVALID")


if __name__ == "__main__":
    raise SystemExit(main())
