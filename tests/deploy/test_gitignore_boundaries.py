from __future__ import annotations

import subprocess


def is_ignored(path: str) -> bool:
    result = subprocess.run(
        ["git", "check-ignore", "--quiet", path],
        check=False,
        capture_output=True,
        text=True,
    )
    return result.returncode == 0


def test_runtime_events_are_ignored_without_hiding_event_service_source() -> None:
    assert is_ignored("events/runtime-event.json") is True
    assert is_ignored("services/events/environment_state.py") is False


def test_local_python_environments_and_editable_metadata_are_ignored() -> None:
    assert is_ignored(".venv-alpha/bin/python") is True
    assert is_ignored("baby_monitor_local.egg-info/PKG-INFO") is True
