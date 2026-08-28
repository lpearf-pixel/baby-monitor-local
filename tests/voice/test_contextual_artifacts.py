from __future__ import annotations

import hashlib
import json
import os
from dataclasses import replace
from pathlib import Path

import pytest

from services.voice.contextual_artifacts import (
    CONTEXTUAL_ARTIFACT,
    CONTEXTUAL_BUNDLE_DIGEST,
    CONTEXTUAL_MANIFEST_NAME,
    ContextualFile,
    build_contextual_manifest,
    contextual_bundle_relative_path,
    validate_contextual_bundle,
)


def _synthetic_spec():
    files = (
        ContextualFile("am.mvn", 3, hashlib.sha256(b"mvn").hexdigest()),
        ContextualFile("config.yaml", 6, hashlib.sha256(b"config").hexdigest()),
        ContextualFile("model_eb.onnx", 2, hashlib.sha256(b"eb").hexdigest()),
        ContextualFile("model_quant.onnx", 5, hashlib.sha256(b"model").hexdigest()),
        ContextualFile("seg_dict", 3, hashlib.sha256(b"seg").hexdigest()),
        ContextualFile("tokens.json", 6, hashlib.sha256(b"tokens").hexdigest()),
    )
    return replace(CONTEXTUAL_ARTIFACT, files=files)


def _write_bundle(root: Path, spec) -> Path:
    manifest = build_contextual_manifest(spec)
    digest = hashlib.sha256(manifest).hexdigest()
    bundle = root / contextual_bundle_relative_path(digest)
    bundle.mkdir(parents=True, mode=0o700)
    bundle.chmod(0o700)
    payloads = {
        "am.mvn": b"mvn",
        "config.yaml": b"config",
        "model_eb.onnx": b"eb",
        "model_quant.onnx": b"model",
        "seg_dict": b"seg",
        "tokens.json": b"tokens",
    }
    for name, payload in payloads.items():
        target = bundle / name
        target.write_bytes(payload)
        target.chmod(0o600)
    (bundle / CONTEXTUAL_MANIFEST_NAME).write_bytes(manifest)
    (bundle / CONTEXTUAL_MANIFEST_NAME).chmod(0o600)
    return bundle


def test_candidate_contract_is_exact_and_immutable() -> None:
    assert CONTEXTUAL_ARTIFACT.artifact_id == "funasr-contextual-paraformer-zh-int8"
    assert CONTEXTUAL_ARTIFACT.upstream_revision == (
        "8f0881c891ceba7360e215b04e54cad564a68c41"
    )
    assert CONTEXTUAL_ARTIFACT.runtime_revision == (
        "67d6d880841e0c8f3a33e0f98d3bfc2122e34eff"
    )
    assert CONTEXTUAL_ARTIFACT.runtime_version == "0.4.2"
    assert CONTEXTUAL_ARTIFACT.model_license == "Apache-2.0"
    assert CONTEXTUAL_ARTIFACT.runtime_license == "MIT"
    assert [(item.path, item.size, item.sha256) for item in CONTEXTUAL_ARTIFACT.files] == [
        (
            "am.mvn",
            11203,
            "29b3c740a2c0cfc6b308126d31d7f265fa2be74f3bb095cd2f143ea970896ae5",
        ),
        (
            "config.yaml",
            2532,
            "1d9057edeaba9e131cb98f26011606497cf3af187d8943525ddb5ee36c836b1b",
        ),
        (
            "model_eb.onnx",
            25618359,
            "d31446a5af664291a2922cca253a4200a523f347d6fc3cb1bff356bf60a116b6",
        ),
        (
            "model_quant.onnx",
            871251660,
            "f404e6eb532b54fd95761e2b4be4ed1998e8cff3cb3b930a9bee1f2d556e5035",
        ),
        (
            "seg_dict",
            8287834,
            "59a2ef803a3f1648ad03a2e1480db1c1ee0c0d7dc4ef4dbd16cea33944329022",
        ),
        (
            "tokens.json",
            93676,
            "2b20c2b12572d682afff84ce1c8d560f67b8b32a4c1f21567411d141ed352127",
        ),
    ]
    assert len(CONTEXTUAL_BUNDLE_DIGEST) == 64
    assert contextual_bundle_relative_path(CONTEXTUAL_BUNDLE_DIGEST) == (
        Path("runtime/models/voice-contextual")
        / CONTEXTUAL_ARTIFACT.artifact_id
        / CONTEXTUAL_BUNDLE_DIGEST
    )


def test_candidate_requirements_are_fully_pinned_and_hashed() -> None:
    requirements = (
        Path(__file__).parents[2] / "config/voice-contextual-requirements.txt"
    ).read_text(encoding="ascii")
    logical_lines = [
        line
        for line in requirements.splitlines()
        if line and not line.startswith("    --hash=")
    ]

    assert "funasr_onnx==0.4.2 \\" in logical_lines
    assert "numpy==1.26.4 \\" in logical_lines
    assert "onnxruntime==1.23.2 \\" in logical_lines
    assert "numba==0.61.2 \\" in logical_lines
    assert "llvmlite==0.44.0 \\" in logical_lines
    assert all("==" in line and line.endswith(" \\") for line in logical_lines)
    assert requirements.count("--hash=sha256:") == len(logical_lines)


def test_valid_bundle_requires_canonical_manifest_and_private_files(tmp_path: Path) -> None:
    spec = _synthetic_spec()
    bundle = _write_bundle(tmp_path, spec)

    assert validate_contextual_bundle(tmp_path, spec=spec) == bundle.resolve()
    manifest = json.loads((bundle / CONTEXTUAL_MANIFEST_NAME).read_text("ascii"))
    assert manifest["schema_version"] == 1
    assert manifest["files"]["model_quant.onnx"]["size"] == 5


@pytest.mark.parametrize("mutation", ["extra", "symlink", "hardlink", "mode", "digest"])
def test_bundle_rejects_filesystem_and_digest_violations(
    tmp_path: Path, mutation: str
) -> None:
    spec = _synthetic_spec()
    bundle = _write_bundle(tmp_path, spec)
    if mutation == "extra":
        (bundle / "extra").write_bytes(b"x")
        (bundle / "extra").chmod(0o600)
    elif mutation == "symlink":
        (bundle / "tokens.json").unlink()
        (bundle / "tokens.json").symlink_to(bundle / "am.mvn")
    elif mutation == "hardlink":
        (bundle / "tokens.json").unlink()
        os.link(bundle / "am.mvn", bundle / "tokens.json")
    elif mutation == "mode":
        (bundle / "tokens.json").chmod(0o644)
    else:
        (bundle / "tokens.json").write_bytes(b"wrong!")

    with pytest.raises(ValueError, match="^VOICE_CONTEXTUAL_ARTIFACT_INVALID$"):
        validate_contextual_bundle(tmp_path, spec=spec)


def test_bundle_rejects_noncanonical_manifest_and_unsafe_parent(tmp_path: Path) -> None:
    spec = _synthetic_spec()
    bundle = _write_bundle(tmp_path, spec)
    manifest_path = bundle / CONTEXTUAL_MANIFEST_NAME
    payload = json.loads(manifest_path.read_text("ascii"))
    manifest_path.write_text(json.dumps(payload, indent=2) + "\n", encoding="ascii")
    manifest_path.chmod(0o600)

    with pytest.raises(ValueError, match="^VOICE_CONTEXTUAL_ARTIFACT_INVALID$"):
        validate_contextual_bundle(tmp_path, spec=spec)

    safe = tmp_path / "safe"
    safe.mkdir(mode=0o700)
    escaped = tmp_path / "escaped"
    escaped.mkdir(mode=0o700)
    runtime = safe / "runtime"
    runtime.symlink_to(escaped, target_is_directory=True)
    with pytest.raises(ValueError, match="^VOICE_CONTEXTUAL_ARTIFACT_INVALID$"):
        validate_contextual_bundle(safe, spec=spec)
