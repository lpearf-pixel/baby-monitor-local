from __future__ import annotations

import hashlib
import io
import json
import tarfile
from pathlib import Path

import pytest

from packages.contracts.settings import VoiceCareSettings
from services.voice.artifacts import validate_voice_source as real_validate_voice_source
from tools.voice_paraformer_source import materialize_paraformer_source


def _archive(path: Path) -> tuple[str, dict[str, str]]:
    files = {"model.int8.onnx": b"synthetic model", "tokens.txt": b"token 1\n"}
    with tarfile.open(path, "w:bz2") as archive:
        for name, payload in files.items():
            info = tarfile.TarInfo(
                f"sherpa-onnx-paraformer-zh-2023-09-14/{name}"
            )
            info.size = len(payload)
            archive.addfile(info, io.BytesIO(payload))
    return hashlib.sha256(path.read_bytes()).hexdigest(), {
        name: hashlib.sha256(payload).hexdigest() for name, payload in files.items()
    }


def test_materializer_extracts_only_fixed_files_and_updates_disabled_settings(
    tmp_path: Path,
) -> None:
    archive = tmp_path / "model.tar.bz2"
    digest, files = _archive(archive)

    source, manifest = materialize_paraformer_source(
        tmp_path,
        archive=archive,
        expected_archive_sha256=digest,
        expected_file_sha256=files,
    )

    assert {entry.name for entry in source.iterdir()} == set(files)
    assert json.loads(manifest.read_text("ascii"))["files"] == files
    settings = VoiceCareSettings.model_validate_json(
        (tmp_path / "runtime/config/voice-care-models.json").read_text("ascii")
    )
    assert settings.enabled is False
    assert settings.paraformer_zh_manifest_sha256 not in (None, "0" * 64)


def test_materializer_rejects_wrong_archive_before_publication(tmp_path: Path) -> None:
    archive = tmp_path / "model.tar.bz2"
    _digest, files = _archive(archive)

    with pytest.raises(ValueError, match="^VOICE_PARAFORMER_SOURCE_UNAVAILABLE$"):
        materialize_paraformer_source(
            tmp_path,
            archive=archive,
            expected_archive_sha256="0" * 64,
            expected_file_sha256=files,
        )

    assert not (tmp_path / "runtime").exists()


def test_materializer_rejects_existing_self_signed_source_drift(tmp_path: Path) -> None:
    archive = tmp_path / "model.tar.bz2"
    digest, files = _archive(archive)
    source, manifest = materialize_paraformer_source(
        tmp_path,
        archive=archive,
        expected_archive_sha256=digest,
        expected_file_sha256=files,
    )
    replacement = b"different tokens"
    (source / "tokens.txt").write_bytes(replacement)
    payload = json.loads(manifest.read_text("ascii"))
    payload["files"]["tokens.txt"] = hashlib.sha256(replacement).hexdigest()
    manifest.write_text(
        json.dumps(payload, sort_keys=True, separators=(",", ":")) + "\n",
        encoding="ascii",
    )

    with pytest.raises(ValueError, match="^VOICE_PARAFORMER_SOURCE_UNAVAILABLE$"):
        materialize_paraformer_source(
            tmp_path,
            archive=archive,
            expected_archive_sha256=digest,
            expected_file_sha256=files,
        )


def test_materializer_does_not_self_sign_a_source_replaced_after_validation(
    tmp_path: Path, monkeypatch
) -> None:
    archive = tmp_path / "model.tar.bz2"
    digest, files = _archive(archive)
    source, _manifest = materialize_paraformer_source(
        tmp_path,
        archive=archive,
        expected_archive_sha256=digest,
        expected_file_sha256=files,
    )
    settings_path = tmp_path / "runtime/config/voice-care-models.json"
    expected_settings = settings_path.read_bytes()

    def validate_then_replace(*args, **kwargs):
        result = real_validate_voice_source(*args, **kwargs)
        (source / "tokens.txt").write_bytes(b"replacement after validation")
        return result

    monkeypatch.setattr(
        "tools.voice_paraformer_source.validate_voice_source",
        validate_then_replace,
    )

    materialize_paraformer_source(
        tmp_path,
        archive=archive,
        expected_archive_sha256=digest,
        expected_file_sha256=files,
    )

    assert settings_path.read_bytes() == expected_settings
