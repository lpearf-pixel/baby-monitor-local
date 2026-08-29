from __future__ import annotations

import stat
from pathlib import Path

import pytest

from packages.contracts.offline_guardian_scenario import (
    OfflineGuardianScenarioV1,
    load_offline_scenario_suite,
)


FIXTURE = (
    Path(__file__).parents[1]
    / "fixtures/offline_guardian_scenarios/scenarios.v1.json"
)


def scenario(identifier: str) -> OfflineGuardianScenarioV1:
    suite = load_offline_scenario_suite(FIXTURE)
    return next(item for item in suite.scenarios if item.scenario_id == identifier)


def private_root(tmp_path: Path) -> Path:
    root = tmp_path / "scenario"
    root.mkdir(mode=0o700)
    return root


@pytest.mark.parametrize(
    ("identifier", "expected"),
    [
        (
            "SAFE-SLEEP-01",
            {
                "dashboard.event": 0,
                "dashboard.open": 0,
            },
        ),
        (
            "FACE-OCCLUSION-01",
            {
                "transition.watch_started.face_not_visible": 1,
                "transition.alert_opened.face_not_visible": 1,
                "transition.recovered.face_not_visible": 1,
                "event.face_not_visible.recovered": 1,
                "dashboard.event": 1,
                "dashboard.open": 0,
            },
        ),
        (
            "ADULT-INTERVENTION-01",
            {
                "transition.watch_started.face_not_visible": 1,
                "transition.alert_opened.face_not_visible": 1,
                "transition.adult_intervention.none": 1,
                "event.face_not_visible.open": 1,
                "dashboard.event": 1,
                "dashboard.open": 1,
            },
        ),
    ],
)
def test_guardian_lane_runs_current_rules_and_dashboard_projection(
    tmp_path: Path,
    identifier: str,
    expected: dict[str, int],
) -> None:
    from services.offline_guardian_scenario import run_guardian_lane

    root = private_root(tmp_path)
    result = run_guardian_lane(scenario(identifier), root)

    assert result.lane == "guardian_deterministic"
    assert result.status == "PASS"
    assert result.reason == "ok"
    assert result.counts == expected
    database = root / "guardian-events.sqlite3"
    assert database.is_file()
    assert stat.S_IMODE(database.stat().st_mode) == 0o600


def test_guardian_lane_rejects_existing_store_without_reading_it(
    tmp_path: Path,
) -> None:
    from services.offline_guardian_scenario import run_guardian_lane

    root = private_root(tmp_path)
    database = root / "guardian-events.sqlite3"
    database.write_bytes(b"private-existing-state")
    database.chmod(0o600)

    result = run_guardian_lane(scenario("SAFE-SLEEP-01"), root)

    assert result.status == "FAIL"
    assert result.reason == "guardian_store_not_empty"
    assert database.read_bytes() == b"private-existing-state"


def test_guardian_lane_rejects_symlink_runtime_root(tmp_path: Path) -> None:
    from services.offline_guardian_scenario import run_guardian_lane

    actual = private_root(tmp_path)
    linked = tmp_path / "linked"
    linked.symlink_to(actual, target_is_directory=True)

    result = run_guardian_lane(scenario("SAFE-SLEEP-01"), linked)

    assert result.status == "FAIL"
    assert result.reason == "offline_scenario_runtime_unsafe"
    assert list(actual.iterdir()) == []


def test_guardian_lane_reports_expectation_mismatch_without_changing_rules(
    tmp_path: Path,
) -> None:
    from services.offline_guardian_scenario import run_guardian_lane

    value = scenario("SAFE-SLEEP-01")
    guardian = value.guardian.model_copy(
        update={"dashboard_event_count": 1},
    )
    changed = value.model_copy(update={"guardian": guardian})

    result = run_guardian_lane(changed, private_root(tmp_path))

    assert result.status == "FAIL"
    assert result.reason == "scenario_guardian_mismatch"
    assert result.counts["dashboard.event"] == 0
