#!/usr/bin/env python3
"""Bounded operator gate for the fixed Xiaomi camera reply path."""

from __future__ import annotations

import math
import os
import platform
import stat
import struct
import subprocess
import sys
import tempfile
import time
import wave
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol, TextIO

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from packages.monitoring.go2rtc_build import (  # noqa: E402
    GO2RTC_COMMIT,
    GO2RTC_DESIGNATED_REQUIREMENT,
    BuildMetadata,
    read_metadata,
    sha256_file,
)
from services.voice.camera_reply import (  # noqa: E402
    CameraReplyAcceptance,
    CameraReplyCode,
    CameraReplyEvidence,
    CameraReplyResult,
    CameraReplyStatus,
    CameraReplyStatusWriter,
    LoopbackCameraReplyTransport,
)


_METADATA = Path("runtime/build/go2rtc.json")
_BINARY = Path(".local/bin/go2rtc")
_APP = Path(".local/Go2RTC.app")
_PATCH = Path("patches/go2rtc-macos-hybrid-hd.patch")
_STATUS = Path("runtime/status/voice-camera-reply.json")
_COMMAND_TIMEOUT_SECONDS = 10.0
_TONE_DURATION_SECONDS = 1.0


class Runner(Protocol):
    def __call__(self, argv: tuple[str, ...], timeout_seconds: float) -> bool: ...


class ProbeTransport(Protocol):
    def inspect(self) -> CameraReplyEvidence | None: ...

    def start(self, media: Path) -> CameraReplyResult: ...

    def stop(self) -> CameraReplyResult: ...


class _ControllingTTY:
    def __init__(self, reader: TextIO, writer: TextIO) -> None:
        self._reader = reader
        self._writer = writer

    def isatty(self) -> bool:
        return self._reader.isatty() and self._writer.isatty()

    def readline(self, limit: int = -1) -> str:
        return self._reader.readline(limit)

    def write(self, value: str) -> int:
        return self._writer.write(value)

    def flush(self) -> None:
        self._writer.flush()


@contextmanager
def open_controlling_tty(
    path: Path = Path("/dev/tty"),
) -> Iterator[_ControllingTTY]:
    with path.open("r", encoding="ascii", buffering=1) as reader:
        with path.open("w", encoding="ascii", buffering=1) as writer:
            yield _ControllingTTY(reader, writer)


@dataclass(frozen=True, slots=True)
class ProbeReport:
    code: CameraReplyCode
    ready: bool
    tone_started: bool
    tone_confirmed: bool
    source_healthy: bool
    voice_healthy: bool
    acceptance_marker_current: bool
    raw_audio_persisted: bool


def run_bounded(argv: tuple[str, ...], timeout_seconds: float) -> bool:
    try:
        subprocess.run(
            argv,
            check=True,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=timeout_seconds,
            shell=False,
        )
        return True
    except (OSError, subprocess.SubprocessError, ValueError):
        return False


def _fixed_commands(root: Path) -> tuple[tuple[str, ...], ...]:
    python = str(root / ".venv-alpha/bin/python")
    source = (
        python,
        str(root / "tools/alpha_quality.py"),
        "check",
        "--base-url",
        "http://127.0.0.1:1984",
        "--dashboard-url",
        "http://127.0.0.1:8080",
    )
    voice = (
        python,
        str(root / "tools/voice_status.py"),
        str(root / "runtime/status/voice.json"),
        "--require-mode",
        "listen_only",
    )
    identity = (
        "/usr/bin/codesign",
        "--verify",
        "--deep",
        "--strict",
        "--requirements",
        GO2RTC_DESIGNATED_REQUIREMENT,
        str(root / _APP),
    )
    return identity, source, voice


def _current_metadata(root: Path) -> BuildMetadata | None:
    metadata = read_metadata(root / _METADATA)
    try:
        if (
            metadata is None
            or metadata.upstream_commit != GO2RTC_COMMIT
            or metadata.platform != "darwin/amd64"
            or sha256_file(root / _PATCH) != metadata.patch_sha256
            or sha256_file(root / _BINARY) != metadata.binary_sha256
            or not (root / _APP).is_dir()
        ):
            return None
    except OSError:
        return None
    return metadata


def _write_tone(path: Path) -> None:
    frames = bytearray()
    for index in range(16_000):
        sample = int(0.20 * 32_767 * math.sin(2.0 * math.pi * 880 * index / 16_000))
        frames.extend(struct.pack("<h", sample))
    with wave.open(str(path), "wb") as output:
        output.setnchannels(1)
        output.setsampwidth(2)
        output.setframerate(16_000)
        output.writeframes(bytes(frames))
    path.chmod(0o600)


def _report(
    code: CameraReplyCode,
    *,
    tone_started: bool = False,
    tone_confirmed: bool = False,
    source_healthy: bool = False,
    voice_healthy: bool = False,
    marker_current: bool = False,
) -> ProbeReport:
    return ProbeReport(
        code=code,
        ready=(
            code in {CameraReplyCode.READY, CameraReplyCode.COMPLETE}
            and marker_current
        ),
        tone_started=tone_started,
        tone_confirmed=tone_confirmed,
        source_healthy=source_healthy,
        voice_healthy=voice_healthy,
        acceptance_marker_current=marker_current,
        raw_audio_persisted=False,
    )


def run_probe(
    root: Path,
    *,
    transport: ProbeTransport,
    tty: TextIO,
    runner: Runner = run_bounded,
    platform_system: str | None = None,
    platform_machine: str | None = None,
    temporary_parent: Path | None = None,
    sleep: Callable[[float], None] = time.sleep,
) -> ProbeReport:
    root = root.resolve()
    if not CameraReplyAcceptance.invalidate(root):
        result = _report(CameraReplyCode.UNAVAILABLE)
        _publish_status(root, result)
        return result
    system = platform_system if platform_system is not None else platform.system()
    machine = platform_machine if platform_machine is not None else platform.machine()
    metadata = _current_metadata(root)
    identity, source_command, voice_command = _fixed_commands(root)
    if (
        system != "Darwin"
        or machine != "x86_64"
        or not tty.isatty()
        or metadata is None
        or not runner(identity, _COMMAND_TIMEOUT_SECONDS)
    ):
        result = _report(CameraReplyCode.UNAVAILABLE)
        _publish_status(root, result)
        return result

    source_healthy = runner(source_command, _COMMAND_TIMEOUT_SECONDS)
    voice_healthy = runner(voice_command, _COMMAND_TIMEOUT_SECONDS)
    if not source_healthy or not voice_healthy or transport.inspect() is None:
        result = _report(
            CameraReplyCode.UNAVAILABLE,
            source_healthy=source_healthy,
            voice_healthy=voice_healthy,
        )
        _publish_status(root, result)
        return result

    temporary_root: Path | None = None
    tone: Path | None = None
    tone_started = False
    tone_confirmed = False
    tone_stopped = False
    stop_result = CameraReplyResult(CameraReplyCode.COMPLETE, False)
    try:
        temporary_root = Path(
            tempfile.mkdtemp(
                prefix="voice-camera-tone-", dir=temporary_parent
            )
        )
        temporary_root.chmod(0o700)
        tone = temporary_root / "tone.wav"
        _write_tone(tone)
        start_result = transport.start(tone)
        tone_started = start_result.delivery_started
        if not tone_started:
            result = _report(
                start_result.code,
                source_healthy=True,
                voice_healthy=True,
            )
            _publish_status(root, result)
            return result
        tty.write("camera_reply_tone_started=true\n")
        tty.flush()
        sleep(_TONE_DURATION_SECONDS)
        try:
            stop_result = transport.stop()
        except Exception:
            stop_result = CameraReplyResult(
                CameraReplyCode.AMBIGUOUS, False
            )
        finally:
            tone_stopped = True
        tty.write("type_yes_if_tone_heard_from_camera=")
        tty.flush()
        tone_confirmed = tty.readline(5) == "YES\n"
    except Exception:
        result = _report(
            CameraReplyCode.AMBIGUOUS
            if tone_started
            else CameraReplyCode.UNAVAILABLE,
            tone_started=tone_started,
            source_healthy=True,
            voice_healthy=True,
        )
        _publish_status(root, result)
        return result
    finally:
        if tone_started and not tone_stopped:
            try:
                stop_result = transport.stop()
            except Exception:
                stop_result = CameraReplyResult(
                    CameraReplyCode.AMBIGUOUS, False
                )
        if tone is not None:
            try:
                tone.unlink()
            except OSError:
                pass
        if temporary_root is not None:
            try:
                temporary_root.rmdir()
            except OSError:
                pass

    if not tone_confirmed:
        result = _report(
            CameraReplyCode.REJECTED,
            tone_started=True,
            source_healthy=True,
            voice_healthy=True,
        )
        _publish_status(root, result)
        return result
    if stop_result.code is not CameraReplyCode.COMPLETE:
        result = _report(
            CameraReplyCode.AMBIGUOUS,
            tone_started=True,
            tone_confirmed=True,
            source_healthy=True,
            voice_healthy=True,
        )
        _publish_status(root, result)
        return result

    source_healthy = runner(source_command, _COMMAND_TIMEOUT_SECONDS)
    voice_healthy = runner(voice_command, _COMMAND_TIMEOUT_SECONDS)
    final_evidence = transport.inspect()
    media_healthy = final_evidence is not None
    marker_current = bool(
        source_healthy
        and voice_healthy
        and media_healthy
        and CameraReplyAcceptance.publish(root, metadata, final_evidence)
        and CameraReplyAcceptance.load(root, metadata) is not None
    )
    code = CameraReplyCode.COMPLETE if marker_current else CameraReplyCode.UNAVAILABLE
    result = _report(
        code,
        tone_started=True,
        tone_confirmed=True,
        source_healthy=source_healthy and media_healthy,
        voice_healthy=voice_healthy,
        marker_current=marker_current,
    )
    _publish_status(root, result)
    return result


def _publish_status(root: Path, report: ProbeReport) -> None:
    try:
        status_root = root / "runtime/status"
        if not status_root.exists():
            runtime = root / "runtime"
            runtime_lstat = runtime.lstat()
            if (
                stat.S_ISLNK(runtime_lstat.st_mode)
                or not stat.S_ISDIR(runtime_lstat.st_mode)
                or runtime_lstat.st_uid != os.getuid()
            ):
                return
            status_root.mkdir(mode=0o700)
        CameraReplyStatusWriter(root / _STATUS, boundary=status_root).write(
            CameraReplyStatus(
                backend="camera",
                ready=report.ready,
                last_code=report.code,
                completed_count=int(report.code is CameraReplyCode.COMPLETE),
                failed_count=int(report.code is not CameraReplyCode.COMPLETE),
                latency_ms=0,
            )
        )
    except Exception:
        pass


def print_report(report: ProbeReport) -> None:
    values = (
        ("camera_reply_code", report.code.value),
        ("camera_reply_ready", report.ready),
        ("tone_started", report.tone_started),
        ("tone_confirmed", report.tone_confirmed),
        ("source_healthy", report.source_healthy),
        ("voice_healthy", report.voice_healthy),
        ("acceptance_marker_current", report.acceptance_marker_current),
        ("raw_audio_persisted", report.raw_audio_persisted),
    )
    for key, value in values:
        text = str(value).lower() if isinstance(value, bool) else value
        print(f"{key}={text}")


def status_report(root: Path) -> ProbeReport:
    metadata = _current_metadata(root)
    current = bool(
        metadata is not None
        and CameraReplyAcceptance.load(root, metadata) is not None
    )
    return _report(
        CameraReplyCode.READY if current else CameraReplyCode.NOT_PROVEN,
        marker_current=current,
    )


def main(argv: list[str] | None = None) -> int:
    args = argv if argv is not None else sys.argv[1:]
    if args not in (["status"], ["verify-marker"], ["probe"]):
        print_report(_report(CameraReplyCode.REJECTED))
        return 2
    if args[0] in {"status", "verify-marker"}:
        report = status_report(ROOT)
        print_report(report)
        return 0 if report.acceptance_marker_current else 2
    if not CameraReplyAcceptance.invalidate(ROOT):
        report = _report(CameraReplyCode.UNAVAILABLE)
        print_report(report)
        return 2
    try:
        with open_controlling_tty() as tty:
            report = run_probe(
                ROOT,
                transport=LoopbackCameraReplyTransport(
                    Path(tempfile.gettempdir()).resolve()
                ),
                tty=tty,
            )
    except OSError:
        report = _report(CameraReplyCode.UNAVAILABLE)
    print_report(report)
    return 0 if report.ready else 2


if __name__ == "__main__":
    raise SystemExit(main())
