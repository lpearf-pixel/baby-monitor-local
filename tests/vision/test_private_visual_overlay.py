from __future__ import annotations

import hashlib
import json
import os
from dataclasses import replace
from pathlib import Path
from typing import Callable

import pytest

from packages.contracts.private_visual_overlay import (
    LocalOverlayReadiness,
    PrivateOverlayDescriptor,
)
from services.vision.private_visual_overlay import (
    PrivateMediaFacts,
    validate_private_overlay,
)


ASSET_ID = "plc-0123456789abcdef0123456789abcdef"
ASSET_BASENAME = "asset.mp4"
ASSET_BYTES = b"synthetic-private-video-only"


def descriptor(
    payload: bytes = ASSET_BYTES,
    **overrides: object,
) -> PrivateOverlayDescriptor:
    asset: dict[str, object] = {
        "private_asset_id": ASSET_ID,
        "sha256": hashlib.sha256(payload).hexdigest(),
        "bytes": len(payload),
        "duration_ms": 25_000,
        "codec": "hevc",
        "width": 2560,
        "height": 1440,
        "fps": 10.0,
        "scenario_ids": ["WIDE-02", "NEG-01"],
        "authorization_review": "pending",
        "privacy_review": "pending",
    }
    asset.update(overrides)
    return PrivateOverlayDescriptor.model_validate(
        {
            "schema_version": 1,
            "source_type": "PRIVATE_LOCAL_CAPTURE",
            "assets": [asset],
        }
    )


def create_overlay(
    tmp_path: Path,
    *,
    payload: bytes = ASSET_BYTES,
    mapping_assets: list[dict[str, str]] | None = None,
) -> tuple[Path, Path]:
    root = tmp_path / "private-overlay"
    assets = root / "assets"
    root.mkdir(mode=0o700)
    assets.mkdir(mode=0o700)
    media = assets / ASSET_BASENAME
    media.write_bytes(payload)
    media.chmod(0o600)
    index = root / "index.json"
    index.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "assets": mapping_assets
                if mapping_assets is not None
                else [
                    {
                        "private_asset_id": ASSET_ID,
                        "basename": ASSET_BASENAME,
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    index.chmod(0o600)
    return root, media


def facts_for(
    path: Path,
    **overrides: object,
) -> PrivateMediaFacts:
    payload = path.read_bytes()
    facts = PrivateMediaFacts(
        bytes=len(payload),
        sha256=hashlib.sha256(payload).hexdigest(),
        video_streams=1,
        audio_streams=0,
        subtitle_streams=0,
        data_streams=0,
        duration_ms=25_000,
        codec="hevc",
        width=2560,
        height=1440,
        fps=10.0,
    )
    return replace(facts, **overrides)


def validate(
    value: PrivateOverlayDescriptor,
    root: Path,
    *,
    probe: Callable[[Path], PrivateMediaFacts] = facts_for,
):
    return validate_private_overlay(value, root, probe=probe)


def test_valid_private_media_reports_bounded_aggregate(tmp_path: Path) -> None:
    root, _ = create_overlay(tmp_path)

    result = validate(descriptor(), root)

    assert result.readiness is LocalOverlayReadiness.LOCAL_PARTIAL
    assert result.reason == "private_overlay_valid"
    assert result.asset_count == 1
    assert result.scenario_count == 2


def test_missing_overlay_is_unavailable_without_creation(tmp_path: Path) -> None:
    root = tmp_path / "missing-private-overlay"

    result = validate(descriptor(), root)

    assert result.readiness is LocalOverlayReadiness.LOCAL_UNAVAILABLE
    assert result.reason == "private_overlay_unavailable"
    assert not root.exists()


@pytest.mark.parametrize("target", ["root", "assets", "index", "media"])
def test_overlay_rejects_non_private_permissions(
    tmp_path: Path,
    target: str,
) -> None:
    root, media = create_overlay(tmp_path)
    paths = {
        "root": root,
        "assets": root / "assets",
        "index": root / "index.json",
        "media": media,
    }
    paths[target].chmod(0o755 if paths[target].is_dir() else 0o644)

    result = validate(descriptor(), root)

    assert result.reason == "private_overlay_permissions_invalid"


def test_overlay_rejects_wrong_owner(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import services.vision.private_visual_overlay as validator

    root, _ = create_overlay(tmp_path)
    actual_uid = os.getuid()
    monkeypatch.setattr(validator.os, "getuid", lambda: actual_uid + 1)

    result = validate(descriptor(), root)

    assert result.reason == "private_overlay_permissions_invalid"


def test_overlay_rejects_symlinked_root(tmp_path: Path) -> None:
    real_root, _ = create_overlay(tmp_path)
    alias = tmp_path / "private-overlay-alias"
    alias.symlink_to(real_root, target_is_directory=True)

    result = validate(descriptor(), alias)

    assert result.reason == "private_overlay_permissions_invalid"


def test_overlay_rejects_symlinked_assets_directory(tmp_path: Path) -> None:
    root, _ = create_overlay(tmp_path)
    assets = root / "assets"
    actual_assets = root / "actual-assets"
    assets.rename(actual_assets)
    assets.symlink_to(actual_assets, target_is_directory=True)

    result = validate(descriptor(), root)

    assert result.reason == "private_overlay_permissions_invalid"


def test_overlay_rejects_symlinked_media(tmp_path: Path) -> None:
    root, media = create_overlay(tmp_path)
    actual_media = tmp_path / "actual-media.mp4"
    media.rename(actual_media)
    media.symlink_to(actual_media)

    result = validate(descriptor(), root)

    assert result.reason == "private_overlay_identity_mismatch"


def test_overlay_rejects_hard_linked_media_without_deleting_it(tmp_path: Path) -> None:
    root, media = create_overlay(tmp_path)
    outside_link = tmp_path / "second-name.mp4"
    os.link(media, outside_link)

    result = validate(descriptor(), root)

    assert result.reason == "private_overlay_identity_mismatch"
    assert media.exists()
    assert outside_link.exists()


@pytest.mark.parametrize("basename", ["../asset.mp4", "/private/asset.mp4", "a/b.mp4"])
def test_overlay_rejects_mapping_escape(tmp_path: Path, basename: str) -> None:
    root, _ = create_overlay(
        tmp_path,
        mapping_assets=[{"private_asset_id": ASSET_ID, "basename": basename}],
    )

    result = validate(descriptor(), root)

    assert result.reason == "private_overlay_mapping_invalid"


def test_overlay_rejects_duplicate_mapping_identity(tmp_path: Path) -> None:
    item = {"private_asset_id": ASSET_ID, "basename": ASSET_BASENAME}
    root, _ = create_overlay(tmp_path, mapping_assets=[item, dict(item)])

    result = validate(descriptor(), root)

    assert result.reason == "private_overlay_mapping_invalid"


def test_overlay_rejects_mapping_for_the_wrong_asset(tmp_path: Path) -> None:
    root, _ = create_overlay(
        tmp_path,
        mapping_assets=[
            {
                "private_asset_id": "plc-fedcba9876543210fedcba9876543210",
                "basename": ASSET_BASENAME,
            }
        ],
    )

    result = validate(descriptor(), root)

    assert result.reason == "private_overlay_identity_mismatch"


@pytest.mark.parametrize("location", ["root", "assets"])
def test_overlay_rejects_unknown_inventory(tmp_path: Path, location: str) -> None:
    root, _ = create_overlay(tmp_path)
    parent = root if location == "root" else root / "assets"
    unknown = parent / "unknown.bin"
    unknown.write_bytes(b"unknown")
    unknown.chmod(0o600)

    result = validate(descriptor(), root)

    assert result.reason == "private_overlay_mapping_invalid"


@pytest.mark.parametrize("fact", ["bytes", "sha256"])
def test_overlay_rejects_probe_identity_mismatch(tmp_path: Path, fact: str) -> None:
    root, _ = create_overlay(tmp_path)

    def mismatched(path: Path) -> PrivateMediaFacts:
        value = facts_for(path)
        replacement: object = value.bytes + 1 if fact == "bytes" else "f" * 64
        return replace(value, **{fact: replacement})

    result = validate(descriptor(), root, probe=mismatched)

    assert result.reason == "private_overlay_identity_mismatch"


@pytest.mark.parametrize(
    ("fact", "value"),
    [
        ("video_streams", 0),
        ("video_streams", 2),
        ("subtitle_streams", 1),
        ("data_streams", 1),
        ("duration_ms", 24_000),
        ("codec", "h264"),
        ("width", 1280),
        ("height", 720),
        ("fps", 9.0),
    ],
)
def test_overlay_rejects_media_fact_mismatch(
    tmp_path: Path,
    fact: str,
    value: object,
) -> None:
    root, _ = create_overlay(tmp_path)

    def mismatched(path: Path) -> PrivateMediaFacts:
        return replace(facts_for(path), **{fact: value})

    result = validate(descriptor(), root, probe=mismatched)

    assert result.reason == "private_overlay_media_invalid"


def test_overlay_rejects_any_audio_stream(tmp_path: Path) -> None:
    root, _ = create_overlay(tmp_path)

    result = validate(
        descriptor(),
        root,
        probe=lambda path: replace(facts_for(path), audio_streams=1),
    )

    assert result.reason == "private_overlay_audio_present"


def test_overlay_rejects_probe_failure_without_exposing_exception(tmp_path: Path) -> None:
    root, _ = create_overlay(tmp_path)

    def failing_probe(_: Path) -> PrivateMediaFacts:
        raise RuntimeError("private filename and decoder output")

    result = validate(descriptor(), root, probe=failing_probe)

    assert result.reason == "private_overlay_media_invalid"
    assert "filename" not in result.reason


def test_overlay_rejects_malformed_probe_result(tmp_path: Path) -> None:
    root, _ = create_overlay(tmp_path)

    result = validate(descriptor(), root, probe=lambda _: object())  # type: ignore[arg-type]

    assert result.reason == "private_overlay_media_invalid"


@pytest.mark.parametrize(
    "override",
    [
        {"bytes": len(ASSET_BYTES) + 1},
        {"sha256": "f" * 64},
    ],
)
def test_overlay_rejects_descriptor_identity_mismatch(
    tmp_path: Path,
    override: dict[str, object],
) -> None:
    root, media = create_overlay(tmp_path)

    result = validate(descriptor(**override), root)

    assert result.reason == "private_overlay_identity_mismatch"
    assert media.exists()


def test_overlay_rejects_malformed_index(tmp_path: Path) -> None:
    root, _ = create_overlay(tmp_path)
    index = root / "index.json"
    index.write_text("{", encoding="utf-8")
    index.chmod(0o600)

    result = validate(descriptor(), root)

    assert result.reason == "private_overlay_mapping_invalid"


def test_overlay_rejects_missing_mapped_file(tmp_path: Path) -> None:
    root, media = create_overlay(tmp_path)
    moved = tmp_path / "moved.mp4"
    media.rename(moved)

    result = validate(descriptor(), root)

    assert result.reason == "private_overlay_mapping_invalid"
    assert moved.exists()


def test_overlay_detects_in_place_change_during_probe(tmp_path: Path) -> None:
    root, media = create_overlay(tmp_path)

    def changing_probe(path: Path) -> PrivateMediaFacts:
        value = facts_for(path)
        media.write_bytes(b"changed-private-video-payload")
        media.chmod(0o600)
        return value

    result = validate(descriptor(), root, probe=changing_probe)

    assert result.reason == "private_overlay_identity_mismatch"
    assert media.exists()


def test_overlay_detects_directory_entry_replacement_during_probe(
    tmp_path: Path,
) -> None:
    root, media = create_overlay(tmp_path)

    def replacing_probe(path: Path) -> PrivateMediaFacts:
        value = facts_for(path)
        replacement = root / "assets" / "replacement.tmp"
        replacement.write_bytes(ASSET_BYTES)
        replacement.chmod(0o600)
        replacement.replace(media)
        return value

    result = validate(descriptor(), root, probe=replacing_probe)

    assert result.reason == "private_overlay_identity_mismatch"
    assert media.exists()


def test_overlay_detects_assets_parent_replaced_by_symlink_during_probe(
    tmp_path: Path,
) -> None:
    root, _ = create_overlay(tmp_path)
    assets = root / "assets"
    moved_assets = root / "moved-assets"

    def replacing_parent(path: Path) -> PrivateMediaFacts:
        value = facts_for(path)
        assets.rename(moved_assets)
        assets.symlink_to(moved_assets, target_is_directory=True)
        return value

    result = validate(descriptor(), root, probe=replacing_parent)

    assert result.reason == "private_overlay_permissions_invalid"


def test_overlay_detects_root_replaced_by_symlink_during_probe(
    tmp_path: Path,
) -> None:
    root, _ = create_overlay(tmp_path)
    moved_root = tmp_path / "moved-overlay"

    def replacing_root(path: Path) -> PrivateMediaFacts:
        value = facts_for(path)
        root.rename(moved_root)
        root.symlink_to(moved_root, target_is_directory=True)
        return value

    result = validate(descriptor(), root, probe=replacing_root)

    assert result.reason == "private_overlay_permissions_invalid"


@pytest.mark.parametrize("location", ["root", "assets"])
def test_overlay_detects_inventory_added_during_probe(
    tmp_path: Path,
    location: str,
) -> None:
    root, _ = create_overlay(tmp_path)
    parent = root if location == "root" else root / "assets"

    def adding_inventory(path: Path) -> PrivateMediaFacts:
        value = facts_for(path)
        added = parent / "late.bin"
        added.write_bytes(b"late")
        added.chmod(0o600)
        return value

    result = validate(descriptor(), root, probe=adding_inventory)

    assert result.reason == "private_overlay_mapping_invalid"


def test_overlay_detects_index_changed_during_probe(tmp_path: Path) -> None:
    root, _ = create_overlay(tmp_path)
    index = root / "index.json"

    def changing_index(path: Path) -> PrivateMediaFacts:
        value = facts_for(path)
        index.write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "assets": [
                        {
                            "private_asset_id": ASSET_ID,
                            "basename": "other.mp4",
                        }
                    ],
                }
            ),
            encoding="utf-8",
        )
        index.chmod(0o600)
        return value

    result = validate(descriptor(), root, probe=changing_index)

    assert result.reason == "private_overlay_mapping_invalid"
