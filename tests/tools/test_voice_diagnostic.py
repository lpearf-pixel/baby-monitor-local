from __future__ import annotations

import json
import os
from pathlib import Path

from tools.voice_diagnostic import main


class Service:
    def __init__(self, result: bool = True) -> None:
        self.result = result
        self.calls: list[str] = []

    def restart_voice(self) -> bool:
        self.calls.append("restart_voice")
        return self.result


def _project(tmp_path: Path, *, camera_reply: bool = False) -> Path:
    runtime = tmp_path / "runtime"
    runtime.mkdir(mode=0o755)
    settings = runtime / "settings.yaml"
    settings.write_text(
        "voice_care:\n"
        "  enabled: false\n"
        "  listen_only_enabled: true\n"
        f"  camera_reply_enabled: {str(camera_reply).lower()}\n",
        encoding="utf-8",
    )
    return tmp_path


def test_start_status_stop_retains_private_session_without_exposing_content(
    tmp_path: Path, capsys
) -> None:
    root = _project(tmp_path)
    service = Service()

    assert main(["start"], project_root=root, epoch=lambda: 1_000.0,
                token_bytes=lambda _size: b"a" * 16,
                service=service) == 0
    start_output = capsys.readouterr().out
    assert start_output == (
        "result=PASS\noperation=start\ndiagnostic_state=active\n"
        "max_seconds=1800\nmax_utterances=50\nmax_bytes=16777216\n"
    )
    assert "aaaaaaaa" not in start_output
    assert service.calls == ["restart_voice"]

    assert main(["status"], project_root=root, epoch=lambda: 1_001.0) == 0
    status_output = capsys.readouterr().out
    assert status_output == (
        "result=PASS\noperation=status\ndiagnostic_state=active\n"
        "complete_count=0\nincomplete_count=0\nbytes_used=0\n"
        "queue_drops=0\nwriter_failures=0\n"
        "expires_in_seconds=1799\n"
    )
    for forbidden in (str(root), "aaaaaaaa", "transcript", "asr_text"):
        assert forbidden not in status_output

    assert main(["stop"], project_root=root, epoch=lambda: 1_002.0,
                service=service) == 0
    assert capsys.readouterr().out == (
        "result=PASS\noperation=stop\ndiagnostic_state=inactive\n"
        "session_retained=true\n"
    )
    assert service.calls == ["restart_voice", "restart_voice"]
    diagnostics = root / "runtime/private/voice-diagnostics"
    assert not (diagnostics / "active.json").exists()
    assert (diagnostics / "sessions" / ("61" * 16)).is_dir()


def test_start_rejects_camera_reply_before_private_write(
    tmp_path: Path, capsys
) -> None:
    root = _project(tmp_path, camera_reply=True)
    service = Service()

    assert main(["start"], project_root=root, epoch=lambda: 1_000.0,
                service=service) == 1

    assert capsys.readouterr().out == (
        "result=FAIL\noperation=start\nreason=voice_diagnostic_mode_unavailable\n"
    )
    assert service.calls == []
    assert not (root / "runtime/private").exists()


def test_failed_voice_restart_invalidates_marker_but_retains_session(
    tmp_path: Path, capsys
) -> None:
    root = _project(tmp_path)
    service = Service(False)

    assert main(["start"], project_root=root, epoch=lambda: 1_000.0,
                token_bytes=lambda _size: b"b" * 16,
                service=service) == 1

    assert capsys.readouterr().out == (
        "result=FAIL\noperation=start\nreason=voice_diagnostic_service_unavailable\n"
    )
    diagnostics = root / "runtime/private/voice-diagnostics"
    assert not (diagnostics / "active.json").exists()
    assert (diagnostics / "sessions" / ("62" * 16)).is_dir()


def test_cli_rejects_unknown_arguments_without_private_write(
    tmp_path: Path, capsys
) -> None:
    root = _project(tmp_path)

    assert main(["start", "--seconds", "60"], project_root=root) == 2
    assert capsys.readouterr().out == (
        "result=FAIL\noperation=invalid\nreason=voice_diagnostic_invalid_action\n"
    )
    assert not (root / "runtime/private").exists()


def test_start_rejects_unsafe_private_parent_before_service_call(
    tmp_path: Path, capsys
) -> None:
    root = _project(tmp_path)
    private = root / "runtime/private"
    private.mkdir(mode=0o755)
    service = Service()

    assert main(["start"], project_root=root, service=service) == 1
    assert capsys.readouterr().out == (
        "result=FAIL\noperation=start\nreason=voice_diagnostic_storage_unavailable\n"
    )
    assert service.calls == []
    assert not (private / "voice-diagnostics").exists()


def test_status_reports_only_aggregate_orphan_and_worker_counts(
    tmp_path: Path, capsys
) -> None:
    root = _project(tmp_path)
    assert main(
        ["start"],
        project_root=root,
        epoch=lambda: 1_000.0,
        token_bytes=lambda _size: b"c" * 16,
        service=Service(),
    ) == 0
    capsys.readouterr()
    session = root / "runtime/private/voice-diagnostics/sessions" / ("63" * 16)
    orphan = session / "audio/000001.wav"
    orphan.write_bytes(b"synthetic")
    orphan.chmod(0o600)
    status = root / "runtime/status/voice.json"
    status.parent.mkdir()
    status.write_text(
        json.dumps(
            {
                "transition_counts": {
                    "voice_diagnostic_drops": 2,
                    "voice_diagnostic_failures": 3,
                }
            }
        ),
        encoding="ascii",
    )
    status.chmod(0o600)

    assert main(["status"], project_root=root, epoch=lambda: 1_001.0) == 0
    output = capsys.readouterr().out
    assert output == (
        "result=PASS\noperation=status\ndiagnostic_state=active\n"
        "complete_count=0\nincomplete_count=1\nbytes_used=0\n"
        "queue_drops=2\nwriter_failures=3\nexpires_in_seconds=1799\n"
    )
    for forbidden in (str(root), "63636363", "synthetic", "transcript"):
        assert forbidden not in output


def test_expired_session_can_be_stopped_and_retained(tmp_path: Path, capsys) -> None:
    root = _project(tmp_path)
    service = Service()
    assert main(
        ["start"],
        project_root=root,
        epoch=lambda: 1_000.0,
        token_bytes=lambda _size: b"d" * 16,
        service=service,
    ) == 0
    capsys.readouterr()

    assert main(["status"], project_root=root, epoch=lambda: 2_801.0) == 0
    assert capsys.readouterr().out == (
        "result=PASS\noperation=status\ndiagnostic_state=expired\n"
        "complete_count=0\nincomplete_count=0\nbytes_used=0\n"
        "queue_drops=0\nwriter_failures=0\nexpires_in_seconds=0\n"
    )
    assert main(
        ["stop"], project_root=root, epoch=lambda: 2_801.0, service=service
    ) == 0
    capsys.readouterr()
    diagnostics = root / "runtime/private/voice-diagnostics"
    assert not (diagnostics / "active.json").exists()
    assert (diagnostics / "sessions" / ("64" * 16)).is_dir()


def test_start_replaces_only_an_expired_valid_marker_and_retains_old_session(
    tmp_path: Path, capsys
) -> None:
    root = _project(tmp_path)
    service = Service()
    assert main(
        ["start"],
        project_root=root,
        epoch=lambda: 1_000.0,
        token_bytes=lambda _size: b"e" * 16,
        service=service,
    ) == 0
    capsys.readouterr()

    assert main(
        ["start"],
        project_root=root,
        epoch=lambda: 2_801.0,
        token_bytes=lambda _size: b"f" * 16,
        service=service,
    ) == 0
    capsys.readouterr()
    sessions = root / "runtime/private/voice-diagnostics/sessions"
    assert (sessions / ("65" * 16)).is_dir()
    assert (sessions / ("66" * 16)).is_dir()


def test_start_rejects_existing_unsafe_lock_without_repairing_it(
    tmp_path: Path, capsys
) -> None:
    root = _project(tmp_path)
    service = Service()
    assert main(
        ["start"], project_root=root, epoch=lambda: 1_000.0,
        token_bytes=lambda _size: b"g" * 16, service=service,
    ) == 0
    capsys.readouterr()
    assert main(
        ["stop"], project_root=root, epoch=lambda: 1_001.0, service=service
    ) == 0
    capsys.readouterr()
    lock = root / "runtime/private/voice-diagnostics/.lifecycle.lock"
    lock.chmod(0o644)
    service.calls.clear()

    assert main(
        ["start"], project_root=root, epoch=lambda: 1_002.0,
        token_bytes=lambda _size: b"h" * 16, service=service,
    ) == 1
    assert capsys.readouterr().out == (
        "result=FAIL\noperation=start\nreason=voice_diagnostic_storage_unavailable\n"
    )
    assert lock.stat().st_mode & 0o777 == 0o644
    assert service.calls == []


def test_interrupted_manifest_write_never_publishes_partial_final(
    tmp_path: Path, capsys, monkeypatch
) -> None:
    root = _project(tmp_path)
    real_write = os.write

    def interrupted_write(descriptor: int, data: bytes) -> int:
        real_write(descriptor, data[:1])
        raise OSError("synthetic write failure")

    monkeypatch.setattr("tools.voice_diagnostic.os.write", interrupted_write)
    assert main(
        ["start"], project_root=root, epoch=lambda: 1_000.0,
        token_bytes=lambda _size: b"i" * 16, service=Service(),
    ) == 1
    capsys.readouterr()
    session = (
        root / "runtime/private/voice-diagnostics/sessions" / ("69" * 16)
    )
    assert not (session / "session.json").exists()
    assert not (root / "runtime/private/voice-diagnostics/active.json").exists()
