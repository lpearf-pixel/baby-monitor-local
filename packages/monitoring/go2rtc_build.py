from __future__ import annotations

import hashlib
import json
import os
import plistlib
import shutil
import subprocess
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Callable


GO2RTC_COMMIT = "b465651a94c1f637d566a8c660b4fad102b35153"
GO2RTC_BUNDLE_IDENTIFIER = "com.babymonitor.go2rtc"
GO2RTC_DESIGNATED_REQUIREMENT = (
    f'=designated => identifier "{GO2RTC_BUNDLE_IDENTIFIER}"'
)
ALLOWED_PATCH_CHANGES = {
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
PROTOCOL_GATE_TIMEOUT_SECONDS = 120


class Go2RTCBuildError(RuntimeError):
    """Raised when the pinned go2rtc build cannot be verified safely."""


@dataclass(frozen=True)
class BuildMetadata:
    upstream_commit: str
    go_version: str
    patch_sha256: str
    binary_sha256: str
    build_time: str
    platform: str

    def as_dict(self) -> dict[str, str]:
        return asdict(self)


METADATA_FIELDS = frozenset(BuildMetadata.__dataclass_fields__)


def install_macos_app_bundle(
    binary: Path,
    app_bundle: Path,
    *,
    signer: Callable[[Path], object],
) -> Path:
    binary = binary.resolve()
    app_bundle = app_bundle.resolve()
    if not binary.is_file() or not os.access(binary, os.X_OK):
        raise Go2RTCBuildError("GO2RTC_BUILD_NOT_FOUND")

    contents = app_bundle / "Contents"
    executable = contents / "MacOS/go2rtc"
    executable.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(binary, executable)
    executable.chmod(0o755)
    info = {
        "CFBundleDevelopmentRegion": "en",
        "CFBundleExecutable": "go2rtc",
        "CFBundleIdentifier": GO2RTC_BUNDLE_IDENTIFIER,
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
    with (contents / "Info.plist").open("wb") as handle:
        plistlib.dump(info, handle, fmt=plistlib.FMT_XML, sort_keys=True)
    signer(app_bundle)
    return executable


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _read_metadata(path: Path) -> dict[str, Any] | None:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if (
        not isinstance(payload, dict)
        or set(payload) != METADATA_FIELDS
        or not all(isinstance(value, str) and value for value in payload.values())
    ):
        return None
    return payload


def read_metadata(path: Path) -> BuildMetadata | None:
    payload = _read_metadata(path)
    return BuildMetadata(**payload) if payload is not None else None


def metadata_matches(
    path: Path,
    *,
    upstream_commit: str,
    patch_sha256: str,
    platform: str,
) -> bool:
    payload = _read_metadata(path)
    return bool(
        payload
        and payload["upstream_commit"] == upstream_commit
        and payload["patch_sha256"] == patch_sha256
        and payload["platform"] == platform
    )


def install_candidate(
    candidate: Path,
    destination: Path,
    backups_root: Path,
    metadata_path: Path,
    metadata: BuildMetadata,
    now: datetime,
) -> Path | None:
    candidate = candidate.resolve()
    destination = destination.resolve()
    metadata_path = metadata_path.resolve()
    if not candidate.is_file() or not os.access(candidate, os.X_OK):
        raise Go2RTCBuildError("CANDIDATE_INVALID")
    if sha256_file(candidate) != metadata.binary_sha256:
        raise Go2RTCBuildError("CANDIDATE_HASH_MISMATCH")

    destination.parent.mkdir(parents=True, exist_ok=True)
    metadata_path.parent.mkdir(parents=True, exist_ok=True)
    binary_stage = destination.with_name(f".{destination.name}.tmp-{os.getpid()}")
    metadata_stage = metadata_path.with_name(
        f".{metadata_path.name}.tmp-{os.getpid()}"
    )
    backup: Path | None = None
    old_binary_exists = destination.is_file()

    try:
        shutil.copy2(candidate, binary_stage)
        binary_stage.chmod(0o755)
        if sha256_file(binary_stage) != metadata.binary_sha256:
            raise Go2RTCBuildError("CANDIDATE_HASH_MISMATCH")

        metadata_stage.write_text(
            json.dumps(metadata.as_dict(), sort_keys=True, indent=2) + "\n",
            encoding="utf-8",
        )
        if _read_metadata(metadata_stage) != metadata.as_dict():
            raise Go2RTCBuildError("METADATA_INVALID")

        if old_binary_exists:
            old_sha = sha256_file(destination)
            backup = backups_root.resolve() / (
                f"{now.strftime('%Y%m%d-%H%M%S')}-{old_sha[:12]}"
            )
            backup.mkdir(parents=True, exist_ok=False)
            shutil.copy2(destination, backup / "go2rtc")
            if metadata_path.is_file():
                shutil.copy2(metadata_path, backup / "build.json")

        binary_stage.replace(destination)
        try:
            metadata_stage.replace(metadata_path)
        except OSError as exc:
            if backup is not None:
                shutil.copy2(backup / "go2rtc", destination)
            else:
                destination.unlink(missing_ok=True)
            raise Go2RTCBuildError("METADATA_INSTALL_FAILED") from exc
    finally:
        binary_stage.unlink(missing_ok=True)
        metadata_stage.unlink(missing_ok=True)

    return backup


def rollback_latest(
    destination: Path,
    backups_root: Path,
    metadata_path: Path,
    now: datetime,
) -> Path:
    selected: tuple[Path, BuildMetadata] | None = None
    if backups_root.is_dir():
        for backup in sorted(
            (path for path in backups_root.iterdir() if path.is_dir()),
            reverse=True,
        ):
            binary = backup / "go2rtc"
            payload = _read_metadata(backup / "build.json")
            if not binary.is_file() or not os.access(binary, os.X_OK) or payload is None:
                continue
            if sha256_file(binary) != payload["binary_sha256"]:
                continue
            selected = (backup, BuildMetadata(**payload))
            break
    if selected is None:
        raise Go2RTCBuildError("NO_VALID_BACKUP")

    backup, metadata = selected
    install_candidate(
        backup / "go2rtc",
        destination,
        backups_root,
        metadata_path,
        metadata,
        now,
    )
    return backup


def _git(source_dir: Path, *args: str) -> str:
    try:
        result = subprocess.run(
            ["git", *args],
            cwd=source_dir,
            check=True,
            capture_output=True,
            text=True,
        )
    except (OSError, subprocess.CalledProcessError) as exc:
        raise Go2RTCBuildError("GIT_OPERATION_FAILED") from exc
    return result.stdout.strip()


def _patch_numstat(source_dir: Path, patch_path: Path) -> dict[str, tuple[int, int]]:
    try:
        result = subprocess.run(
            ["git", "apply", "--numstat", str(patch_path)],
            cwd=source_dir,
            check=True,
            capture_output=True,
            text=True,
        )
    except (OSError, subprocess.CalledProcessError) as exc:
        raise Go2RTCBuildError("PATCH_CONTEXT_MISMATCH") from exc

    entries: dict[str, tuple[int, int]] = {}
    for line in result.stdout.splitlines():
        fields = line.split("\t", 2)
        if len(fields) != 3 or not fields[0].isdigit() or not fields[1].isdigit():
            raise Go2RTCBuildError("PATCH_SCOPE_INVALID")
        if fields[2] in entries:
            raise Go2RTCBuildError("PATCH_SCOPE_INVALID")
        entries[fields[2]] = (int(fields[0]), int(fields[1]))
    return entries


def run_upstream_protocol_gate(
    source_dir: Path,
    go: str,
    *,
    runner: Callable[..., subprocess.CompletedProcess[Any]] = subprocess.run,
) -> None:
    commands = (
        [
            go,
            "test",
            "./pkg/xiaomi/miss/cs2",
            "-run",
            "^(TestWritePacketCopiesPayload|TestWritePacketRejectsEmptyAndAdvancesChannel3Sequence|TestRepeatedSpeakerResponsesDoNotCloseMediaChannel|TestCommandChannel)",
            "-count=1",
        ],
        [
            go,
            "test",
            "./pkg/xiaomi/miss",
            "-run",
            "^(TestSpeakerLifecycle|TestRepeatedSpeakerLifecycle)",
            "-count=1",
        ],
        [
            go,
            "test",
            "./internal/streams",
            "-run",
            "^(TestPlayEmpty|TestNaturalSourceEnd|TestNaturalSourceEOF|TestCancelAndNaturalEnd)",
            "-count=1",
        ],
    )
    try:
        for command in commands:
            runner(
                command,
                cwd=source_dir,
                check=True,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=PROTOCOL_GATE_TIMEOUT_SECONDS,
            )
    except (OSError, subprocess.SubprocessError) as exc:
        raise Go2RTCBuildError("GO2RTC_PROTOCOL_GATE_FAILED") from exc


def run_upstream_protocol_diagnostic_gate(
    source_dir: Path,
    go: str,
    *,
    runner: Callable[..., subprocess.CompletedProcess[Any]] = subprocess.run,
) -> None:
    test_pattern = (
        "^(TestWritePacketRejectsEmptyAndAdvancesChannel3Sequence|"
        "TestSpeakerLifecycleCountsOnlySuccessfulOpusPayload|"
        "TestSpeakerLifecycleReportsSuccessfulOpusPacketsAndBytes|"
        "TestRepeatedSpeakerLifecycleKeepsMediaReadable|"
        "TestPlaybackSettlementDoesNotReplaceProducer|"
        "TestReconnectBackoffDoesNotDuplicateWorkers|"
        "TestReadTimeoutClassificationIsPayloadFree)$"
    )
    commands = (
        [
            go,
            "test",
            "./pkg/xiaomi/miss/cs2",
            "./pkg/xiaomi/miss",
            "./internal/streams",
            "-run",
            test_pattern,
            "-count=1",
        ],
        [
            go,
            "test",
            "-race",
            "./pkg/xiaomi/miss/cs2",
            "./pkg/xiaomi/miss",
            "./internal/streams",
            "-run",
            test_pattern,
            "-count=1",
        ],
    )
    try:
        for command in commands:
            runner(
                command,
                cwd=source_dir,
                check=True,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                timeout=PROTOCOL_GATE_TIMEOUT_SECONDS,
            )
    except (OSError, subprocess.SubprocessError) as exc:
        raise Go2RTCBuildError("GO2RTC_PROTOCOL_DIAGNOSTIC_FAILED") from exc


def verify_and_apply_patch(
    source_dir: Path,
    patch_path: Path,
    *,
    expected_commit: str = GO2RTC_COMMIT,
) -> str:
    source_dir = source_dir.resolve()
    patch_path = patch_path.resolve()
    if not source_dir.is_dir() or not patch_path.is_file():
        raise Go2RTCBuildError("BUILD_INPUT_MISSING")

    actual_commit = _git(source_dir, "rev-parse", "HEAD")
    if actual_commit != expected_commit:
        raise Go2RTCBuildError("UPSTREAM_COMMIT_MISMATCH")
    if _git(source_dir, "status", "--porcelain"):
        raise Go2RTCBuildError("UPSTREAM_NOT_CLEAN")

    numstat = _patch_numstat(source_dir, patch_path)
    if numstat != ALLOWED_PATCH_CHANGES:
        raise Go2RTCBuildError("PATCH_SCOPE_INVALID")

    cs2_path = source_dir / "pkg/xiaomi/miss/cs2/conn.go"
    codecs_path = source_dir / "pkg/iso/codecs.go"
    client_path = source_dir / "pkg/xiaomi/miss/client.go"
    backchannel_path = source_dir / "pkg/xiaomi/miss/backchannel.go"
    play_path = source_dir / "internal/streams/play.go"
    cs2_before = cs2_path.read_text(encoding="utf-8")
    codecs_before = codecs_path.read_text(encoding="utf-8")
    client_before = client_path.read_text(encoding="utf-8")
    backchannel_before = backchannel_path.read_text(encoding="utf-8")
    play_before = play_path.read_text(encoding="utf-8")
    if (
        cs2_before.count('net.ListenUDP("udp", nil)') != 1
        or 'net.ListenUDP("udp4", nil)' in cs2_before
        or cs2_before.count('copy(req[offset+hdrSize:], hdr)') != 1
        or 'copy(req[offset+hdrSize:], payload)' in cs2_before
        or codecs_before.count('m.StartAtom("hev1")') != 1
        or 'm.StartAtom("hvc1")' in codecs_before
        or client_before.count("func (c *Client) StartSpeaker() error") != 1
        or "startCommandDispatcher" in client_before
        or backchannel_before.count("_ = p.client.WriteAudio") != 4
        or "SettleBackchannel" in backchannel_before
        or play_before.count('if source = urlOrProd.(string); source == "" {') != 1
        or "stopPlaybacks" in play_before
    ):
        raise Go2RTCBuildError("PATCH_PRECONDITION_FAILED")

    try:
        _git(
            source_dir,
            "apply",
            "--unidiff-zero",
            "--check",
            str(patch_path),
        )
    except Go2RTCBuildError as exc:
        raise Go2RTCBuildError("PATCH_CONTEXT_MISMATCH") from exc
    _git(source_dir, "apply", "--unidiff-zero", str(patch_path))

    cs2_after = cs2_path.read_text(encoding="utf-8")
    codecs_after = codecs_path.read_text(encoding="utf-8")
    client_after = client_path.read_text(encoding="utf-8")
    backchannel_after = backchannel_path.read_text(encoding="utf-8")
    play_after = play_path.read_text(encoding="utf-8")
    regression_paths = (
        source_dir / "pkg/xiaomi/miss/cs2/conn_test.go",
        source_dir / "pkg/xiaomi/miss/cs2/lifecycle_review_test.go",
        source_dir / "pkg/xiaomi/miss/lifecycle_review_test.go",
        source_dir / "internal/streams/play_lifecycle_review_test.go",
    )
    try:
        regressions_after = "\n".join(
            path.read_text(encoding="utf-8") for path in regression_paths
        )
    except OSError:
        regressions_after = ""
    required_regression_fragments = (
        "func TestWritePacketCopiesPayload(t *testing.T)",
        "func TestWritePacketRejectsEmptyAndAdvancesChannel3Sequence(t *testing.T)",
        "reader, writer := net.Pipe()",
        "got := make([]byte, 12+len(header)+len(payload))",
        "bytes.Equal(got[12:12+hdrSize], header)",
        "bytes.Equal(got[12+hdrSize:], payload)",
        "func TestRepeatedSpeakerResponsesDoNotCloseMediaChannel(t *testing.T)",
        "func TestCommandChannelOverflowDropsCompleteFrame(t *testing.T)",
        "func TestCommandChannelRejectsOversizedFrameWithoutRetainingBytes(t *testing.T)",
        "func TestCommandChannelPreservesIngressTimeAcrossDelayedRead(t *testing.T)",
        "func TestSpeakerLifecycleStartsAndStopsExactlyOnce(t *testing.T)",
        "func TestSpeakerLifecycleAcceptsCS2WireOrderResponse(t *testing.T)",
        "func TestSpeakerLifecycleRejectsOverlappingStart(t *testing.T)",
        "func TestSpeakerLifecycleStopsWritesAfterStop(t *testing.T)",
        "func TestSpeakerLifecycleSurfacesFirstWriteError(t *testing.T)",
        "func TestRepeatedSpeakerLifecycleLeavesNoActiveGeneration(t *testing.T)",
        "func TestSpeakerLifecycleConcurrentStopWaitsAndSendsOneCommand(t *testing.T)",
        "func TestSpeakerLifecycleProducerSettlementRejectsQueuedWriteBeforeSenderDrain(t *testing.T)",
        "func TestSpeakerLifecycleRejectsResponseBeforeTransportAck(t *testing.T)",
        "func TestSpeakerLifecycleRejectsQueuedPreAckResponseAfterAck(t *testing.T)",
        "func TestSpeakerLifecycleRejectsPreviousResponseDuringQuiescence(t *testing.T)",
        "func TestSpeakerLifecycleKeepsFirstFailureStage(t *testing.T)",
        "func TestSpeakerLifecycleCountsOnlySuccessfulOpusPayload(t *testing.T)",
        "func TestSpeakerLifecycleReportsSuccessfulOpusPacketsAndBytes(t *testing.T)",
        "func TestPlayEmptySettlesBackchannelBeforeSuccess(t *testing.T)",
        "func TestPlayEmptyPropagatesBackchannelStopFailure(t *testing.T)",
        "func TestPlayEmptyTimesOutBlockedSettlementAndKeepsGenerationBusy(t *testing.T)",
        "func TestNaturalSourceFailurePropagatesOnEmptyStop(t *testing.T)",
        "func TestNaturalSourceEndSettlesBackchannelOnce(t *testing.T)",
        "func TestNaturalSourceEOFSucceedsForFiniteMedia(t *testing.T)",
        "func TestCancelAndNaturalEndDoNotDoubleStop(t *testing.T)",
    )
    if (
        'net.ListenUDP("udp", nil)' in cs2_after
        or cs2_after.count('net.ListenUDP("udp4", nil)') != 1
        or 'copy(req[offset+hdrSize:], hdr)' in cs2_after
        or cs2_after.count('copy(req[offset+hdrSize:], payload)') != 1
        or 'm.StartAtom("hev1")' in codecs_after
        or codecs_after.count('m.StartAtom("hvc1")') != 1
        or client_after.count("func (c *Client) startCommandDispatcher()") != 1
        or client_after.count("func (c *Client) StartSpeaker() (*SpeakerSession, error)") != 1
        or backchannel_after.count("func (p *Producer) SettleBackchannel() error") != 1
        or play_after.count("func (s *Stream) stopPlaybacks() error") != 1
        or any(
            regressions_after.count(fragment) != 1
            for fragment in required_regression_fragments
        )
    ):
        raise Go2RTCBuildError("PATCH_POSTCONDITION_FAILED")
    return actual_commit
