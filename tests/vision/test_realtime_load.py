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


def test_load_reports_hand_calculated_bounded_distribution() -> None:
    module = load_module()
    controller = module.RealtimeLoadController()

    status = None
    for monotonic_now, processing_ms in enumerate(
        (10.001, 20.002, 30.003, 40.004)
    ):
        status = controller.observe(
            processing_ms,
            monotonic_now=float(monotonic_now),
        )

    assert status is not None
    assert status.sample_count == 4
    assert status.p50_ms == 20.002
    assert status.p95_ms == 40.004
    assert status.max_ms == 40.004


def test_load_rounds_half_up_to_three_decimal_places() -> None:
    module = load_module()
    controller = module.RealtimeLoadController()

    status = controller.observe(202.2505, monotonic_now=0.0)

    assert status.p50_ms == 202.251
    assert status.p95_ms == 202.251
    assert status.max_ms == 202.251


def test_load_accepts_large_finite_processing_time() -> None:
    module = load_module()
    controller = module.RealtimeLoadController()

    status = controller.observe(1e30, monotonic_now=0.0)

    assert status.p50_ms == 1e30
    assert status.p95_ms == 1e30
    assert status.max_ms == 1e30


def test_load_evicts_expired_samples_and_caps_window_at_fifty_one() -> None:
    module = load_module()
    controller = module.RealtimeLoadController()

    for tick in range(101):
        status = controller.observe(10.0, monotonic_now=tick / 10)

    assert status.sample_count == 51

    expired = module.RealtimeLoadController()
    expired.observe(10.0, monotonic_now=0.0)
    expired.observe(20.0, monotonic_now=10.0)
    status = expired.observe(30.0, monotonic_now=10.001)

    assert status.sample_count == 2
    assert status.p50_ms == 20.0
    assert status.p95_ms == 30.0
    assert status.max_ms == 30.0


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
