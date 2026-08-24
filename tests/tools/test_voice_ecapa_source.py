from __future__ import annotations

import json
import stat
from pathlib import Path

import pytest

from packages.contracts.settings import VoiceCareSettings
from services.voice.artifacts import voice_artifact_spec
from tools.voice_ecapa_source import materialize_ecapa_source


def _spec():
    return voice_artifact_spec(
        VoiceCareSettings(
            enabled=False,
            speechbrain_ecapa_manifest_sha256="0" * 64,
        ),
        "speechbrain-ecapa-voxceleb",
    )


def test_materializer_fetches_only_the_registry_fixed_ecapa_revision(
    tmp_path: Path,
) -> None:
    spec = _spec()
    cache = tmp_path / "cache"
    cache.mkdir()
    calls: list[dict[str, object]] = []

    def fetch(**kwargs: object) -> str:
        calls.append(kwargs)
        filename = kwargs["filename"]
        assert isinstance(filename, str)
        target = cache / filename
        target.write_bytes(b"public synthetic model " + filename.encode("ascii"))
        return str(target)

    source, manifest = materialize_ecapa_source(tmp_path, fetch=fetch)

    assert [call["filename"] for call in calls] == list(spec.source_files)
    assert all(
        call
        == {
            "repo_id": "speechbrain/spkrec-ecapa-voxceleb",
            "revision": spec.source_revision,
            "filename": call["filename"],
        }
        for call in calls
    )
    assert {path.name for path in source.iterdir()} == set(spec.source_files)
    assert stat.S_IMODE(source.parent.stat().st_mode) == 0o700
    assert stat.S_IMODE(source.stat().st_mode) == 0o700
    assert all(stat.S_IMODE(path.stat().st_mode) == 0o600 for path in source.iterdir())
    assert stat.S_IMODE(manifest.stat().st_mode) == 0o600

    payload = json.loads(manifest.read_text(encoding="ascii"))
    assert set(payload["files"]) == set(spec.source_files)
    settings = VoiceCareSettings.model_validate_json(
        (tmp_path / "runtime/config/voice-care-models.json").read_text("ascii")
    )
    assert settings.enabled is False
    assert settings.speechbrain_ecapa_manifest_sha256 not in (None, "0" * 64)


def test_materializer_is_idempotent_after_valid_publication(tmp_path: Path) -> None:
    cache = tmp_path / "cache"
    cache.mkdir()

    def fetch(**kwargs: object) -> str:
        target = cache / str(kwargs["filename"])
        target.write_bytes(b"synthetic model")
        return str(target)

    expected = materialize_ecapa_source(tmp_path, fetch=fetch)

    assert materialize_ecapa_source(
        tmp_path,
        fetch=lambda **_kwargs: pytest.fail("valid source must not be downloaded again"),
    ) == expected


@pytest.mark.parametrize("invalid_kind", ("directory", "empty", "oversize"))
def test_materializer_rejects_invalid_cache_files_without_partial_publication(
    tmp_path: Path, invalid_kind: str
) -> None:
    cache = tmp_path / "cache"
    cache.mkdir()

    def fetch(**kwargs: object) -> str:
        target = cache / str(kwargs["filename"])
        if invalid_kind == "directory":
            target.mkdir()
        elif invalid_kind == "empty":
            target.touch()
        else:
            target.write_bytes(b"x" * 33)
        return str(target)

    with pytest.raises(ValueError, match="^VOICE_ECAPA_SOURCE_UNAVAILABLE$"):
        materialize_ecapa_source(tmp_path, fetch=fetch, max_file_bytes=32)

    assert not (
        tmp_path
        / "runtime/models/voice-care-sources/speechbrain-ecapa-voxceleb"
    ).exists()
    assert not (tmp_path / "runtime/config/voice-care-models.json").exists()


def test_materializer_rejects_a_symlinked_private_publication_boundary(
    tmp_path: Path,
) -> None:
    outside = tmp_path / "outside"
    outside.mkdir()
    (tmp_path / "runtime").symlink_to(outside, target_is_directory=True)

    with pytest.raises(ValueError, match="^VOICE_ECAPA_SOURCE_UNAVAILABLE$"):
        materialize_ecapa_source(
            tmp_path,
            fetch=lambda **_kwargs: pytest.fail("fetch must not run"),
        )

    assert list(outside.iterdir()) == []
