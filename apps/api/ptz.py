from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from threading import Lock
from time import monotonic
from typing import Callable, Protocol


class PtzDirection(str, Enum):
    UP = "up"
    DOWN = "down"
    LEFT = "left"
    RIGHT = "right"


class PtzCode(str, Enum):
    OK = "PTZ_OK"
    BUSY = "PTZ_BUSY"
    DISABLED = "PTZ_DISABLED"
    UNAVAILABLE = "PTZ_UNAVAILABLE"
    TIMEOUT = "PTZ_TIMEOUT"


@dataclass(frozen=True)
class PtzResult:
    code: PtzCode
    cooldown_ms: int = 0

    def as_dict(self) -> dict[str, str | int]:
        return {"result": self.code.value, "cooldown_ms": self.cooldown_ms}


class PtzAdapter(Protocol):
    def step(
        self, direction: PtzDirection, timeout_seconds: float
    ) -> PtzCode: ...


class DisabledPtzAdapter:
    def step(self, direction: PtzDirection, timeout_seconds: float) -> PtzCode:
        return PtzCode.DISABLED


class StepPtzController:
    def __init__(
        self,
        *,
        adapter: PtzAdapter,
        minimum_interval_seconds: float = 0.75,
        timeout_seconds: float = 1.0,
        clock: Callable[[], float] = monotonic,
    ) -> None:
        self._adapter = adapter
        self._minimum_interval_seconds = minimum_interval_seconds
        self._timeout_seconds = timeout_seconds
        self._clock = clock
        self._lock = Lock()
        self._last_accepted_at: float | None = None

    @property
    def cooldown_ms(self) -> int:
        return round(self._minimum_interval_seconds * 1000)

    def step(self, direction: PtzDirection) -> PtzResult:
        if not self._lock.acquire(blocking=False):
            return PtzResult(PtzCode.BUSY, self.cooldown_ms)

        try:
            started_at = self._clock()
            if (
                self._last_accepted_at is not None
                and started_at - self._last_accepted_at
                < self._minimum_interval_seconds
            ):
                return PtzResult(PtzCode.BUSY, self.cooldown_ms)

            try:
                code = self._adapter.step(direction, self._timeout_seconds)
            except TimeoutError:
                return PtzResult(PtzCode.TIMEOUT)
            except Exception:
                return PtzResult(PtzCode.UNAVAILABLE)

            if not isinstance(code, PtzCode):
                return PtzResult(PtzCode.UNAVAILABLE)
            if code is PtzCode.OK:
                self._last_accepted_at = started_at
                return PtzResult(code, self.cooldown_ms)
            if code is PtzCode.BUSY:
                return PtzResult(code, self.cooldown_ms)
            return PtzResult(code)
        finally:
            self._lock.release()
