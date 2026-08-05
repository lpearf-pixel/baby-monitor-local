from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

from packages.monitoring.go2rtc_build import (
    BuildMetadata,
    Go2RTCBuildError,
    install_candidate,
    metadata_matches,
    rollback_latest,
    verify_and_apply_patch,
)


ROOT = Path(__file__).resolve().parents[2]


def _git(repo: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", *args],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def _source_repo(tmp_path: Path) -> tuple[Path, str]:
    source = tmp_path / "go2rtc"
    (source / "pkg/xiaomi/miss/cs2").mkdir(parents=True)
    (source / "pkg/iso").mkdir(parents=True)
    (source / "pkg/xiaomi/miss/cs2/conn.go").write_text(
        'conn, err := net.ListenUDP("udp", nil)\n',
        encoding="utf-8",
    )
    (source / "pkg/iso/codecs.go").write_text(
        'case core.CodecH265:\n\tm.StartAtom("hev1")\n',
        encoding="utf-8",
    )
    _git(source, "init", "-q")
    _git(source, "config", "user.email", "tests@example.invalid")
    _git(source, "config", "user.name", "Tests")
    _git(source, "add", ".")
    _git(source, "commit", "-qm", "fixture")
    return source, _git(source, "rev-parse", "HEAD")


def _compat_patch(path: Path, *, extra_file: bool = False) -> Path:
    content = """diff --git a/pkg/xiaomi/miss/cs2/conn.go b/pkg/xiaomi/miss/cs2/conn.go
--- a/pkg/xiaomi/miss/cs2/conn.go
+++ b/pkg/xiaomi/miss/cs2/conn.go
@@ -1 +1 @@
-conn, err := net.ListenUDP(\"udp\", nil)
+conn, err := net.ListenUDP(\"udp4\", nil)
diff --git a/pkg/iso/codecs.go b/pkg/iso/codecs.go
--- a/pkg/iso/codecs.go
+++ b/pkg/iso/codecs.go
@@ -1,2 +1,2 @@
 case core.CodecH265:
-\tm.StartAtom(\"hev1\")
+\tm.StartAtom(\"hvc1\")
"""
    if extra_file:
        content += """diff --git a/README.md b/README.md
--- /dev/null
+++ b/README.md
@@ -0,0 +1 @@
+unexpected
"""
    path.write_text(content, encoding="utf-8")
    return path


def test_verify_and_apply_patch_changes_only_udp_socket_and_hevc_sample_entry(
    tmp_path: Path,
) -> None:
    source, head = _source_repo(tmp_path)
    patch = _compat_patch(tmp_path / "compat.patch")

    result = verify_and_apply_patch(source, patch, expected_commit=head)

    assert result == head
    assert 'ListenUDP("udp4", nil)' in (
        source / "pkg/xiaomi/miss/cs2/conn.go"
    ).read_text(encoding="utf-8")
    assert 'StartAtom("hvc1")' in (source / "pkg/iso/codecs.go").read_text(
        encoding="utf-8"
    )
    assert _git(source, "diff", "--name-only").splitlines() == [
        "pkg/iso/codecs.go",
        "pkg/xiaomi/miss/cs2/conn.go",
    ]


def test_verify_and_apply_patch_rejects_wrong_commit_without_modifying_source(
    tmp_path: Path,
) -> None:
    source, _head = _source_repo(tmp_path)
    before = _git(source, "status", "--porcelain")

    with pytest.raises(Go2RTCBuildError, match="UPSTREAM_COMMIT_MISMATCH"):
        verify_and_apply_patch(
            source,
            _compat_patch(tmp_path / "compat.patch"),
            expected_commit="0" * 40,
        )

    assert _git(source, "status", "--porcelain") == before


def test_verify_and_apply_patch_rejects_changes_outside_allowlist(
    tmp_path: Path,
) -> None:
    source, head = _source_repo(tmp_path)

    with pytest.raises(Go2RTCBuildError, match="PATCH_SCOPE_INVALID"):
        verify_and_apply_patch(
            source,
            _compat_patch(tmp_path / "compat.patch", extra_file=True),
            expected_commit=head,
        )

    assert _git(source, "status", "--porcelain") == ""


def _executable(path: Path, payload: bytes) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(payload)
    path.chmod(0o755)
    return path


def _metadata(candidate: Path, **overrides: str) -> BuildMetadata:
    values = {
        "upstream_commit": "a" * 40,
        "go_version": "go1.24.5",
        "patch_sha256": "b" * 64,
        "binary_sha256": hashlib.sha256(candidate.read_bytes()).hexdigest(),
        "build_time": "2026-08-04T20:00:00+00:00",
        "platform": "darwin/amd64",
    }
    values.update(overrides)
    return BuildMetadata(**values)


def test_install_candidate_backs_up_old_binary_and_writes_verified_metadata(
    tmp_path: Path,
) -> None:
    destination = _executable(tmp_path / "bin/go2rtc", b"old-binary")
    candidate = _executable(tmp_path / "candidate", b"new-binary")
    metadata_path = tmp_path / "build/go2rtc.json"
    metadata = _metadata(candidate)

    backup = install_candidate(
        candidate,
        destination,
        tmp_path / "backups",
        metadata_path,
        metadata,
        datetime(2026, 8, 4, 20, 0, tzinfo=timezone.utc),
    )

    assert destination.read_bytes() == b"new-binary"
    assert destination.stat().st_mode & 0o777 == 0o755
    assert backup is not None
    assert (backup / "go2rtc").read_bytes() == b"old-binary"
    assert json.loads(metadata_path.read_text(encoding="utf-8")) == metadata.as_dict()


def test_install_candidate_rejects_wrong_binary_hash_without_touching_old_binary(
    tmp_path: Path,
) -> None:
    destination = _executable(tmp_path / "bin/go2rtc", b"known-good")
    candidate = _executable(tmp_path / "candidate", b"candidate")
    metadata = _metadata(candidate, binary_sha256="0" * 64)

    with pytest.raises(Go2RTCBuildError, match="CANDIDATE_HASH_MISMATCH"):
        install_candidate(
            candidate,
            destination,
            tmp_path / "backups",
            tmp_path / "build/go2rtc.json",
            metadata,
            datetime(2026, 8, 4, 20, 0, tzinfo=timezone.utc),
        )

    assert destination.read_bytes() == b"known-good"
    assert not (tmp_path / "backups").exists()


def test_metadata_matches_requires_exact_commit_patch_and_platform(tmp_path: Path) -> None:
    candidate = _executable(tmp_path / "candidate", b"candidate")
    metadata = _metadata(candidate)
    metadata_path = tmp_path / "go2rtc.json"
    metadata_path.write_text(json.dumps(metadata.as_dict()), encoding="utf-8")

    assert metadata_matches(
        metadata_path,
        upstream_commit="a" * 40,
        patch_sha256="b" * 64,
        platform="darwin/amd64",
    )
    assert not metadata_matches(
        metadata_path,
        upstream_commit="c" * 40,
        patch_sha256="b" * 64,
        platform="darwin/amd64",
    )
    assert not metadata_matches(
        metadata_path,
        upstream_commit="a" * 40,
        patch_sha256="d" * 64,
        platform="darwin/amd64",
    )
    assert not metadata_matches(
        metadata_path,
        upstream_commit="a" * 40,
        patch_sha256="b" * 64,
        platform="linux/amd64",
    )


def test_rollback_backs_up_current_binary_then_restores_latest_valid_backup(
    tmp_path: Path,
) -> None:
    destination = _executable(tmp_path / "bin/go2rtc", b"current")
    metadata_path = tmp_path / "build/go2rtc.json"
    metadata_path.parent.mkdir(parents=True)
    current_metadata = _metadata(destination, build_time="2026-08-04T22:00:00+00:00")
    metadata_path.write_text(json.dumps(current_metadata.as_dict()), encoding="utf-8")
    backups = tmp_path / "backups"

    older = backups / "20260804-190000-older"
    older_candidate = _executable(older / "go2rtc", b"older")
    older_metadata = _metadata(
        older_candidate,
        binary_sha256=hashlib.sha256(b"older").hexdigest(),
        build_time="2026-08-04T19:00:00+00:00",
    )
    (older / "build.json").write_text(
        json.dumps(older_metadata.as_dict()), encoding="utf-8"
    )

    latest = backups / "20260804-200000-latest"
    latest_candidate = _executable(latest / "go2rtc", b"latest")
    latest_metadata = _metadata(
        latest_candidate,
        binary_sha256=hashlib.sha256(b"latest").hexdigest(),
        build_time="2026-08-04T20:00:00+00:00",
    )
    (latest / "build.json").write_text(
        json.dumps(latest_metadata.as_dict()), encoding="utf-8"
    )

    restored = rollback_latest(
        destination,
        backups,
        metadata_path,
        datetime(2026, 8, 4, 23, 0, tzinfo=timezone.utc),
    )

    assert restored == latest
    assert destination.read_bytes() == b"latest"
    assert json.loads(metadata_path.read_text(encoding="utf-8")) == (
        latest_metadata.as_dict()
    )
    current_backup = backups / (
        "20260804-230000-" + hashlib.sha256(b"current").hexdigest()[:12]
    )
    assert (current_backup / "go2rtc").read_bytes() == b"current"
    assert json.loads((current_backup / "build.json").read_text()) == (
        current_metadata.as_dict()
    )


def test_rollback_rejects_missing_valid_backup_without_touching_current(
    tmp_path: Path,
) -> None:
    destination = _executable(tmp_path / "bin/go2rtc", b"current")
    invalid = tmp_path / "backups/20260804-200000-invalid"
    _executable(invalid / "go2rtc", b"invalid")
    (invalid / "build.json").write_text("{}", encoding="utf-8")

    with pytest.raises(Go2RTCBuildError, match="NO_VALID_BACKUP"):
        rollback_latest(
            destination,
            tmp_path / "backups",
            tmp_path / "build/go2rtc.json",
            datetime(2026, 8, 4, 23, 0, tzinfo=timezone.utc),
        )

    assert destination.read_bytes() == b"current"


def test_build_cli_info_prints_only_allowlisted_metadata(tmp_path: Path) -> None:
    binary = _executable(tmp_path / ".local/bin/go2rtc", b"candidate")
    metadata = _metadata(binary)
    metadata_path = tmp_path / "runtime/build/go2rtc.json"
    metadata_path.parent.mkdir(parents=True)
    metadata_path.write_text(json.dumps(metadata.as_dict()), encoding="utf-8")

    result = subprocess.run(
        [
            sys.executable,
            str(ROOT / "tools/go2rtc_build.py"),
            "--root",
            str(tmp_path),
            "info",
        ],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0
    assert result.stderr == ""
    assert result.stdout.splitlines() == [
        f"upstream_commit={metadata.upstream_commit}",
        f"go_version={metadata.go_version}",
        f"patch_sha256={metadata.patch_sha256}",
        f"binary_sha256={metadata.binary_sha256}",
        f"build_time={metadata.build_time}",
        f"platform={metadata.platform}",
    ]


def test_build_cli_help_exposes_only_fixed_lifecycle_commands() -> None:
    result = subprocess.run(
        [sys.executable, str(ROOT / "tools/go2rtc_build.py"), "--help"],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0
    for command in ("ensure", "rebuild", "info", "rollback"):
        assert command in result.stdout
