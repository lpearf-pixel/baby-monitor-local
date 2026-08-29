from __future__ import annotations

import hashlib
import json
import math
import os
import re
import stat
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from packages.contracts.private_visual_overlay import (
    LocalOverlayReadiness,
    PrivateAssetMetadata,
    PrivateOverlayDescriptor,
)


MAX_INDEX_BYTES = 64 * 1024
_ALLOWED_ROOT_ENTRIES = frozenset(
    {"index.json", "assets", "review-frames", "results", "temp"}
)
_OPTIONAL_DIRECTORIES = frozenset({"review-frames", "results", "temp"})
_ASSET_ID_PATTERN = re.compile(r"^plc-[0-9a-f]{32}$")
_BASENAME_PATTERN = re.compile(r"^[a-z0-9][a-z0-9._-]{0,95}$")


@dataclass(frozen=True)
class PrivateMediaFacts:
    bytes: int
    sha256: str
    video_streams: int
    audio_streams: int
    subtitle_streams: int
    data_streams: int
    duration_ms: int
    codec: str
    width: int
    height: int
    fps: float


@dataclass(frozen=True)
class PrivateOverlayValidation:
    readiness: LocalOverlayReadiness
    reason: str
    asset_count: int
    scenario_count: int


PrivateMediaProbe = Callable[[Path], PrivateMediaFacts]


class _PrivateOverlayFailure(RuntimeError):
    def __init__(self, reason: str) -> None:
        super().__init__(reason)
        self.reason = reason


def validate_private_overlay(
    descriptor: PrivateOverlayDescriptor,
    overlay_root: Path,
    *,
    probe: PrivateMediaProbe,
) -> PrivateOverlayValidation:
    try:
        root, root_identity = _validate_root(Path(overlay_root))
        mapping = _load_mapping(root / "index.json")
        expected_ids = {asset.private_asset_id for asset in descriptor.assets}
        if set(mapping) != expected_ids:
            raise _PrivateOverlayFailure("private_overlay_identity_mismatch")

        _validate_root_inventory(root)
        assets_root = root / "assets"
        assets_identity = _require_directory(assets_root)
        mapped_basenames = set(mapping.values())
        if _inventory(assets_root) != mapped_basenames:
            raise _PrivateOverlayFailure("private_overlay_mapping_invalid")

        for asset in descriptor.assets:
            _validate_asset(
                asset,
                assets_root / mapping[asset.private_asset_id],
                assets_identity,
                probe,
            )

        try:
            root_after = os.lstat(root)
        except OSError as exc:
            raise _PrivateOverlayFailure(
                "private_overlay_permissions_invalid"
            ) from exc
        if not _same_private_directory(root_identity, root_after):
            raise _PrivateOverlayFailure("private_overlay_permissions_invalid")
        try:
            assets_after = os.lstat(assets_root)
        except OSError as exc:
            raise _PrivateOverlayFailure(
                "private_overlay_permissions_invalid"
            ) from exc
        if not _same_private_directory(assets_identity, assets_after):
            raise _PrivateOverlayFailure("private_overlay_permissions_invalid")
        if _load_mapping(root / "index.json") != mapping:
            raise _PrivateOverlayFailure("private_overlay_mapping_invalid")
        _validate_root_inventory(root)
        if _inventory(assets_root) != mapped_basenames:
            raise _PrivateOverlayFailure("private_overlay_mapping_invalid")

        return PrivateOverlayValidation(
            readiness=LocalOverlayReadiness.LOCAL_PARTIAL,
            reason="private_overlay_valid",
            asset_count=len(descriptor.assets),
            scenario_count=len(
                {
                    scenario
                    for asset in descriptor.assets
                    for scenario in asset.scenario_ids
                }
            ),
        )
    except _PrivateOverlayFailure as exc:
        return _failure(exc.reason)
    except OSError:
        return _failure("private_overlay_unavailable")


def _validate_root(root: Path) -> tuple[Path, os.stat_result]:
    if not root.is_absolute() or not root.exists():
        raise _PrivateOverlayFailure("private_overlay_unavailable")
    try:
        if root.resolve(strict=True) != root:
            raise _PrivateOverlayFailure("private_overlay_permissions_invalid")
        root_identity = _require_directory(root)
        _require_directory(root / "assets")
        _require_private_file(root / "index.json")
    except FileNotFoundError as exc:
        raise _PrivateOverlayFailure("private_overlay_unavailable") from exc
    return root, root_identity


def _validate_root_inventory(root: Path) -> None:
    entries = _inventory(root)
    if not {"index.json", "assets"}.issubset(entries) or not entries.issubset(
        _ALLOWED_ROOT_ENTRIES
    ):
        raise _PrivateOverlayFailure("private_overlay_mapping_invalid")
    for name in _OPTIONAL_DIRECTORIES.intersection(entries):
        _require_directory(root / name)


def _inventory(path: Path) -> set[str]:
    with os.scandir(path) as entries:
        return {entry.name for entry in entries}


def _require_directory(path: Path) -> os.stat_result:
    value = os.lstat(path)
    if (
        not stat.S_ISDIR(value.st_mode)
        or stat.S_ISLNK(value.st_mode)
        or value.st_uid != os.getuid()
        or stat.S_IMODE(value.st_mode) != 0o700
    ):
        raise _PrivateOverlayFailure("private_overlay_permissions_invalid")
    return value


def _require_private_file(path: Path) -> os.stat_result:
    value = os.lstat(path)
    if (
        not stat.S_ISREG(value.st_mode)
        or stat.S_ISLNK(value.st_mode)
        or value.st_uid != os.getuid()
        or stat.S_IMODE(value.st_mode) != 0o600
        or value.st_nlink != 1
    ):
        raise _PrivateOverlayFailure("private_overlay_permissions_invalid")
    return value


def _load_mapping(path: Path) -> dict[str, str]:
    before = _require_private_file(path)
    descriptor = _open_read_only(path)
    try:
        held = os.fstat(descriptor)
        if not _same_identity(before, held):
            raise _PrivateOverlayFailure("private_overlay_mapping_invalid")
        raw = _read_bounded(descriptor, MAX_INDEX_BYTES)
        after = os.fstat(descriptor)
        entry_after = os.stat(path, follow_symlinks=False)
        if not _same_stable_file(held, after) or not _same_identity(after, entry_after):
            raise _PrivateOverlayFailure("private_overlay_mapping_invalid")
    finally:
        os.close(descriptor)

    try:
        payload = json.loads(raw.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise _PrivateOverlayFailure("private_overlay_mapping_invalid") from exc
    if (
        not isinstance(payload, dict)
        or set(payload) != {"schema_version", "assets"}
        or type(payload.get("schema_version")) is not int
        or payload["schema_version"] != 1
        or not isinstance(payload.get("assets"), list)
        or not 1 <= len(payload["assets"]) <= 20
    ):
        raise _PrivateOverlayFailure("private_overlay_mapping_invalid")

    mapping: dict[str, str] = {}
    basenames: set[str] = set()
    for item in payload["assets"]:
        if not isinstance(item, dict) or set(item) != {
            "private_asset_id",
            "basename",
        }:
            raise _PrivateOverlayFailure("private_overlay_mapping_invalid")
        asset_id = item["private_asset_id"]
        basename = item["basename"]
        if (
            not isinstance(asset_id, str)
            or _ASSET_ID_PATTERN.fullmatch(asset_id) is None
            or not isinstance(basename, str)
            or _BASENAME_PATTERN.fullmatch(basename) is None
            or basename in {".", ".."}
            or Path(basename).name != basename
            or asset_id in mapping
            or basename in basenames
        ):
            raise _PrivateOverlayFailure("private_overlay_mapping_invalid")
        mapping[asset_id] = basename
        basenames.add(basename)
    return mapping


def _validate_asset(
    expected: PrivateAssetMetadata,
    path: Path,
    parent_before: os.stat_result,
    probe: PrivateMediaProbe,
) -> None:
    try:
        entry_before = os.stat(path, follow_symlinks=False)
    except OSError as exc:
        raise _PrivateOverlayFailure("private_overlay_identity_mismatch") from exc
    if stat.S_ISLNK(entry_before.st_mode) or not stat.S_ISREG(entry_before.st_mode):
        raise _PrivateOverlayFailure("private_overlay_identity_mismatch")

    descriptor = _open_read_only(path, identity_failure=True)
    try:
        held_before = os.fstat(descriptor)
        if not _same_identity(entry_before, held_before):
            raise _PrivateOverlayFailure("private_overlay_identity_mismatch")
        if held_before.st_nlink != 1:
            raise _PrivateOverlayFailure("private_overlay_identity_mismatch")
        if (
            held_before.st_uid != os.getuid()
            or stat.S_IMODE(held_before.st_mode) != 0o600
        ):
            raise _PrivateOverlayFailure("private_overlay_permissions_invalid")

        size_before, digest_before = _hash_descriptor(descriptor)
        if size_before != expected.bytes or digest_before != expected.sha256:
            raise _PrivateOverlayFailure("private_overlay_identity_mismatch")

        os.lseek(descriptor, 0, os.SEEK_SET)
        try:
            facts = probe(Path(f"/dev/fd/{descriptor}"))
        except Exception as exc:
            raise _PrivateOverlayFailure("private_overlay_media_invalid") from exc

        held_after = os.fstat(descriptor)
        try:
            entry_after = os.stat(path, follow_symlinks=False)
        except OSError as exc:
            raise _PrivateOverlayFailure("private_overlay_identity_mismatch") from exc
        size_after, digest_after = _hash_descriptor(descriptor)
        if (
            not _same_stable_file(held_before, held_after)
            or not _same_identity(held_after, entry_after)
            or size_after != expected.bytes
            or digest_after != expected.sha256
        ):
            raise _PrivateOverlayFailure("private_overlay_identity_mismatch")
        try:
            parent_after = os.lstat(path.parent)
        except OSError as exc:
            raise _PrivateOverlayFailure(
                "private_overlay_permissions_invalid"
            ) from exc
        if not _same_private_directory(parent_before, parent_after):
            raise _PrivateOverlayFailure("private_overlay_permissions_invalid")
        _validate_media_facts(expected, facts, digest_after)
    finally:
        os.close(descriptor)


def _validate_media_facts(
    expected: PrivateAssetMetadata,
    facts: PrivateMediaFacts,
    digest: str,
) -> None:
    if not isinstance(facts, PrivateMediaFacts):
        raise _PrivateOverlayFailure("private_overlay_media_invalid")
    numeric_counts = (
        facts.bytes,
        facts.video_streams,
        facts.audio_streams,
        facts.subtitle_streams,
        facts.data_streams,
        facts.duration_ms,
        facts.width,
        facts.height,
    )
    if any(type(value) is not int or value < 0 for value in numeric_counts):
        raise _PrivateOverlayFailure("private_overlay_media_invalid")
    if facts.bytes != expected.bytes or facts.sha256 != digest:
        raise _PrivateOverlayFailure("private_overlay_identity_mismatch")
    if facts.audio_streams != 0:
        raise _PrivateOverlayFailure("private_overlay_audio_present")
    if (
        facts.video_streams != 1
        or facts.subtitle_streams != 0
        or facts.data_streams != 0
        or facts.duration_ms != expected.duration_ms
        or facts.codec != expected.codec
        or facts.width != expected.width
        or facts.height != expected.height
        or type(facts.fps) not in {int, float}
        or not math.isfinite(float(facts.fps))
        or not math.isclose(float(facts.fps), expected.fps, rel_tol=0, abs_tol=1e-6)
    ):
        raise _PrivateOverlayFailure("private_overlay_media_invalid")


def _open_read_only(path: Path, *, identity_failure: bool = False) -> int:
    flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0) | getattr(os, "O_NOFOLLOW", 0)
    try:
        return os.open(path, flags)
    except OSError as exc:
        reason = (
            "private_overlay_identity_mismatch"
            if identity_failure
            else "private_overlay_mapping_invalid"
        )
        raise _PrivateOverlayFailure(reason) from exc


def _read_bounded(descriptor: int, maximum: int) -> bytes:
    os.lseek(descriptor, 0, os.SEEK_SET)
    chunks: list[bytes] = []
    total = 0
    while total <= maximum:
        chunk = os.read(descriptor, min(64 * 1024, maximum + 1 - total))
        if not chunk:
            return b"".join(chunks)
        chunks.append(chunk)
        total += len(chunk)
    raise _PrivateOverlayFailure("private_overlay_mapping_invalid")


def _hash_descriptor(descriptor: int) -> tuple[int, str]:
    os.lseek(descriptor, 0, os.SEEK_SET)
    digest = hashlib.sha256()
    total = 0
    while True:
        chunk = os.read(descriptor, 1024 * 1024)
        if not chunk:
            return total, digest.hexdigest()
        total += len(chunk)
        digest.update(chunk)


def _same_identity(left: os.stat_result, right: os.stat_result) -> bool:
    return (left.st_dev, left.st_ino) == (right.st_dev, right.st_ino)


def _same_stable_file(left: os.stat_result, right: os.stat_result) -> bool:
    return (
        _same_identity(left, right)
        and left.st_size == right.st_size
        and left.st_mode == right.st_mode
        and left.st_uid == right.st_uid
        and left.st_nlink == right.st_nlink
        and left.st_mtime_ns == right.st_mtime_ns
        and left.st_ctime_ns == right.st_ctime_ns
    )


def _same_private_directory(left: os.stat_result, right: os.stat_result) -> bool:
    return (
        _same_identity(left, right)
        and stat.S_ISDIR(right.st_mode)
        and not stat.S_ISLNK(right.st_mode)
        and right.st_uid == os.getuid()
        and stat.S_IMODE(right.st_mode) == 0o700
    )


def _failure(reason: str) -> PrivateOverlayValidation:
    return PrivateOverlayValidation(
        readiness=LocalOverlayReadiness.LOCAL_UNAVAILABLE,
        reason=reason,
        asset_count=0,
        scenario_count=0,
    )


__all__ = [
    "PrivateMediaFacts",
    "PrivateMediaProbe",
    "PrivateOverlayValidation",
    "validate_private_overlay",
]
