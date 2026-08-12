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
