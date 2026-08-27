"""Fail-closed macOS identity and ownership checks for Xiaomi media diagnostics."""

from __future__ import annotations

import os
import platform
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, Protocol

from packages.monitoring.go2rtc_build import GO2RTC_DESIGNATED_REQUIREMENT


PreflightCode = Literal[
    "ready",
    "unsupported",
    "app_identity_invalid",
    "launchd_owner_invalid",
    "listener_owner_invalid",
    "local_network_blocked",
    "local_network_unknown",
]
LocalNetworkState = Literal["available", "blocked", "unknown"]

_CODESIGN = "/usr/bin/codesign"
_LAUNCHCTL = "/bin/launchctl"
_LSOF = "/usr/sbin/lsof"
_FIREWALL = "/usr/libexec/ApplicationFirewall/socketfilterfw"
_LABEL = "com.babymonitor.go2rtc"
_COMMAND_TIMEOUT_SECONDS = 10.0
_MAX_RESULT_BYTES = 1_048_576
_PID_PATTERN = re.compile(rb"(?m)^[ \t]*pid = ([1-9][0-9]*)[ \t]*$")


@dataclass(frozen=True, slots=True)
class CommandResult:
    started: bool
    returncode: int | None
    stdout: bytes
    stderr: bytes


class BoundedRunner(Protocol):
    def __call__(
        self, argv: tuple[str, ...], timeout_seconds: float
    ) -> CommandResult: ...


@dataclass(frozen=True, slots=True)
class MacOSMediaPreflight:
    code: PreflightCode
    app_identity_ready: bool
    launchd_owner_count: int
    listener_owned_by_launchd: bool
    local_network_state: LocalNetworkState


def run_macos_media_preflight(
    root: Path, *, runner: BoundedRunner
) -> MacOSMediaPreflight:
    """Inspect only the installed app identity and local process ownership."""

    if platform.system() != "Darwin" or platform.machine() != "x86_64":
        return _report("unsupported")

    resolved_root = root.resolve()
    app = resolved_root / ".local/Go2RTC.app"
    executable = app / "Contents/MacOS/go2rtc"
    config = resolved_root / "runtime/go2rtc.yaml"
    if not _installed_app_exists(app, executable):
        return _report("app_identity_invalid")

    verify = runner(
        (
            _CODESIGN,
            "--verify",
            "--deep",
            "--strict",
            "--requirements",
            GO2RTC_DESIGNATED_REQUIREMENT,
            str(app),
        ),
        _COMMAND_TIMEOUT_SECONDS,
    )
    if verify.returncode != 0:
        return _report("app_identity_invalid")

    requirement = runner(
        (_CODESIGN, "-d", "-r-", str(app)), _COMMAND_TIMEOUT_SECONDS
    )
    if not _stable_requirement(requirement):
        return _report("app_identity_invalid")

    uid = os.getuid()
    launchctl = runner(
        (_LAUNCHCTL, "print", f"gui/{uid}/{_LABEL}"),
        _COMMAND_TIMEOUT_SECONDS,
    )
    owner_count, owner_pid, command_matches = _launchd_owner(
        launchctl,
        uid=uid,
        executable=executable,
        config=config,
    )
    if owner_count != 1 or owner_pid is None or not command_matches:
        return _report(
            "launchd_owner_invalid",
            app_identity_ready=True,
            launchd_owner_count=owner_count,
        )

    listener = runner(
        (_LSOF, "-nP", "-iTCP:1984", "-sTCP:LISTEN"),
        _COMMAND_TIMEOUT_SECONDS,
    )
    listener_ready = _listener_owned_by(listener, owner_pid)
    if not listener_ready:
        return _report(
            "listener_owner_invalid",
            app_identity_ready=True,
            launchd_owner_count=1,
        )

    firewall = runner(
        (_FIREWALL, "--getappblocked", str(app)),
        _COMMAND_TIMEOUT_SECONDS,
    )
    network_state = _firewall_state(firewall, app)
    if network_state == "blocked":
        code: PreflightCode = "local_network_blocked"
    elif network_state == "unknown":
        code = "local_network_unknown"
    else:
        code = "ready"
    return _report(
        code,
        app_identity_ready=True,
        launchd_owner_count=1,
        listener_owned_by_launchd=True,
        local_network_state=network_state,
    )


def _report(
    code: PreflightCode,
    *,
    app_identity_ready: bool = False,
    launchd_owner_count: int = 0,
    listener_owned_by_launchd: bool = False,
    local_network_state: LocalNetworkState = "unknown",
) -> MacOSMediaPreflight:
    return MacOSMediaPreflight(
        code=code,
        app_identity_ready=app_identity_ready,
        launchd_owner_count=launchd_owner_count,
        listener_owned_by_launchd=listener_owned_by_launchd,
        local_network_state=local_network_state,
    )


def _installed_app_exists(app: Path, executable: Path) -> bool:
    try:
        return app.is_dir() and executable.is_file() and os.access(executable, os.X_OK)
    except OSError:
        return False


def _payload(result: CommandResult) -> bytes | None:
    if (
        not result.started
        or result.returncode is None
        or len(result.stdout) + len(result.stderr) > _MAX_RESULT_BYTES
    ):
        return None
    return result.stdout + result.stderr


def _text(result: CommandResult) -> str | None:
    payload = _payload(result)
    if payload is None:
        return None
    try:
        return payload.decode("utf-8")
    except UnicodeDecodeError:
        return None


def _stable_requirement(result: CommandResult) -> bool:
    if result.returncode != 0:
        return False
    output = _text(result)
    if output is None or "cdhash" in output.lower():
        return False
    expected = GO2RTC_DESIGNATED_REQUIREMENT.removeprefix("=")
    designated = [
        line.strip()
        for line in output.splitlines()
        if line.strip().startswith("designated =>")
    ]
    return designated == [expected]


def _launchd_owner(
    result: CommandResult,
    *,
    uid: int,
    executable: Path,
    config: Path,
) -> tuple[int, int | None, bool]:
    payload = _payload(result)
    if result.returncode != 0 or payload is None:
        return 0, None, False
    matches = _PID_PATTERN.findall(payload)
    count = min(len(matches), 2)
    owner_pid = int(matches[0]) if len(matches) == 1 else None
    try:
        output = payload.decode("utf-8")
    except UnicodeDecodeError:
        return count, owner_pid, False

    lines = [line.strip() for line in output.splitlines() if line.strip()]
    header = f"gui/{uid}/{_LABEL} = {{"
    program = f"program = {executable}"
    state_ready = lines.count("state = running") == 1
    program_ready = lines.count(program) == 1
    arguments = _launchd_arguments(lines)
    expected_arguments = (str(executable), "-config", str(config))
    return (
        count,
        owner_pid,
        bool(lines and lines[0] == header and state_ready and program_ready)
        and arguments == expected_arguments,
    )


def _launchd_arguments(lines: list[str]) -> tuple[str, ...] | None:
    starts = [index for index, value in enumerate(lines) if value == "arguments = {"]
    if len(starts) != 1:
        return None
    values: list[str] = []
    for value in lines[starts[0] + 1 :]:
        if value == "}":
            return tuple(values)
        values.append(value)
    return None


def _listener_owned_by(result: CommandResult, owner_pid: int) -> bool:
    if result.returncode != 0:
        return False
    output = _text(result)
    if output is None:
        return False
    rows: list[tuple[int, str]] = []
    for line in output.splitlines():
        fields = line.split()
        if len(fields) < 4 or fields[-1] != "(LISTEN)" or not fields[1].isdigit():
            continue
        rows.append((int(fields[1]), fields[-2]))
    loopback = {"127.0.0.1:1984", "[::1]:1984"}
    return bool(rows) and all(
        pid == owner_pid and name in loopback for pid, name in rows
    )


def _firewall_state(result: CommandResult, app: Path) -> LocalNetworkState:
    """Classify only the exact app-firewall result, never media reachability."""

    if result.returncode != 0:
        return "unknown"
    output = _text(result)
    if output is None:
        return "unknown"
    lines = [line.strip() for line in output.splitlines() if line.strip()]
    permitted = f"Incoming connection to {app} is permitted"
    blocked = f"Incoming connection to {app} is blocked"
    if lines == [permitted]:
        return "available"
    if lines == [blocked]:
        return "blocked"
    return "unknown"
