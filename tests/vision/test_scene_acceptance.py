from __future__ import annotations

import json
import os
import stat
from pathlib import Path

import pytest

from services.vision.scene_acceptance import (
    OUTCOMES,
    SCENES,
    GuardianSceneAcceptanceStore,
)


def test_new_run_uses_closed_schema_and_private_atomic_file(tmp_path: Path) -> None:
    store = GuardianSceneAcceptanceStore(tmp_path, wall_clock=lambda: 100.0)

    run = store.start()

    assert run["schema_version"] == 1
    assert run["state"] == "incomplete"
    assert run["trials"] == []
    assert set(run) == {"schema_version", "state", "started_at_unix", "updated_at_unix", "trials"}
    target = tmp_path / "guardian-scene-acceptance.json"
    assert stat.S_IMODE(target.stat().st_mode) == 0o600
    assert [path for path in tmp_path.iterdir()] == [target]


def test_records_fixed_scene_outcome_and_monotonic_ordinal(tmp_path: Path) -> None:
    store = GuardianSceneAcceptanceStore(tmp_path, wall_clock=lambda: 101.0)
    store.start()

    first = store.record(SCENES[0], OUTCOMES[0])
    second = store.record(SCENES[0], OUTCOMES[1])

    assert [trial["ordinal"] for trial in second["trials"]] == [1, 2]
    assert first["trials"][0]["scene"] == SCENES[0]
    assert second["trials"][1]["outcome"] == OUTCOMES[1]


@pytest.mark.parametrize("scene,outcome", [("other", "correct"), ("empty_bed", "other")])
def test_rejects_unknown_scene_or_outcome(tmp_path: Path, scene: str, outcome: str) -> None:
    store = GuardianSceneAcceptanceStore(tmp_path)
    store.start()

    with pytest.raises(ValueError, match="invalid scene acceptance trial"):
        store.record(scene, outcome)


def test_rejects_more_than_ten_trials_for_one_scene(tmp_path: Path) -> None:
    store = GuardianSceneAcceptanceStore(tmp_path)
    store.start()
    for _ in range(10):
        store.record("empty_bed", "correct")

    with pytest.raises(ValueError, match="scene trial limit reached"):
        store.record("empty_bed", "correct")


def test_resume_rejects_extra_or_duplicate_json_fields(tmp_path: Path) -> None:
    target = tmp_path / "guardian-scene-acceptance.json"
    target.write_text('{"schema_version":1,"schema_version":1}', encoding="utf-8")

    with pytest.raises(ValueError, match="invalid scene acceptance state"):
        GuardianSceneAcceptanceStore(tmp_path).load()


def test_finalize_applies_conservative_thresholds(tmp_path: Path) -> None:
    store = GuardianSceneAcceptanceStore(tmp_path)
    store.start()
    for scene in SCENES:
        outcomes = ["correct"] * 10
        if scene == "camera_obstruction":
            outcomes[-1] = "missed"
        for outcome in outcomes:
            store.record(scene, outcome)

    completed = store.finalize()

    assert completed["state"] == "passed"


@pytest.mark.parametrize(
    "scene,outcome",
    [("empty_bed", "false_positive"), ("camera_obstruction", "unavailable")],
)
def test_finalize_fails_closed_for_negative_scene_error_or_unavailable(
    tmp_path: Path,
    scene: str,
    outcome: str,
) -> None:
    store = GuardianSceneAcceptanceStore(tmp_path)
    store.start()
    for current_scene in SCENES:
        for ordinal in range(10):
            selected = outcome if current_scene == scene and ordinal == 0 else "correct"
            store.record(current_scene, selected)

    assert store.finalize()["state"] == "failed"


def test_rejects_symlinked_runtime_root(tmp_path: Path) -> None:
    real = tmp_path / "real"
    real.mkdir()
    linked = tmp_path / "linked"
    linked.symlink_to(real, target_is_directory=True)

    with pytest.raises(ValueError, match="unsafe scene acceptance root"):
        GuardianSceneAcceptanceStore(linked).start()


def test_rejects_symlinked_runtime_root_ancestor(tmp_path: Path) -> None:
    real = tmp_path / "real"
    real.mkdir()
    linked = tmp_path / "linked"
    linked.symlink_to(real, target_is_directory=True)

    with pytest.raises(ValueError, match="unsafe scene acceptance root"):
        GuardianSceneAcceptanceStore(linked / "status").start()


def test_failed_replace_leaves_previous_state_and_no_temporary(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store = GuardianSceneAcceptanceStore(tmp_path)
    original = store.start()

    def fail_replace(_source: object, _destination: object) -> None:
        raise OSError("private failure")

    monkeypatch.setattr(os, "replace", fail_replace)
    with pytest.raises(OSError):
        store.record("empty_bed", "correct")

    assert json.loads((tmp_path / "guardian-scene-acceptance.json").read_text()) == original
    assert len(list(tmp_path.iterdir())) == 1
