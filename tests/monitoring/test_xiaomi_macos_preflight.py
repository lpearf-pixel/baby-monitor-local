from __future__ import annotations

from pathlib import Path

import pytest

from packages.monitoring import xiaomi_macos_preflight as preflight
from packages.monitoring.xiaomi_macos_preflight import (
    CommandResult,
    MacOSMediaPreflight,
    run_macos_media_preflight,
)


_CODESIGN = "/usr/bin/codesign"
_LAUNCHCTL = "/bin/launchctl"
_LSOF = "/usr/sbin/lsof"
_FIREWALL = "/usr/libexec/ApplicationFirewall/socketfilterfw"
_LABEL = "com.babymonitor.go2rtc"
_PID = 4242


class FakeRunner:
    def __init__(self, responses: dict[tuple[str, ...], CommandResult]) -> None:
        self.responses = responses
        self.calls: list[tuple[tuple[str, ...], float]] = []

    def __call__(
        self, argv: tuple[str, ...], timeout_seconds: float
    ) -> CommandResult:
        self.calls.append((argv, timeout_seconds))
        return self.responses.get(argv, CommandResult(False, None, b"", b""))


def _installed_app(root: Path) -> tuple[Path, Path]:
    app = root / ".local/Go2RTC.app"
    executable = app / "Contents/MacOS/go2rtc"
    executable.parent.mkdir(parents=True)
    executable.write_bytes(b"synthetic executable")
    executable.chmod(0o755)
    return app, executable


def _commands(root: Path) -> dict[str, tuple[str, ...]]:
    app = root / ".local/Go2RTC.app"
    executable = app / "Contents/MacOS/go2rtc"
    config = root / "runtime/go2rtc.yaml"
    return {
        "verify": (
            _CODESIGN,
            "--verify",
            "--deep",
            "--strict",
            "--requirements",
            '=designated => identifier "com.babymonitor.go2rtc"',
            str(app),
        ),
        "requirement": (_CODESIGN, "-d", "-r-", str(app)),
        "launchctl": (_LAUNCHCTL, "print", f"gui/501/{_LABEL}"),
        "lsof": (_LSOF, "-nP", "-iTCP:1984", "-sTCP:LISTEN"),
        "firewall": (_FIREWALL, "--getappblocked", str(app)),
        "executable": (str(executable),),
        "config": (str(config),),
    }


def _launchctl_payload(root: Path, *pids: int) -> bytes:
    commands = _commands(root)
    executable = commands["executable"][0]
    config = commands["config"][0]
    pid_lines = "\n".join(f"\tpid = {pid}" for pid in pids)
    return (
        f"gui/501/{_LABEL} = {{\n"
        "\tstate = running\n"
        f"\tprogram = {executable}\n"
        "\targuments = {\n"
        f"\t\t{executable}\n"
        "\t\t-config\n"
        f"\t\t{config}\n"
        "\t}\n"
        f"{pid_lines}\n"
        "}\n"
    ).encode("utf-8")


def _ready_responses(root: Path) -> dict[tuple[str, ...], CommandResult]:
    app, _executable = _installed_app(root)
    commands = _commands(root)
    return {
        commands["verify"]: CommandResult(True, 0, b"", b""),
        commands["requirement"]: CommandResult(
            True,
            0,
            b"",
            (
                b"Executable=synthetic\n"
                b'designated => identifier "com.babymonitor.go2rtc"\n'
            ),
        ),
        commands["launchctl"]: CommandResult(
            True, 0, _launchctl_payload(root, _PID), b""
        ),
        commands["lsof"]: CommandResult(
            True,
            0,
            (
                "COMMAND PID USER FD TYPE DEVICE SIZE/OFF NODE NAME\n"
                f"go2rtc {_PID} test 4u IPv4 0x0 0t0 TCP "
                "127.0.0.1:1984 (LISTEN)\n"
            ).encode("ascii"),
            b"",
        ),
        commands["firewall"]: CommandResult(
            True,
            0,
            f"Incoming connection to {app} is permitted\n".encode("utf-8"),
            b"",
        ),
    }


@pytest.fixture(autouse=True)
def _intel_macos(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(preflight.platform, "system", lambda: "Darwin")
    monkeypatch.setattr(preflight.platform, "machine", lambda: "x86_64")
    monkeypatch.setattr(preflight.os, "getuid", lambda: 501)


def test_preflight_accepts_exact_app_launchd_listener_and_permitted_firewall(
    tmp_path: Path,
) -> None:
    runner = FakeRunner(_ready_responses(tmp_path))

    result = run_macos_media_preflight(tmp_path, runner=runner)

    assert result == MacOSMediaPreflight(
        code="ready",
        app_identity_ready=True,
        launchd_owner_count=1,
        listener_owned_by_launchd=True,
        local_network_state="available",
    )
    assert [timeout for _argv, timeout in runner.calls] == [10.0] * 5


def test_preflight_rejects_hash_based_designated_requirement(tmp_path: Path) -> None:
    responses = _ready_responses(tmp_path)
    commands = _commands(tmp_path)
    responses[commands["requirement"]] = CommandResult(
        True,
        0,
        b"",
        b'designated => cdhash H"0123456789abcdef"\n',
    )
    runner = FakeRunner(responses)

    result = run_macos_media_preflight(tmp_path, runner=runner)

    assert result.code == "app_identity_invalid"
    assert result.app_identity_ready is False
    assert len(runner.calls) == 2


@pytest.mark.parametrize(("pids", "expected_count"), (((), 0), ((_PID, 4343), 2)))
def test_preflight_rejects_zero_or_multiple_launchd_owners(
    tmp_path: Path,
    pids: tuple[int, ...],
    expected_count: int,
) -> None:
    responses = _ready_responses(tmp_path)
    commands = _commands(tmp_path)
    responses[commands["launchctl"]] = CommandResult(
        True, 0, _launchctl_payload(tmp_path, *pids), b""
    )
    runner = FakeRunner(responses)

    result = run_macos_media_preflight(tmp_path, runner=runner)

    assert result.code == "launchd_owner_invalid"
    assert result.launchd_owner_count == expected_count
    assert len(runner.calls) == 3


def test_preflight_requires_loaded_launchd_job_to_use_exact_app_command(
    tmp_path: Path,
) -> None:
    responses = _ready_responses(tmp_path)
    commands = _commands(tmp_path)
    payload = _launchctl_payload(tmp_path, _PID).replace(
        commands["executable"][0].encode("utf-8"), b"/synthetic/legacy/go2rtc"
    )
    responses[commands["launchctl"]] = CommandResult(True, 0, payload, b"")

    result = run_macos_media_preflight(tmp_path, runner=FakeRunner(responses))

    assert result.code == "launchd_owner_invalid"
    assert result.launchd_owner_count == 1


@pytest.mark.parametrize(
    "listener",
    (
        "go2rtc 4343 test 4u IPv4 0x0 0t0 TCP 127.0.0.1:1984 (LISTEN)\n",
        f"go2rtc {_PID} test 4u IPv4 0x0 0t0 TCP 0.0.0.0:1984 (LISTEN)\n",
    ),
)
def test_preflight_requires_launchd_pid_to_own_only_loopback_listener(
    tmp_path: Path,
    listener: str,
) -> None:
    responses = _ready_responses(tmp_path)
    commands = _commands(tmp_path)
    responses[commands["lsof"]] = CommandResult(
        True,
        0,
        ("COMMAND PID USER FD TYPE DEVICE SIZE/OFF NODE NAME\n" + listener).encode(
            "ascii"
        ),
        b"",
    )

    result = run_macos_media_preflight(tmp_path, runner=FakeRunner(responses))

    assert result.code == "listener_owner_invalid"
    assert result.listener_owned_by_launchd is False


def test_preflight_reports_firewall_query_failure_as_unknown(tmp_path: Path) -> None:
    responses = _ready_responses(tmp_path)
    commands = _commands(tmp_path)
    responses[commands["firewall"]] = CommandResult(True, 1, b"", b"denied")

    result = run_macos_media_preflight(tmp_path, runner=FakeRunner(responses))

    assert result.code == "local_network_unknown"
    assert result.local_network_state == "unknown"


def test_preflight_reports_explicit_firewall_block(tmp_path: Path) -> None:
    responses = _ready_responses(tmp_path)
    commands = _commands(tmp_path)
    app = tmp_path / ".local/Go2RTC.app"
    responses[commands["firewall"]] = CommandResult(
        True,
        0,
        f"Incoming connection to {app} is blocked\n".encode("utf-8"),
        b"",
    )

    result = run_macos_media_preflight(tmp_path, runner=FakeRunner(responses))

    assert result.code == "local_network_blocked"
    assert result.local_network_state == "blocked"


def test_preflight_rejects_unsupported_platform_without_commands(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(preflight.platform, "machine", lambda: "arm64")
    runner = FakeRunner({})

    result = run_macos_media_preflight(tmp_path, runner=runner)

    assert result.code == "unsupported"
    assert runner.calls == []
