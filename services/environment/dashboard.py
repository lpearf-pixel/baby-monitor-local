from __future__ import annotations

from datetime import datetime
from typing import Protocol
from uuid import uuid4

from services.events.environment_state import (
    EnvironmentIncident,
    EnvironmentSnapshot,
    EnvironmentSnapshotProvider,
    EnvironmentStateMachine,
    EnvironmentStatePolicy,
)
from services.gauge.calibration import (
    CalibrationInvalid,
    CalibrationMissing,
    GaugeCalibrationStore,
    Ws2021Calibration,
)
from services.storage.environment import (
    EnvironmentIncidentCounts,
    EnvironmentStore,
    EnvironmentTrend,
    TrendWindow,
)


class GaugeCalibrationDraft(Protocol):
    def model_dump(self) -> dict[str, object]: ...


class LocalEnvironmentDashboardService:
    def __init__(
        self,
        *,
        store: EnvironmentStore,
        calibration_store: GaugeCalibrationStore,
        policy: EnvironmentStatePolicy,
    ) -> None:
        self._store = store
        self._calibration_store = calibration_store
        self._policy = policy

    def _state_machine(self) -> EnvironmentStateMachine:
        snapshot = self._store.load_state_snapshot()
        if snapshot is None:
            return EnvironmentStateMachine(self._policy)
        return EnvironmentStateMachine.restore(self._policy, snapshot)

    def current(self, now: datetime) -> EnvironmentSnapshot:
        return EnvironmentSnapshotProvider(
            store=self._store,
            state_machine=self._state_machine(),
        ).current(now)

    def trend(self, window: TrendWindow, now: datetime) -> EnvironmentTrend:
        return self._store.trend(window, now=now)

    def incidents(self) -> tuple[EnvironmentIncident, ...]:
        return tuple(
            EnvironmentIncident(
                incident_id=item.incident_id,
                kind=item.kind,
                state=item.state,
                severity=item.severity,
                opened_at=item.opened_at,
                updated_at=item.updated_at,
                recovered_at=item.recovered_at,
                reasons=item.reasons,
                opening_reading_id=item.opening_reading_id,
                data_available=(item.kind == "range" or item.state == "recovered"),
            )
            for item in self._store.incidents()
        )

    def incident_counts(
        self,
        *,
        started_at: datetime,
        ended_at: datetime,
    ) -> EnvironmentIncidentCounts:
        return self._store.incident_counts(started_at=started_at, ended_at=ended_at)

    def calibration_status(self) -> dict[str, object]:
        try:
            calibration = self._calibration_store.current()
        except CalibrationMissing:
            return {"state": "missing", "schema_version": 2}
        except CalibrationInvalid:
            return {"state": "invalid", "schema_version": 2}
        return {
            "state": "available",
            "schema_version": calibration.schema_version,
            "calibration_id": calibration.calibration_id,
            "created_at": calibration.created_at,
            "source_width": calibration.source_width,
            "source_height": calibration.source_height,
        }

    def save_calibration(
        self,
        draft: GaugeCalibrationDraft,
        reference_jpeg: bytes,
        now: datetime,
    ) -> dict[str, object]:
        calibration_id = uuid4().hex
        calibration = Ws2021Calibration(
            schema_version=2,
            calibration_id=calibration_id,
            created_at=now,
            reference_version=calibration_id,
            **draft.model_dump(),
        )
        saved = self._calibration_store.save(calibration, reference_jpeg)
        return {
            "state": "available",
            "schema_version": saved.schema_version,
            "calibration_id": saved.calibration_id,
            "created_at": saved.created_at,
        }
