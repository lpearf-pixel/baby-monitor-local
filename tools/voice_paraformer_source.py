from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import tarfile
import tempfile
from pathlib import Path

from packages.contracts.settings import VoiceCareSettings
from services.voice.artifacts import (
    VoiceArtifactSpec,
    validate_voice_source,
    voice_artifact_manifest_sha256_from_digests,
    voice_artifact_spec,
)


ARTIFACT_ID = "sherpa-onnx-paraformer-zh-2023-09-14"
ARCHIVE_SHA256 = "9c49fd9c6fb63de8e18c1054cf3d100f804741b7e608e187923cd8ff09fa9f03"
FILE_SHA256 = {
    "model.int8.onnx": "f36a0433bcf096bd6d6f11b80a3ac8bed110bdca632fe0d731df8d1a84475945",
    "tokens.txt": "59aba8873a2ed1e122c25fee421e25f283b63290efbde85c1f01a853d83cb6e6",
}
SOURCE_RELATIVE = Path("runtime/models/voice-care-sources") / ARTIFACT_ID
SETTINGS_RELATIVE = Path("runtime/config/voice-care-models.json")
SOURCE_ERROR = "VOICE_PARAFORMER_SOURCE_UNAVAILABLE"
_ARCHIVE_PREFIX = f"{ARTIFACT_ID}/"
_MAX_FILE_BYTES = 300 * 1024 * 1024


def materialize_paraformer_source(
    project_root: Path,
    *,
    archive: Path,
    expected_archive_sha256: str = ARCHIVE_SHA256,
    expected_file_sha256: dict[str, str] = FILE_SHA256,
) -> tuple[Path, Path]:
    """Verify and extract only the two pinned public Paraformer model files."""

    try:
        root = project_root.resolve(strict=True)
        if root.is_symlink() or archive.is_symlink() or not archive.is_file():
            raise ValueError(SOURCE_ERROR)
        if _sha256_file(archive) != expected_archive_sha256:
            raise ValueError(SOURCE_ERROR)
        if set(expected_file_sha256) != {"model.int8.onnx", "tokens.txt"}:
            raise ValueError(SOURCE_ERROR)
        artifact_root = _destination(root, SOURCE_RELATIVE)
        source = artifact_root / "source"
        manifest = artifact_root / "source-manifest.json"
        spec = voice_artifact_spec(
            VoiceCareSettings(enabled=False, paraformer_zh_manifest_sha256="0" * 64),
            ARTIFACT_ID,
        )
        if artifact_root.exists():
            _finish_existing(
                root, spec, source, manifest, expected_file_sha256
            )
            return source, manifest

        parent = artifact_root.parent
        parent.mkdir(parents=True, exist_ok=True)
        _reject_symlink_components(root, SOURCE_RELATIVE.parent)
        staging = Path(tempfile.mkdtemp(prefix=".staging-paraformer-", dir=parent))
        staging.chmod(0o700)
        try:
            staged_source = staging / "source"
            staged_source.mkdir(mode=0o700)
            with tarfile.open(archive, "r:bz2") as bundle:
                for filename in spec.source_files:
                    member = bundle.getmember(_ARCHIVE_PREFIX + filename)
                    if not member.isfile() or not 0 < member.size <= _MAX_FILE_BYTES:
                        raise ValueError(SOURCE_ERROR)
                    input_file = bundle.extractfile(member)
                    if input_file is None:
                        raise ValueError(SOURCE_ERROR)
                    target = staged_source / filename
                    digest = _copy_stream(input_file, target)
                    if digest != expected_file_sha256[filename]:
                        raise ValueError(SOURCE_ERROR)
            manifest_bytes = _source_manifest(spec, expected_file_sha256)
            staged_manifest = staging / "source-manifest.json"
            staged_manifest.write_bytes(manifest_bytes)
            staged_manifest.chmod(0o600)
            validate_voice_source(
                spec,
                staged_source,
                staged_manifest,
                hashlib.sha256(manifest_bytes).hexdigest(),
            )
            parent.chmod(0o700)
            staging.rename(artifact_root)
        finally:
            if staging.exists():
                shutil.rmtree(staging)
        _update_settings(root, spec, manifest, expected_file_sha256)
        return source, manifest
    except (KeyError, OSError, tarfile.TarError, ValueError, json.JSONDecodeError):
        raise ValueError(SOURCE_ERROR) from None


def _finish_existing(
    root: Path,
    spec: VoiceArtifactSpec,
    source: Path,
    manifest: Path,
    expected_file_sha256: dict[str, str],
) -> None:
    manifest_bytes = manifest.read_bytes()
    payload = json.loads(manifest_bytes.decode("ascii"))
    if not isinstance(payload, dict) or payload.get("files") != expected_file_sha256:
        raise ValueError(SOURCE_ERROR)
    digest = hashlib.sha256(manifest_bytes).hexdigest()
    validate_voice_source(spec, source, manifest, digest)
    _update_settings(root, spec, manifest, expected_file_sha256)


def _update_settings(
    root: Path,
    spec: VoiceArtifactSpec,
    manifest: Path,
    expected_file_sha256: dict[str, str],
) -> None:
    source_manifest_sha256 = hashlib.sha256(manifest.read_bytes()).hexdigest()
    runtime_digest = voice_artifact_manifest_sha256_from_digests(
        spec, expected_file_sha256, source_manifest_sha256
    )
    settings_path = _destination(root, SETTINGS_RELATIVE)
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
    payload["paraformer_zh_manifest_sha256"] = runtime_digest
    VoiceCareSettings.model_validate(payload)
    data = (json.dumps(payload, sort_keys=True, separators=(",", ":")) + "\n").encode(
        "ascii"
    )
    descriptor, name = tempfile.mkstemp(
        prefix=".voice-care-models-", dir=settings_path.parent
    )
    temporary = Path(name)
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


def _copy_stream(input_file: object, target: Path) -> str:
    hasher = hashlib.sha256()
    total = 0
    with target.open("xb") as output:
        target.chmod(0o600)
        while True:
            chunk = input_file.read(1024 * 1024)  # type: ignore[attr-defined]
            if not chunk:
                break
            total += len(chunk)
            if total > _MAX_FILE_BYTES:
                raise ValueError(SOURCE_ERROR)
            hasher.update(chunk)
            output.write(chunk)
        output.flush()
        os.fsync(output.fileno())
    if not total:
        raise ValueError(SOURCE_ERROR)
    return hasher.hexdigest()


def _source_manifest(spec: VoiceArtifactSpec, digests: dict[str, str]) -> bytes:
    return (
        json.dumps(
            {
                "artifact_id": spec.artifact_id,
                "files": digests,
                "source_revision": spec.source_revision,
                "spdx_license": spec.spdx_license,
                "upstream_project": spec.upstream_project,
            },
            sort_keys=True,
            separators=(",", ":"),
        )
        + "\n"
    ).encode("ascii")


def _destination(root: Path, relative: Path) -> Path:
    _reject_symlink_components(root, relative)
    return root / relative


def _reject_symlink_components(root: Path, relative: Path) -> None:
    current = root
    for component in relative.parts:
        current = current / component
        if current.is_symlink() or (
            current.exists() and not (current.is_dir() or current.is_file())
        ):
            raise ValueError(SOURCE_ERROR)


def _sha256_file(path: Path) -> str:
    hasher = hashlib.sha256()
    with path.open("rb") as input_file:
        for chunk in iter(lambda: input_file.read(1024 * 1024), b""):
            hasher.update(chunk)
    return hasher.hexdigest()


def main() -> int:
    parser = argparse.ArgumentParser(description="Verify the pinned Paraformer archive")
    parser.add_argument("--archive", type=Path, required=True)
    parser.add_argument("--project-root", type=Path, default=Path.cwd())
    arguments = parser.parse_args()
    try:
        materialize_paraformer_source(arguments.project_root, archive=arguments.archive)
    except (OSError, ValueError):
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
