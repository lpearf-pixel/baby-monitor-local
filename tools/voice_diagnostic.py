from __future__ import annotations

import ctypes
import errno
import fcntl
import json
import math
import os
import platform
import secrets
import shlex
import signal
import stat
import subprocess
import sys
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

import yaml

from services.voice.diagnostic import (
    DIAGNOSTIC_LIFETIME_SECONDS,
    DIAGNOSTIC_MAX_BYTES,
    DIAGNOSTIC_MAX_UTTERANCES,
    load_marker_session,
    snapshot_session_artifacts,
)


ROOT = Path(__file__).resolve().parents[1]
_PRIVATE_RELATIVE = Path("runtime/private/voice-diagnostics")
_MAX_SETTINGS_BYTES = 65_536
_MAX_STATUS_BYTES = 65_536
_SESSION_ID_BYTES = 16
_VOICE_LABEL = "com.babymonitor.voice"
_VOICE_JOB_BYTES = 65_536
_VOICE_RESTART_SECONDS = 45.0


class RestartService(Protocol):
    def restart_voice(self) -> bool: ...


@dataclass(frozen=True, slots=True)
class _LifecycleTree:
    root: int
    runtime: int
    private: int
    diagnostics: int
    sessions: int


@dataclass(frozen=True, slots=True)
class _TemporaryFile:
    descriptor: int
    name: str
    device: int
    inode: int


class VoiceService:
    def __init__(self, project_root: Path) -> None:
        self._project_root = project_root

    def restart_voice(self) -> bool:
        commands = (
            ("bash", "tools/stop_alpha.sh", "--voice-only"),
            ("bash", "tools/voice_listen_lifecycle.sh", "start"),
        )
        environment = {
            "HOME": str(Path.home()),
            "PATH": "/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin",
        }
        for index, (command, timeout) in enumerate(
            zip(commands, (10.0, 45.0), strict=True)
        ):
            try:
                completed = subprocess.run(
                    command,
                    cwd=self._project_root,
                    stdin=subprocess.DEVNULL,
                    stdout=subprocess.DEVNULL,
                    stderr=(
                        subprocess.PIPE if index == 0 else subprocess.DEVNULL
                    ),
                    check=False,
                    timeout=timeout,
                    env=environment,
                )
            except (OSError, subprocess.TimeoutExpired):
                if index == 1:
                    self._stop_after_failed_start(environment)
                return False
            if completed.returncode != 0:
                if (
                    index == 0
                    and _permission_denied(completed.stderr)
                    and self._restart_loaded_voice(environment)
                ):
                    return True
                if index == 1:
                    self._stop_after_failed_start(environment)
                return False
        return True

    def _restart_loaded_voice(self, environment: dict[str, str]) -> bool:
        if platform.system() != "Darwin":
            return False
        before = self._voice_job_pid(environment)
        if before is None:
            return False
        not_before_epoch_us = time.time_ns() // 1_000
        try:
            os.kill(before, signal.SIGTERM)
        except OSError:
            return False
        deadline = time.monotonic() + _VOICE_RESTART_SECONDS
        while time.monotonic() < deadline:
            after = self._voice_job_pid(environment)
            if after is not None and after != before:
                if self._voice_status_matches_worker(
                    environment, after, not_before_epoch_us
                ):
                    return True
            time.sleep(0.25)
        return False

    def _voice_job_pid(self, environment: dict[str, str]) -> int | None:
        root = self._project_root.resolve(strict=True)
        python = root / ".venv-alpha/bin/python"
        worker = root / "tools/run_voice_worker.py"
        settings = root / "runtime/settings.yaml"
        models = root / "runtime/config/voice-care-models.json"
        expected_command = (
            str(python),
            str(worker),
            "--settings",
            str(settings),
            "--voice-models",
            str(models),
        )
        if any("\n" in value or "\r" in value for value in expected_command):
            return None
        target = f"gui/{os.getuid()}/{_VOICE_LABEL}"
        try:
            completed = subprocess.run(
                ("/bin/launchctl", "print", target),
                cwd=root,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                check=False,
                timeout=2.0,
                env=environment,
            )
        except (OSError, subprocess.TimeoutExpired):
            return None
        payload = completed.stdout
        if (
            completed.returncode != 0
            or type(payload) is not bytes
            or not 0 < len(payload) <= _VOICE_JOB_BYTES
        ):
            return None
        try:
            text = payload.decode("utf-8")
        except UnicodeError:
            return None
        required_lines = (
            f"{target} = {{",
            "\ttype = LaunchAgent",
            "\tstate = running",
            f"\tprogram = {python}",
            f"\tworking directory = {root}",
            f"\t\t{python}",
            f"\t\t{worker}",
            "\t\t--settings",
            f"\t\t{settings}",
            "\t\t--voice-models",
            f"\t\t{models}",
        )
        lines = text.splitlines()
        if any(lines.count(line) != 1 for line in required_lines):
            return None
        pid_lines = [line for line in lines if line.startswith("\tpid = ")]
        if len(pid_lines) != 1 or not pid_lines[0][len("\tpid = ") :].isdigit():
            return None
        pid = int(pid_lines[0][len("\tpid = ") :])
        if pid <= 1:
            return None
        try:
            process = subprocess.run(
                (
                    "/bin/ps",
                    "-ww",
                    "-p",
                    str(pid),
                    "-o",
                    "uid=",
                    "-o",
                    "command=",
                ),
                cwd=root,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                check=False,
                timeout=2.0,
                env=environment,
            )
        except (OSError, subprocess.TimeoutExpired):
            return None
        output = process.stdout
        if (
            process.returncode != 0
            or type(output) is not bytes
            or not 0 < len(output) <= _VOICE_JOB_BYTES
        ):
            return None
        try:
            uid_text, command_text = output.decode("utf-8").strip().split(None, 1)
            command = tuple(shlex.split(command_text))
        except (UnicodeError, ValueError):
            return None
        if uid_text != str(os.getuid()) or command != expected_command:
            return None
        return pid

    def _voice_status_matches_worker(
        self,
        environment: dict[str, str],
        worker_pid: int,
        not_before_epoch_us: int,
    ) -> bool:
        root = self._project_root.resolve(strict=True)
        try:
            completed = subprocess.run(
                (
                    str(root / ".venv-alpha/bin/python"),
                    str(root / "tools/voice_status.py"),
                    str(root / "runtime/status/voice.json"),
                    "--require-mode",
                    "listen_only",
                    "--require-worker-pid",
                    str(worker_pid),
                    "--not-before-epoch-us",
                    str(not_before_epoch_us),
                ),
                cwd=root,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                check=False,
                timeout=2.0,
                env=environment,
            )
        except (OSError, subprocess.TimeoutExpired):
            return False
        return completed.returncode == 0

    def _stop_after_failed_start(self, environment: dict[str, str]) -> None:
        try:
            subprocess.run(
                ("bash", "tools/stop_alpha.sh", "--voice-only"),
                cwd=self._project_root,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                check=False,
                timeout=10.0,
                env=environment,
            )
        except (OSError, subprocess.TimeoutExpired):
            pass


def _permission_denied(stderr: object) -> bool:
    return type(stderr) is bytes and stderr in {
        b"Boot-out failed: 1: Operation not permitted",
        b"Boot-out failed: 1: Operation not permitted\n",
    }


def main(
    argv: list[str] | None = None,
    *,
    project_root: Path = ROOT,
    epoch: Callable[[], float] = time.time,
    token_bytes: Callable[[int], bytes] = secrets.token_bytes,
    service: RestartService | None = None,
    printer: Callable[[str], None] = print,
) -> int:
    arguments = list(sys.argv[1:] if argv is None else argv)
    if len(arguments) != 1 or arguments[0] not in {"start", "status", "stop"}:
        _failure(printer, "invalid", "voice_diagnostic_invalid_action")
        return 2
    operation = arguments[0]
    try:
        root = Path(project_root).resolve(strict=True)
        now_epoch = float(epoch())
        if not math.isfinite(now_epoch):
            raise ValueError("voice_diagnostic_storage_unavailable")
        if operation == "start":
            return _start(
                root,
                now_epoch=now_epoch,
                token_bytes=token_bytes,
                service=service or VoiceService(root),
                printer=printer,
            )
        if operation == "status":
            return _status(root, now_epoch=now_epoch, printer=printer)
        return _stop(
            root,
            now_epoch=now_epoch,
            service=service or VoiceService(root),
            printer=printer,
        )
    except (Exception, KeyboardInterrupt) as exc:
        reason = str(exc)
        if reason not in {
            "voice_diagnostic_already_active",
            "voice_diagnostic_mode_unavailable",
            "voice_diagnostic_service_unavailable",
            "voice_diagnostic_state_unavailable",
            "voice_diagnostic_storage_unavailable",
        }:
            reason = "voice_diagnostic_storage_unavailable"
        _failure(printer, operation, reason)
        return 1


def _start(
    root: Path,
    *,
    now_epoch: float,
    token_bytes: Callable[[int], bytes],
    service: RestartService,
    printer: Callable[[str], None],
) -> int:
    _require_listen_only_mode(root)
    _prepare_private_tree(root)
    with _open_lifecycle_tree(root, create=False) as tree:
        with _lifecycle_lock(tree.diagnostics):
            _require_lifecycle_bindings(tree)
            if _entry_exists_at(tree.diagnostics, "active.json"):
                identity = _private_file_identity_at(
                    tree.diagnostics, "active.json"
                )
                previous = load_marker_session(root)
                _require_lifecycle_bindings(tree)
                if previous is None or now_epoch < previous.created_epoch:
                    raise ValueError("voice_diagnostic_state_unavailable")
                if now_epoch < previous.expires_epoch:
                    raise ValueError("voice_diagnostic_already_active")
                _unlink_owned_marker_at(
                    tree.diagnostics, "active.json", identity
                )
            token = token_bytes(_SESSION_ID_BYTES)
            if type(token) is not bytes or len(token) != _SESSION_ID_BYTES:
                raise ValueError("voice_diagnostic_storage_unavailable")
            session_id = token.hex()
            session_fd = _create_private_directory_at(
                tree.sessions, session_id
            )
            try:
                audio_fd = _create_private_directory_at(session_fd, "audio")
                os.close(audio_fd)
                events_fd = _create_private_directory_at(session_fd, "events")
                os.close(events_fd)
                payload = {
                    "schema_version": 1,
                    "session_id": session_id,
                    "created_epoch": now_epoch,
                    "expires_epoch": now_epoch
                    + DIAGNOSTIC_LIFETIME_SECONDS,
                    "max_utterances": DIAGNOSTIC_MAX_UTTERANCES,
                    "max_bytes": DIAGNOSTIC_MAX_BYTES,
                }
                _write_new_private_json_at(
                    session_fd, "session.json", payload
                )
                _require_lifecycle_bindings(tree)
                marker_identity = _write_new_private_json_at(
                    tree.diagnostics, "active.json", payload
                )
                if not service.restart_voice():
                    _unlink_owned_marker_at(
                        tree.diagnostics,
                        "active.json",
                        marker_identity,
                    )
                    raise ValueError("voice_diagnostic_service_unavailable")
                _require_lifecycle_bindings(tree)
            finally:
                os.close(session_fd)
    printer("result=PASS")
    printer("operation=start")
    printer("diagnostic_state=active")
    printer(f"max_seconds={DIAGNOSTIC_LIFETIME_SECONDS}")
    printer(f"max_utterances={DIAGNOSTIC_MAX_UTTERANCES}")
    printer(f"max_bytes={DIAGNOSTIC_MAX_BYTES}")
    return 0


def _status(
    root: Path, *, now_epoch: float, printer: Callable[[str], None]
) -> int:
    diagnostics = root / _PRIVATE_RELATIVE
    marker = diagnostics / "active.json"
    if not marker.exists() and not marker.is_symlink():
        _print_status(
            printer,
            state="inactive",
            complete=0,
            incomplete=0,
            used=0,
            drops=0,
            failures=0,
            expires=0,
        )
        return 0
    session = load_marker_session(root)
    if session is None:
        raise ValueError("voice_diagnostic_state_unavailable")
    if now_epoch < session.created_epoch:
        raise ValueError("voice_diagnostic_state_unavailable")
    snapshot = snapshot_session_artifacts(session)
    drops, failures = _worker_diagnostic_counts(root)
    _print_status(
        printer,
        state="active" if now_epoch < session.expires_epoch else "expired",
        complete=snapshot.complete_count,
        incomplete=snapshot.incomplete_count,
        used=snapshot.complete_bytes,
        drops=drops,
        failures=failures,
        expires=max(0, int(session.expires_epoch - now_epoch)),
    )
    return 0


def _stop(
    root: Path,
    *,
    now_epoch: float,
    service: RestartService,
    printer: Callable[[str], None],
) -> int:
    with _open_lifecycle_tree(root, create=False) as tree:
        with _lifecycle_lock(tree.diagnostics):
            _require_lifecycle_bindings(tree)
            identity = _private_file_identity_at(
                tree.diagnostics, "active.json"
            )
            session = load_marker_session(root)
            _require_lifecycle_bindings(tree)
            if session is None or now_epoch < session.created_epoch:
                raise ValueError("voice_diagnostic_state_unavailable")
            payload = {
                "schema_version": 1,
                "session_id": session.session_id,
                "created_epoch": session.created_epoch,
                "expires_epoch": session.expires_epoch,
                "max_utterances": DIAGNOSTIC_MAX_UTTERANCES,
                "max_bytes": DIAGNOSTIC_MAX_BYTES,
            }
            _unlink_owned_marker_at(
                tree.diagnostics, "active.json", identity
            )
            if not service.restart_voice():
                _require_lifecycle_bindings(tree)
                _write_new_private_json_at(
                    tree.diagnostics, "active.json", payload
                )
                raise ValueError("voice_diagnostic_service_unavailable")
            _require_lifecycle_bindings(tree)
    printer("result=PASS")
    printer("operation=stop")
    printer("diagnostic_state=inactive")
    printer("session_retained=true")
    return 0


def _require_listen_only_mode(root: Path) -> None:
    path = root / "runtime/settings.yaml"
    payload = _read_bounded_file(path, _MAX_SETTINGS_BYTES)
    parsed = yaml.safe_load(payload.decode("utf-8"))
    voice = parsed.get("voice_care") if isinstance(parsed, dict) else None
    if not isinstance(voice, dict) or not (
        voice.get("enabled") is False
        and voice.get("listen_only_enabled") is True
        and voice.get("camera_reply_enabled") is False
    ):
        raise ValueError("voice_diagnostic_mode_unavailable")


def _prepare_private_tree(root: Path) -> Path:
    with _open_lifecycle_tree(root, create=True):
        pass
    return root / _PRIVATE_RELATIVE


@contextmanager
def _open_lifecycle_tree(
    root: Path, *, create: bool
) -> Iterator[_LifecycleTree]:
    opened: list[int] = []
    flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(
        os, "O_NOFOLLOW", 0
    )
    try:
        root_fd = os.open(root, flags)
        opened.append(root_fd)
        runtime_fd = _open_directory_at(
            root_fd, "runtime", private=False, create=False
        )
        opened.append(runtime_fd)
        private_fd = _open_directory_at(
            runtime_fd, "private", private=True, create=create
        )
        opened.append(private_fd)
        diagnostics_fd = _open_directory_at(
            private_fd,
            "voice-diagnostics",
            private=True,
            create=create,
        )
        opened.append(diagnostics_fd)
        sessions_fd = _open_directory_at(
            diagnostics_fd, "sessions", private=True, create=create
        )
        opened.append(sessions_fd)
        tree = _LifecycleTree(
            root_fd,
            runtime_fd,
            private_fd,
            diagnostics_fd,
            sessions_fd,
        )
        _require_lifecycle_bindings(tree)
        yield tree
    finally:
        for descriptor in reversed(opened):
            os.close(descriptor)


def _open_directory_at(
    parent_fd: int,
    name: str,
    *,
    private: bool,
    create: bool,
) -> int:
    flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(
        os, "O_NOFOLLOW", 0
    )
    if create:
        try:
            os.mkdir(name, 0o700, dir_fd=parent_fd)
            os.fsync(parent_fd)
        except FileExistsError:
            pass
    descriptor = os.open(name, flags, dir_fd=parent_fd)
    try:
        info = os.fstat(descriptor)
        mode = stat.S_IMODE(info.st_mode)
        if (
            not stat.S_ISDIR(info.st_mode)
            or info.st_uid != os.getuid()
            or private
            and mode != 0o700
            or not private
            and mode & 0o022
        ):
            raise ValueError("voice_diagnostic_storage_unavailable")
        return descriptor
    except Exception:
        os.close(descriptor)
        raise


def _create_private_directory_at(parent_fd: int, name: str) -> int:
    return _open_directory_at(
        parent_fd, name, private=True, create=True
    )


def _require_lifecycle_bindings(tree: _LifecycleTree) -> None:
    for parent, name, child, private in (
        (tree.root, "runtime", tree.runtime, False),
        (tree.runtime, "private", tree.private, True),
        (tree.private, "voice-diagnostics", tree.diagnostics, True),
        (tree.diagnostics, "sessions", tree.sessions, True),
    ):
        entry = os.stat(name, dir_fd=parent, follow_symlinks=False)
        opened = os.fstat(child)
        for info in (entry, opened):
            mode = stat.S_IMODE(info.st_mode)
            if (
                not stat.S_ISDIR(info.st_mode)
                or info.st_uid != os.getuid()
                or private
                and mode != 0o700
                or not private
                and mode & 0o022
            ):
                raise ValueError("voice_diagnostic_storage_unavailable")
        if (entry.st_dev, entry.st_ino) != (opened.st_dev, opened.st_ino):
            raise ValueError("voice_diagnostic_storage_unavailable")


@contextmanager
def _lifecycle_lock(diagnostics_fd: int) -> Iterator[None]:
    flags = os.O_RDWR | os.O_NONBLOCK | getattr(os, "O_NOFOLLOW", 0)
    created = False
    try:
        descriptor = os.open(
            ".lifecycle.lock",
            flags | os.O_CREAT | os.O_EXCL,
            0o600,
            dir_fd=diagnostics_fd,
        )
        created = True
    except FileExistsError:
        descriptor = os.open(
            ".lifecycle.lock", flags, dir_fd=diagnostics_fd
        )
    try:
        if created:
            os.fchmod(descriptor, 0o600)
        info = os.fstat(descriptor)
        if (
            not stat.S_ISREG(info.st_mode)
            or info.st_uid != os.getuid()
            or stat.S_IMODE(info.st_mode) != 0o600
            or info.st_nlink != 1
        ):
            raise ValueError("voice_diagnostic_storage_unavailable")
        try:
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise ValueError("voice_diagnostic_storage_unavailable") from None
        if created:
            os.fsync(diagnostics_fd)
        yield
    finally:
        os.close(descriptor)


def _write_new_private_json_at(
    directory_fd: int, name: str, payload: dict[str, object]
) -> tuple[int, int]:
    data = (json.dumps(payload, ensure_ascii=True, sort_keys=True) + "\n").encode(
        "ascii"
    )
    temporary = _new_temporary_file(directory_fd, name)
    try:
        offset = 0
        while offset < len(data):
            count = os.write(temporary.descriptor, data[offset:])
            if count <= 0:
                raise OSError
            offset += count
        os.fsync(temporary.descriptor)
        _require_temporary_identity(directory_fd, temporary)
        _rename_no_replace_at(directory_fd, temporary.name, name)
        try:
            info = _private_file_info_at(
                directory_fd,
                name,
                reason="voice_diagnostic_storage_unavailable",
            )
            if (info.st_dev, info.st_ino) != (
                temporary.device,
                temporary.inode,
            ):
                raise ValueError("voice_diagnostic_storage_unavailable")
            os.fsync(directory_fd)
            return info.st_dev, info.st_ino
        except Exception:
            os.fchmod(temporary.descriptor, 0o600)
            os.fsync(temporary.descriptor)
            _rollback_final_at(directory_fd, temporary, name)
            os.fsync(directory_fd)
            raise
    finally:
        os.close(temporary.descriptor)


def _new_temporary_file(directory_fd: int, basename: str) -> _TemporaryFile:
    flags = os.O_RDWR | os.O_CREAT | os.O_EXCL | getattr(
        os, "O_NOFOLLOW", 0
    )
    for _attempt in range(8):
        name = f".{basename}.{secrets.token_hex(8)}.tmp"
        try:
            descriptor = os.open(
                name, flags, 0o600, dir_fd=directory_fd
            )
        except FileExistsError:
            continue
        try:
            os.fchmod(descriptor, 0o600)
            info = os.fstat(descriptor)
            return _TemporaryFile(
                descriptor, name, info.st_dev, info.st_ino
            )
        except Exception:
            os.close(descriptor)
            raise
    raise ValueError("voice_diagnostic_storage_unavailable")


def _require_temporary_identity(
    directory_fd: int, temporary: _TemporaryFile
) -> None:
    opened = os.fstat(temporary.descriptor)
    entry = os.stat(
        temporary.name, dir_fd=directory_fd, follow_symlinks=False
    )
    expected = (temporary.device, temporary.inode)
    for info in (opened, entry):
        if (
            not stat.S_ISREG(info.st_mode)
            or info.st_uid != os.getuid()
            or stat.S_IMODE(info.st_mode) != 0o600
            or info.st_nlink != 1
            or (info.st_dev, info.st_ino) != expected
        ):
            raise ValueError("voice_diagnostic_storage_unavailable")


def _rename_no_replace_at(
    directory_fd: int, source: str, destination: str
) -> None:
    library = ctypes.CDLL(None, use_errno=True)
    system = platform.system()
    if system == "Darwin":
        function = library.renameatx_np
        flag = 4
    elif system == "Linux":
        function = library.renameat2
        flag = 1
    else:
        raise OSError
    function.argtypes = (
        ctypes.c_int,
        ctypes.c_char_p,
        ctypes.c_int,
        ctypes.c_char_p,
        ctypes.c_uint,
    )
    function.restype = ctypes.c_int
    result = function(
        directory_fd,
        os.fsencode(source),
        directory_fd,
        os.fsencode(destination),
        flag,
    )
    if result != 0:
        error = ctypes.get_errno()
        if error == errno.EEXIST:
            raise FileExistsError(
                error, "voice_diagnostic_storage_unavailable"
            )
        raise OSError(error, "voice_diagnostic_storage_unavailable")


def _rollback_final_at(
    directory_fd: int, temporary: _TemporaryFile, final: str
) -> str:
    candidates = [temporary.name]
    candidates.extend(
        f".{final}.{secrets.token_hex(8)}.quarantine" for _ in range(8)
    )
    for candidate in candidates:
        try:
            _rename_no_replace_at(directory_fd, final, candidate)
            return candidate
        except FileExistsError:
            continue
    raise ValueError("voice_diagnostic_storage_unavailable")


def _private_file_info_at(
    directory_fd: int,
    name: str,
    *,
    reason: str = "voice_diagnostic_state_unavailable",
) -> os.stat_result:
    info = os.stat(name, dir_fd=directory_fd, follow_symlinks=False)
    if (
        not stat.S_ISREG(info.st_mode)
        or info.st_uid != os.getuid()
        or stat.S_IMODE(info.st_mode) != 0o600
        or info.st_nlink != 1
    ):
        raise ValueError(reason)
    return info


def _private_file_identity_at(
    directory_fd: int, name: str
) -> tuple[int, int]:
    info = _private_file_info_at(directory_fd, name)
    return info.st_dev, info.st_ino


def _unlink_owned_marker_at(
    directory_fd: int, name: str, expected: tuple[int, int]
) -> None:
    if _private_file_identity_at(directory_fd, name) != expected:
        raise ValueError("voice_diagnostic_state_unavailable")
    os.unlink(name, dir_fd=directory_fd)
    os.fsync(directory_fd)


def _entry_exists_at(directory_fd: int, name: str) -> bool:
    try:
        os.stat(name, dir_fd=directory_fd, follow_symlinks=False)
        return True
    except FileNotFoundError:
        return False


def _read_bounded_file(path: Path, maximum: int) -> bytes:
    descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
    try:
        info = os.fstat(descriptor)
        if (
            not stat.S_ISREG(info.st_mode)
            or info.st_uid != os.getuid()
            or info.st_mode & 0o022
            or info.st_nlink != 1
            or not 0 < info.st_size <= maximum
        ):
            raise ValueError
        data = os.read(descriptor, maximum + 1)
        if len(data) != info.st_size:
            raise ValueError
        return data
    finally:
        os.close(descriptor)


def _worker_diagnostic_counts(root: Path) -> tuple[int, int]:
    try:
        payload = json.loads(
            _read_bounded_file(root / "runtime/status/voice.json", _MAX_STATUS_BYTES)
        )
        counts = payload.get("transition_counts")
        if not isinstance(counts, dict):
            return 0, 0
        drops = counts.get("voice_diagnostic_drops", 0)
        failures = counts.get("voice_diagnostic_failures", 0)
        if any(type(value) is not int or not 0 <= value <= 9_007_199_254_740_991
               for value in (drops, failures)):
            return 0, 0
        return drops, failures
    except Exception:
        return 0, 0


def _print_status(
    printer: Callable[[str], None],
    *,
    state: str,
    complete: int,
    incomplete: int,
    used: int,
    drops: int,
    failures: int,
    expires: int,
) -> None:
    printer("result=PASS")
    printer("operation=status")
    printer(f"diagnostic_state={state}")
    printer(f"complete_count={complete}")
    printer(f"incomplete_count={incomplete}")
    printer(f"bytes_used={used}")
    printer(f"queue_drops={drops}")
    printer(f"writer_failures={failures}")
    printer(f"expires_in_seconds={expires}")


def _failure(printer: Callable[[str], None], operation: str, reason: str) -> None:
    printer("result=FAIL")
    printer(f"operation={operation}")
    printer(f"reason={reason}")


if __name__ == "__main__":
    raise SystemExit(main())
