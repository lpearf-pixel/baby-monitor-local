from __future__ import annotations

import os
import plistlib
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def executable(path: Path, content: str) -> Path:
    path.write_text(content, encoding="ascii")
    path.chmod(0o700)
    return path


def project_fixture(tmp_path: Path) -> Path:
    project = tmp_path / "project"
    template = project / "deploy/launchd/com.babymonitor.visual.plist.example"
    template.parent.mkdir(parents=True)
    template.write_bytes(
        (ROOT / "deploy/launchd/com.babymonitor.visual.plist.example").read_bytes()
    )
    return project


def background_plist(project: Path) -> bytes:
    template = (
        project / "deploy/launchd/com.babymonitor.visual.plist.example"
    ).read_bytes()
    return template.replace(
        b"<string>Interactive</string>",
        b"<string>Background</string>",
    ).replace(b"__PROJECT_ROOT__", str(project).encode("ascii"))


def launchd_environment(
    tmp_path: Path,
    project: Path,
    *,
    removal_observations: int = 0,
    candidate_bootstrap_failures: int = 0,
    rollback_bootstrap_failures: int = 0,
) -> tuple[dict[str, str], Path, Path, Path]:
    home = tmp_path / "home"
    plist = home / "Library/LaunchAgents/com.babymonitor.visual.plist"
    plist.parent.mkdir(parents=True)
    plist.write_bytes(background_plist(project))

    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    state = tmp_path / "launchd-state"
    state.write_text("loaded\n", encoding="ascii")
    calls = tmp_path / "calls.log"
    removal_count = tmp_path / "removal-observations"
    removal_count.write_text(f"{removal_observations}\n", encoding="ascii")
    candidate_failures = tmp_path / "candidate-bootstrap-failures"
    candidate_failures.write_text(
        f"{candidate_bootstrap_failures}\n",
        encoding="ascii",
    )
    rollback_failures = tmp_path / "rollback-bootstrap-failures"
    rollback_failures.write_text(
        f"{rollback_bootstrap_failures}\n",
        encoding="ascii",
    )

    executable(
        fake_bin / "uname",
        """#!/bin/sh
if test "${1:-}" = "-m"; then
  printf 'x86_64\\n'
else
  printf 'Darwin\\n'
fi
""",
    )
    executable(fake_bin / "plutil", "#!/bin/sh\nexit 0\n")
    executable(
        fake_bin / "sleep",
        "#!/bin/sh\nprintf 'sleep %s\\n' \"$*\" >> \"$CALL_LOG\"\n",
    )
    executable(
        fake_bin / "launchctl",
        """#!/bin/sh
printf '%s\\n' "$*" >> "$CALL_LOG"
case "$1" in
  print)
    current_state="$(cat "$LAUNCHD_STATE")"
    case "$current_state" in
      loaded)
        exit 0
        ;;
      removing:*)
        remaining="${current_state#removing:}"
        if test "$remaining" -gt 0; then
          remaining=$((remaining - 1))
          printf 'removing:%s\\n' "$remaining" > "$LAUNCHD_STATE"
          exit 0
        fi
        printf 'unloaded\\n' > "$LAUNCHD_STATE"
        exit 1
        ;;
      *)
        exit 1
        ;;
    esac
    ;;
  bootout)
    printf 'removing:%s\\n' "$(cat "$REMOVAL_OBSERVATIONS")" > "$LAUNCHD_STATE"
    ;;
  bootstrap)
    if test "$(cat "$LAUNCHD_STATE")" != unloaded; then
      exit 8
    fi
    if grep -q '<string>Interactive</string>' "$3"; then
      remaining="$(cat "$CANDIDATE_BOOTSTRAP_FAILURES")"
      if test "$remaining" -lt 0; then
        exit 9
      fi
      if test "$remaining" -gt 0; then
        remaining=$((remaining - 1))
        printf '%s\\n' "$remaining" > "$CANDIDATE_BOOTSTRAP_FAILURES"
        exit 9
      fi
    else
      remaining="$(cat "$ROLLBACK_BOOTSTRAP_FAILURES")"
      if test "$remaining" -lt 0; then
        exit 10
      fi
      if test "$remaining" -gt 0; then
        remaining=$((remaining - 1))
        printf '%s\\n' "$remaining" > "$ROLLBACK_BOOTSTRAP_FAILURES"
        exit 10
      fi
    fi
    printf 'loaded\\n' > "$LAUNCHD_STATE"
    ;;
  kickstart)
    test "$(cat "$LAUNCHD_STATE")" = loaded
    ;;
esac
""",
    )

    environment = {
        **os.environ,
        "BABY_MONITOR_PROJECT_ROOT": str(project),
        "CALL_LOG": str(calls),
        "CANDIDATE_BOOTSTRAP_FAILURES": str(candidate_failures),
        "HOME": str(home),
        "LAUNCHD_STATE": str(state),
        "PATH": f"{fake_bin}:{os.environ['PATH']}",
        "REMOVAL_OBSERVATIONS": str(removal_count),
        "ROLLBACK_BOOTSTRAP_FAILURES": str(rollback_failures),
    }
    return environment, plist, state, calls


def test_update_waits_for_delayed_unregistration_before_bootstrap(
    tmp_path: Path,
) -> None:
    project = project_fixture(tmp_path)
    environment, plist, state, calls = launchd_environment(
        tmp_path,
        project,
        removal_observations=2,
    )

    completed = subprocess.run(
        ["bash", str(ROOT / "tools/update_visual_launchd.sh")],
        cwd=ROOT,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )

    assert completed.returncode == 0
    assert completed.stdout == (
        "visual_launchd_update=PASS process_type=Interactive\n"
    )
    assert completed.stderr == ""
    with plist.open("rb") as source:
        assert plistlib.load(source)["ProcessType"] == "Interactive"
    assert state.read_text(encoding="ascii") == "loaded\n"
    lines = calls.read_text(encoding="ascii").splitlines()
    first_bootstrap = lines.index(f"bootstrap gui/{os.getuid()} {plist}")
    assert lines[:first_bootstrap].count("sleep 1") == 2


def test_update_retries_transient_candidate_bootstrap_failures(
    tmp_path: Path,
) -> None:
    project = project_fixture(tmp_path)
    environment, plist, state, calls = launchd_environment(
        tmp_path,
        project,
        candidate_bootstrap_failures=2,
    )

    completed = subprocess.run(
        ["bash", str(ROOT / "tools/update_visual_launchd.sh")],
        cwd=ROOT,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )

    assert completed.returncode == 0
    assert completed.stdout == (
        "visual_launchd_update=PASS process_type=Interactive\n"
    )
    assert completed.stderr == ""
    assert state.read_text(encoding="ascii") == "loaded\n"
    lines = calls.read_text(encoding="ascii").splitlines()
    assert lines.count(f"bootstrap gui/{os.getuid()} {plist}") == 3
    assert lines.count("sleep 1") == 2


def test_update_replaces_registered_visual_worker_and_preserves_background_backup(
    tmp_path: Path,
) -> None:
    project = project_fixture(tmp_path)
    environment, plist, state, calls = launchd_environment(tmp_path, project)
    original = plist.read_bytes()

    completed = subprocess.run(
        ["bash", str(ROOT / "tools/update_visual_launchd.sh")],
        cwd=ROOT,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )

    assert completed.returncode == 0
    assert completed.stdout == (
        "visual_launchd_update=PASS process_type=Interactive\n"
    )
    assert completed.stderr == ""
    with plist.open("rb") as source:
        assert plistlib.load(source)["ProcessType"] == "Interactive"
    rendered = project / "runtime/launchd/com.babymonitor.visual.plist"
    assert rendered.read_bytes() == plist.read_bytes()
    assert Path(f"{plist}.r3-background.bak").read_bytes() == original
    assert state.read_text(encoding="ascii") == "loaded\n"
    assert calls.read_text(encoding="ascii").splitlines() == [
        f"print gui/{os.getuid()}/com.babymonitor.visual",
        f"bootout gui/{os.getuid()}/com.babymonitor.visual",
        f"print gui/{os.getuid()}/com.babymonitor.visual",
        f"bootstrap gui/{os.getuid()} {plist}",
        f"kickstart -k gui/{os.getuid()}/com.babymonitor.visual",
        f"print gui/{os.getuid()}/com.babymonitor.visual",
    ]


def test_update_retries_rollback_bootstrap_and_restores_previous_job(
    tmp_path: Path,
) -> None:
    project = project_fixture(tmp_path)
    environment, plist, state, calls = launchd_environment(
        tmp_path,
        project,
        candidate_bootstrap_failures=-1,
        rollback_bootstrap_failures=2,
    )
    original = plist.read_bytes()
    backup = Path(f"{plist}.r3-background.bak")
    preserved_backup = b"preserve-existing-background-backup\n"
    backup.write_bytes(preserved_backup)

    completed = subprocess.run(
        ["bash", str(ROOT / "tools/update_visual_launchd.sh")],
        cwd=ROOT,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )

    assert completed.returncode == 2
    assert completed.stdout == (
        "visual_launchd_update=FAIL reason=activation_bootstrap_timeout\n"
    )
    assert completed.stderr == ""
    assert plist.read_bytes() == original
    assert backup.read_bytes() == preserved_backup
    assert state.read_text(encoding="ascii") == "loaded\n"
    lines = calls.read_text(encoding="ascii").splitlines()
    assert lines.count(f"bootstrap gui/{os.getuid()} {plist}") == 33
    assert lines[-3:] == [
        f"bootstrap gui/{os.getuid()} {plist}",
        f"kickstart -k gui/{os.getuid()}/com.babymonitor.visual",
        f"print gui/{os.getuid()}/com.babymonitor.visual",
    ]


def test_update_reports_specific_rollback_bootstrap_timeout(
    tmp_path: Path,
) -> None:
    project = project_fixture(tmp_path)
    environment, plist, state, _calls = launchd_environment(
        tmp_path,
        project,
        candidate_bootstrap_failures=-1,
        rollback_bootstrap_failures=-1,
    )
    original = plist.read_bytes()

    completed = subprocess.run(
        ["bash", str(ROOT / "tools/update_visual_launchd.sh")],
        cwd=ROOT,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )

    assert completed.returncode == 3
    assert completed.stdout == (
        "visual_launchd_update=FAIL reason=rollback_bootstrap_timeout\n"
    )
    assert completed.stderr == ""
    assert plist.read_bytes() == original
    assert state.read_text(encoding="ascii") == "unloaded\n"


def test_update_rejects_invalid_template_before_stopping_worker(
    tmp_path: Path,
) -> None:
    project = project_fixture(tmp_path)
    environment, plist, state, calls = launchd_environment(tmp_path, project)
    original = plist.read_bytes()
    fake_bin = Path(environment["PATH"].split(":", 1)[0])
    executable(fake_bin / "plutil", "#!/bin/sh\nexit 1\n")

    completed = subprocess.run(
        ["bash", str(ROOT / "tools/update_visual_launchd.sh")],
        cwd=ROOT,
        env=environment,
        capture_output=True,
        text=True,
        check=False,
    )

    assert completed.returncode == 2
    assert completed.stdout == (
        "visual_launchd_update=FAIL reason=template_invalid\n"
    )
    assert completed.stderr == ""
    assert plist.read_bytes() == original
    assert state.read_text(encoding="ascii") == "loaded\n"
    assert calls.read_text(encoding="ascii").splitlines() == [
        f"print gui/{os.getuid()}/com.babymonitor.visual",
    ]


def test_make_target_invokes_visual_launchd_update_script(tmp_path: Path) -> None:
    fake_bash = executable(
        tmp_path / "bash",
        "#!/bin/sh\nprintf '%s\\n' \"$1\"\n",
    )

    completed = subprocess.run(
        [
            "make",
            "-f",
            str(ROOT / "Makefile"),
            "alpha-visual-launchd-update",
            f"BASH={fake_bash}",
        ],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=False,
    )

    assert completed.returncode == 0
    assert completed.stdout == "tools/update_visual_launchd.sh\n"
