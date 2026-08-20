from __future__ import annotations

import argparse
import hashlib
import os
import shutil
import tempfile
import urllib.request
from pathlib import Path

from packages.contracts.settings import VoiceCareSettings
from services.voice.artifacts import VoiceArtifactSpec, validate_voice_artifact, voice_artifact_specs


def install_voice_artifact(
    spec: VoiceArtifactSpec, *, source: Path, project_root: Path
) -> Path:
    """Atomically place one explicitly supplied artifact after local validation."""

    if source.is_symlink() or not source.is_file() or _sha256_file(source) != spec.sha256:
        raise ValueError("VOICE_ARTIFACT_INVALID")
    root = project_root.resolve(strict=True)
    _reject_symlink_destination(root, spec.runtime_path)
    destination = root / spec.runtime_path
    if spec.runtime_path.is_absolute() or ".." in spec.runtime_path.parts:
        raise ValueError("VOICE_ARTIFACT_INVALID")
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        dir=destination.parent, delete=False, prefix=".voice-artifact-"
    ) as staged_file:
        staged = Path(staged_file.name)
        with source.open("rb") as source_file:
            shutil.copyfileobj(source_file, staged_file)
    try:
        if _sha256_file(staged) != spec.sha256:
            raise ValueError("VOICE_ARTIFACT_INVALID")
        os.replace(staged, destination)
        return validate_voice_artifact(spec, root)
    except Exception:
        staged.unlink(missing_ok=True)
        raise


def download_and_install_voice_artifact(
    spec: VoiceArtifactSpec, *, source_url: str, project_root: Path
) -> Path:
    """Download only on direct installer invocation, then validate before placement."""

    if not source_url.startswith("https://"):
        raise ValueError("VOICE_ARTIFACT_INVALID")
    with tempfile.TemporaryDirectory(prefix="voice-artifact-") as temporary_directory:
        source = Path(temporary_directory) / "download"
        with urllib.request.urlopen(source_url, timeout=60) as response, source.open(
            "wb"
        ) as target:
            shutil.copyfileobj(response, target)
        return install_voice_artifact(spec, source=source, project_root=project_root)


def main() -> int:
    parser = argparse.ArgumentParser(description="Install one pinned Voice Care artifact")
    parser.add_argument("--settings", type=Path, required=True)
    parser.add_argument("--artifact", required=True)
    source_group = parser.add_mutually_exclusive_group(required=True)
    source_group.add_argument("--source", type=Path)
    source_group.add_argument("--download-url")
    parser.add_argument("--project-root", type=Path, default=Path.cwd())
    arguments = parser.parse_args()
    settings = VoiceCareSettings.model_validate_json(arguments.settings.read_text("utf-8"))
    specs = {spec.artifact_id: spec for spec in voice_artifact_specs(settings)}
    spec = specs.get(arguments.artifact)
    if spec is None:
        parser.error("unknown Voice Care artifact")
    if arguments.source is not None:
        install_voice_artifact(spec, source=arguments.source, project_root=arguments.project_root)
    else:
        download_and_install_voice_artifact(
            spec, source_url=arguments.download_url, project_root=arguments.project_root
        )
    return 0


def _sha256_file(path: Path) -> str:
    hasher = hashlib.sha256()
    with path.open("rb") as artifact_file:
        for chunk in iter(lambda: artifact_file.read(1024 * 1024), b""):
            hasher.update(chunk)
    return hasher.hexdigest()


def _reject_symlink_destination(root: Path, runtime_path: Path) -> None:
    current = root
    for component in runtime_path.parts:
        current = current / component
        if current.is_symlink():
            raise ValueError("VOICE_ARTIFACT_INVALID")


if __name__ == "__main__":
    raise SystemExit(main())
