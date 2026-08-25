from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path

from packages.contracts.settings import VoiceCareSettings


RUNTIME_PREFIX = Path("runtime/models/voice-care")
MANIFEST_NAME = "manifest.json"
VOICE_ARTIFACT_IDS = (
    "silero-vad-v6.2",
    "openai-whisper-base",
    "openai-whisper-small",
    "sherpa-onnx-paraformer-zh-2023-09-14",
    "speechbrain-ecapa-voxceleb",
)


@dataclass(frozen=True)
class _ArtifactDefinition:
    artifact_id: str
    upstream_project: str
    source_revision: str
    spdx_license: str
    acquisition: str
    source_files: tuple[str, ...]
    required_files: tuple[str, ...]


_REGISTRY = (
    _ArtifactDefinition(
        artifact_id="silero-vad-v6.2",
        upstream_project="https://github.com/snakers4/silero-vad",
        source_revision="be95df9152c0d7618fa1edfeb296fc3dae32376f",
        spdx_license="MIT",
        acquisition="collect",
        source_files=("silero_vad.onnx",),
        required_files=("silero_vad.onnx",),
    ),
    _ArtifactDefinition(
        artifact_id="openai-whisper-base",
        upstream_project="https://huggingface.co/openai/whisper-base",
        source_revision="e37978b90ca9030d5170a5c07aadb050351a65bb",
        spdx_license="Apache-2.0",
        acquisition="convert-whisper",
        source_files=(
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
        ),
        required_files=(
            "config.json",
            "model.bin",
            "preprocessor_config.json",
            "tokenizer.json",
            "vocabulary.json",
        ),
    ),
    _ArtifactDefinition(
        artifact_id="openai-whisper-small",
        upstream_project="https://huggingface.co/openai/whisper-small",
        source_revision="973afd24965f72e36ca33b3055d56a652f456b4d",
        spdx_license="Apache-2.0",
        acquisition="convert-whisper",
        source_files=(
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
        ),
        required_files=(
            "config.json",
            "model.bin",
            "preprocessor_config.json",
            "tokenizer.json",
            "vocabulary.json",
        ),
    ),
    _ArtifactDefinition(
        artifact_id="sherpa-onnx-paraformer-zh-2023-09-14",
        upstream_project=(
            "https://huggingface.co/csukuangfj/"
            "sherpa-onnx-paraformer-zh-2023-09-14"
        ),
        source_revision="def027084691107096b5ebba69785756d63de6c5",
        spdx_license="Apache-2.0",
        acquisition="collect",
        source_files=("model.int8.onnx", "tokens.txt"),
        required_files=("model.int8.onnx", "tokens.txt"),
    ),
    _ArtifactDefinition(
        artifact_id="speechbrain-ecapa-voxceleb",
        upstream_project="https://huggingface.co/speechbrain/spkrec-ecapa-voxceleb",
        source_revision="0f99f2d0ebe89ac095bcc5903c4dd8f72b367286",
        spdx_license="Apache-2.0",
        acquisition="collect",
        source_files=(
            "classifier.ckpt",
            "embedding_model.ckpt",
            "hyperparams.yaml",
            "label_encoder.txt",
            "mean_var_norm_emb.ckpt",
        ),
        required_files=(
            "classifier.ckpt",
            "embedding_model.ckpt",
            "hyperparams.yaml",
            "label_encoder.txt",
            "mean_var_norm_emb.ckpt",
        ),
    ),
)
_DEFINITIONS = {definition.artifact_id: definition for definition in _REGISTRY}


@dataclass(frozen=True)
class VoiceArtifactSpec:
    """One immutable local model bundle selected by a canonical manifest digest."""

    artifact_id: str
    upstream_project: str
    source_revision: str
    spdx_license: str
    acquisition: str
    source_files: tuple[str, ...]
    required_files: tuple[str, ...]
    manifest_sha256: str
    bundle_relative_path: Path

    def __post_init__(self) -> None:
        definition = _DEFINITIONS.get(self.artifact_id)
        expected_path = RUNTIME_PREFIX / self.artifact_id / self.manifest_sha256
        if (
            definition is None
            or self.upstream_project != definition.upstream_project
            or self.source_revision != definition.source_revision
            or self.spdx_license != definition.spdx_license
            or self.acquisition != definition.acquisition
            or self.source_files != definition.source_files
            or self.required_files != definition.required_files
            or len(self.source_revision) != 40
            or any(character not in "0123456789abcdef" for character in self.source_revision)
            or not _is_sha256(self.manifest_sha256)
            or self.bundle_relative_path != expected_path
        ):
            raise ValueError("VOICE_ARTIFACT_INVALID")


def voice_artifact_specs(settings: VoiceCareSettings) -> tuple[VoiceArtifactSpec, ...]:
    """Build the closed registry using settings-pinned manifest digests."""

    digests = (
        settings.silero_vad_manifest_sha256,
        settings.whisper_base_manifest_sha256,
        settings.whisper_small_manifest_sha256,
        settings.paraformer_zh_manifest_sha256,
        settings.speechbrain_ecapa_manifest_sha256,
    )
    return tuple(
        _spec_from_definition(definition, _required_digest(digest))
        for definition, digest in zip(_REGISTRY, digests, strict=True)
    )


def voice_artifact_spec(
    settings: VoiceCareSettings, artifact_id: str
) -> VoiceArtifactSpec:
    """Select one closed-registry artifact without requiring unrelated digests."""

    definition = _DEFINITIONS.get(artifact_id)
    digest_field = {
        "silero-vad-v6.2": "silero_vad_manifest_sha256",
        "openai-whisper-base": "whisper_base_manifest_sha256",
        "openai-whisper-small": "whisper_small_manifest_sha256",
        "sherpa-onnx-paraformer-zh-2023-09-14": "paraformer_zh_manifest_sha256",
        "speechbrain-ecapa-voxceleb": "speechbrain_ecapa_manifest_sha256",
    }.get(artifact_id)
    if definition is None or digest_field is None:
        raise ValueError("VOICE_ARTIFACT_INVALID")
    return _spec_from_definition(
        definition, _required_digest(getattr(settings, digest_field))
    )


def voice_artifact_manifest_sha256(
    spec: VoiceArtifactSpec, bundle: Path, source_manifest_sha256: str
) -> str:
    """Derive the runtime manifest identity from a complete local source bundle."""

    return hashlib.sha256(
        _artifact_manifest_bytes(spec, bundle, source_manifest_sha256)
    ).hexdigest()


def voice_artifact_manifest_sha256_from_digests(
    spec: VoiceArtifactSpec,
    file_sha256: dict[str, str],
    source_manifest_sha256: str,
) -> str:
    """Derive one artifact identity from already verified fixed source digests."""

    if (
        not _is_sha256(source_manifest_sha256)
        or set(file_sha256) != set(spec.required_files)
        or any(not _is_sha256(value) for value in file_sha256.values())
    ):
        raise ValueError("VOICE_ARTIFACT_INVALID")
    return hashlib.sha256(
        _canonical_json(
            {
                "artifact_id": spec.artifact_id,
                "files": file_sha256,
                "source_manifest_sha256": source_manifest_sha256,
                "source_revision": spec.source_revision,
                "spdx_license": spec.spdx_license,
            }
        )
    ).hexdigest()


def validate_voice_artifact(spec: VoiceArtifactSpec, project_root: Path) -> Path:
    """Return the absolute validated immutable bundle directory before runner creation."""

    try:
        root = project_root.resolve(strict=True)
        _reject_symlink_components(root, spec.bundle_relative_path)
        bundle = (root / spec.bundle_relative_path).resolve(strict=True)
        if not bundle.is_relative_to(root):
            raise ValueError("VOICE_ARTIFACT_INVALID")
        _validate_bundle(spec, bundle)
    except (OSError, ValueError) as exc:
        if str(exc) == "VOICE_ARTIFACT_INVALID":
            raise
        raise ValueError("VOICE_ARTIFACT_INVALID") from exc
    return bundle


def validate_voice_artifact_bundle(spec: VoiceArtifactSpec, bundle: Path) -> Path:
    """Validate a staged bundle without permitting it to become a runtime destination."""

    try:
        _validate_bundle(spec, bundle)
    except (OSError, ValueError) as exc:
        if str(exc) == "VOICE_ARTIFACT_INVALID":
            raise
        raise ValueError("VOICE_ARTIFACT_INVALID") from exc
    return bundle.resolve(strict=True)


def validate_voice_source(
    spec: VoiceArtifactSpec,
    source_dir: Path,
    source_manifest: Path,
    source_manifest_sha256: str,
) -> Path:
    """Validate immutable source provenance and every fixed conversion input."""

    try:
        if not _is_sha256(source_manifest_sha256):
            raise ValueError("VOICE_ARTIFACT_INVALID")
        if source_dir.is_symlink() or not source_dir.is_dir() or source_manifest.is_symlink():
            raise ValueError("VOICE_ARTIFACT_INVALID")
        manifest_bytes = source_manifest.read_bytes()
        if hashlib.sha256(manifest_bytes).hexdigest() != source_manifest_sha256:
            raise ValueError("VOICE_ARTIFACT_INVALID")
        manifest = json.loads(manifest_bytes.decode("ascii"))
        if not isinstance(manifest, dict) or manifest_bytes != _canonical_json(manifest):
            raise ValueError("VOICE_ARTIFACT_INVALID")
        if (
            set(manifest)
            != {"artifact_id", "files", "source_revision", "spdx_license", "upstream_project"}
            or manifest["artifact_id"] != spec.artifact_id
            or manifest["upstream_project"] != spec.upstream_project
            or manifest["source_revision"] != spec.source_revision
            or manifest["spdx_license"] != spec.spdx_license
            or not isinstance(manifest["files"], dict)
            or set(manifest["files"]) != set(spec.source_files)
        ):
            raise ValueError("VOICE_ARTIFACT_INVALID")
        _validate_exact_files(source_dir, spec.source_files, manifest["files"])
    except (OSError, ValueError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        if str(exc) == "VOICE_ARTIFACT_INVALID":
            raise
        raise ValueError("VOICE_ARTIFACT_INVALID") from exc
    return source_dir.resolve(strict=True)


def write_canonical_manifest(
    spec: VoiceArtifactSpec, bundle: Path, source_manifest_sha256: str
) -> None:
    """Write the canonical manifest after an explicit conversion has created all files."""

    manifest = _artifact_manifest_bytes(spec, bundle, source_manifest_sha256)
    if hashlib.sha256(manifest).hexdigest() != spec.manifest_sha256:
        raise ValueError("VOICE_ARTIFACT_INVALID")
    (bundle / MANIFEST_NAME).write_bytes(manifest)


def _artifact_manifest_bytes(
    spec: VoiceArtifactSpec, bundle: Path, source_manifest_sha256: str
) -> bytes:
    if not _is_sha256(source_manifest_sha256):
        raise ValueError("VOICE_ARTIFACT_INVALID")
    files: dict[str, str] = {}
    actual_files: set[str] = set()
    for entry in bundle.rglob("*"):
        if entry.is_symlink():
            raise ValueError("VOICE_ARTIFACT_INVALID")
        if entry.is_file():
            actual_files.add(entry.relative_to(bundle).as_posix())
        elif not entry.is_dir():
            raise ValueError("VOICE_ARTIFACT_INVALID")
    if actual_files != set(spec.required_files):
        raise ValueError("VOICE_ARTIFACT_INVALID")
    for relative_path in spec.required_files:
        artifact_file = bundle / relative_path
        files[relative_path] = _sha256_file(artifact_file)
    return _canonical_json(
        {
            "artifact_id": spec.artifact_id,
            "files": files,
            "source_manifest_sha256": source_manifest_sha256,
            "source_revision": spec.source_revision,
            "spdx_license": spec.spdx_license,
        }
    )


def _spec_from_definition(
    definition: _ArtifactDefinition, manifest_sha256: str
) -> VoiceArtifactSpec:
    return VoiceArtifactSpec(
        artifact_id=definition.artifact_id,
        upstream_project=definition.upstream_project,
        source_revision=definition.source_revision,
        spdx_license=definition.spdx_license,
        acquisition=definition.acquisition,
        source_files=definition.source_files,
        required_files=definition.required_files,
        manifest_sha256=manifest_sha256,
        bundle_relative_path=RUNTIME_PREFIX / definition.artifact_id / manifest_sha256,
    )


def _validate_bundle(spec: VoiceArtifactSpec, bundle: Path) -> None:
    if bundle.is_symlink() or not bundle.is_dir():
        raise ValueError("VOICE_ARTIFACT_INVALID")
    actual_files: set[str] = set()
    for entry in bundle.rglob("*"):
        if entry.is_symlink():
            raise ValueError("VOICE_ARTIFACT_INVALID")
        if entry.is_file():
            actual_files.add(entry.relative_to(bundle).as_posix())
        elif not entry.is_dir():
            raise ValueError("VOICE_ARTIFACT_INVALID")
    expected_files = {MANIFEST_NAME, *spec.required_files}
    if actual_files != expected_files:
        raise ValueError("VOICE_ARTIFACT_INVALID")
    manifest_path = bundle / MANIFEST_NAME
    manifest_bytes = manifest_path.read_bytes()
    if hashlib.sha256(manifest_bytes).hexdigest() != spec.manifest_sha256:
        raise ValueError("VOICE_ARTIFACT_INVALID")
    try:
        manifest = json.loads(manifest_bytes.decode("ascii"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("VOICE_ARTIFACT_INVALID") from exc
    if not isinstance(manifest, dict) or manifest_bytes != _canonical_json(manifest):
        raise ValueError("VOICE_ARTIFACT_INVALID")
    if (
        set(manifest)
        != {
            "artifact_id",
            "files",
            "source_manifest_sha256",
            "source_revision",
            "spdx_license",
        }
        or manifest["artifact_id"] != spec.artifact_id
        or manifest["source_revision"] != spec.source_revision
        or manifest["spdx_license"] != spec.spdx_license
        or not isinstance(manifest["source_manifest_sha256"], str)
        or not _is_sha256(manifest["source_manifest_sha256"])
        or not isinstance(manifest["files"], dict)
        or set(manifest["files"]) != set(spec.required_files)
    ):
        raise ValueError("VOICE_ARTIFACT_INVALID")
    for relative_path in spec.required_files:
        expected = manifest["files"][relative_path]
        artifact_file = bundle / relative_path
        if not isinstance(expected, str) or not _is_sha256(expected):
            raise ValueError("VOICE_ARTIFACT_INVALID")
        if _sha256_file(artifact_file) != expected:
            raise ValueError("VOICE_ARTIFACT_INVALID")


def _validate_exact_files(
    root: Path, required_files: tuple[str, ...], digests: object
) -> None:
    if not isinstance(digests, dict):
        raise ValueError("VOICE_ARTIFACT_INVALID")
    actual_files: set[str] = set()
    for entry in root.rglob("*"):
        if entry.is_symlink():
            raise ValueError("VOICE_ARTIFACT_INVALID")
        if entry.is_file():
            actual_files.add(entry.relative_to(root).as_posix())
        elif not entry.is_dir():
            raise ValueError("VOICE_ARTIFACT_INVALID")
    if actual_files != set(required_files) or set(digests) != set(required_files):
        raise ValueError("VOICE_ARTIFACT_INVALID")
    for relative_path in required_files:
        expected = digests[relative_path]
        if not isinstance(expected, str) or not _is_sha256(expected):
            raise ValueError("VOICE_ARTIFACT_INVALID")
        if _sha256_file(root / relative_path) != expected:
            raise ValueError("VOICE_ARTIFACT_INVALID")


def _required_digest(digest: str | None) -> str:
    if digest is None:
        raise ValueError("VOICE_ARTIFACT_DIGEST_REQUIRED")
    return digest


def _reject_symlink_components(root: Path, relative_path: Path) -> None:
    current = root
    for component in relative_path.parts:
        current = current / component
        if current.is_symlink():
            raise ValueError("VOICE_ARTIFACT_INVALID")


def _is_sha256(value: str) -> bool:
    return len(value) == 64 and all(character in "0123456789abcdef" for character in value)


def _sha256_file(path: Path) -> str:
    hasher = hashlib.sha256()
    with path.open("rb") as artifact_file:
        for chunk in iter(lambda: artifact_file.read(1024 * 1024), b""):
            hasher.update(chunk)
    return hasher.hexdigest()


def _canonical_json(value: object) -> bytes:
    return (json.dumps(value, separators=(",", ":"), sort_keys=True) + "\n").encode(
        "ascii"
    )
