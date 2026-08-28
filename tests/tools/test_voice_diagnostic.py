from __future__ import annotations

import json
import os
import signal
import stat
import subprocess
from pathlib import Path

import pytest

from tools import voice_diagnostic as voice_diagnostic_module
from tools.voice_diagnostic import main


class Service:
    def __init__(self, result: bool = True) -> None:
        self.result = result
        self.calls: list[str] = []

    def restart_voice(self) -> bool:
        self.calls.append("restart_voice")
        return self.result


def test_voice_restart_falls_back_to_exact_launchd_owned_pid_on_ssh_permission_error(
    tmp_path: Path, monkeypatch
) -> None:
    root = _project(tmp_path)
    python = root / ".venv-alpha/bin/python"
    worker = root / "tools/run_voice_worker.py"
    settings = root / "runtime/settings.yaml"
    models = root / "runtime/config/voice-care-models.json"
    status = root / "runtime/status/voice.json"
    for path in (python, worker, models, status):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.touch()
    old_pid = 41001
    new_pid = 41002
    current_pid = old_pid
    signalled: list[tuple[int, int]] = []
    signal_epoch_us = 200

    def launchctl_payload(pid: int) -> str:
        return f"""gui/501/com.babymonitor.voice = {{
\ttype = LaunchAgent
\tstate = running
\tprogram = {python}
\targuments = {{
\t\t{python}
\t\t{worker}
\t\t--settings
\t\t{settings}
\t\t--voice-models
\t\t{models}
\t}}
\tworking directory = {root}
\tpid = {pid}
}}
"""

    def fake_run(command, **_kwargs):
        nonlocal current_pid
        if command[:2] == ("bash", "tools/stop_alpha.sh"):
            return subprocess.CompletedProcess(
                command,
                1,
                b"",
                b"Boot-out failed: 1: Operation not permitted\n",
            )
        if command[:2] == ("/bin/launchctl", "print"):
            return subprocess.CompletedProcess(
                command, 0, launchctl_payload(current_pid).encode(), b""
            )
        if command[:2] == ("/bin/ps", "-ww"):
            output = (
                f"501 {python} {worker} --settings {settings} "
                f"--voice-models {models}\n"
            )
            return subprocess.CompletedProcess(command, 0, output.encode(), b"")
        if command[0] == str(python) and command[1] == str(
            root / "tools/voice_status.py"
        ):
            return subprocess.CompletedProcess(
                command,
                0
                if command[-4:]
                == (
                    "--require-worker-pid",
                    str(new_pid),
                    "--not-before-epoch-us",
                    str(signal_epoch_us),
                )
                else 1,
                b"",
                b"",
            )
        raise AssertionError(command)

    def fake_kill(pid: int, signum: int) -> None:
        nonlocal current_pid
        signalled.append((pid, signum))
        current_pid = new_pid

    monkeypatch.setattr(voice_diagnostic_module.os, "getuid", lambda: 501)
    monkeypatch.setattr(voice_diagnostic_module.os, "kill", fake_kill)
    monkeypatch.setattr(voice_diagnostic_module.platform, "system", lambda: "Darwin")
    monkeypatch.setattr(voice_diagnostic_module.subprocess, "run", fake_run)
    monkeypatch.setattr(voice_diagnostic_module.time, "sleep", lambda _value: None)
    monkeypatch.setattr(
        voice_diagnostic_module.time,
        "time_ns",
        lambda: signal_epoch_us * 1_000,
    )
    monotonic = iter((0.0, 0.0, 100.0))
    monkeypatch.setattr(
        voice_diagnostic_module.time, "monotonic", lambda: next(monotonic)
    )

    assert voice_diagnostic_module.VoiceService(root).restart_voice() is True
    assert signalled == [(old_pid, signal.SIGTERM)]


@pytest.mark.parametrize(
    ("stderr", "expected"),
    (
        (b"Boot-out failed: 1: Operation not permitted\n", True),
        (b"synthetic Operation not permitted\n", False),
        (b"Not privileged to signal service.\n", False),
    ),
)
def test_voice_restart_permission_fallback_requires_exact_launchctl_error(
    stderr: bytes, expected: bool
) -> None:
    assert voice_diagnostic_module._permission_denied(stderr) is expected


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


def test_private_uncommitted_temp_does_not_block_status_or_stop(
    tmp_path: Path, capsys
) -> None:
    root = _project(tmp_path)
    service = Service()
    assert main(
        ["start"],
        project_root=root,
        epoch=lambda: 1_000.0,
        token_bytes=lambda _size: b"q" * 16,
        service=service,
    ) == 0
    capsys.readouterr()
    audio = (
        root
        / "runtime/private/voice-diagnostics/sessions"
        / ("71" * 16)
        / "audio"
    )
    retained = audio / ".000001.0123456789abcdef.tmp"
    retained.write_bytes(b"synthetic")
    retained.chmod(0o600)

    assert main(
        ["status"], project_root=root, epoch=lambda: 1_001.0
    ) == 0
    assert "incomplete_count=1\n" in capsys.readouterr().out
    assert main(
        ["stop"],
        project_root=root,
        epoch=lambda: 1_002.0,
        service=service,
    ) == 0
    assert "diagnostic_state=inactive\n" in capsys.readouterr().out
    assert retained.is_file()


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


def test_failed_stop_restores_active_marker_for_honest_retry(
    tmp_path: Path, capsys
) -> None:
    root = _project(tmp_path)
    service = Service()
    assert main(
        ["start"], project_root=root, epoch=lambda: 1_000.0,
        token_bytes=lambda _size: b"j" * 16, service=service,
    ) == 0
    capsys.readouterr()
    service.result = False

    assert main(
        ["stop"], project_root=root, epoch=lambda: 1_001.0, service=service
    ) == 1
    assert capsys.readouterr().out == (
        "result=FAIL\noperation=stop\n"
        "reason=voice_diagnostic_service_unavailable\n"
    )
    assert (root / "runtime/private/voice-diagnostics/active.json").is_file()


def test_stop_parent_swap_fails_without_touching_replacement_marker(
    tmp_path: Path, capsys, monkeypatch
) -> None:
    root = _project(tmp_path)
    service = Service()
    assert main(
        ["start"],
        project_root=root,
        epoch=lambda: 1_000.0,
        token_bytes=lambda _size: b"l" * 16,
        service=service,
    ) == 0
    capsys.readouterr()
    diagnostics = root / "runtime/private/voice-diagnostics"
    outside = tmp_path / "outside"
    outside.mkdir(mode=0o700)
    replacement_marker = outside / "active.json"
    replacement_marker.write_bytes((diagnostics / "active.json").read_bytes())
    replacement_marker.chmod(0o600)
    real_load = voice_diagnostic_module.load_marker_session

    def swap_after_load(project_root: Path):
        session = real_load(project_root)
        diagnostics.rename(
            diagnostics.with_name("voice-diagnostics-original")
        )
        diagnostics.symlink_to(outside, target_is_directory=True)
        return session

    monkeypatch.setattr(
        voice_diagnostic_module, "load_marker_session", swap_after_load
    )
    service.calls.clear()

    assert main(
        ["stop"], project_root=root, epoch=lambda: 1_001.0, service=service
    ) == 1
    assert capsys.readouterr().out == (
        "result=FAIL\noperation=stop\n"
        "reason=voice_diagnostic_storage_unavailable\n"
    )
    assert replacement_marker.is_file()
    assert service.calls == []


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


def test_start_parent_swap_never_writes_into_replacement_directory(
    tmp_path: Path, capsys, monkeypatch
) -> None:
    root = _project(tmp_path)
    outside = tmp_path / "outside"
    outside.mkdir(mode=0o700)
    real_prepare = voice_diagnostic_module._prepare_private_tree

    def swap_after_prepare(project_root: Path) -> Path:
        diagnostics = real_prepare(project_root)
        diagnostics.rename(diagnostics.with_name("voice-diagnostics-original"))
        diagnostics.symlink_to(outside, target_is_directory=True)
        return diagnostics

    monkeypatch.setattr(
        voice_diagnostic_module, "_prepare_private_tree", swap_after_prepare
    )

    assert main(
        ["start"],
        project_root=root,
        epoch=lambda: 1_000.0,
        token_bytes=lambda _size: b"k" * 16,
        service=Service(),
    ) == 1
    assert capsys.readouterr().out == (
        "result=FAIL\noperation=start\n"
        "reason=voice_diagnostic_storage_unavailable\n"
    )
    assert list(outside.iterdir()) == []


def test_start_fails_if_private_parent_mode_changes_during_restart(
    tmp_path: Path, capsys
) -> None:
    root = _project(tmp_path)
    diagnostics = root / "runtime/private/voice-diagnostics"

    class WideningService(Service):
        def restart_voice(self) -> bool:
            self.calls.append("restart_voice")
            diagnostics.chmod(0o755)
            return True

    service = WideningService()
    assert main(
        ["start"],
        project_root=root,
        epoch=lambda: 1_000.0,
        token_bytes=lambda _size: b"m" * 16,
        service=service,
    ) == 1
    assert capsys.readouterr().out == (
        "result=FAIL\noperation=start\n"
        "reason=voice_diagnostic_storage_unavailable\n"
    )
    assert service.calls == ["restart_voice"]


def test_manifest_temp_mode_change_after_validation_leaves_no_final(
    tmp_path: Path, capsys, monkeypatch
) -> None:
    root = _project(tmp_path)
    real_require_identity = voice_diagnostic_module._require_temporary_identity
    changed = False

    def change_after_validation(directory_fd: int, temporary) -> None:
        nonlocal changed
        real_require_identity(directory_fd, temporary)
        if not changed:
            os.chmod(
                temporary.name,
                0o644,
                dir_fd=directory_fd,
                follow_symlinks=False,
            )
            changed = True

    monkeypatch.setattr(
        voice_diagnostic_module,
        "_require_temporary_identity",
        change_after_validation,
    )

    assert main(
        ["start"],
        project_root=root,
        epoch=lambda: 1_000.0,
        token_bytes=lambda _size: b"n" * 16,
        service=Service(),
    ) == 1
    assert capsys.readouterr().out == (
        "result=FAIL\noperation=start\n"
        "reason=voice_diagnostic_storage_unavailable\n"
    )
    session = (
        root
        / "runtime/private/voice-diagnostics/sessions"
        / ("6e" * 16)
    )
    assert not (session / "session.json").exists()


def test_cli_rollback_quarantine_is_retained_private_and_synced(
    tmp_path: Path, monkeypatch
) -> None:
    directory = tmp_path / "artifacts"
    directory.mkdir(mode=0o700)
    directory_fd = os.open(directory, os.O_RDONLY)
    real_require_identity = voice_diagnostic_module._require_temporary_identity
    real_rename = voice_diagnostic_module._rename_no_replace_at
    changed = False

    def change_after_validation(directory_fd: int, temporary) -> None:
        nonlocal changed
        real_require_identity(directory_fd, temporary)
        if not changed:
            os.chmod(
                temporary.name,
                0o644,
                dir_fd=directory_fd,
                follow_symlinks=False,
            )
            changed = True

    def occupy_original_after_rename(
        directory_fd: int, source: str, destination: str
    ) -> None:
        real_rename(directory_fd, source, destination)
        if destination == "session.json":
            descriptor = os.open(
                source,
                os.O_WRONLY | os.O_CREAT | os.O_EXCL,
                0o600,
                dir_fd=directory_fd,
            )
            os.close(descriptor)

    fsync_calls: list[int] = []
    real_fsync = voice_diagnostic_module.os.fsync

    def record_fsync(descriptor: int) -> None:
        fsync_calls.append(descriptor)
        real_fsync(descriptor)

    monkeypatch.setattr(
        voice_diagnostic_module,
        "_require_temporary_identity",
        change_after_validation,
    )
    monkeypatch.setattr(
        voice_diagnostic_module,
        "_rename_no_replace_at",
        occupy_original_after_rename,
    )
    monkeypatch.setattr(voice_diagnostic_module.os, "fsync", record_fsync)
    try:
        with pytest.raises(ValueError):
            voice_diagnostic_module._write_new_private_json_at(
                directory_fd,
                "session.json",
                {"schema_version": 1},
            )
    finally:
        os.close(directory_fd)

    names = [path.name for path in directory.iterdir()]
    quarantine = [
        path for path in directory.iterdir() if path.name.endswith(".quarantine")
    ]
    assert len(quarantine) == 1
    assert stat.S_IMODE(quarantine[0].stat().st_mode) == 0o600
    assert "session.json" not in names
    assert fsync_calls


def test_cli_replaced_rollback_candidate_is_not_deleted(
    tmp_path: Path, monkeypatch
) -> None:
    directory = tmp_path / "artifacts"
    directory.mkdir(mode=0o700)
    directory_fd = os.open(directory, os.O_RDONLY)
    real_require_identity = voice_diagnostic_module._require_temporary_identity
    real_rollback = voice_diagnostic_module._rollback_final_at
    changed = False
    replacement: Path | None = None

    def change_after_validation(directory_fd: int, temporary) -> None:
        nonlocal changed
        real_require_identity(directory_fd, temporary)
        if not changed:
            os.chmod(
                temporary.name,
                0o644,
                dir_fd=directory_fd,
                follow_symlinks=False,
            )
            changed = True

    def replace_after_rollback(directory_fd: int, temporary, final: str) -> str:
        nonlocal replacement
        candidate = real_rollback(directory_fd, temporary, final)
        held = f".{final}.held"
        os.rename(
            candidate,
            held,
            src_dir_fd=directory_fd,
            dst_dir_fd=directory_fd,
        )
        descriptor = os.open(
            candidate,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL,
            0o600,
            dir_fd=directory_fd,
        )
        os.close(descriptor)
        replacement = directory / candidate
        return candidate

    monkeypatch.setattr(
        voice_diagnostic_module,
        "_require_temporary_identity",
        change_after_validation,
    )
    monkeypatch.setattr(
        voice_diagnostic_module, "_rollback_final_at", replace_after_rollback
    )
    try:
        with pytest.raises(ValueError):
            voice_diagnostic_module._write_new_private_json_at(
                directory_fd,
                "session.json",
                {"schema_version": 1},
            )
    finally:
        os.close(directory_fd)

    assert replacement is not None
    assert replacement.is_file()


def test_cli_temporary_creation_failure_closes_fd_and_retains_private_name(
    tmp_path: Path, monkeypatch
) -> None:
    directory = tmp_path / "artifacts"
    directory.mkdir(mode=0o700)
    directory_fd = os.open(directory, os.O_RDONLY)
    real_open = voice_diagnostic_module.os.open
    opened: list[int] = []

    def recording_open(*args, **kwargs) -> int:
        descriptor = real_open(*args, **kwargs)
        opened.append(descriptor)
        return descriptor

    monkeypatch.setattr(voice_diagnostic_module.os, "open", recording_open)
    monkeypatch.setattr(
        voice_diagnostic_module.os,
        "fchmod",
        lambda _descriptor, _mode: (_ for _ in ()).throw(OSError()),
    )
    try:
        with pytest.raises(OSError):
            voice_diagnostic_module._new_temporary_file(
                directory_fd, "session.json"
            )
    finally:
        monkeypatch.undo()
        os.close(directory_fd)

    assert len(opened) == 1
    with pytest.raises(OSError):
        os.fstat(opened[0])
    retained = list(directory.iterdir())
    assert len(retained) == 1
    assert retained[0].name.endswith(".tmp")
    assert stat.S_IMODE(retained[0].stat().st_mode) == 0o600


@pytest.mark.parametrize(
    ("system", "function_name", "expected_flag"),
    (("Darwin", "renameatx_np", 4), ("Linux", "renameat2", 1)),
)
def test_cli_native_no_replace_uses_platform_function_and_flag(
    monkeypatch, system: str, function_name: str, expected_flag: int
) -> None:
    calls: list[tuple[object, ...]] = []

    class Function:
        argtypes = None
        restype = None

        def __call__(self, *args) -> int:
            calls.append(args)
            return 0

    function = Function()
    library = type("Library", (), {function_name: function})()
    monkeypatch.setattr(
        voice_diagnostic_module.platform, "system", lambda: system
    )
    monkeypatch.setattr(
        voice_diagnostic_module.ctypes,
        "CDLL",
        lambda *_args, **_kwargs: library,
    )

    voice_diagnostic_module._rename_no_replace_at(9, "source", "final")

    assert calls == [(9, b"source", 9, b"final", expected_flag)]


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
