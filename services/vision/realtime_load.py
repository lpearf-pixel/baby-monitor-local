from __future__ import annotations

import math
from collections import deque
from dataclasses import dataclass
from enum import StrEnum
from typing import Literal


class RealtimeLoadTransitionCode(StrEnum):
    DEGRADED = "realtime_degraded"
    RECOVERED = "realtime_recovered"


@dataclass(frozen=True)
class RealtimeLoadStatus:
    target_fps: Literal[1, 3, 5]
    p95_ms: float
    transition_code: RealtimeLoadTransitionCode | None = None


class RealtimeLoadController:
    def __init__(self) -> None:
        self._target_fps: Literal[1, 3, 5] = 5
        self._samples: deque[tuple[float, float]] = deque()
        self._last_monotonic: float | None = None
        self._overload_since: float | None = None
        self._healthy_since: float | None = None

    def observe(
        self,
        processing_ms: float,
        *,
        monotonic_now: float,
    ) -> RealtimeLoadStatus:
        if not math.isfinite(processing_ms) or processing_ms < 0:
            raise ValueError("processing time must be finite and non-negative")
        if not math.isfinite(monotonic_now) or monotonic_now < 0:
            raise ValueError("monotonic time must be finite and non-negative")
        if self._last_monotonic is not None and monotonic_now < self._last_monotonic:
            raise ValueError("monotonic time cannot decrease")
        self._last_monotonic = monotonic_now
        self._samples.append((monotonic_now, processing_ms))
        while self._samples and monotonic_now - self._samples[0][0] > 10.0:
            self._samples.popleft()
        p95 = self._p95()
        transition: RealtimeLoadTransitionCode | None = None

        budget, duration = (
            (180.0, 5.0) if self._target_fps == 5 else (300.0, 10.0)
        )
        if self._target_fps > 1 and p95 > budget:
            self._healthy_since = None
            if self._overload_since is None:
                self._overload_since = monotonic_now
            if monotonic_now - self._overload_since + 1e-9 >= duration:
                self._target_fps = 3 if self._target_fps == 5 else 1
                self._reset_evidence()
                transition = RealtimeLoadTransitionCode.DEGRADED
        else:
            self._overload_since = None
            recovery_budget = 300.0 if self._target_fps == 1 else 180.0
            if self._target_fps < 5 and processing_ms <= recovery_budget:
                if self._healthy_since is None:
                    self._healthy_since = monotonic_now
                if monotonic_now - self._healthy_since + 1e-9 >= 60.0:
                    self._target_fps = 3 if self._target_fps == 1 else 5
                    self._reset_evidence()
                    transition = RealtimeLoadTransitionCode.RECOVERED
            else:
                self._healthy_since = None
        return RealtimeLoadStatus(
            target_fps=self._target_fps,
            p95_ms=p95,
            transition_code=transition,
        )

    def _p95(self) -> float:
        values = sorted(value for _, value in self._samples)
        index = max(0, math.ceil(0.95 * len(values)) - 1)
        return round(values[index], 3)

    def _reset_evidence(self) -> None:
        self._samples.clear()
        self._overload_since = None
        self._healthy_since = None
