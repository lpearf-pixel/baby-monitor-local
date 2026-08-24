from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import tempfile
from collections.abc import Callable
from pathlib import Path

from packages.contracts.settings import VoiceCareSettings
from services.voice.artifacts import (
    VoiceArtifactSpec,
    validate_voice_source,
    voice_artifact_manifest_sha256,
    voice_artifact_spec,
)


ARTIFACT_ID = "speechbrain-ecapa-voxceleb"
REPOSITORY_ID = "speechbrain/spkrec-ecapa-voxceleb"
SOURCE_RELATIVE = Path("runtime/models/voice-care-sources") / ARTIFACT_ID
SETTINGS_RELATIVE = Path("runtime/config/voice-care-models.json")
SOURCE_ERROR = "VOICE_ECAPA_SOURCE_UNAVAILABLE"
MAX_FILE_BYTES = 500 * 1024 * 1024
Fetch = Callable[..., str]


def materialize_ecapa_source(
    project_root: Path,
    *,
    fetch: Fetch,
    max_file_bytes: int = MAX_FILE_BYTES,
) -> tuple[Path, Path]:
    """Explicitly acquire the one registry-pinned ECAPA source into private storage."""

    try:
        root = project_root.resolve(strict=True)
        if root.is_symlink() or max_file_bytes < 1:
            raise ValueError(SOURCE_ERROR)
        artifact_root = _private_destination(root, SOURCE_RELATIVE)
        source = artifact_root / "source"
        manifest = artifact_root / "source-manifest.json"
        provisional = voice_artifact_spec(
            VoiceCareSettings(
                enabled=False, speechbrain_ecapa_manifest_sha256="0" * 64
            ),
            ARTIFACT_ID,
        )
        if artifact_root.exists():
            _finish_existing_source(root, provisional, source, manifest)
            return source, manifest

        parent = artifact_root.parent
        parent.mkdir(parents=True, exist_ok=True)
        _reject_symlink_components(root, SOURCE_RELATIVE.parent)
        staging = Path(tempfile.mkdtemp(prefix=".staging-ecapa-", dir=parent))
        staging.chmod(0o700)
        try:
            staged_source = staging / "source"
            staged_source.mkdir(mode=0o700)
            digests: dict[str, str] = {}
            for filename in provisional.source_files:
                cache_path = Path(
                    fetch(
                        repo_id=REPOSITORY_ID,
                        revision=provisional.source_revision,
                        filename=filename,
                    )
                ).resolve(strict=True)
                if not cache_path.is_file():
                    raise ValueError(SOURCE_ERROR)
                target = staged_source / filename
                digests[filename] = _copy_private(
                    cache_path, target, max_file_bytes=max_file_bytes
                )
            manifest_bytes = _source_manifest(provisional, digests)
            staged_manifest = staging / "source-manifest.json"
            staged_manifest.write_bytes(manifest_bytes)
            staged_manifest.chmod(0o600)
            manifest_sha256 = hashlib.sha256(manifest_bytes).hexdigest()
            validate_voice_source(
                provisional,
                staged_source,
                staged_manifest,
                manifest_sha256,
            )
            artifact_root.parent.chmod(0o700)
            staging.rename(artifact_root)
        finally:
            if staging.exists():
                shutil.rmtree(staging)

        _update_settings(root, provisional, source, manifest)
        return source, manifest
    except (OSError, UnicodeDecodeError, ValueError, json.JSONDecodeError):
        raise ValueError(SOURCE_ERROR) from None


def _finish_existing_source(
    root: Path, spec: VoiceArtifactSpec, source: Path, manifest: Path
) -> None:
    manifest_bytes = manifest.read_bytes()
    manifest_sha256 = hashlib.sha256(manifest_bytes).hexdigest()
    validate_voice_source(spec, source, manifest, manifest_sha256)
    _update_settings(root, spec, source, manifest)


def _update_settings(
    root: Path, spec: VoiceArtifactSpec, source: Path, manifest: Path
) -> None:
    manifest_sha256 = hashlib.sha256(manifest.read_bytes()).hexdigest()
    runtime_digest = voice_artifact_manifest_sha256(
        spec, source, manifest_sha256
    )
    settings_path = _private_destination(root, SETTINGS_RELATIVE)
    settings_path.parent.mkdir(parents=True, exist_ok=True)
    _reject_symlink_components(root, SETTINGS_RELATIVE.parent)
    if settings_path.exists():
        if settings_path.is_symlink() or not settings_path.is_file():
            raise ValueError(SOURCE_ERROR)
        payload = json.loads(settings_path.read_text(encoding="ascii"))
    else:
        payload = {"enabled": False}
    current = VoiceCareSettings.model_validate(payload)
    if current.enabled:
        raise ValueError(SOURCE_ERROR)
    payload["speechbrain_ecapa_manifest_sha256"] = runtime_digest
    VoiceCareSettings.model_validate(payload)
    data = (json.dumps(payload, sort_keys=True, separators=(",", ":")) + "\n").encode(
        "ascii"
    )
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=".voice-care-models-", dir=settings_path.parent
    )
    temporary = Path(temporary_name)
    try:
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "wb") as output:
            output.write(data)
            output.flush()
            os.fsync(output.fileno())
        os.replace(temporary, settings_path)
    finally:
        if temporary.exists():
            temporary.unlink()


def _copy_private(source: Path, target: Path, *, max_file_bytes: int) -> str:
    hasher = hashlib.sha256()
    total = 0
    with source.open("rb") as input_file, target.open("xb") as output_file:
        target.chmod(0o600)
        for chunk in iter(lambda: input_file.read(1024 * 1024), b""):
            total += len(chunk)
            if total > max_file_bytes:
                raise ValueError(SOURCE_ERROR)
            hasher.update(chunk)
            output_file.write(chunk)
        output_file.flush()
        os.fsync(output_file.fileno())
    if total == 0:
        raise ValueError(SOURCE_ERROR)
    return hasher.hexdigest()


def _source_manifest(spec: VoiceArtifactSpec, digests: dict[str, str]) -> bytes:
    payload = {
        "artifact_id": spec.artifact_id,
        "files": digests,
        "source_revision": spec.source_revision,
        "spdx_license": spec.spdx_license,
        "upstream_project": spec.upstream_project,
    }
    return (json.dumps(payload, sort_keys=True, separators=(",", ":")) + "\n").encode(
        "ascii"
    )


def _private_destination(root: Path, relative: Path) -> Path:
    _reject_symlink_components(root, relative)
    return root / relative


def _reject_symlink_components(root: Path, relative: Path) -> None:
    current = root
    for component in relative.parts:
        current = current / component
        if current.is_symlink() or (current.exists() and not (current.is_dir() or current.is_file())):
            raise ValueError(SOURCE_ERROR)


def main() -> int:
    parser = argparse.ArgumentParser(description="Acquire the pinned local ECAPA source")
    parser.add_argument("--project-root", type=Path, default=Path.cwd())
    arguments = parser.parse_args()
    try:
        from huggingface_hub import hf_hub_download

        materialize_ecapa_source(arguments.project_root, fetch=hf_hub_download)
    except (ImportError, OSError, ValueError):
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
