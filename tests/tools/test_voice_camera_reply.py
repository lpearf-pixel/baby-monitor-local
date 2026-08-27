from __future__ import annotations

import io
import json
import os
import pty
import stat
import tty as tty_module
import wave
from dataclasses import replace
from pathlib import Path

import pytest

import tools.voice_camera_reply as voice_camera_reply

from packages.monitoring.go2rtc_build import BuildMetadata, sha256_file
from services.voice.camera_reply import (
    CameraReplyAcceptance,
    CameraReplyCode,
    CameraReplyEvidence,
    CameraReplyResult,
)
from tools.voice_camera_reply import (
    ProbeReport,
    print_report,
    run_probe,
    status_report,
)


def _metadata(root: Path) -> BuildMetadata:
    patch = root / "patches/go2rtc-macos-hybrid-hd.patch"
    patch.parent.mkdir(parents=True, exist_ok=True)
    patch.write_bytes(b"synthetic-patch")
    binary = root / ".local/bin/go2rtc"
    binary.parent.mkdir(parents=True, exist_ok=True)
    binary.write_bytes(b"synthetic-binary")
    binary.chmod(0o755)
    metadata = BuildMetadata(
        upstream_commit="b465651a94c1f637d566a8c660b4fad102b35153",
        go_version="go1.24.13",
        patch_sha256=sha256_file(patch),
        binary_sha256=sha256_file(binary),
        build_time="2026-08-26T00:00:00+00:00",
        platform="darwin/amd64",
    )
    build = root / "runtime/build"
    build.mkdir(parents=True, mode=0o700)
    (build / "go2rtc.json").write_text(
        json.dumps(metadata.as_dict()), encoding="ascii"
    )
    (root / ".local/Go2RTC.app").mkdir(parents=True)
    return metadata


def _marker(
    root: Path, metadata: BuildMetadata, *, protocol: str = "cs2+udp"
) -> Path:
    status = root / "runtime/status"
    status.mkdir(parents=True, mode=0o700)
    path = status / "voice-camera-reply-acceptance.json"
    path.write_text(
        json.dumps(
            {
                "schema_version": 2,
                "accepted": True,
                "upstream_commit": metadata.upstream_commit,
                "patch_sha256": metadata.patch_sha256,
                "binary_sha256": metadata.binary_sha256,
                "transport_mode": "auto",
                "negotiated_protocol": protocol,
            },
            sort_keys=True,
            separators=(",", ":"),
        )
        + "\n",
        encoding="ascii",
    )
    path.chmod(0o600)
    return path


def _evidence(
    *, protocol: str = "cs2+udp", generation: int = 2
) -> CameraReplyEvidence:
    return CameraReplyEvidence(
        source_ready=True,
        video_ready=True,
        incoming_audio_ready=True,
        sendonly_audio_ready=True,
        protocol=protocol,
        video_codec="HEVC",
        incoming_audio_codec="OPUS",
        sendonly_audio_codec="OPUS",
        speaker_state="closed",
        speaker_session_generation=generation,
        speaker_start_requests=generation,
        speaker_start_responses=generation,
        speaker_stop_commands=generation,
        speaker_audio_packets=generation,
        speaker_audio_bytes=generation * 100,
        producer_id=41 if generation else 0,
        producer_generation=generation,
    )


def test_controlling_tty_supports_real_nonseekable_terminal_io() -> None:
    master_fd, slave_fd = pty.openpty()
    tty_module.setraw(slave_fd)
    slave_path = Path(os.ttyname(slave_fd))
    try:
        with voice_camera_reply.open_controlling_tty(slave_path) as terminal:
            assert terminal.isatty() is True
            os.write(master_fd, b"YES\n")
            assert terminal.readline(5) == "YES\n"
            assert terminal.write("ready") == 5
            terminal.flush()
            assert os.read(master_fd, 5) == b"ready"
    finally:
        os.close(slave_fd)
        os.close(master_fd)


@pytest.mark.parametrize("protocol", ["cs2+udp", "cs2+tcp"])
def test_acceptance_loads_only_exact_current_private_marker(
    tmp_path: Path, protocol: str
) -> None:
    metadata = _metadata(tmp_path)
    marker = _marker(tmp_path, metadata, protocol=protocol)

    assert CameraReplyAcceptance.load(tmp_path, metadata) == _evidence(
        protocol=protocol, generation=0
    )
    assert stat.S_IMODE(marker.stat().st_mode) == 0o600


@pytest.mark.parametrize("protocol", ["cs2+udp", "cs2+tcp"])
def test_acceptance_publishes_schema_v2_from_closed_owned_generation(
    tmp_path: Path, protocol: str
) -> None:
    metadata = _metadata(tmp_path)
    evidence = _evidence(protocol=protocol)

    assert CameraReplyAcceptance.publish(tmp_path, metadata, evidence) is True

    marker = tmp_path / "runtime/status/voice-camera-reply-acceptance.json"
    assert json.loads(marker.read_bytes()) == {
        "schema_version": 2,
        "accepted": True,
        "upstream_commit": metadata.upstream_commit,
        "patch_sha256": metadata.patch_sha256,
        "binary_sha256": metadata.binary_sha256,
        "transport_mode": "auto",
        "negotiated_protocol": protocol,
    }


@pytest.mark.parametrize(
    "evidence",
    [
        _evidence(generation=0),
        _evidence(protocol="cs2+quic"),
        replace(_evidence(generation=1), speaker_start_requests=True),
    ],
)
def test_acceptance_refuses_unowned_or_unknown_protocol_evidence(
    tmp_path: Path, evidence: CameraReplyEvidence
) -> None:
    metadata = _metadata(tmp_path)

    assert CameraReplyAcceptance.publish(tmp_path, metadata, evidence) is False
    assert not (
        tmp_path / "runtime/status/voice-camera-reply-acceptance.json"
    ).exists()


@pytest.mark.parametrize(
    "mutation",
    [
        "unknown",
        "stale",
        "protocol",
        "protocol_shape",
        "transport",
        "schema",
        "mode",
        "symlink",
    ],
)
def test_acceptance_rejects_invalid_marker_without_repair(
    tmp_path: Path, mutation: str
) -> None:
    metadata = _metadata(tmp_path)
    marker = _marker(tmp_path, metadata)
    original = marker.read_bytes()
    if mutation in {
        "unknown",
        "stale",
        "protocol",
        "protocol_shape",
        "transport",
        "schema",
    }:
        payload = json.loads(original)
        if mutation == "unknown":
            payload["private_detail"] = "must-not-leak"
        elif mutation == "stale":
            payload["binary_sha256"] = "0" * 64
        elif mutation == "protocol":
            payload["negotiated_protocol"] = "cs2+quic"
        elif mutation == "protocol_shape":
            payload["negotiated_protocol"] = ["cs2+udp"]
        elif mutation == "transport":
            payload["transport_mode"] = "udp"
        elif mutation == "schema":
            payload["schema_version"] = 1
        else:
            raise AssertionError("unreachable")
        marker.write_text(json.dumps(payload), encoding="ascii")
        marker.chmod(0o600)
        original = marker.read_bytes()
    elif mutation == "mode":
        marker.chmod(0o644)
        original = marker.read_bytes()
    else:
        target = marker.with_suffix(".target")
        target.write_bytes(original)
        target.chmod(0o600)
        marker.unlink()
        marker.symlink_to(target)

    assert CameraReplyAcceptance.load(tmp_path, metadata) is None
    assert marker.read_bytes() == original
    if mutation == "mode":
        assert stat.S_IMODE(marker.stat().st_mode) == 0o644
    if mutation == "symlink":
        assert marker.is_symlink()


class FakeTTY:
    def __init__(self, answer: str, *, controlling: bool = True) -> None:
        self.answer = answer
        self.controlling = controlling
        self.output = ""

    def isatty(self) -> bool:
        return self.controlling

    def write(self, value: str) -> int:
        self.output += value
        return len(value)

    def flush(self) -> None:
        return None

    def readline(self, limit: int = -1) -> str:
        return self.answer[:limit]


class FakeTransport:
    def __init__(self, *, inspections: list[CameraReplyEvidence | None] | None = None) -> None:
        self.inspections = inspections or [_evidence(), _evidence()]
        self.events: list[str] = []
        self.wave_bytes = b""
        self.wave_mode = 0

    def inspect(self) -> CameraReplyEvidence | None:
        self.events.append("inspect")
        return self.inspections.pop(0)

    def start(self, media: Path) -> CameraReplyResult:
        self.events.append("start")
        self.wave_bytes = media.read_bytes()
        self.wave_mode = stat.S_IMODE(media.stat().st_mode)
        return CameraReplyResult(CameraReplyCode.READY, True)

    def stop(self) -> CameraReplyResult:
        self.events.append("stop")
        return CameraReplyResult(CameraReplyCode.COMPLETE, False)


class FixedRunner:
    def __init__(self, outcomes: list[bool] | None = None) -> None:
        self.outcomes = outcomes or [True] * 5
        self.calls: list[tuple[str, ...]] = []

    def __call__(self, argv: tuple[str, ...], timeout_seconds: float) -> bool:
        self.calls.append(argv)
        assert 0.1 <= timeout_seconds <= 10.0
        return self.outcomes.pop(0)


def test_probe_uses_tty_fixed_health_gates_one_second_tone_and_cleanup(
    tmp_path: Path,
) -> None:
    root = tmp_path / "repo"
    root.mkdir(mode=0o700)
    root.chmod(0o755)
    metadata = _metadata(root)
    temporary_parent = tmp_path / "system-temp"
    temporary_parent.mkdir(mode=0o700)
    tty = FakeTTY("YES\n")
    transport = FakeTransport()
    runner = FixedRunner()

    report = run_probe(
        root,
        transport=transport,
        tty=tty,
        runner=runner,
        platform_system="Darwin",
        platform_machine="x86_64",
        temporary_parent=temporary_parent,
    )

    assert report == ProbeReport(
        code=CameraReplyCode.COMPLETE,
        ready=True,
        tone_started=True,
        tone_confirmed=True,
        source_healthy=True,
        voice_healthy=True,
        acceptance_marker_current=True,
        raw_audio_persisted=False,
    )
    assert tty.output == (
        "camera_reply_tone_started=true\n"
        "type_yes_if_tone_heard_from_camera="
    )
    assert transport.events == ["inspect", "start", "stop", "inspect"]
    assert transport.wave_mode == 0o600
    with wave.open(io.BytesIO(transport.wave_bytes), "rb") as source:
        assert source.getnchannels() == 1
        assert source.getsampwidth() == 2
        assert source.getframerate() == 16_000
        assert source.getnframes() == 16_000
    assert list(temporary_parent.iterdir()) == []
    assert CameraReplyAcceptance.load(root, metadata) == _evidence(generation=0)
    status_path = root / "runtime/status/voice-camera-reply.json"
    assert status_path.is_file()
    assert stat.S_IMODE(status_path.stat().st_mode) == 0o600
    assert len(runner.calls) == 5


def test_status_report_marks_current_acceptance_ready(tmp_path: Path) -> None:
    metadata = _metadata(tmp_path)
    _marker(tmp_path, metadata)

    report = status_report(tmp_path)

    assert report.code is CameraReplyCode.READY
    assert report.ready is True
    assert report.acceptance_marker_current is True


@pytest.mark.parametrize("answer", ["yes\n", "YES ", "NO\n", ""])
def test_probe_requires_exact_tty_yes_and_always_stops(
    tmp_path: Path, answer: str
) -> None:
    root = tmp_path / "repo"
    root.mkdir(mode=0o700)
    _metadata(root)
    temporary_parent = tmp_path / "system-temp"
    temporary_parent.mkdir(mode=0o700)
    transport = FakeTransport()

    report = run_probe(
        root,
        transport=transport,
        tty=FakeTTY(answer),
        runner=FixedRunner(),
        platform_system="Darwin",
        platform_machine="x86_64",
        temporary_parent=temporary_parent,
    )

    assert report.tone_started is True
    assert report.tone_confirmed is False
    assert report.acceptance_marker_current is False
    assert transport.events == ["inspect", "start", "stop"]
    assert not (root / "runtime/status/voice-camera-reply-acceptance.json").exists()
    assert list(temporary_parent.iterdir()) == []


def test_probe_rejects_non_tty_before_commands_or_camera(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    root.mkdir(mode=0o700)
    _metadata(root)
    runner = FixedRunner()
    transport = FakeTransport()

    report = run_probe(
        root,
        transport=transport,
        tty=FakeTTY("YES\n", controlling=False),
        runner=runner,
        platform_system="Darwin",
        platform_machine="x86_64",
    )

    assert report.code is CameraReplyCode.UNAVAILABLE
    assert runner.calls == []
    assert transport.events == []


def test_probe_entrypoint_invalidates_marker_when_tty_is_unavailable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    metadata = _metadata(tmp_path)
    marker = _marker(tmp_path, metadata)

    class UnavailableTTY:
        def __enter__(self):
            raise OSError("synthetic unavailable tty")

        def __exit__(self, *args: object) -> None:
            return None

    monkeypatch.setattr(voice_camera_reply, "ROOT", tmp_path)
    monkeypatch.setattr(
        voice_camera_reply,
        "open_controlling_tty",
        lambda: UnavailableTTY(),
    )

    assert voice_camera_reply.main(["probe"]) == 2
    assert not marker.exists()


def test_failed_post_check_invalidates_existing_acceptance_marker(
    tmp_path: Path,
) -> None:
    root = tmp_path / "repo"
    root.mkdir(mode=0o700)
    metadata = _metadata(root)
    marker = _marker(root, metadata)
    temporary_parent = tmp_path / "system-temp"
    temporary_parent.mkdir(mode=0o700)

    report = run_probe(
        root,
        transport=FakeTransport(),
        tty=FakeTTY("YES\n"),
        runner=FixedRunner([True, True, True, False, True]),
        platform_system="Darwin",
        platform_machine="x86_64",
        temporary_parent=temporary_parent,
    )

    assert report.code is CameraReplyCode.UNAVAILABLE
    assert report.acceptance_marker_current is False
    assert not marker.exists()


def test_probe_output_contains_only_allowlisted_aggregate_fields(capsys) -> None:
    report = ProbeReport(
        code=CameraReplyCode.UNAVAILABLE,
        ready=False,
        tone_started=False,
        tone_confirmed=False,
        source_healthy=False,
        voice_healthy=False,
        acceptance_marker_current=False,
        raw_audio_persisted=False,
    )

    print_report(report)

    assert capsys.readouterr().out == (
        "camera_reply_code=CAMERA_REPLY_UNAVAILABLE\n"
        "camera_reply_ready=false\n"
        "tone_started=false\n"
        "tone_confirmed=false\n"
        "source_healthy=false\n"
        "voice_healthy=false\n"
        "acceptance_marker_current=false\n"
        "raw_audio_persisted=false\n"
    )
