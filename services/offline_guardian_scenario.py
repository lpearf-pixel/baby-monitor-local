from __future__ import annotations

import os
import stat
from pathlib import Path

from packages.contracts.offline_guardian_scenario import (
    OfflineGuardianScenarioV1,
    ScenarioLaneResult,
)
from services.vision.corpus_replay import (
    GuardianReplayProjector,
    GuardianReplayReview,
)


def run_guardian_lane(
    scenario: OfflineGuardianScenarioV1,
    runtime_root: Path,
) -> ScenarioLaneResult:
    """Project one fixed semantic timeline into a new isolated event store."""

    root = Path(runtime_root)
    if not _private_runtime_root(root):
        return _failure("offline_scenario_runtime_unsafe")
    if scenario.guardian is None or "guardian_deterministic" not in scenario.required_lanes:
        return _failure("offline_scenario_lane_unavailable")

    database = root / "guardian-events.sqlite3"
    if database.exists() or database.is_symlink():
        return _failure("guardian_store_not_empty")

    reviews = tuple(
        GuardianReplayReview(
            observed_at=entry.observed_at,
            review=entry.review,
        )
        for entry in scenario.guardian.timeline
    )
    aggregate = GuardianReplayProjector(database_path=database).run(
        semantic_profile="synthetic_test",
        reviews=reviews,
    )
    if aggregate.status != "PASS":
        return _failure(aggregate.reason)

    try:
        database.chmod(0o600)
    except OSError:
        return _failure("offline_scenario_runtime_unsafe")

    counts = {
        **{
            f"transition.{key}": count
            for key, count in aggregate.transition_counts.items()
        },
        **{f"event.{key}": count for key, count in aggregate.event_counts.items()},
        "dashboard.event": aggregate.dashboard_event_count,
        "dashboard.open": aggregate.dashboard_open_event_count,
    }
    expected = {
        **{
            f"transition.{key}": count
            for key, count in scenario.guardian.transition_counts.items()
        },
        **{
            f"event.{key}": count
            for key, count in scenario.guardian.event_counts.items()
        },
        "dashboard.event": scenario.guardian.dashboard_event_count,
        "dashboard.open": scenario.guardian.dashboard_open_event_count,
    }
    return ScenarioLaneResult(
        lane="guardian_deterministic",
        status="PASS" if counts == expected else "FAIL",
        reason="ok" if counts == expected else "scenario_guardian_mismatch",
        counts=counts,
    )


def _private_runtime_root(root: Path) -> bool:
    try:
        metadata = root.lstat()
    except OSError:
        return False
    return (
        stat.S_ISDIR(metadata.st_mode)
        and not root.is_symlink()
        and metadata.st_uid == os.getuid()
        and stat.S_IMODE(metadata.st_mode) == 0o700
    )


def _failure(reason: str) -> ScenarioLaneResult:
    return ScenarioLaneResult(
        lane="guardian_deterministic",
        status="FAIL",
        reason=reason,
    )


__all__ = ["run_guardian_lane"]
