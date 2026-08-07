from __future__ import annotations

import pytest


def load_module():
    from services.vision import realtime_load

    return realtime_load


def feed(controller: object, start: float, end: float, value: float) -> object:
    status = None
    tick = start
    while tick <= end + 1e-9:
        status = controller.observe(value, monotonic_now=round(tick, 6))
        tick += 0.2
    return status


def test_load_degrades_from_five_to_three_after_five_overloaded_seconds() -> None:
    module = load_module()
    controller = module.RealtimeLoadController()

    before = feed(controller, 0.0, 4.8, 200.0)
    due = controller.observe(200.0, monotonic_now=5.0)

    assert before.target_fps == 5
    assert due.target_fps == 3
    assert due.transition_code is module.RealtimeLoadTransitionCode.DEGRADED


def test_three_fps_degrades_to_one_after_ten_more_overloaded_seconds() -> None:
    module = load_module()
    controller = module.RealtimeLoadController()
    feed(controller, 0.0, 5.0, 200.0)

    before = feed(controller, 5.2, 15.0, 350.0)
    due = controller.observe(350.0, monotonic_now=15.2)

    assert before.target_fps == 3
    assert due.target_fps == 1
    assert due.transition_code is module.RealtimeLoadTransitionCode.DEGRADED


def test_load_recovers_only_one_tier_after_sixty_healthy_seconds() -> None:
    module = load_module()
    controller = module.RealtimeLoadController()
    feed(controller, 0.0, 5.0, 200.0)
    feed(controller, 5.2, 15.2, 350.0)

    feed(controller, 15.4, 75.2, 100.0)
    recovered = controller.observe(100.0, monotonic_now=75.4)

    assert recovered.target_fps == 3
    assert recovered.transition_code is module.RealtimeLoadTransitionCode.RECOVERED


@pytest.mark.parametrize("value", [-1.0, float("nan"), float("inf")])
def test_load_rejects_invalid_processing_time(value: float) -> None:
    module = load_module()
    controller = module.RealtimeLoadController()

    with pytest.raises(ValueError, match="processing"):
        controller.observe(value, monotonic_now=0.0)


def test_load_rejects_time_rollback() -> None:
    module = load_module()
    controller = module.RealtimeLoadController()
    controller.observe(10.0, monotonic_now=1.0)

    with pytest.raises(ValueError, match="monotonic"):
        controller.observe(10.0, monotonic_now=0.9)
