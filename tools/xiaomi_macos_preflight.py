#!/usr/bin/env python3
"""Run the bounded, redacted Xiaomi macOS media preflight."""

from __future__ import annotations

import os
import selectors
import signal
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from packages.monitoring.xiaomi_macos_preflight import (  # noqa: E402
    CommandResult,
    MacOSMediaPreflight,
    run_macos_media_preflight,
)


_MAX_COMMAND_OUTPUT_BYTES = 1_048_576
_MAX_TIMEOUT_SECONDS = 10.0


def run_bounded(argv: tuple[str, ...], timeout_seconds: float) -> CommandResult:
    if (
        not argv
        or any(type(value) is not str or not value for value in argv)
        or not 0.05 <= timeout_seconds <= _MAX_TIMEOUT_SECONDS
    ):
        return CommandResult(False, None, b"", b"")

    process: subprocess.Popen[bytes] | None = None
    selector = selectors.DefaultSelector()
    stdout = bytearray()
    stderr = bytearray()
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
        selector.register(process.stdout, selectors.EVENT_READ, stdout)
        selector.register(process.stderr, selectors.EVENT_READ, stderr)
        deadline = time.monotonic() + timeout_seconds

        while selector.get_map():
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                _settle_failed_process(process)
                return CommandResult(True, None, b"", b"")
            for key, _mask in selector.select(min(0.05, remaining)):
                try:
                    chunk = os.read(key.fileobj.fileno(), 65_536)
                except OSError:
                    chunk = b""
                if not chunk:
                    selector.unregister(key.fileobj)
                    continue
                total += len(chunk)
                if total > _MAX_COMMAND_OUTPUT_BYTES:
                    _settle_failed_process(process)
                    return CommandResult(True, None, b"", b"")
                key.data.extend(chunk)

        remaining = deadline - time.monotonic()
        if remaining <= 0:
            _settle_failed_process(process)
            return CommandResult(True, None, b"", b"")
        returncode = process.wait(timeout=remaining)
        return CommandResult(True, returncode, bytes(stdout), bytes(stderr))
    except (OSError, subprocess.SubprocessError, ValueError):
        if process is not None:
            _settle_failed_process(process)
        return CommandResult(process is not None, None, b"", b"")
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


def format_report(report: MacOSMediaPreflight) -> tuple[str, ...]:
    return (
        f"result={'PASS' if report.code == 'ready' else 'FAIL'}",
        "operation=xiaomi-media-preflight",
        f"code={report.code}",
        f"app_identity_ready={str(report.app_identity_ready).lower()}",
        f"launchd_owner_count={report.launchd_owner_count}",
        "listener_owned_by_launchd="
        f"{str(report.listener_owned_by_launchd).lower()}",
        f"local_network_state={report.local_network_state}",
    )


def main() -> int:
    report = run_macos_media_preflight(ROOT, runner=run_bounded)
    for line in format_report(report):
        print(line)
    return 0 if report.code == "ready" else 1


if __name__ == "__main__":
    raise SystemExit(main())
