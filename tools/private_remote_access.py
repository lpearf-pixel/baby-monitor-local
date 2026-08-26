"""Bounded, redacted local evidence collection for private Dashboard access."""

from __future__ import annotations

import argparse
import dataclasses
import json
import os
import secrets
import selectors
import signal
import stat
import subprocess
import sys
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Mapping, Protocol

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from packages.monitoring.private_remote_access import (
    DashboardEvidence,
    ListenerEvidence,
    RemoteAccessReport,
    RemoteCode,
    evaluate_remote_access,
    parse_serve_status,
    parse_tailnet_status,
)


TAILSCALE = "/usr/local/bin/tailscale"
LSOF = "/usr/sbin/lsof"
COMMAND_TIMEOUT_SECONDS = 5.0
CONFIGURE_TIMEOUT_SECONDS = 10.0
HTTP_TIMEOUT_SECONDS = 2.0
MAX_COMMAND_OUTPUT_BYTES = 1_048_576
MAX_HTTP_BODY_BYTES = 4_096
MAX_POLICY_BYTES = 4_096
POLICY_RELATIVE_PATH = Path("runtime/status/private-remote-policy.json")
HEALTH_URL = "http://127.0.0.1:8080/healthz"
DASHBOARD_URL = "http://127.0.0.1:8080/"
_HTTP_URLS = frozenset({HEALTH_URL, DASHBOARD_URL})
_POLICY_DOCUMENT = {
    "schema_version": 1,
    "policy_reviewed": True,
    "serve_applied": True,
}
_POLICY_BYTES = (
    json.dumps(_POLICY_DOCUMENT, separators=(",", ":"), sort_keys=True) + "\n"
).encode("ascii")
_CONFIGURE_ARGV = (
    TAILSCALE,
    "serve",
    "--bg",
    "http://127.0.0.1:8080",
)
_CONFIGURE_PRE_STATES = frozenset(
    {
        RemoteCode.POLICY_UNVERIFIED,
        RemoteCode.SERVE_UNCONFIGURED,
        RemoteCode.READY_SOFTWARE,
    }
)


@dataclass(frozen=True)
class CommandResult:
    started: bool
    returncode: int | None
    stdout: bytes


@dataclass(frozen=True)
class HttpResult:
    status: int | None
    headers: Mapping[str, str]
    body: bytes


class CommandRunner(Protocol):
    def __call__(
        self, argv: tuple[str, ...], timeout_seconds: float
    ) -> CommandResult: ...


class HttpGetter(Protocol):
    def __call__(self, url: str, timeout_seconds: float) -> HttpResult: ...


def run_bounded(
    argv: tuple[str, ...], timeout_seconds: float
) -> CommandResult:
    if (
        not argv
        or any(type(value) is not str or not value for value in argv)
        or not 0.1 <= timeout_seconds <= 30.0
    ):
        return CommandResult(False, None, b"")

    process: subprocess.Popen[bytes] | None = None
    selector = selectors.DefaultSelector()
    stdout = bytearray()
    total = 0
    try:
        process = subprocess.Popen(
            argv,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            shell=False,
            start_new_session=True,
            close_fds=True,
        )
        assert process.stdout is not None
        assert process.stderr is not None
        selector.register(process.stdout, selectors.EVENT_READ, True)
        selector.register(process.stderr, selectors.EVENT_READ, False)
        deadline = time.monotonic() + timeout_seconds

        while selector.get_map():
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                _settle_failed_process(process)
                return CommandResult(True, None, b"")
            events = selector.select(min(0.05, remaining))
            for key, _mask in events:
                try:
                    chunk = os.read(key.fileobj.fileno(), 65_536)
                except OSError:
                    chunk = b""
                if not chunk:
                    selector.unregister(key.fileobj)
                    continue
                total += len(chunk)
                if total > MAX_COMMAND_OUTPUT_BYTES:
                    _settle_failed_process(process)
                    return CommandResult(True, None, b"")
                if key.data is True:
                    stdout.extend(chunk)

        returncode = process.wait(timeout=max(0.1, deadline - time.monotonic()))
        return CommandResult(True, returncode, bytes(stdout))
    except (OSError, subprocess.SubprocessError, ValueError):
        if process is not None:
            _settle_failed_process(process)
        return CommandResult(process is not None, None, b"")
    finally:
        selector.close()
        if process is not None:
            if process.stdout is not None:
                process.stdout.close()
            if process.stderr is not None:
                process.stderr.close()


def _settle_failed_process(process: subprocess.Popen[bytes]) -> None:
    try:
        os.killpg(process.pid, signal.SIGTERM)
    except (OSError, ProcessLookupError):
        pass
    try:
        process.wait(timeout=0.25)
    except (OSError, subprocess.TimeoutExpired):
        pass
    try:
        os.killpg(process.pid, signal.SIGKILL)
    except (OSError, ProcessLookupError):
        pass
    try:
        process.wait(timeout=1.0)
    except (OSError, subprocess.TimeoutExpired):
        pass


def bounded_http_get(url: str, timeout_seconds: float) -> HttpResult:
    if url not in _HTTP_URLS or timeout_seconds != HTTP_TIMEOUT_SECONDS:
        return HttpResult(None, {}, b"")
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    request = urllib.request.Request(url, method="GET")
    response = None
    try:
        try:
            response = opener.open(request, timeout=timeout_seconds)
        except urllib.error.HTTPError as exc:
            response = exc
        body = response.read(MAX_HTTP_BODY_BYTES + 1)
        if len(body) > MAX_HTTP_BODY_BYTES:
            return HttpResult(None, {}, b"")
        headers: dict[str, str] = {}
        challenge = response.headers.get("WWW-Authenticate")
        if isinstance(challenge, str) and len(challenge) <= 256:
            headers["www-authenticate"] = challenge
        return HttpResult(int(response.status), headers, body)
    except (OSError, ValueError, urllib.error.URLError):
        return HttpResult(None, {}, b"")
    finally:
        if response is not None:
            response.close()


def collect_preflight(
    root: Path | str | None = None,
    *,
    runner: CommandRunner = run_bounded,
    http_get: HttpGetter = bounded_http_get,
) -> RemoteAccessReport:
    project_root = (
        Path(root) if root is not None else Path(__file__).resolve().parents[1]
    )
    tailnet_result = runner(
        (TAILSCALE, "status", "--json"), COMMAND_TIMEOUT_SECONDS
    )
    serve_result = runner(
        (TAILSCALE, "serve", "status", "--json"), COMMAND_TIMEOUT_SECONDS
    )
    listener_results = {
        port: runner(
            (LSOF, "-nP", f"-iTCP:{port}", "-sTCP:LISTEN"),
            COMMAND_TIMEOUT_SECONDS,
        )
        for port in (8080, 1984, 8554, 8555)
    }

    health = http_get(HEALTH_URL, HTTP_TIMEOUT_SECONDS)
    dashboard = http_get(DASHBOARD_URL, HTTP_TIMEOUT_SECONDS)
    dashboard_scope = _listener_scope(listener_results[8080], 8080)
    go2rtc_scopes = (
        _listener_scope(listener_results[1984], 1984),
        _listener_scope(listener_results[8554], 8554),
        _listener_scope(listener_results[8555], 8555),
    )
    installed = tailnet_result.started
    tailnet_payload = (
        tailnet_result.stdout if tailnet_result.returncode == 0 else b""
    )
    serve_payload = serve_result.stdout if serve_result.returncode == 0 else b""

    return evaluate_remote_access(
        installed=installed,
        tailnet=parse_tailnet_status(tailnet_payload),
        serve=parse_serve_status(serve_payload),
        listeners=ListenerEvidence(
            dashboard_available=dashboard_scope
            in {"loopback", "all_interfaces", "specific_interface"},
            go2rtc_loopback_only=all(
                scope in {"closed", "loopback"} for scope in go2rtc_scopes
            ),
        ),
        dashboard=DashboardEvidence(
            health_ok=_health_is_exact(health),
            basic_auth_required=_basic_challenge_is_exact(dashboard),
        ),
        policy_reviewed=read_policy_acknowledgement(project_root),
    )


def _listener_scope(result: CommandResult, port: int) -> str:
    if not result.started or result.returncode is None:
        return "invalid"
    if result.returncode == 1 and not result.stdout:
        return "closed"
    if result.returncode != 0 or not result.stdout:
        return "invalid"

    names: list[str] = []
    try:
        for raw_line in result.stdout.decode("utf-8").splitlines():
            fields = raw_line.split()
            if fields and fields[-1] == "(LISTEN)" and len(fields) >= 2:
                names.append(fields[-2])
    except UnicodeDecodeError:
        return "invalid"
    if not names:
        return "invalid"

    scopes: set[str] = set()
    suffix = f":{port}"
    for name in names:
        if not name.endswith(suffix):
            return "invalid"
        address = name[: -len(suffix)]
        if address in {"127.0.0.1", "[::1]"}:
            scopes.add("loopback")
        elif address in {"*", "0.0.0.0", "[::]"}:
            scopes.add("all_interfaces")
        elif address:
            scopes.add("specific_interface")
        else:
            return "invalid"
    return next(iter(scopes)) if len(scopes) == 1 else "specific_interface"


def _health_is_exact(result: HttpResult) -> bool:
    if result.status != 200 or len(result.body) > MAX_HTTP_BODY_BYTES:
        return False
    try:
        return json.loads(result.body) == {"status": "ok"}
    except (UnicodeDecodeError, json.JSONDecodeError):
        return False


def _basic_challenge_is_exact(result: HttpResult) -> bool:
    if result.status != 401:
        return False
    headers = {str(key).lower(): value for key, value in result.headers.items()}
    challenge = headers.get("www-authenticate")
    return bool(
        isinstance(challenge, str)
        and challenge.split(" ", 1)[0].lower() == "basic"
    )


def read_policy_acknowledgement(root: Path | str) -> bool:
    root_path = Path(root)
    path = root_path / POLICY_RELATIVE_PATH
    try:
        current = root_path
        root_stat = os.lstat(current)
        if not stat.S_ISDIR(root_stat.st_mode) or stat.S_ISLNK(root_stat.st_mode):
            return False
        for component in POLICY_RELATIVE_PATH.parts[:-1]:
            current = current / component
            current_stat = os.lstat(current)
            if not stat.S_ISDIR(current_stat.st_mode) or stat.S_ISLNK(
                current_stat.st_mode
            ):
                return False

        before = os.lstat(path)
        if (
            not stat.S_ISREG(before.st_mode)
            or stat.S_ISLNK(before.st_mode)
            or before.st_uid != os.getuid()
            or stat.S_IMODE(before.st_mode) != 0o600
            or before.st_size > MAX_POLICY_BYTES
        ):
            return False
        flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0)
        descriptor = os.open(path, flags)
        try:
            opened = os.fstat(descriptor)
            if (
                not stat.S_ISREG(opened.st_mode)
                or (opened.st_dev, opened.st_ino) != (before.st_dev, before.st_ino)
            ):
                return False
            payload = os.read(descriptor, MAX_POLICY_BYTES + 1)
        finally:
            os.close(descriptor)
    except OSError:
        return False
    if len(payload) > MAX_POLICY_BYTES:
        return False
    try:
        return json.loads(payload) == _POLICY_DOCUMENT
    except (UnicodeDecodeError, json.JSONDecodeError):
        return False


def write_policy_acknowledgement(root: Path | str) -> bool:
    root_path = Path(root)
    status_directory = _ensure_status_directory(root_path)
    if status_directory is None:
        return False
    path = status_directory / POLICY_RELATIVE_PATH.name
    temporary = status_directory / (
        f".private-remote-policy.{os.getpid()}.{secrets.token_hex(8)}"
    )
    descriptor: int | None = None
    try:
        if path.exists() or path.is_symlink():
            existing = os.lstat(path)
            if (
                not stat.S_ISREG(existing.st_mode)
                or stat.S_ISLNK(existing.st_mode)
                or existing.st_uid != os.getuid()
                or stat.S_IMODE(existing.st_mode) != 0o600
            ):
                return False
        flags = (
            os.O_WRONLY
            | os.O_CREAT
            | os.O_EXCL
            | getattr(os, "O_NOFOLLOW", 0)
        )
        descriptor = os.open(temporary, flags, 0o600)
        os.fchmod(descriptor, 0o600)
        remaining = memoryview(_POLICY_BYTES)
        while remaining:
            written = os.write(descriptor, remaining)
            if written <= 0:
                raise OSError("policy write failed")
            remaining = remaining[written:]
        os.fsync(descriptor)
        os.close(descriptor)
        descriptor = None
        os.replace(temporary, path)
        directory_flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
        directory_descriptor = os.open(status_directory, directory_flags)
        try:
            os.fsync(directory_descriptor)
        finally:
            os.close(directory_descriptor)
        return read_policy_acknowledgement(root_path)
    except OSError:
        return False
    finally:
        if descriptor is not None:
            try:
                os.close(descriptor)
            except OSError:
                pass
        try:
            temporary.unlink(missing_ok=True)
        except OSError:
            pass


def _ensure_status_directory(root: Path) -> Path | None:
    try:
        root_status = os.lstat(root)
        if (
            not stat.S_ISDIR(root_status.st_mode)
            or stat.S_ISLNK(root_status.st_mode)
            or root_status.st_uid != os.getuid()
        ):
            return None
        current = root
        for component in ("runtime", "status"):
            current = current / component
            try:
                os.mkdir(current, 0o700)
            except FileExistsError:
                pass
            current_status = os.lstat(current)
            if (
                not stat.S_ISDIR(current_status.st_mode)
                or stat.S_ISLNK(current_status.st_mode)
                or current_status.st_uid != os.getuid()
            ):
                return None
        return current
    except OSError:
        return None


def configure_remote_access(
    root: Path | str | None = None,
    *,
    runner: CommandRunner = run_bounded,
    http_get: HttpGetter = bounded_http_get,
    read_confirmation: Callable[[], str] | None = None,
    printer: Callable[[str], object] = print,
    policy_writer: Callable[[Path | str], bool] = write_policy_acknowledgement,
) -> RemoteAccessReport:
    project_root = (
        Path(root) if root is not None else Path(__file__).resolve().parents[1]
    )
    before = collect_preflight(project_root, runner=runner, http_get=http_get)
    if not _configure_preflight_is_safe(before):
        return before

    printer("policy_review_confirmation=required")
    printer("type_yes_to_apply_fixed_private_serve=")
    confirmation_reader = read_confirmation or _read_tty_confirmation
    try:
        confirmation = confirmation_reader()
    except (OSError, UnicodeError):
        return before
    if confirmation != "YES":
        return before

    after = before
    if not before.serve_fixed:
        mutation = runner(_CONFIGURE_ARGV, CONFIGURE_TIMEOUT_SECONDS)
        if mutation.returncode != 0:
            return before
        after = collect_preflight(project_root, runner=runner, http_get=http_get)
        if not _post_apply_is_safe(after):
            return after
    if not policy_writer(project_root):
        return after
    return dataclasses.replace(
        after,
        code=RemoteCode.READY_SOFTWARE,
        policy_reviewed=True,
    )


def _configure_preflight_is_safe(report: RemoteAccessReport) -> bool:
    return bool(
        report.code in _CONFIGURE_PRE_STATES
        and report.tailnet_authenticated
        and report.funnel_absent
        and report.dashboard_healthy
        and report.basic_auth_required
        and report.go2rtc_private
    )


def _post_apply_is_safe(report: RemoteAccessReport) -> bool:
    return bool(
        report.code in {RemoteCode.POLICY_UNVERIFIED, RemoteCode.READY_SOFTWARE}
        and report.tailnet_authenticated
        and report.serve_fixed
        and report.funnel_absent
        and report.dashboard_healthy
        and report.basic_auth_required
        and report.go2rtc_private
    )


def _read_tty_confirmation() -> str:
    descriptor = os.open("/dev/tty", os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
    try:
        payload = os.read(descriptor, 16)
    finally:
        os.close(descriptor)
    try:
        return payload.decode("ascii").rstrip("\r\n")
    except UnicodeDecodeError:
        return ""


def format_report(report: RemoteAccessReport) -> str:
    boolean = lambda value: "true" if value else "false"
    return "\n".join(
        (
            f"remote_code={report.code.value}",
            f"tailnet_authenticated={boolean(report.tailnet_authenticated)}",
            f"serve_fixed={boolean(report.serve_fixed)}",
            f"funnel_absent={boolean(report.funnel_absent)}",
            f"dashboard_healthy={boolean(report.dashboard_healthy)}",
            f"basic_auth_required={boolean(report.basic_auth_required)}",
            f"go2rtc_private={boolean(report.go2rtc_private)}",
            f"policy_reviewed={boolean(report.policy_reviewed)}",
        )
    )


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(
        description="Audit fixed private Dashboard access without changing state"
    )
    result.add_argument("command", choices=("preflight", "status", "configure"))
    return result


def main(argv: list[str] | None = None) -> int:
    options = parser().parse_args(argv)
    report = (
        configure_remote_access()
        if options.command == "configure"
        else collect_preflight()
    )
    print(format_report(report))
    return 0 if report.code is RemoteCode.READY_SOFTWARE else 1


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "CommandResult",
    "HttpResult",
    "bounded_http_get",
    "collect_preflight",
    "configure_remote_access",
    "format_report",
    "main",
    "read_policy_acknowledgement",
    "run_bounded",
    "write_policy_acknowledgement",
]
