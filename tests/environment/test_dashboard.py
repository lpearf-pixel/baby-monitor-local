from __future__ import annotations

from datetime import UTC, datetime, timedelta

from services.environment.dashboard import LocalEnvironmentDashboardService
from services.events.environment_state import EnvironmentStatePolicy
from services.storage.environment import EnvironmentIncidentCounts


NOW = datetime(2026, 8, 5, 12, 0, tzinfo=UTC)


class RecordingStore:
    def __init__(self) -> None:
        self.boundaries: list[tuple[datetime, datetime]] = []
        self.incidents_called = False

    def incident_counts(
        self,
        *,
        started_at: datetime,
        ended_at: datetime,
    ) -> EnvironmentIncidentCounts:
        self.boundaries.append((started_at, ended_at))
        return EnvironmentIncidentCounts(
            range_normal=4,
            range_critical=2,
            unreadable=1,
        )

    def incidents(self) -> tuple[object, ...]:
        self.incidents_called = True
        raise AssertionError("incident_counts must not call incidents")


class UnusedCalibrationStore:
    pass


def test_incident_counts_forwards_aware_boundaries_once_without_listing() -> None:
    store = RecordingStore()
    service = LocalEnvironmentDashboardService(
        store=store,  # type: ignore[arg-type]
        calibration_store=UnusedCalibrationStore(),  # type: ignore[arg-type]
        policy=EnvironmentStatePolicy(),
    )
    started_at = NOW - timedelta(days=7)

    result = service.incident_counts(started_at=started_at, ended_at=NOW)

    assert result == EnvironmentIncidentCounts(
        range_normal=4,
        range_critical=2,
        unreadable=1,
    )
    assert store.boundaries == [(started_at, NOW)]
    assert store.incidents_called is False
