from __future__ import annotations

import hashlib
import json
import plistlib
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

from packages.monitoring.go2rtc_build import (
    ALLOWED_PATCH_CHANGES,
    BuildMetadata,
    Go2RTCBuildError,
    install_candidate,
    metadata_matches,
    rollback_latest,
    run_upstream_protocol_diagnostic_gate,
    run_upstream_protocol_gate,
    verify_and_apply_patch,
)
from packages.monitoring import go2rtc_build as go2rtc_build_module
from tools import go2rtc_build as go2rtc_build_cli


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


def _materialize_patch_preimage(source: Path, content: str) -> None:
    sections = re.split(r"(?m)(?=^diff --git )", content)
    for section in sections:
        match = re.match(r"diff --git a/(.+) b/(.+)\n", section)
        if match is None or "\n--- /dev/null\n" in section:
            continue
        relative = match.group(1)
        hunks = list(
            re.finditer(
                r"(?m)^@@ -(\d+)(?:,(\d+))? \+\d+(?:,\d+)? @@.*\n",
                section,
            )
        )
        lines: list[str] = []
        for index, hunk in enumerate(hunks):
            old_start = int(hunk.group(1))
            old_count = int(hunk.group(2) or "1")
            body_end = hunks[index + 1].start() if index + 1 < len(hunks) else len(section)
            old_lines = [
                line[1:]
                for line in section[hunk.end() : body_end].splitlines(keepends=True)
                if line.startswith((" ", "-"))
            ]
            assert len(old_lines) == old_count
            while len(lines) < old_start - 1:
                lines.append("// synthetic upstream filler\n")
            assert len(lines) == old_start - 1
            lines.extend(old_lines)
        path = source / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("".join(lines), encoding="utf-8")


def _source_repo(tmp_path: Path) -> tuple[Path, str]:
    source = tmp_path / "go2rtc"
    source.mkdir()
    content = (ROOT / "patches/go2rtc-macos-hybrid-hd.patch").read_text(
        encoding="utf-8"
    )
    _materialize_patch_preimage(source, content)
    _git(source, "init", "-q")
    _git(source, "config", "user.email", "tests@example.invalid")
    _git(source, "config", "user.name", "Tests")
    _git(source, "add", ".")
    _git(source, "commit", "-qm", "fixture")
    return source, _git(source, "rev-parse", "HEAD")


def _compat_patch(
    path: Path, *, extra_file: bool = False, include_regression: bool = True
) -> Path:
    content = (ROOT / "patches/go2rtc-macos-hybrid-hd.patch").read_text(
        encoding="utf-8"
    )
    if not include_regression:
        marker = "diff --git a/pkg/xiaomi/miss/cs2/conn_test.go"
        sections = re.split(r"(?m)(?=^diff --git )", content)
        content = "".join(
            section for section in sections if not section.startswith(marker)
        )
    if extra_file:
        content += """diff --git a/README.md b/README.md
--- /dev/null
+++ b/README.md
@@ -0,0 +1 @@
+unexpected
"""
    path.write_text(content, encoding="utf-8")
    return path


def test_verify_and_apply_patch_changes_only_approved_protocol_paths(
    tmp_path: Path,
) -> None:
    source, head = _source_repo(tmp_path)
    patch = _compat_patch(tmp_path / "compat.patch")

    result = verify_and_apply_patch(source, patch, expected_commit=head)

    assert result == head
    cs2 = (source / "pkg/xiaomi/miss/cs2/conn.go").read_text(encoding="utf-8")
    assert 'ListenUDP("udp4", nil)' in cs2
    assert 'ListenUDP("udp", nil)' not in cs2
    assert 'copy(req[offset+hdrSize:], payload)' in cs2
    assert 'copy(req[offset+hdrSize:], hdr)' not in cs2
    assert 'StartAtom("hvc1")' in (source / "pkg/iso/codecs.go").read_text(
        encoding="utf-8"
    )
    lifecycle = (source / "pkg/xiaomi/miss/lifecycle_review_test.go").read_text(
        encoding="utf-8"
    )
    playback = (
        source / "internal/streams/play_lifecycle_review_test.go"
    ).read_text(encoding="utf-8")
    for name in (
        "TestRepeatedSpeakerLifecycleKeepsMediaReadable",
        "TestReadTimeoutClassificationIsPayloadFree",
    ):
        assert f"func {name}" in lifecycle
    for name in (
        "TestPlaybackSettlementDoesNotReplaceProducer",
        "TestReconnectBackoffDoesNotDuplicateWorkers",
    ):
        assert f"func {name}" in playback
    producer = (source / "pkg/xiaomi/miss/producer.go").read_text(encoding="utf-8")
    assert 'errors.New("xiaomi: media read timeout")' in producer
    changed = set(_git(source, "diff", "--name-only").splitlines())
    changed.update(
        _git(source, "ls-files", "--others", "--exclude-standard").splitlines()
    )
    assert sorted(changed) == [
        "internal/streams/play.go",
        "internal/streams/play_lifecycle_review_test.go",
        "internal/streams/stream.go",
        "pkg/iso/codecs.go",
        "pkg/xiaomi/miss/backchannel.go",
        "pkg/xiaomi/miss/client.go",
        "pkg/xiaomi/miss/cs2/conn.go",
        "pkg/xiaomi/miss/cs2/conn_test.go",
        "pkg/xiaomi/miss/cs2/lifecycle_review_test.go",
        "pkg/xiaomi/miss/lifecycle_review_test.go",
        "pkg/xiaomi/miss/producer.go",
    ]


def test_patch_scope_is_exact_and_requires_the_upstream_regression() -> None:
    assert ALLOWED_PATCH_CHANGES == {
        "internal/streams/play.go": (168, 13),
        "internal/streams/play_lifecycle_review_test.go": (305, 0),
        "internal/streams/stream.go": (1, 0),
        "pkg/iso/codecs.go": (1, 1),
        "pkg/xiaomi/miss/backchannel.go": (49, 9),
        "pkg/xiaomi/miss/client.go": (468, 4),
        "pkg/xiaomi/miss/cs2/conn.go": (63, 12),
        "pkg/xiaomi/miss/cs2/conn_test.go": (95, 0),
        "pkg/xiaomi/miss/cs2/lifecycle_review_test.go": (135, 0),
        "pkg/xiaomi/miss/lifecycle_review_test.go": (809, 0),
        "pkg/xiaomi/miss/producer.go": (35, 1),
    }


def test_patch_numstat_rejects_duplicate_path_entries(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    output = "1\t0\tpkg/xiaomi/miss/client.go\n2\t0\tpkg/xiaomi/miss/client.go\n"
    monkeypatch.setattr(
        go2rtc_build_module.subprocess,
        "run",
        lambda *_args, **_kwargs: subprocess.CompletedProcess(
            ["git", "apply", "--numstat"], 0, stdout=output
        ),
    )

    with pytest.raises(Go2RTCBuildError, match="^PATCH_SCOPE_INVALID$"):
        go2rtc_build_module._patch_numstat(tmp_path, tmp_path / "patch")


def test_verify_and_apply_patch_rejects_missing_protocol_regression(
    tmp_path: Path,
) -> None:
    source, head = _source_repo(tmp_path)

    with pytest.raises(Go2RTCBuildError, match="PATCH_SCOPE_INVALID"):
        verify_and_apply_patch(
            source,
            _compat_patch(
                tmp_path / "compat.patch", include_regression=False
            ),
            expected_commit=head,
        )

    assert _git(source, "status", "--porcelain") == ""


def test_run_upstream_protocol_gate_uses_fixed_lifecycle_commands(tmp_path: Path) -> None:
    calls: list[tuple[list[str], dict[str, object]]] = []

    def runner(args: list[str], **kwargs: object) -> subprocess.CompletedProcess[bytes]:
        calls.append((args, kwargs))
        return subprocess.CompletedProcess(args, 0)

    run_upstream_protocol_gate(tmp_path, "/fixed/go", runner=runner)

    assert calls == [
        (
            [
                "/fixed/go",
                "test",
                "./pkg/xiaomi/miss/cs2",
                "-run",
                "^(TestWritePacketCopiesPayload|TestWritePacketRejectsEmptyAndAdvancesChannel3Sequence|TestRepeatedSpeakerResponsesDoNotCloseMediaChannel|TestCommandChannel)",
                "-count=1",
            ],
            {
                "cwd": tmp_path,
                "check": True,
                "stdin": subprocess.DEVNULL,
                "stdout": subprocess.DEVNULL,
                "stderr": subprocess.DEVNULL,
                "timeout": 120,
            },
        ),
        (
            [
                "/fixed/go",
                "test",
                "./pkg/xiaomi/miss",
                "-run",
                "^(TestSpeakerLifecycle|TestRepeatedSpeakerLifecycle)",
                "-count=1",
            ],
            {
                "cwd": tmp_path,
                "check": True,
                "stdin": subprocess.DEVNULL,
                "stdout": subprocess.DEVNULL,
                "stderr": subprocess.DEVNULL,
                "timeout": 120,
            },
        ),
        (
            [
                "/fixed/go",
                "test",
                "./internal/streams",
                "-run",
                "^(TestPlayEmpty|TestNaturalSourceEnd|TestNaturalSourceEOF|TestCancelAndNaturalEnd)",
                "-count=1",
            ],
            {
                "cwd": tmp_path,
                "check": True,
                "stdin": subprocess.DEVNULL,
                "stdout": subprocess.DEVNULL,
                "stderr": subprocess.DEVNULL,
                "timeout": 120,
            },
        ),
    ]


@pytest.mark.parametrize(
    "failure",
    (OSError("missing"), subprocess.CalledProcessError(1, ["go", "test"])),
)
def test_run_upstream_protocol_gate_redacts_every_failure(
    tmp_path: Path, failure: BaseException
) -> None:
    def runner(*_args: object, **_kwargs: object) -> subprocess.CompletedProcess[bytes]:
        raise failure

    with pytest.raises(Go2RTCBuildError, match="^GO2RTC_PROTOCOL_GATE_FAILED$"):
        run_upstream_protocol_gate(tmp_path, "/fixed/go", runner=runner)


def test_run_upstream_protocol_diagnostic_gate_uses_fixed_focused_and_race_commands(
    tmp_path: Path,
) -> None:
    calls: list[list[str]] = []

    def runner(args: list[str], **_kwargs: object) -> subprocess.CompletedProcess[bytes]:
        calls.append(args)
        return subprocess.CompletedProcess(args, 0)

    run_upstream_protocol_diagnostic_gate(tmp_path, "/fixed/go", runner=runner)

    assert calls == [
        [
            "/fixed/go",
            "test",
            "./pkg/xiaomi/miss/cs2",
            "./pkg/xiaomi/miss",
            "./internal/streams",
            "-run",
            "^(TestWritePacketRejectsEmptyAndAdvancesChannel3Sequence|TestSpeakerLifecycleCountsOnlySuccessfulOpusPayload|TestSpeakerLifecycleReportsSuccessfulOpusPacketsAndBytes|TestRepeatedSpeakerLifecycleKeepsMediaReadable|TestPlaybackSettlementDoesNotReplaceProducer|TestReconnectBackoffDoesNotDuplicateWorkers|TestReadTimeoutClassificationIsPayloadFree)$",
            "-count=1",
        ],
        [
            "/fixed/go",
            "test",
            "-race",
            "./pkg/xiaomi/miss/cs2",
            "./pkg/xiaomi/miss",
            "./internal/streams",
            "-run",
            "^(TestWritePacketRejectsEmptyAndAdvancesChannel3Sequence|TestSpeakerLifecycleCountsOnlySuccessfulOpusPayload|TestSpeakerLifecycleReportsSuccessfulOpusPacketsAndBytes|TestRepeatedSpeakerLifecycleKeepsMediaReadable|TestPlaybackSettlementDoesNotReplaceProducer|TestReconnectBackoffDoesNotDuplicateWorkers|TestReadTimeoutClassificationIsPayloadFree)$",
            "-count=1",
        ],
    ]


@pytest.mark.parametrize(
    "failure",
    (OSError("private"), subprocess.CalledProcessError(1, ["go", "test"])),
)
def test_run_upstream_protocol_diagnostic_gate_redacts_every_failure(
    tmp_path: Path, failure: BaseException
) -> None:
    def runner(*_args: object, **_kwargs: object) -> subprocess.CompletedProcess[bytes]:
        raise failure

    with pytest.raises(
        Go2RTCBuildError, match="^GO2RTC_PROTOCOL_DIAGNOSTIC_FAILED$"
    ):
        run_upstream_protocol_diagnostic_gate(tmp_path, "/fixed/go", runner=runner)


def test_protocol_test_clones_pinned_patch_without_installing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    patch = tmp_path / "patches/go2rtc-macos-hybrid-hd.patch"
    patch.parent.mkdir(parents=True)
    patch.write_text("synthetic", encoding="ascii")
    commands: list[list[str]] = []
    applied: list[tuple[Path, Path]] = []
    gated: list[tuple[Path, str]] = []
    monkeypatch.setattr(go2rtc_build_cli, "_platform_guard", lambda: None)
    monkeypatch.setattr(
        go2rtc_build_cli,
        "_go_toolchain",
        lambda: ("/fixed/go", "go1.24.13", {"PATH": "/fixed"}),
    )
    monkeypatch.setattr(
        go2rtc_build_cli,
        "_run",
        lambda args, **_kwargs: commands.append(args) or "",
    )
    monkeypatch.setattr(
        go2rtc_build_cli,
        "verify_and_apply_patch",
        lambda source, patch_path: applied.append((source, patch_path))
        or go2rtc_build_module.GO2RTC_COMMIT,
    )
    monkeypatch.setattr(
        go2rtc_build_cli,
        "run_upstream_protocol_diagnostic_gate",
        lambda source, go, **_kwargs: gated.append((source, go)),
    )

    go2rtc_build_cli._protocol_test(tmp_path)

    assert commands[0][:4] == ["git", "clone", "--filter=blob:none", "--no-checkout"]
    assert commands[1] == [
        "git",
        "checkout",
        "--detach",
        go2rtc_build_module.GO2RTC_COMMIT,
    ]
    assert len(applied) == 1
    assert applied[0][1] == patch.resolve()
    assert gated == [(applied[0][0], "/fixed/go")]
    assert not any(
        token in command
        for command in commands
        for token in ("build", "codesign", "install", "launchctl")
    )
    assert capsys.readouterr().out == (
        "go2rtc_protocol_test=D2_BOUNDARY_HARDENED_CAUSE_UNPROVEN\n"
    )


def test_build_runs_protocol_gate_before_compiling_candidate() -> None:
    source = Path(go2rtc_build_cli.__file__).read_text(encoding="utf-8")

    assert source.index("run_upstream_protocol_gate(") < source.index(
        '[go, "build", "-trimpath"'
    )


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


def test_install_macos_app_bundle_gives_launchd_a_stable_network_identity(
    tmp_path: Path,
) -> None:
    binary = _executable(tmp_path / "bin/go2rtc", b"go2rtc-binary")
    app_bundle = tmp_path / "Go2RTC.app"
    signed: list[Path] = []

    executable = go2rtc_build_module.install_macos_app_bundle(
        binary,
        app_bundle,
        signer=signed.append,
    )

    assert executable == app_bundle / "Contents/MacOS/go2rtc"
    assert executable.read_bytes() == b"go2rtc-binary"
    assert executable.stat().st_mode & 0o777 == 0o755
    with (app_bundle / "Contents/Info.plist").open("rb") as handle:
        info = plistlib.load(handle)
    assert info == {
        "CFBundleDevelopmentRegion": "en",
        "CFBundleExecutable": "go2rtc",
        "CFBundleIdentifier": "com.babymonitor.go2rtc",
        "CFBundleInfoDictionaryVersion": "6.0",
        "CFBundleName": "Baby Monitor go2rtc",
        "CFBundlePackageType": "APPL",
        "CFBundleShortVersionString": "1.0",
        "CFBundleVersion": "1",
        "LSUIElement": True,
        "NSLocalNetworkUsageDescription": (
            "Baby Monitor Local connects to the configured camera on your private network."
        ),
    }
    assert signed == [app_bundle]


def test_unchanged_build_still_refreshes_signed_macos_app_bundle(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    binary = _executable(tmp_path / ".local/bin/go2rtc", b"current-binary")
    patch = tmp_path / "patches/go2rtc-macos-hybrid-hd.patch"
    patch.parent.mkdir(parents=True)
    patch.write_bytes(b"pinned-patch")
    metadata = BuildMetadata(
        upstream_commit=go2rtc_build_module.GO2RTC_COMMIT,
        go_version="go1.24.5",
        patch_sha256=hashlib.sha256(patch.read_bytes()).hexdigest(),
        binary_sha256=hashlib.sha256(binary.read_bytes()).hexdigest(),
        build_time="2026-08-20T18:00:00+00:00",
        platform="darwin/amd64",
    )
    metadata_path = tmp_path / "runtime/build/go2rtc.json"
    metadata_path.parent.mkdir(parents=True)
    metadata_path.write_text(json.dumps(metadata.as_dict()), encoding="utf-8")
    commands: list[list[str]] = []
    monkeypatch.setattr(go2rtc_build_cli.platform, "system", lambda: "Darwin")
    monkeypatch.setattr(go2rtc_build_cli.platform, "machine", lambda: "x86_64")
    monkeypatch.setattr(
        go2rtc_build_cli,
        "_run",
        lambda args, **_kwargs: commands.append(args) or "",
    )

    go2rtc_build_cli._build(tmp_path, force=False)

    app_bundle = tmp_path / ".local/Go2RTC.app"
    assert (app_bundle / "Contents/MacOS/go2rtc").read_bytes() == b"current-binary"
    assert commands == [
        [
            "codesign",
            "--force",
            "--deep",
            "--sign",
            "-",
            "--requirements",
            '=designated => identifier "com.babymonitor.go2rtc"',
            str(app_bundle),
        ],
        [
            "codesign",
            "--verify",
            "--deep",
            "--strict",
            "--requirements",
            '=designated => identifier "com.babymonitor.go2rtc"',
            str(app_bundle),
        ],
    ]


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
