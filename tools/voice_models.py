from __future__ import annotations

import argparse
import shutil
import subprocess
import tempfile
from collections.abc import Callable
from pathlib import Path

from packages.contracts.settings import VoiceCareSettings
from services.voice.artifacts import (
    VoiceArtifactSpec,
    validate_voice_artifact,
    validate_voice_artifact_bundle,
    validate_voice_source,
    voice_artifact_specs,
    write_canonical_manifest,
)


Runner = Callable[..., object]


def collect_voice_artifact(
    spec: VoiceArtifactSpec,
    *,
    source_dir: Path,
    source_manifest: Path,
    source_manifest_sha256: str,
    project_root: Path,
) -> Path:
    """Collect a registry-fixed source set into its runtime bundle without network I/O."""

    if spec.acquisition != "collect":
        raise ValueError("VOICE_ARTIFACT_INVALID")
    source = validate_voice_source(
        spec, source_dir, source_manifest, source_manifest_sha256
    )
    with tempfile.TemporaryDirectory(prefix="voice-collect-") as temporary:
        bundle = Path(temporary) / "bundle"
        bundle.mkdir()
        for relative_path in spec.required_files:
            shutil.copyfile(source / relative_path, bundle / relative_path)
        write_canonical_manifest(spec, bundle, source_manifest_sha256)
        return install_voice_artifact(spec, source_bundle=bundle, project_root=project_root)


def convert_whisper_bundle(
    spec: VoiceArtifactSpec,
    *,
    source_dir: Path,
    source_manifest: Path,
    source_manifest_sha256: str,
    project_root: Path,
    runner: Runner = subprocess.run,
) -> Path:
    """Explicitly convert only a verified Whisper source into a CTranslate2 bundle."""

    if spec.acquisition != "convert-whisper":
        raise ValueError("VOICE_ARTIFACT_INVALID")
    source = validate_voice_source(
        spec, source_dir, source_manifest, source_manifest_sha256
    )
    with tempfile.TemporaryDirectory(prefix="voice-whisper-convert-") as temporary:
        bundle = Path(temporary) / "bundle"
        runner(
            (
                "ct2-transformers-converter",
                "--model",
                str(source),
                "--output_dir",
                str(bundle),
                "--copy_files",
                "tokenizer.json",
                "preprocessor_config.json",
            ),
            check=True,
        )
        write_canonical_manifest(spec, bundle, source_manifest_sha256)
        return install_voice_artifact(spec, source_bundle=bundle, project_root=project_root)


def acquire_voice_artifact(
    spec: VoiceArtifactSpec,
    *,
    source_dir: Path,
    source_manifest: Path,
    source_manifest_sha256: str,
    project_root: Path,
) -> Path:
    """Run the only registry-authorized acquisition path for one artifact."""

    if spec.acquisition == "collect":
        return collect_voice_artifact(
            spec,
            source_dir=source_dir,
            source_manifest=source_manifest,
            source_manifest_sha256=source_manifest_sha256,
            project_root=project_root,
        )
    return convert_whisper_bundle(
        spec,
        source_dir=source_dir,
        source_manifest=source_manifest,
        source_manifest_sha256=source_manifest_sha256,
        project_root=project_root,
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


def main() -> int:
    parser = argparse.ArgumentParser(description="Acquire a pinned Voice Care model bundle")
    parser.add_argument("--settings", type=Path, required=True)
    parser.add_argument("--artifact", required=True)
    parser.add_argument("--operation", choices=("acquire", "convert-whisper"), required=True)
    parser.add_argument("--source-dir", type=Path, required=True)
    parser.add_argument("--source-manifest", type=Path, required=True)
    parser.add_argument("--source-manifest-sha256", required=True)
    parser.add_argument("--project-root", type=Path, default=Path.cwd())
    arguments = parser.parse_args()
    settings = VoiceCareSettings.model_validate_json(arguments.settings.read_text("utf-8"))
    specs = {spec.artifact_id: spec for spec in voice_artifact_specs(settings)}
    spec = specs.get(arguments.artifact)
    if spec is None:
        parser.error("unknown Voice Care artifact")
    if arguments.operation == "convert-whisper" and spec.acquisition != "convert-whisper":
        parser.error("convert-whisper is only valid for Whisper artifacts")
    if arguments.operation == "acquire":
        acquire_voice_artifact(
            spec,
            source_dir=arguments.source_dir,
            source_manifest=arguments.source_manifest,
            source_manifest_sha256=arguments.source_manifest_sha256,
            project_root=arguments.project_root,
        )
    else:
        convert_whisper_bundle(
            spec,
            source_dir=arguments.source_dir,
            source_manifest=arguments.source_manifest,
            source_manifest_sha256=arguments.source_manifest_sha256,
            project_root=arguments.project_root,
        )
    return 0


def _reject_symlink_destination(root: Path, relative_path: Path) -> None:
    current = root
    for component in relative_path.parts:
        current = current / component
        if current.is_symlink():
            raise ValueError("VOICE_ARTIFACT_INVALID")


if __name__ == "__main__":
    raise SystemExit(main())
