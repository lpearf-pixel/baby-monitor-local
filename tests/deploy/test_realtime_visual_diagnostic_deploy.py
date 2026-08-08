from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[2]


def executable(path: Path, content: str) -> Path:
    path.write_text(content, encoding="ascii")
    path.chmod(0o700)
    return path


@pytest.mark.parametrize("diagnostic_exit", [0, 7])
def test_wrapper_restores_visual_worker_and_preserves_diagnostic_exit(
    tmp_path: Path,
    diagnostic_exit: int,
) -> None:
    home = tmp_path / "home"
    plist = home / "Library/LaunchAgents/com.babymonitor.visual.plist"
    plist.parent.mkdir(parents=True)
    plist.write_text("synthetic plist", encoding="ascii")
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    state = tmp_path / "launchd-state"
    state.write_text("loaded\n", encoding="ascii")
    log = tmp_path / "calls.log"

    executable(
        fake_bin / "uname",
        "#!/bin/sh\nprintf 'Darwin\\n'\n",
    )
    executable(
        fake_bin / "launchctl",
        """#!/bin/sh
printf '%s\\n' "$*" >> "$CALL_LOG"
case "$1" in
  print)
    test "$(cat "$LAUNCHD_STATE")" = loaded
    ;;
  bootout)
    printf 'unloaded\\n' > "$LAUNCHD_STATE"
    ;;
  bootstrap)
    printf 'loaded\\n' > "$LAUNCHD_STATE"
    ;;
  kickstart)
    test "$(cat "$LAUNCHD_STATE")" = loaded
    ;;
esac
""",
    )
    fake_python = executable(
        tmp_path / "python",
        f"#!/bin/sh\nprintf 'diagnostic invoked\\n' >> \"$CALL_LOG\"\nexit {diagnostic_exit}\n",
    )
    environment = {
        **os.environ,
        "HOME": str(home),
        "PATH": f"{fake_bin}:{os.environ['PATH']}",
        "PYTHON": str(fake_python),
        "CALL_LOG": str(log),
        "LAUNCHD_STATE": str(state),
    }

    completed = subprocess.run(
        ["bash", str(ROOT / "tools/run_realtime_visual_diagnostic.sh")],
        cwd=ROOT,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )

    assert completed.returncode == diagnostic_exit
    assert state.read_text(encoding="ascii") == "loaded\n"
    assert log.read_text(encoding="ascii").splitlines() == [
        f"print gui/{os.getuid()}/com.babymonitor.visual",
        f"bootout gui/{os.getuid()}/com.babymonitor.visual",
        "diagnostic invoked",
        f"print gui/{os.getuid()}/com.babymonitor.visual",
        (
            f"bootstrap gui/{os.getuid()} "
            f"{plist}"
        ),
        f"kickstart -k gui/{os.getuid()}/com.babymonitor.visual",
    ]


def test_make_target_invokes_repository_wrapper(tmp_path: Path) -> None:
    fake_bash = executable(
        tmp_path / "bash",
        "#!/bin/sh\nprintf '%s\\n' \"$1\"\n",
    )

    completed = subprocess.run(
        [
            "make",
            "-f",
            str(ROOT / "Makefile"),
            "alpha-visual-diagnostic",
            f"BASH={fake_bash}",
        ],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=False,
    )

    assert completed.returncode == 0
    assert completed.stdout == "tools/run_realtime_visual_diagnostic.sh\n"
