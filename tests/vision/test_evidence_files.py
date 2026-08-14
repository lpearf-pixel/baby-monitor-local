from __future__ import annotations

from datetime import UTC, datetime, timedelta
import hashlib
from io import BytesIO
from pathlib import Path
import stat

from PIL import Image
import pytest

from services.vision.evidence_files import GuardianEvidenceFiles
from services.vision.frame_policy import PreparedAnalysisFrame


NOW = datetime(2026, 8, 11, 12, 0, tzinfo=UTC)


def safe_frame(seconds: int, color: tuple[int, int, int]) -> PreparedAnalysisFrame:
    output = BytesIO()
    Image.new("RGB", (32, 18), color).save(output, format="JPEG", quality=80)
    return PreparedAnalysisFrame(
        jpeg=output.getvalue(),
        captured_at=NOW + timedelta(seconds=seconds),
        width=32,
        height=18,
        crop_box=(0, 0, 32, 18),
    )


def test_private_digest_paths_hold_readable_snapshot_and_animated_clip(
    tmp_path: Path,
) -> None:
    files = GuardianEvidenceFiles(tmp_path / "guardian-evidence")
    frames = (
        safe_frame(0, (255, 0, 0)),
        safe_frame(2, (0, 255, 0)),
        safe_frame(4, (0, 0, 255)),
    )

    snapshot_key = files.write_snapshot("family/event-face", frames[1])
    clip_key = files.write_clip("family/event-face", frames)

    digest = hashlib.sha256(b"family/event-face").hexdigest()
    assert snapshot_key == f"visual-risk/{digest}/snapshot.jpg"
    assert clip_key == f"visual-risk/{digest}/clip.webp"
    assert "family" not in snapshot_key
    snapshot_path = tmp_path / "guardian-evidence" / snapshot_key
    clip_path = tmp_path / "guardian-evidence" / clip_key
    with Image.open(snapshot_path) as snapshot:
        assert snapshot.format == "JPEG"
        assert snapshot.size == (32, 18)
    with Image.open(clip_path) as clip:
        assert clip.format == "WEBP"
        assert clip.is_animated is True
        assert clip.n_frames == 3
    assert stat.S_IMODE(snapshot_path.parent.stat().st_mode) == 0o700
    assert stat.S_IMODE(snapshot_path.stat().st_mode) == 0o600
    assert stat.S_IMODE(clip_path.stat().st_mode) == 0o600


def test_invalid_safe_frame_leaves_no_media_artifact(tmp_path: Path) -> None:
    files = GuardianEvidenceFiles(tmp_path / "guardian-evidence")
    invalid = PreparedAnalysisFrame(
        jpeg=b"not-a-jpeg",
        captured_at=NOW,
        width=32,
        height=18,
        crop_box=(0, 0, 32, 18),
    )

    with pytest.raises(ValueError, match="safe frame"):
        files.write_snapshot("event-face", invalid)
    with pytest.raises(ValueError, match="safe frame"):
        files.write_clip("event-face", (safe_frame(0, (1, 2, 3)), invalid))

    assert list((tmp_path / "guardian-evidence").rglob("*.jpg")) == []
    assert list((tmp_path / "guardian-evidence").rglob("*.webp")) == []


def test_empty_clip_is_rejected_without_creating_a_directory(tmp_path: Path) -> None:
    files = GuardianEvidenceFiles(tmp_path / "guardian-evidence")

    with pytest.raises(ValueError, match="at least one"):
        files.write_clip("event-face", ())

    assert not (tmp_path / "guardian-evidence").exists()


def test_usage_and_event_delete_are_exact_idempotent_and_isolated(
    tmp_path: Path,
) -> None:
    root = tmp_path / "guardian-evidence"
    files = GuardianEvidenceFiles(root)
    frame = safe_frame(0, (1, 2, 3))
    first_snapshot = files.write_snapshot("event-first", frame)
    first_clip = files.write_clip("event-first", (frame,))
    second_snapshot = files.write_snapshot("event-second", frame)
    unmanaged = root / "unmanaged.bin"
    unmanaged.write_bytes(b"unmanaged")

    first_size = (
        (root / first_snapshot).stat().st_size
        + (root / first_clip).stat().st_size
    )
    total_size = (
        first_size
        + (root / second_snapshot).stat().st_size
        + len(b"unmanaged")
    )

    assert files.event_bytes("event-first") == first_size
    assert files.total_bytes() == total_size
    assert files.delete_event("event-first") == first_size
    assert files.event_bytes("event-first") == 0
    assert files.delete_event("event-first") == 0
    assert (root / second_snapshot).is_file()
    assert unmanaged.read_bytes() == b"unmanaged"
    assert files.total_bytes() == total_size - first_size


def test_event_delete_rejects_unexpected_entry_without_partial_deletion(
    tmp_path: Path,
) -> None:
    root = tmp_path / "guardian-evidence"
    files = GuardianEvidenceFiles(root)
    snapshot_key = files.write_snapshot("event-unsafe", safe_frame(0, (1, 2, 3)))
    event_directory = (root / snapshot_key).parent
    unexpected = event_directory / "notes.txt"
    unexpected.write_text("private", encoding="utf-8")

    with pytest.raises(ValueError, match="unsafe evidence entry"):
        files.delete_event("event-unsafe")

    assert (root / snapshot_key).is_file()
    assert unexpected.is_file()


def test_usage_and_delete_never_follow_symbolic_links(tmp_path: Path) -> None:
    root = tmp_path / "guardian-evidence"
    files = GuardianEvidenceFiles(root)
    snapshot_key = files.write_snapshot("event-linked", safe_frame(0, (1, 2, 3)))
    event_directory = (root / snapshot_key).parent
    target = tmp_path / "outside-private.bin"
    target.write_bytes(b"must-remain")
    (event_directory / "clip.webp").symlink_to(target)

    with pytest.raises(ValueError, match="unsafe evidence entry"):
        files.event_bytes("event-linked")
    with pytest.raises(ValueError, match="unsafe evidence entry"):
        files.delete_event("event-linked")
    with pytest.raises(ValueError, match="unsafe evidence entry"):
        files.total_bytes()

    assert target.read_bytes() == b"must-remain"
    assert (root / snapshot_key).is_file()


@pytest.mark.parametrize("symlink_level", ["root", "visual-risk"])
def test_event_delete_rejects_symlinked_ancestor_without_external_deletion(
    tmp_path: Path,
    symlink_level: str,
) -> None:
    root = tmp_path / "guardian-evidence"
    outside = tmp_path / "outside-evidence"
    digest = hashlib.sha256(b"event-escape").hexdigest()
    if symlink_level == "root":
        event_directory = outside / "visual-risk" / digest
        root.symlink_to(outside, target_is_directory=True)
    else:
        root.mkdir()
        event_directory = outside / digest
        (root / "visual-risk").symlink_to(outside, target_is_directory=True)
    event_directory.mkdir(parents=True)
    snapshot = event_directory / "snapshot.jpg"
    clip = event_directory / "clip.webp"
    snapshot.write_bytes(b"outside-snapshot")
    clip.write_bytes(b"outside-clip")

    files = GuardianEvidenceFiles(root)
    with pytest.raises((OSError, ValueError)):
        files.delete_event("event-escape")

    assert snapshot.read_bytes() == b"outside-snapshot"
    assert clip.read_bytes() == b"outside-clip"
    assert event_directory.is_dir()
