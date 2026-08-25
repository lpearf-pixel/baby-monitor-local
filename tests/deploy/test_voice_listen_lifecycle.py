from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def _write_executable(path: Path, content: str) -> None:
    path.write_text(content, encoding="ascii")
    path.chmod(0o755)


def test_start_waits_for_listen_only_status_and_stop_is_voice_only(tmp_path: Path) -> None:
    project = tmp_path / "project"
    (project / "tools").mkdir(parents=True)
    for name in ("voice_listen_lifecycle.sh", "start_alpha.sh", "stop_alpha.sh"):
        shutil.copy2(ROOT / "tools" / name, project / "tools" / name)
    (project / "runtime/status").mkdir(parents=True)
    (project / ".venv-alpha/bin").mkdir(parents=True)
    calls = project / "calls"
    _write_executable(
        project / ".venv-alpha/bin/python",
        "#!/bin/sh\nprintf '%s\\n' \"$*\" >> \"$VOICE_TEST_CALLS\"\n"
        "case $* in *--require-mode*listen_only*) exit 0;; esac\nexit 2\n",
    )
    _write_executable(
        project / "tools/start_alpha.sh",
        "#!/bin/sh\nprintf 'start %s\\n' \"$*\" >> \"$VOICE_TEST_CALLS\"\n",
    )
    _write_executable(
        project / "tools/stop_alpha.sh",
        "#!/bin/sh\nprintf 'stop %s\\n' \"$*\" >> \"$VOICE_TEST_CALLS\"\n",
    )
    environment = os.environ.copy()
    environment["VOICE_TEST_CALLS"] = str(calls)

    started = subprocess.run(
        ["bash", "tools/voice_listen_lifecycle.sh", "start"],
        cwd=project,
        env=environment,
        check=False,
    )
    stopped = subprocess.run(
        ["bash", "tools/voice_listen_lifecycle.sh", "stop"],
        cwd=project,
        env=environment,
        check=False,
    )

    assert started.returncode == 0
    assert stopped.returncode == 0
    lines = calls.read_text(encoding="ascii").splitlines()
    assert lines[0] == "start --voice-only"
    assert lines[-1] == "stop --voice-only"
    assert any("--require-mode listen_only" in line for line in lines)
