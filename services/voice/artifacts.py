from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path

from packages.contracts.settings import VoiceCareSettings


VOICE_ARTIFACT_IDS = (
    "silero-vad-v6.2",
    "openai-whisper-base",
    "openai-whisper-small",
    "speechbrain-ecapa-voxceleb",
)


@dataclass(frozen=True)
class VoiceArtifactSpec:
    """One pinned local artifact, never a network model reference."""

    artifact_id: str
    runtime_path: Path
    upstream_project: str
    source_revision: str
    spdx_license: str
    sha256: str

    def __post_init__(self) -> None:
        if (
            self.runtime_path.is_absolute()
            or ".." in self.runtime_path.parts
            or not self.runtime_path.parts
            or not self.upstream_project.startswith("https://")
            or not self.source_revision
            or not self.spdx_license
            or len(self.sha256) != 64
            or any(character not in "0123456789abcdef" for character in self.sha256)
        ):
            raise ValueError("VOICE_ARTIFACT_INVALID")


def voice_artifact_specs(settings: VoiceCareSettings) -> tuple[VoiceArtifactSpec, ...]:
    """Build the only supported local artifact registry from pinned settings digests."""

    return (
        VoiceArtifactSpec(
            artifact_id="silero-vad-v6.2",
            runtime_path=Path("runtime/models/voice-care/silero-vad-v6.2/silero_vad.onnx"),
            upstream_project="https://github.com/snakers4/silero-vad",
            source_revision="v6.2",
            spdx_license="MIT",
            sha256=_required_digest(settings.silero_vad_sha256),
        ),
        VoiceArtifactSpec(
            artifact_id="openai-whisper-base",
            runtime_path=Path("runtime/models/voice-care/openai-whisper-base/model.bin"),
            upstream_project="https://github.com/openai/whisper",
            source_revision="v20250625",
            spdx_license="MIT",
            sha256=_required_digest(settings.whisper_base_sha256),
        ),
        VoiceArtifactSpec(
            artifact_id="openai-whisper-small",
            runtime_path=Path("runtime/models/voice-care/openai-whisper-small/model.bin"),
            upstream_project="https://github.com/openai/whisper",
            source_revision="v20250625",
            spdx_license="MIT",
            sha256=_required_digest(settings.whisper_small_sha256),
        ),
        VoiceArtifactSpec(
            artifact_id="speechbrain-ecapa-voxceleb",
            runtime_path=Path(
                "runtime/models/voice-care/speechbrain-ecapa-voxceleb/embedding_model.ckpt"
            ),
            upstream_project="https://huggingface.co/speechbrain/spkrec-ecapa-voxceleb",
            source_revision="aa018d",
            spdx_license="Apache-2.0",
            sha256=_required_digest(settings.speechbrain_ecapa_sha256),
        ),
    )


def validate_voice_artifact(spec: VoiceArtifactSpec, project_root: Path) -> Path:
    """Return an absolute validated artifact path without starting any runtime."""

    try:
        root = project_root.resolve(strict=True)
        _reject_symlink_components(root, spec.runtime_path)
        artifact = (root / spec.runtime_path).resolve(strict=True)
        if not artifact.is_relative_to(root) or not artifact.is_file():
            raise ValueError("VOICE_ARTIFACT_INVALID")
        if _sha256_file(artifact) != spec.sha256:
            raise ValueError("VOICE_ARTIFACT_INVALID")
    except (OSError, ValueError) as exc:
        if str(exc) == "VOICE_ARTIFACT_INVALID":
            raise
        raise ValueError("VOICE_ARTIFACT_INVALID") from exc
    return artifact


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


def _sha256_file(path: Path) -> str:
    hasher = hashlib.sha256()
    with path.open("rb") as artifact_file:
        for chunk in iter(lambda: artifact_file.read(1024 * 1024), b""):
            hasher.update(chunk)
    return hasher.hexdigest()
