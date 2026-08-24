from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def _project(tmp_path: Path, *, probe_exit: int) -> tuple[Path, Path]:
    project = tmp_path / "project"
    (project / "tools").mkdir(parents=True)
    shutil.copy2(
        ROOT / "tools/authorize_voice_keychain.command",
        project / "tools/authorize_voice_keychain.command",
    )
    python = project / ".venv-alpha/bin/python"
    python.parent.mkdir(parents=True)
    calls = tmp_path / "calls"
    python.write_text(
        "#!/bin/sh\n"
        "test \"$PWD\" = \"$VOICE_KEYCHAIN_TEST_ROOT\" || exit 9\n"
        "printf '%s\\n' \"$*\" > \"$VOICE_KEYCHAIN_TEST_CALLS\"\n"
        "printf '%s\\n' 'migration="
        + ("PASS" if probe_exit == 0 else "FAIL")
        + "'\n"
        f"exit {probe_exit}\n",
        encoding="ascii",
    )
    python.chmod(0o755)
    return project, calls


def test_authorizer_runs_only_fixed_migration_and_persists_aggregate_status(
    tmp_path: Path,
) -> None:
    project, calls = _project(tmp_path, probe_exit=0)

    result = subprocess.run(
        ["bash", str(project / "tools/authorize_voice_keychain.command")],
        cwd=tmp_path,
        env={
            **os.environ,
            "VOICE_KEYCHAIN_TEST_CALLS": str(calls),
            "VOICE_KEYCHAIN_TEST_ROOT": str(project),
        },
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0
    assert result.stdout == "migration=PASS\n"
    assert result.stderr == ""
    assert calls.read_text(encoding="ascii") == "-m tools.voice_keychain_migrate\n"
    assert (
        project / "runtime/status/voice-keychain-check.txt"
    ).read_text(encoding="ascii") == "migration=PASS\n"


def test_authorizer_preserves_migration_failure_without_raw_diagnostics(
    tmp_path: Path,
) -> None:
    project, _calls = _project(tmp_path, probe_exit=7)

    result = subprocess.run(
        ["bash", str(project / "tools/authorize_voice_keychain.command")],
        cwd=tmp_path,
        env={
            **os.environ,
            "VOICE_KEYCHAIN_TEST_CALLS": str(tmp_path / "calls"),
            "VOICE_KEYCHAIN_TEST_ROOT": str(project),
        },
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 7
    assert result.stdout == "migration=FAIL\n"
    assert result.stderr == ""
