from __future__ import annotations

import json
import os
import socket
import stat
import subprocess
import sys
import tempfile
import time
from pathlib import Path

import pytest

from packages.monitoring.private_remote_access import RemoteCode
from tools import private_remote_access as private_remote_access_module
from tools.private_remote_access import (
    CommandResult,
    HttpResult,
    collect_preflight,
    format_report,
    read_policy_acknowledgement,
    run_bounded,
)


TAILSCALE = "/usr/local/bin/tailscale"
LSOF = "/usr/sbin/lsof"
TAILNET = b'{"BackendState":"Running","Self":{"Online":true}}'
SERVE = b'''{
  "TCP":{"443":{"HTTPS":true}},
  "Web":{"node.example.invalid:443":{"Handlers":{"/":{"Proxy":"http://127.0.0.1:8080"}}}}
}'''
HEALTH = HttpResult(200, {}, b'{"status":"ok"}')
ROOT_CHALLENGE = HttpResult(401, {"www-authenticate": "Basic realm=monitor"}, b"")


class RecordingRunner:
    def __init__(self, responses: dict[tuple[str, ...], CommandResult]) -> None:
        self.responses = responses
        self.calls: list[tuple[tuple[str, ...], float]] = []

    def __call__(
        self, argv: tuple[str, ...], timeout_seconds: float
    ) -> CommandResult:
        self.calls.append((argv, timeout_seconds))
        return self.responses[argv]


class RecordingHttp:
    def __init__(self) -> None:
        self.calls: list[tuple[str, float]] = []

    def __call__(self, url: str, timeout_seconds: float) -> HttpResult:
        self.calls.append((url, timeout_seconds))
        if url.endswith("/healthz"):
            return HEALTH
        if url == "http://127.0.0.1:8080/":
            return ROOT_CHALLENGE
        raise AssertionError("unexpected HTTP target")


def _ok(stdout: bytes) -> CommandResult:
    return CommandResult(started=True, returncode=0, stdout=stdout)


def _closed() -> CommandResult:
    return CommandResult(started=True, returncode=1, stdout=b"")


def _responses() -> dict[tuple[str, ...], CommandResult]:
    return {
        (TAILSCALE, "status", "--json"): _ok(TAILNET),
        (TAILSCALE, "serve", "status", "--json"): _ok(SERVE),
        (LSOF, "-nP", "-iTCP:8080", "-sTCP:LISTEN"): _ok(
            b"COMMAND PID USER FD TYPE DEVICE SIZE/OFF NODE NAME\n"
            b"Python 123 user 4u IPv4 0t0 TCP *:8080 (LISTEN)\n"
        ),
        (LSOF, "-nP", "-iTCP:1984", "-sTCP:LISTEN"): _ok(
            b"COMMAND PID USER FD TYPE DEVICE SIZE/OFF NODE NAME\n"
            b"go2rtc 456 user 4u IPv4 0t0 TCP 127.0.0.1:1984 (LISTEN)\n"
        ),
        (LSOF, "-nP", "-iTCP:8554", "-sTCP:LISTEN"): _closed(),
        (LSOF, "-nP", "-iTCP:8555", "-sTCP:LISTEN"): _closed(),
    }


def _write_policy(root: Path) -> Path:
    path = root / "runtime/status/private-remote-policy.json"
    path.parent.mkdir(parents=True)
    path.write_text(
        '{"schema_version":1,"policy_reviewed":true,"serve_applied":true}\n',
        encoding="utf-8",
    )
    path.chmod(0o600)
    return path


def test_collect_preflight_uses_only_fixed_commands_and_loopback_http(
    tmp_path: Path,
) -> None:
    _write_policy(tmp_path)
    runner = RecordingRunner(_responses())
    http = RecordingHttp()

    report = collect_preflight(tmp_path, runner=runner, http_get=http)

    assert report.code is RemoteCode.READY_SOFTWARE
    assert runner.calls == [
        ((TAILSCALE, "status", "--json"), 5.0),
        ((TAILSCALE, "serve", "status", "--json"), 5.0),
        ((LSOF, "-nP", "-iTCP:8080", "-sTCP:LISTEN"), 5.0),
        ((LSOF, "-nP", "-iTCP:1984", "-sTCP:LISTEN"), 5.0),
        ((LSOF, "-nP", "-iTCP:8554", "-sTCP:LISTEN"), 5.0),
        ((LSOF, "-nP", "-iTCP:8555", "-sTCP:LISTEN"), 5.0),
    ]
    assert http.calls == [
        ("http://127.0.0.1:8080/healthz", 2.0),
        ("http://127.0.0.1:8080/", 2.0),
    ]


def test_report_output_is_exact_and_contains_no_collected_canary(tmp_path: Path) -> None:
    canary = b"secret-token@example.invalid private exception /Users/private"
    responses = _responses()
    responses[(TAILSCALE, "status", "--json")] = CommandResult(
        started=True,
        returncode=2,
        stdout=canary,
    )
    report = collect_preflight(
        tmp_path,
        runner=RecordingRunner(responses),
        http_get=RecordingHttp(),
    )

    output = format_report(report)

    assert output.splitlines() == [
        "remote_code=REMOTE_NOT_AUTHENTICATED",
        "tailnet_authenticated=false",
        "serve_fixed=true",
        "funnel_absent=true",
        "dashboard_healthy=true",
        "basic_auth_required=true",
        "go2rtc_private=true",
        "policy_reviewed=false",
    ]
    assert canary.decode() not in output


def test_missing_tailscale_executable_reports_not_installed(tmp_path: Path) -> None:
    responses = _responses()
    responses[(TAILSCALE, "status", "--json")] = CommandResult(
        started=False,
        returncode=None,
        stdout=b"",
    )

    report = collect_preflight(
        tmp_path,
        runner=RecordingRunner(responses),
        http_get=RecordingHttp(),
    )

    assert report.code is RemoteCode.NOT_INSTALLED


@pytest.mark.parametrize(
    ("port", "line"),
    (
        (1984, b"go2rtc 1 user 4u IPv4 0t0 TCP *:1984 (LISTEN)\n"),
        (8554, b"go2rtc 1 user 4u IPv4 0t0 TCP 10.0.0.2:8554 (LISTEN)\n"),
        (8555, b"malformed listener output\n"),
    ),
)
def test_go2rtc_nonloopback_or_invalid_listener_fails_closed(
    tmp_path: Path, port: int, line: bytes
) -> None:
    _write_policy(tmp_path)
    responses = _responses()
    responses[(LSOF, "-nP", f"-iTCP:{port}", "-sTCP:LISTEN")] = _ok(line)

    report = collect_preflight(
        tmp_path,
        runner=RecordingRunner(responses),
        http_get=RecordingHttp(),
    )

    assert report.code is RemoteCode.SERVE_CONFLICT
    assert report.go2rtc_private is False


@pytest.mark.parametrize(
    "health,root",
    (
        (HttpResult(200, {}, b'{"status":"degraded"}'), ROOT_CHALLENGE),
        (HttpResult(500, {}, b"failure"), ROOT_CHALLENGE),
        (HEALTH, HttpResult(200, {}, b"dashboard")),
        (HEALTH, HttpResult(401, {"www-authenticate": "Bearer"}, b"")),
    ),
)
def test_dashboard_requires_exact_health_and_basic_challenge(
    tmp_path: Path, health: HttpResult, root: HttpResult
) -> None:
    def http_get(url: str, _timeout: float) -> HttpResult:
        return health if url.endswith("/healthz") else root

    report = collect_preflight(
        tmp_path,
        runner=RecordingRunner(_responses()),
        http_get=http_get,
    )

    assert report.code is RemoteCode.DASHBOARD_UNHEALTHY


def test_policy_acknowledgement_accepts_only_exact_private_regular_file(
    tmp_path: Path,
) -> None:
    _write_policy(tmp_path)

    assert read_policy_acknowledgement(tmp_path) is True


@pytest.mark.parametrize(
    "payload",
    (
        "{}",
        '{"schema_version":1,"policy_reviewed":false,"serve_applied":true}',
        '{"schema_version":1,"policy_reviewed":true,"serve_applied":false}',
        '{"schema_version":1,"policy_reviewed":true,"serve_applied":true,"extra":1}',
        "not-json",
    ),
)
def test_policy_acknowledgement_rejects_wrong_schema_without_repair(
    tmp_path: Path, payload: str
) -> None:
    path = _write_policy(tmp_path)
    path.write_text(payload, encoding="utf-8")
    path.chmod(0o600)

    assert read_policy_acknowledgement(tmp_path) is False
    assert path.read_text(encoding="utf-8") == payload


def test_policy_acknowledgement_rejects_wrong_mode_without_chmod(
    tmp_path: Path,
) -> None:
    path = _write_policy(tmp_path)
    path.chmod(0o644)

    assert read_policy_acknowledgement(tmp_path) is False
    assert stat.S_IMODE(path.stat().st_mode) == 0o644


def test_policy_acknowledgement_rejects_wrong_owner_without_repair(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    path = _write_policy(tmp_path)
    actual_uid = os.getuid()
    monkeypatch.setattr(
        private_remote_access_module.os,
        "getuid",
        lambda: actual_uid + 1,
    )

    assert read_policy_acknowledgement(tmp_path) is False
    assert path.is_file()


def test_policy_acknowledgement_rejects_symlink_leaf_and_parent(
    tmp_path: Path,
) -> None:
    outside = tmp_path / "outside"
    outside.mkdir()
    target = outside / "policy.json"
    target.write_text(
        '{"schema_version":1,"policy_reviewed":true,"serve_applied":true}',
        encoding="utf-8",
    )
    target.chmod(0o600)

    leaf_root = tmp_path / "leaf-root"
    (leaf_root / "runtime/status").mkdir(parents=True)
    (leaf_root / "runtime/status/private-remote-policy.json").symlink_to(target)
    parent_root = tmp_path / "parent-root"
    parent_root.mkdir()
    (parent_root / "runtime").symlink_to(outside, target_is_directory=True)

    assert read_policy_acknowledgement(leaf_root) is False
    assert read_policy_acknowledgement(parent_root) is False
    assert target.is_file()


def test_policy_acknowledgement_rejects_fifo(tmp_path: Path) -> None:
    path = tmp_path / "runtime/status/private-remote-policy.json"
    path.parent.mkdir(parents=True)
    os.mkfifo(path, 0o600)

    assert read_policy_acknowledgement(tmp_path) is False
    assert stat.S_ISFIFO(path.lstat().st_mode)


def test_policy_acknowledgement_rejects_unix_socket() -> None:
    with tempfile.TemporaryDirectory(prefix="pra-", dir="/tmp") as temporary:
        root = Path(temporary)
        path = root / "runtime/status/private-remote-policy.json"
        path.parent.mkdir(parents=True)
        listener = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        try:
            try:
                listener.bind(str(path))
            except PermissionError:
                pytest.skip("sandbox does not permit Unix socket fixtures")
            assert read_policy_acknowledgement(root) is False
            assert stat.S_ISSOCK(path.lstat().st_mode)
        finally:
            listener.close()


def test_policy_acknowledgement_rejects_oversized_payload(tmp_path: Path) -> None:
    path = _write_policy(tmp_path)
    path.write_bytes(b"{" + b" " * 4096 + b"}")
    path.chmod(0o600)

    assert read_policy_acknowledgement(tmp_path) is False


def test_run_bounded_captures_stdout_and_discards_stderr() -> None:
    result = run_bounded(
        (
            sys.executable,
            "-c",
            "import sys;sys.stdout.buffer.write(b'public');sys.stderr.write('private')",
        ),
        2.0,
    )

    assert result == CommandResult(started=True, returncode=0, stdout=b"public")
    assert "private" not in repr(result)


def test_run_bounded_timeout_settles_child_before_return(tmp_path: Path) -> None:
    marker = tmp_path / "late-marker"
    code = (
        "import pathlib,signal,time;"
        "signal.signal(signal.SIGTERM,signal.SIG_IGN);"
        "time.sleep(0.6);"
        f"pathlib.Path({str(marker)!r}).write_text('late')"
    )

    result = run_bounded((sys.executable, "-c", code), 0.1)
    time.sleep(0.7)

    assert result.started is True
    assert result.returncode is None
    assert result.stdout == b""
    assert marker.exists() is False


def test_run_bounded_timeout_settles_same_group_descendant_before_return(
    tmp_path: Path,
) -> None:
    marker = tmp_path / "descendant-late-marker"
    ready = tmp_path / "descendant-ready"
    descendant = (
        "import pathlib,signal,time;"
        f"pathlib.Path({str(ready)!r}).write_text('ready');"
        "signal.signal(signal.SIGTERM,signal.SIG_IGN);"
        "time.sleep(0.8);"
        f"pathlib.Path({str(marker)!r}).write_text('late')"
    )
    parent = (
        "import pathlib,subprocess,sys,time;"
        f"subprocess.Popen([sys.executable,'-c',{descendant!r}]);"
        f"ready=pathlib.Path({str(ready)!r});"
        "[(time.sleep(0.01)) for _ in range(100) if not ready.exists()];"
        "time.sleep(2)"
    )

    result = run_bounded((sys.executable, "-c", parent), 0.5)
    time.sleep(0.9)

    assert result.started is True
    assert result.returncode is None
    assert ready.exists() is True
    assert marker.exists() is False


def test_run_bounded_output_cap_stops_and_discards_oversized_child() -> None:
    code = "import sys,time;sys.stdout.buffer.write(b'x'*1048577);sys.stdout.flush();time.sleep(1)"

    result = run_bounded((sys.executable, "-c", code), 2.0)

    assert result.started is True
    assert result.returncode is None
    assert result.stdout == b""


def test_cli_help_exposes_only_read_only_commands() -> None:
    result = subprocess.run(
        [sys.executable, str(Path(private_remote_access_module.__file__)), "--help"],
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0
    assert "preflight" in result.stdout
    assert "status" in result.stdout
    assert "configure" not in result.stdout
