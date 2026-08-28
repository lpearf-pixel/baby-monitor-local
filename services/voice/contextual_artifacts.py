from __future__ import annotations

import hashlib
import json
import os
import stat
from dataclasses import dataclass
from pathlib import Path, PurePosixPath


INVALID = "VOICE_CONTEXTUAL_ARTIFACT_INVALID"
CONTEXTUAL_MANIFEST_NAME = "manifest.json"
_RUNTIME_PREFIX = Path("runtime/models/voice-contextual")


def _is_sha256(value: object) -> bool:
    return isinstance(value, str) and len(value) == 64 and all(
        character in "0123456789abcdef" for character in value
    )


def _is_revision(value: object) -> bool:
    return isinstance(value, str) and len(value) == 40 and all(
        character in "0123456789abcdef" for character in value
    )


@dataclass(frozen=True, slots=True)
class ContextualFile:
    path: str
    size: int
    sha256: str

    def __post_init__(self) -> None:
        path = PurePosixPath(self.path)
        if (
            not self.path
            or path.is_absolute()
            or len(path.parts) != 1
            or path.name in {"", ".", "..", CONTEXTUAL_MANIFEST_NAME}
            or type(self.size) is not int
            or self.size <= 0
            or not _is_sha256(self.sha256)
        ):
            raise ValueError(INVALID)


@dataclass(frozen=True, slots=True)
class ContextualArtifact:
    artifact_id: str
    upstream_project: str
    upstream_revision: str
    model_license: str
    runtime_project: str
    runtime_revision: str
    runtime_version: str
    runtime_license: str
    files: tuple[ContextualFile, ...]

    def __post_init__(self) -> None:
        names = tuple(item.path for item in self.files)
        if (
            self.artifact_id != "funasr-contextual-paraformer-zh-int8"
            or self.upstream_project
            != (
                "https://www.modelscope.cn/iic/"
                "speech_paraformer-large-contextual_asr_nat-zh-cn-16k-"
                "common-vocab8404-onnx"
            )
            or not _is_revision(self.upstream_revision)
            or self.model_license != "Apache-2.0"
            or self.runtime_project != "https://github.com/modelscope/FunASR"
            or not _is_revision(self.runtime_revision)
            or self.runtime_version != "0.4.2"
            or self.runtime_license != "MIT"
            or not self.files
            or names != tuple(sorted(names))
            or len(set(names)) != len(names)
        ):
            raise ValueError(INVALID)


CONTEXTUAL_ARTIFACT = ContextualArtifact(
    artifact_id="funasr-contextual-paraformer-zh-int8",
    upstream_project=(
        "https://www.modelscope.cn/iic/"
        "speech_paraformer-large-contextual_asr_nat-zh-cn-16k-common-vocab8404-onnx"
    ),
    upstream_revision="8f0881c891ceba7360e215b04e54cad564a68c41",
    model_license="Apache-2.0",
    runtime_project="https://github.com/modelscope/FunASR",
    runtime_revision="67d6d880841e0c8f3a33e0f98d3bfc2122e34eff",
    runtime_version="0.4.2",
    runtime_license="MIT",
    files=(
        ContextualFile(
            "am.mvn",
            11_203,
            "29b3c740a2c0cfc6b308126d31d7f265fa2be74f3bb095cd2f143ea970896ae5",
        ),
        ContextualFile(
            "config.yaml",
            2_532,
            "1d9057edeaba9e131cb98f26011606497cf3af187d8943525ddb5ee36c836b1b",
        ),
        ContextualFile(
            "model_eb.onnx",
            25_618_359,
            "d31446a5af664291a2922cca253a4200a523f347d6fc3cb1bff356bf60a116b6",
        ),
        ContextualFile(
            "model_quant.onnx",
            871_251_660,
            "f404e6eb532b54fd95761e2b4be4ed1998e8cff3cb3b930a9bee1f2d556e5035",
        ),
        ContextualFile(
            "seg_dict",
            8_287_834,
            "59a2ef803a3f1648ad03a2e1480db1c1ee0c0d7dc4ef4dbd16cea33944329022",
        ),
        ContextualFile(
            "tokens.json",
            93_676,
            "2b20c2b12572d682afff84ce1c8d560f67b8b32a4c1f21567411d141ed352127",
        ),
    ),
)


def build_contextual_manifest(spec: ContextualArtifact = CONTEXTUAL_ARTIFACT) -> bytes:
    payload = {
        "artifact_id": spec.artifact_id,
        "files": {
            item.path: {"sha256": item.sha256, "size": item.size}
            for item in spec.files
        },
        "model_license": spec.model_license,
        "runtime_license": spec.runtime_license,
        "runtime_project": spec.runtime_project,
        "runtime_revision": spec.runtime_revision,
        "runtime_version": spec.runtime_version,
        "schema_version": 1,
        "upstream_project": spec.upstream_project,
        "upstream_revision": spec.upstream_revision,
    }
    return (
        json.dumps(payload, ensure_ascii=True, separators=(",", ":"), sort_keys=True)
        + "\n"
    ).encode("ascii")


CONTEXTUAL_BUNDLE_DIGEST = hashlib.sha256(build_contextual_manifest()).hexdigest()


def contextual_bundle_relative_path(
    manifest_sha256: str = CONTEXTUAL_BUNDLE_DIGEST,
) -> Path:
    if not _is_sha256(manifest_sha256):
        raise ValueError(INVALID)
    return _RUNTIME_PREFIX / CONTEXTUAL_ARTIFACT.artifact_id / manifest_sha256


def validate_contextual_bundle(
    project_root: Path,
    *,
    spec: ContextualArtifact = CONTEXTUAL_ARTIFACT,
) -> Path:
    """Validate the exact private bundle without following mutable leaf identities."""

    try:
        root = Path(project_root)
        if root.is_symlink() or not root.is_dir():
            raise ValueError(INVALID)
        root = root.resolve(strict=True)
        manifest = build_contextual_manifest(spec)
        digest = hashlib.sha256(manifest).hexdigest()
        relative = _RUNTIME_PREFIX / spec.artifact_id / digest
        _reject_symlink_components(root, relative)
        bundle = root / relative
        _validate_bundle_at(bundle, spec, manifest)
        final = bundle.resolve(strict=True)
        if not final.is_relative_to(root):
            raise ValueError(INVALID)
        return final
    except (OSError, TypeError, ValueError) as exc:
        if str(exc) == INVALID:
            raise
        raise ValueError(INVALID) from None


def validate_contextual_bundle_candidate(
    project_root: Path,
    candidate: Path,
    *,
    spec: ContextualArtifact = CONTEXTUAL_ARTIFACT,
) -> Path:
    """Validate one unpublished private staging directory below the fixed parent."""

    try:
        root = Path(project_root).resolve(strict=True)
        parent = (
            root / _RUNTIME_PREFIX / spec.artifact_id
        ).resolve(strict=True)
        candidate = Path(candidate)
        if (
            candidate.parent.resolve(strict=True) != parent
            or not candidate.name.startswith(".staging-")
            or candidate.is_symlink()
        ):
            raise ValueError(INVALID)
        manifest = build_contextual_manifest(spec)
        _validate_bundle_at(candidate, spec, manifest)
        return candidate.resolve(strict=True)
    except (OSError, TypeError, ValueError) as exc:
        if str(exc) == INVALID:
            raise
        raise ValueError(INVALID) from None


def _validate_bundle_at(
    bundle: Path, spec: ContextualArtifact, manifest: bytes
) -> None:
    bundle_info = bundle.lstat()
    if (
        not stat.S_ISDIR(bundle_info.st_mode)
        or stat.S_IMODE(bundle_info.st_mode) != 0o700
        or bundle_info.st_uid != os.getuid()
    ):
        raise ValueError(INVALID)
    expected_names = {item.path for item in spec.files} | {
        CONTEXTUAL_MANIFEST_NAME
    }
    with os.scandir(bundle) as entries:
        actual_names = {entry.name for entry in entries}
    if actual_names != expected_names:
        raise ValueError(INVALID)
    _validate_file(bundle / CONTEXTUAL_MANIFEST_NAME, manifest)
    for item in spec.files:
        _validate_file(
            bundle / item.path,
            None,
            expected_size=item.size,
            expected_sha256=item.sha256,
        )


def _validate_file(
    path: Path,
    expected_bytes: bytes | None,
    *,
    expected_size: int | None = None,
    expected_sha256: str | None = None,
) -> None:
    before = path.lstat()
    if (
        not stat.S_ISREG(before.st_mode)
        or stat.S_IMODE(before.st_mode) != 0o600
        or before.st_uid != os.getuid()
        or before.st_nlink != 1
    ):
        raise ValueError(INVALID)
    flags = os.O_RDONLY
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    descriptor = os.open(path, flags)
    try:
        opened = os.fstat(descriptor)
        if (
            (opened.st_dev, opened.st_ino) != (before.st_dev, before.st_ino)
            or not stat.S_ISREG(opened.st_mode)
            or stat.S_IMODE(opened.st_mode) != 0o600
            or opened.st_uid != os.getuid()
            or opened.st_nlink != 1
        ):
            raise ValueError(INVALID)
        digest = hashlib.sha256()
        collected = bytearray() if expected_bytes is not None else None
        size = 0
        while True:
            chunk = os.read(descriptor, 1024 * 1024)
            if not chunk:
                break
            size += len(chunk)
            digest.update(chunk)
            if collected is not None:
                collected.extend(chunk)
        if (
            (expected_bytes is not None and bytes(collected or b"") != expected_bytes)
            or (expected_size is not None and size != expected_size)
            or (
                expected_sha256 is not None
                and digest.hexdigest() != expected_sha256
            )
        ):
            raise ValueError(INVALID)
        after = os.fstat(descriptor)
        if (
            (after.st_dev, after.st_ino, after.st_size, after.st_mtime_ns)
            != (opened.st_dev, opened.st_ino, opened.st_size, opened.st_mtime_ns)
        ):
            raise ValueError(INVALID)
    finally:
        os.close(descriptor)


def _reject_symlink_components(root: Path, relative: Path) -> None:
    current = root
    for component in relative.parts:
        current = current / component
        info = current.lstat()
        if stat.S_ISLNK(info.st_mode):
            raise ValueError(INVALID)
