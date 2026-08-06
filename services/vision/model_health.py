from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


FAILURE_THRESHOLD = 3
DEGRADED_SECONDS = 60.0
RECOVERY_SUCCESSES = 2


class ModelHealthState(StrEnum):
    HEALTHY = "healthy"
    DEGRADED = "degraded"


class ModelHealthCode(StrEnum):
    MODEL_DEGRADED = "model_degraded"
    MODEL_RECOVERED = "model_recovered"


@dataclass(frozen=True)
class ModelHealthStatus:
    state: ModelHealthState
    failure_count: int
    success_count: int
    failure_duration_seconds: float


@dataclass(frozen=True)
class ModelHealthTransition:
    state: ModelHealthState
    code: ModelHealthCode
    failure_count: int
    success_count: int
    duration_seconds: float


class VisualModelHealthMonitor:
    def __init__(self) -> None:
        self._state = ModelHealthState.HEALTHY
        self._first_failure_at: float | None = None
        self._failure_count = 0
        self._success_count = 0
        self._last_monotonic: float | None = None

    def status(self) -> ModelHealthStatus:
        duration = 0.0
        if self._first_failure_at is not None and self._last_monotonic is not None:
            duration = self._last_monotonic - self._first_failure_at
        return ModelHealthStatus(
            state=self._state,
            failure_count=self._failure_count,
            success_count=self._success_count,
            failure_duration_seconds=duration,
        )

    def failed(
        self,
        *,
        monotonic_now: float,
    ) -> ModelHealthTransition | None:
        self._require_monotonic(monotonic_now)
        self._last_monotonic = monotonic_now
        self._success_count = 0
        if self._first_failure_at is None:
            self._first_failure_at = monotonic_now
            self._failure_count = 1
        else:
            self._failure_count += 1
        duration = monotonic_now - self._first_failure_at
        if self._state is ModelHealthState.DEGRADED:
            return None
        if self._failure_count < FAILURE_THRESHOLD and duration < DEGRADED_SECONDS:
            return None
        self._state = ModelHealthState.DEGRADED
        return ModelHealthTransition(
            state=self._state,
            code=ModelHealthCode.MODEL_DEGRADED,
            failure_count=self._failure_count,
            success_count=0,
            duration_seconds=duration,
        )

    def succeeded(
        self,
        *,
        monotonic_now: float,
    ) -> ModelHealthTransition | None:
        self._require_monotonic(monotonic_now)
        self._last_monotonic = monotonic_now
        if self._state is ModelHealthState.HEALTHY:
            self._reset_evidence()
            return None
        self._success_count += 1
        if self._success_count < RECOVERY_SUCCESSES:
            return None
        duration = (
            monotonic_now - self._first_failure_at
            if self._first_failure_at is not None
            else 0.0
        )
        transition = ModelHealthTransition(
            state=ModelHealthState.HEALTHY,
            code=ModelHealthCode.MODEL_RECOVERED,
            failure_count=self._failure_count,
            success_count=self._success_count,
            duration_seconds=duration,
        )
        self._state = ModelHealthState.HEALTHY
        self._reset_evidence()
        return transition

    def _require_monotonic(self, value: float) -> None:
        if value < 0:
            raise ValueError("monotonic time must be non-negative")
        if self._last_monotonic is not None and value < self._last_monotonic:
            raise ValueError("monotonic time cannot decrease")

    def _reset_evidence(self) -> None:
        self._first_failure_at = None
        self._failure_count = 0
        self._success_count = 0

