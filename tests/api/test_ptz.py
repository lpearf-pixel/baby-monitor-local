from __future__ import annotations

from dataclasses import dataclass, field
from threading import Event, Thread

from apps.api.ptz import (
    DisabledPtzAdapter,
    PtzCode,
    PtzDirection,
    StepPtzController,
)


@dataclass
class ManualClock:
    value: float = 0.0

    def __call__(self) -> float:
        return self.value

    def advance(self, seconds: float) -> None:
        self.value += seconds


@dataclass
class RecordingAdapter:
    result: object = PtzCode.OK
    directions: list[PtzDirection] = field(default_factory=list)
    timeouts: list[float] = field(default_factory=list)

    def step(self, direction: PtzDirection, timeout_seconds: float) -> object:
        self.directions.append(direction)
        self.timeouts.append(timeout_seconds)
        return self.result


@dataclass
class BlockingAdapter:
    started: Event = field(default_factory=Event)
    release: Event = field(default_factory=Event)
    directions: list[PtzDirection] = field(default_factory=list)

    def step(self, direction: PtzDirection, timeout_seconds: float) -> PtzCode:
        self.directions.append(direction)
        self.started.set()
        if not self.release.wait(timeout_seconds):
            raise TimeoutError
        return PtzCode.OK


class TimeoutAdapter:
    def step(self, direction: PtzDirection, timeout_seconds: float) -> PtzCode:
        raise TimeoutError("sensitive transport detail")


class BrokenAdapter:
    def step(self, direction: PtzDirection, timeout_seconds: float) -> PtzCode:
        raise RuntimeError("sensitive camera URI")


def test_disabled_adapter_fails_closed_without_device_io() -> None:
    controller = StepPtzController(adapter=DisabledPtzAdapter())

    result = controller.step(PtzDirection.LEFT)

    assert result.code is PtzCode.DISABLED
    assert result.cooldown_ms == 0


def test_controller_passes_closed_direction_and_bounded_timeout_once() -> None:
    adapter = RecordingAdapter()
    controller = StepPtzController(
        adapter=adapter,
        minimum_interval_seconds=0,
        timeout_seconds=0.4,
    )

    result = controller.step(PtzDirection.UP)

    assert result.code is PtzCode.OK
    assert adapter.directions == [PtzDirection.UP]
    assert adapter.timeouts == [0.4]


def test_controller_serializes_in_flight_steps() -> None:
    adapter = BlockingAdapter()
    controller = StepPtzController(
        adapter=adapter,
        minimum_interval_seconds=0,
        timeout_seconds=1,
    )
    first_result: list[PtzCode] = []
    first = Thread(
        target=lambda: first_result.append(controller.step(PtzDirection.LEFT).code)
    )

    first.start()
    assert adapter.started.wait(1)
    second = controller.step(PtzDirection.RIGHT)
    adapter.release.set()
    first.join(1)

    assert second.code is PtzCode.BUSY
    assert first_result == [PtzCode.OK]
    assert adapter.directions == [PtzDirection.LEFT]


def test_controller_rate_limits_recent_accepted_step() -> None:
    clock = ManualClock()
    adapter = RecordingAdapter()
    controller = StepPtzController(
        adapter=adapter,
        clock=clock,
        minimum_interval_seconds=0.75,
    )

    first = controller.step(PtzDirection.LEFT)
    blocked = controller.step(PtzDirection.RIGHT)
    clock.advance(0.75)
    accepted = controller.step(PtzDirection.RIGHT)

    assert first.code is PtzCode.OK
    assert first.cooldown_ms == 750
    assert blocked.code is PtzCode.BUSY
    assert blocked.cooldown_ms == 750
    assert accepted.code is PtzCode.OK
    assert adapter.directions == [PtzDirection.LEFT, PtzDirection.RIGHT]


def test_disabled_result_does_not_start_rate_limit() -> None:
    clock = ManualClock()
    adapter = RecordingAdapter(PtzCode.DISABLED)
    controller = StepPtzController(adapter=adapter, clock=clock)

    first = controller.step(PtzDirection.LEFT)
    second = controller.step(PtzDirection.RIGHT)

    assert first.code is PtzCode.DISABLED
    assert second.code is PtzCode.DISABLED
    assert adapter.directions == [PtzDirection.LEFT, PtzDirection.RIGHT]


def test_timeout_is_reduced_to_stable_code_without_detail() -> None:
    controller = StepPtzController(adapter=TimeoutAdapter())

    result = controller.step(PtzDirection.DOWN)

    assert result.code is PtzCode.TIMEOUT
    assert result.as_dict() == {"result": "PTZ_TIMEOUT", "cooldown_ms": 0}
    assert "sensitive" not in str(result.as_dict())


def test_exception_is_reduced_to_unavailable_without_detail() -> None:
    controller = StepPtzController(adapter=BrokenAdapter())

    result = controller.step(PtzDirection.DOWN)

    assert result.code is PtzCode.UNAVAILABLE
    assert result.as_dict() == {"result": "PTZ_UNAVAILABLE", "cooldown_ms": 0}
    assert "camera URI" not in str(result.as_dict())


def test_unknown_adapter_result_fails_closed() -> None:
    controller = StepPtzController(adapter=RecordingAdapter(result="raw-device-ok"))

    result = controller.step(PtzDirection.RIGHT)

    assert result.code is PtzCode.UNAVAILABLE
    assert result.as_dict() == {"result": "PTZ_UNAVAILABLE", "cooldown_ms": 0}
