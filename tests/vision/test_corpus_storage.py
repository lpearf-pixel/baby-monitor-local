from __future__ import annotations

import importlib
import os
import stat
from pathlib import Path

import pytest


def storage():
    return importlib.import_module("services.vision.corpus_storage")


def test_layout_rejects_runtime_parent_symlink(tmp_path: Path) -> None:
    module = storage()
    outside = tmp_path / "outside"
    outside.mkdir()
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "runtime").symlink_to(outside, target_is_directory=True)

    with pytest.raises(
        module.CorpusStorageError,
        match="^visual_corpus_storage_unsafe$",
    ):
        module.CorpusLayout.for_repository(repo)

    assert list(outside.iterdir()) == []


def test_layout_creates_only_private_owned_directories(tmp_path: Path) -> None:
    module = storage()
    repo = tmp_path / "repo"
    repo.mkdir()

    layout = module.CorpusLayout.for_repository(repo)

    assert layout.root == repo / "runtime" / "test-corpus" / "visual"
    for path in (
        layout.root,
        layout.downloads,
        layout.prepared,
        layout.results,
        layout.temp,
    ):
        info = path.lstat()
        assert stat.S_ISDIR(info.st_mode)
        assert stat.S_IMODE(info.st_mode) == 0o700
        assert info.st_uid == os.getuid()


@pytest.mark.parametrize("kind", ["symlink", "hardlink", "mode"])
def test_sha256_rejects_unsafe_files(tmp_path: Path, kind: str) -> None:
    module = storage()
    original = tmp_path / "source"
    original.write_bytes(b"source")
    original.chmod(0o600)
    candidate = original
    if kind == "symlink":
        candidate = tmp_path / "candidate"
        candidate.symlink_to(original)
    elif kind == "hardlink":
        candidate = tmp_path / "candidate"
        os.link(original, candidate)
    else:
        original.chmod(0o644)

    with pytest.raises(
        module.CorpusStorageError,
        match="^visual_corpus_artifact_unsafe$",
    ):
        module.sha256_file(candidate, max_bytes=1024)


def test_sha256_is_bounded_and_detects_file_replacement(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    module = storage()
    candidate = tmp_path / "candidate"
    candidate.write_bytes(b"abcdef")
    candidate.chmod(0o600)

    with pytest.raises(
        module.CorpusStorageError,
        match="^visual_corpus_artifact_too_large$",
    ):
        module.sha256_file(candidate, max_bytes=5)

    real_fstat = module.os.fstat
    calls = 0

    def changed_fstat(descriptor: int):
        nonlocal calls
        calls += 1
        result = real_fstat(descriptor)
        if calls == 2:
            return os.stat_result((*result[:6], result.st_size + 1, *result[7:]))
        return result

    monkeypatch.setattr(module.os, "fstat", changed_fstat)
    with pytest.raises(
        module.CorpusStorageError,
        match="^visual_corpus_artifact_changed$",
    ):
        module.sha256_file(candidate, max_bytes=1024)


def test_private_publication_never_replaces_existing_final(tmp_path: Path) -> None:
    module = storage()
    repo = tmp_path / "repo"
    repo.mkdir()
    layout = module.CorpusLayout.for_repository(repo)
    final = layout.downloads / "source.bin"
    final.write_bytes(b"existing")
    final.chmod(0o600)
    temporary = layout.new_temporary_file(prefix="download")
    os.write(temporary.descriptor, b"replacement")
    os.fsync(temporary.descriptor)

    with pytest.raises(
        module.CorpusStorageError,
        match="^visual_corpus_artifact_exists$",
    ):
        layout.publish_no_replace(temporary, final)

    assert final.read_bytes() == b"existing"
    assert temporary.path.read_bytes() == b"replacement"
    temporary.close()
