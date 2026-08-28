from __future__ import annotations

import fcntl
import json
import math
import os
import secrets
import stat
import subprocess
import sys
import tempfile
import time
from collections.abc import Callable, Iterator
from contextlib import contextmanager
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


class RestartService(Protocol):
    def restart_voice(self) -> bool: ...


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
                    stderr=subprocess.DEVNULL,
                    check=False,
                    timeout=timeout,
                    env=environment,
                )
            except (OSError, subprocess.TimeoutExpired):
                if index == 1:
                    self._stop_after_failed_start(environment)
                return False
            if completed.returncode != 0:
                if index == 1:
                    self._stop_after_failed_start(environment)
                return False
        return True

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
    diagnostics = _prepare_private_tree(root)
    with _lifecycle_lock(diagnostics):
        marker = diagnostics / "active.json"
        if marker.exists() or marker.is_symlink():
            identity = _private_file_identity(marker)
            previous = load_marker_session(root)
            if previous is None or now_epoch < previous.created_epoch:
                raise ValueError("voice_diagnostic_state_unavailable")
            if now_epoch < previous.expires_epoch:
                raise ValueError("voice_diagnostic_already_active")
            _unlink_owned_marker(marker, identity)
        token = token_bytes(_SESSION_ID_BYTES)
        if type(token) is not bytes or len(token) != _SESSION_ID_BYTES:
            raise ValueError("voice_diagnostic_storage_unavailable")
        session_id = token.hex()
        session_root = diagnostics / "sessions" / session_id
        _create_private_directory(session_root)
        _create_private_directory(session_root / "audio")
        _create_private_directory(session_root / "events")
        payload = {
            "schema_version": 1,
            "session_id": session_id,
            "created_epoch": now_epoch,
            "expires_epoch": now_epoch + DIAGNOSTIC_LIFETIME_SECONDS,
            "max_utterances": DIAGNOSTIC_MAX_UTTERANCES,
            "max_bytes": DIAGNOSTIC_MAX_BYTES,
        }
        _write_new_private_json(session_root / "session.json", payload)
        marker_identity = _write_new_private_json(marker, payload)
        if not service.restart_voice():
            _unlink_owned_marker(marker, marker_identity)
            raise ValueError("voice_diagnostic_service_unavailable")
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
    diagnostics = root / _PRIVATE_RELATIVE
    _require_private_directory(diagnostics)
    with _lifecycle_lock(diagnostics):
        marker = diagnostics / "active.json"
        identity = _private_file_identity(marker)
        session = load_marker_session(root)
        if session is None or now_epoch < session.created_epoch:
            raise ValueError("voice_diagnostic_state_unavailable")
        _unlink_owned_marker(marker, identity)
        if not service.restart_voice():
            raise ValueError("voice_diagnostic_service_unavailable")
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
    runtime = root / "runtime"
    _require_owned_directory(runtime)
    private = runtime / "private"
    diagnostics = private / "voice-diagnostics"
    sessions = diagnostics / "sessions"
    for directory in (private, diagnostics, sessions):
        if directory.exists() or directory.is_symlink():
            _require_private_directory(directory)
        else:
            _create_private_directory(directory)
    return diagnostics


def _create_private_directory(path: Path) -> None:
    path.mkdir(mode=0o700)
    _require_private_directory(path)
    _fsync_directory(path.parent)


@contextmanager
def _lifecycle_lock(diagnostics: Path) -> Iterator[None]:
    lock_path = diagnostics / ".lifecycle.lock"
    flags = os.O_RDWR | os.O_NONBLOCK | getattr(os, "O_NOFOLLOW", 0)
    created = False
    try:
        descriptor = os.open(lock_path, flags | os.O_CREAT | os.O_EXCL, 0o600)
        created = True
    except FileExistsError:
        descriptor = os.open(lock_path, flags)
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
        yield
    finally:
        os.close(descriptor)


def _write_new_private_json(
    path: Path, payload: dict[str, object]
) -> tuple[int, int]:
    data = (json.dumps(payload, ensure_ascii=True, sort_keys=True) + "\n").encode(
        "ascii"
    )
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
    )
    temporary = Path(temporary_name)
    try:
        try:
            os.fchmod(descriptor, 0o600)
            offset = 0
            while offset < len(data):
                offset += os.write(descriptor, data[offset:])
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
        os.link(temporary, path, follow_symlinks=False)
        temporary.unlink()
        _fsync_directory(path.parent)
        info = path.lstat()
        return info.st_dev, info.st_ino
    finally:
        try:
            temporary.unlink()
        except FileNotFoundError:
            pass


def _private_file_identity(path: Path) -> tuple[int, int]:
    info = path.lstat()
    if (
        not stat.S_ISREG(info.st_mode)
        or info.st_uid != os.getuid()
        or stat.S_IMODE(info.st_mode) != 0o600
        or info.st_nlink != 1
    ):
        raise ValueError("voice_diagnostic_state_unavailable")
    return info.st_dev, info.st_ino


def _unlink_owned_marker(path: Path, expected: tuple[int, int]) -> None:
    if _private_file_identity(path) != expected:
        raise ValueError("voice_diagnostic_state_unavailable")
    path.unlink()
    _fsync_directory(path.parent)


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


def _require_private_directory(path: Path) -> None:
    info = path.lstat()
    if (
        not stat.S_ISDIR(info.st_mode)
        or info.st_uid != os.getuid()
        or stat.S_IMODE(info.st_mode) != 0o700
    ):
        raise ValueError("voice_diagnostic_storage_unavailable")


def _require_owned_directory(path: Path) -> None:
    info = path.lstat()
    if (
        not stat.S_ISDIR(info.st_mode)
        or info.st_uid != os.getuid()
        or stat.S_IMODE(info.st_mode) & 0o022
    ):
        raise ValueError("voice_diagnostic_storage_unavailable")


def _fsync_directory(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


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
