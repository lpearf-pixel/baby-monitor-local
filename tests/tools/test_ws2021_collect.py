from __future__ import annotations

from packages.monitoring.ws2021_dataset import CollectionCode
from tools.ws2021_collect import _collect_for_duration


def test_collection_uses_wall_clock_deadline_not_fixed_attempt_count() -> None:
    class Clock:
        value = 0.0

        def monotonic(self) -> float:
            return self.value

        def sleep(self, seconds: float) -> None:
            self.value += seconds

    clock = Clock()
    attempts = 0

    def attempt() -> CollectionCode:
        nonlocal attempts
        attempts += 1
        clock.value += 1.2
        return CollectionCode.ACCEPTED

    counts = _collect_for_duration(
        attempt,
        duration_seconds=3,
        interval_seconds=0.5,
        monotonic=clock.monotonic,
        sleep=clock.sleep,
    )

    assert attempts == 2
    assert counts.accepted == 2
    assert clock.value == 3
