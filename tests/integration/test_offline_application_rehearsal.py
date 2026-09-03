from __future__ import annotations

from itertools import count
from pathlib import Path

from packages.contracts.offline_application_rehearsal import load_rehearsal_suite


SUITE = Path(__file__).parents[1] / "fixtures/offline_application_rehearsal/scenarios.v1.json"


def ids(prefix: str):
    values = count(1)
    return lambda: f"{prefix}-{next(values):04d}"


def test_six_application_oracles_match_exact_fixture_counts(tmp_path: Path) -> None:
    from services.offline_application_rehearsal import run_application_oracle_scenario

    suite = load_rehearsal_suite(SUITE)
    scenarios = [item for item in suite.scenarios if item.lane == "application_oracle"]
    results = [
        run_application_oracle_scenario(
            scenario,
            tmp_path / scenario.scenario_id,
            event_id_factory=ids(f"event-{index}"),
            notification_id_factory=ids(f"notification-{index}"),
        )
        for index, scenario in enumerate(scenarios, 1)
    ]

    assert len(results) == 6
    assert all(item.status == "PASS" and item.reason == "ok" for item in results)
    assert [item.counts for item in results] == [item.expected_counts for item in scenarios]
    assert results[0].event_ids == ()
    assert results[1].counts["notification.risk_recovered"] == 1
    assert results[2].counts["face.output"] == 0
    assert results[3].counts["transition.adult_intervention.none"] == 1
    assert results[4].counts["semantic_conflict.face_without_subject"] == 1
    assert results[5].counts["resolution.subject_outside"] == 1
    assert results[5].counts["notification.risk_recovered"] == 0


def test_runner_preserves_fixture_order_for_application_lane(tmp_path: Path) -> None:
    from services.offline_application_rehearsal import OfflineApplicationRehearsalRunner

    suite = load_rehearsal_suite(SUITE)
    runner = OfflineApplicationRehearsalRunner(tmp_path)
    results = runner.run_functional_pack(suite)
    assert [item.scenario_id for item in results] == [
        item.scenario_id for item in suite.scenarios if item.lane == "application_oracle"
    ]
