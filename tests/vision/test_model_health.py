from __future__ import annotations

import pytest


def health_module():
    from services.vision import model_health

    return model_health


def test_third_consecutive_failure_degrades_once() -> None:
    module = health_module()
    monitor = module.VisualModelHealthMonitor()

    assert monitor.failed(monotonic_now=0.0) is None
    assert monitor.failed(monotonic_now=10.0) is None
    transition = monitor.failed(monotonic_now=20.0)
    repeated = monitor.failed(monotonic_now=30.0)

    assert transition.code is module.ModelHealthCode.MODEL_DEGRADED
    assert transition.state is module.ModelHealthState.DEGRADED
    assert transition.failure_count == 3
    assert transition.duration_seconds == 20.0
    assert repeated is None


def test_sixty_second_failure_span_degrades_even_before_three_failures() -> None:
    module = health_module()
    monitor = module.VisualModelHealthMonitor()

    monitor.failed(monotonic_now=5.0)
    transition = monitor.failed(monotonic_now=65.0)

    assert transition.code is module.ModelHealthCode.MODEL_DEGRADED
    assert transition.failure_count == 2
    assert transition.duration_seconds == 60.0


def test_two_consecutive_successes_are_required_for_one_recovery() -> None:
    module = health_module()
    monitor = module.VisualModelHealthMonitor()
    monitor.failed(monotonic_now=0.0)
    monitor.failed(monotonic_now=10.0)
    monitor.failed(monotonic_now=20.0)

    assert monitor.succeeded(monotonic_now=30.0) is None
    transition = monitor.succeeded(monotonic_now=40.0)
    repeated = monitor.succeeded(monotonic_now=50.0)

    assert transition.code is module.ModelHealthCode.MODEL_RECOVERED
    assert transition.state is module.ModelHealthState.HEALTHY
    assert transition.success_count == 2
    assert repeated is None


def test_failure_between_successes_resets_recovery_evidence() -> None:
    module = health_module()
    monitor = module.VisualModelHealthMonitor()
    for second in (0.0, 10.0, 20.0):
        monitor.failed(monotonic_now=second)

    monitor.succeeded(monotonic_now=30.0)
    monitor.failed(monotonic_now=40.0)
    assert monitor.succeeded(monotonic_now=50.0) is None
    transition = monitor.succeeded(monotonic_now=60.0)

    assert transition.code is module.ModelHealthCode.MODEL_RECOVERED


def test_healthy_success_clears_partial_failure_evidence() -> None:
    module = health_module()
    monitor = module.VisualModelHealthMonitor()

    monitor.failed(monotonic_now=0.0)
    monitor.failed(monotonic_now=10.0)
    monitor.succeeded(monotonic_now=20.0)
    monitor.failed(monotonic_now=30.0)
    monitor.failed(monotonic_now=40.0)

    assert monitor.status().state is module.ModelHealthState.HEALTHY
    assert monitor.status().failure_count == 2


def test_monotonic_rollback_is_rejected_without_mutation() -> None:
    module = health_module()
    monitor = module.VisualModelHealthMonitor()
    monitor.failed(monotonic_now=10.0)

    with pytest.raises(ValueError, match="monotonic"):
        monitor.failed(monotonic_now=9.0)

    assert monitor.status().failure_count == 1

