from __future__ import annotations

from hashlib import sha256
from pathlib import Path

from packages.monitoring.realtime_models import (
    ModelAsset,
    ModelAssetCode,
    install_realtime_model_assets,
    verify_realtime_model_assets,
)


def asset(payload: bytes = b"synthetic-model") -> ModelAsset:
    return ModelAsset(
        filename="synthetic/model.bin",
        url="https://models.example.test/model.bin",
        size=len(payload),
        sha256=sha256(payload).hexdigest(),
    )


def test_model_asset_verification_distinguishes_stable_failure_codes(
    tmp_path: Path,
) -> None:
    expected = asset()

    missing = verify_realtime_model_assets(tmp_path, manifest=(expected,))
    assert missing.code is ModelAssetCode.MISSING
    assert "tmp" not in repr(missing).lower()

    target = tmp_path / expected.filename
    target.parent.mkdir(parents=True)
    target.write_bytes(b"short")
    wrong_size = verify_realtime_model_assets(tmp_path, manifest=(expected,))
    assert wrong_size.code is ModelAssetCode.SIZE_MISMATCH

    same_size_bad_digest = b"x" * expected.size
    target.write_bytes(same_size_bad_digest)
    wrong_digest = verify_realtime_model_assets(tmp_path, manifest=(expected,))
    assert wrong_digest.code is ModelAssetCode.DIGEST_MISMATCH

    target.write_bytes(b"synthetic-model")
    valid = verify_realtime_model_assets(tmp_path, manifest=(expected,))
    assert valid.code is ModelAssetCode.OK
    assert valid.checked_count == 1


def test_explicit_install_verifies_before_atomic_destination_replace(
    tmp_path: Path,
) -> None:
    payload = b"synthetic-model"
    expected = asset(payload)
    target = tmp_path / expected.filename
    target.parent.mkdir(parents=True)
    target.write_bytes(b"old-model-data")

    installed = install_realtime_model_assets(
        tmp_path,
        manifest=(expected,),
        fetcher=lambda url, maximum: payload,
    )

    assert installed.code is ModelAssetCode.OK
    assert target.read_bytes() == payload
    assert list(target.parent.glob("*.partial")) == []


def test_failed_install_preserves_existing_destination(tmp_path: Path) -> None:
    expected = asset()
    target = tmp_path / expected.filename
    target.parent.mkdir(parents=True)
    target.write_bytes(b"old-model-data")

    status = install_realtime_model_assets(
        tmp_path,
        manifest=(expected,),
        fetcher=lambda url, maximum: b"bad",
    )

    assert status.code is ModelAssetCode.SIZE_MISMATCH
    assert target.read_bytes() == b"old-model-data"


def test_manifest_rejects_non_https_or_parent_paths() -> None:
    for filename, url in (
        ("../private.bin", "https://models.example.test/model.bin"),
        ("model.bin", "http://models.example.test/model.bin"),
    ):
        try:
            ModelAsset(filename=filename, url=url, size=1, sha256="0" * 64)
        except ValueError as exc:
            assert str(exc) == "invalid_realtime_model_manifest"
        else:
            raise AssertionError("unsafe model manifest was accepted")
