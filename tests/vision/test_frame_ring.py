from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from services.vision.frame_policy import PreparedAnalysisFrame
from services.vision.frame_ring import AnalysisFrameRing


NOW = datetime(2026, 8, 5, 12, 0, tzinfo=timezone.utc)


def frame(seconds: float, *, aware: bool = True) -> PreparedAnalysisFrame:
    captured_at = NOW + timedelta(seconds=seconds)
    if not aware:
        captured_at = captured_at.replace(tzinfo=None)
    return PreparedAnalysisFrame(
        jpeg=f"frame-{seconds}".encode(),
        captured_at=captured_at,
        width=960,
        height=540,
        crop_box=(0, 0, 10, 10),
    )


def test_ring_evicts_frames_older_than_forty_seconds() -> None:
    ring = AnalysisFrameRing()
    ring.add(frame(0))
    ring.add(frame(2))

    ring.add(frame(42))

    assert len(ring) == 2


def test_ring_never_keeps_more_than_twenty_one_frames() -> None:
    ring = AnalysisFrameRing()

    for seconds in range(22):
        ring.add(frame(seconds))

    assert len(ring) == 21


def test_select_review_frames_returns_four_chronological_two_second_samples() -> None:
    ring = AnalysisFrameRing()
    for seconds in [0.1, 2.1, 4.2, 6.0]:
        ring.add(frame(seconds))

    selected = ring.select_review_frames(count=4, spacing_seconds=2)

    assert [item.jpeg for item in selected] == [
        b"frame-0.1",
        b"frame-2.1",
        b"frame-4.2",
        b"frame-6.0",
    ]


def test_select_review_frames_returns_empty_when_history_is_insufficient() -> None:
    ring = AnalysisFrameRing()
    ring.add(frame(0))
    ring.add(frame(2))
    ring.add(frame(4))

    assert ring.select_review_frames(count=4, spacing_seconds=2) == ()


def test_ring_rejects_naive_frame_time() -> None:
    ring = AnalysisFrameRing()

    with pytest.raises(ValueError, match="timezone-aware"):
        ring.add(frame(0, aware=False))


def test_ring_rejects_decreasing_frame_time_without_mutation() -> None:
    ring = AnalysisFrameRing()
    ring.add(frame(10))

    with pytest.raises(ValueError, match="monotonic"):
        ring.add(frame(9))

    assert len(ring) == 1


def test_snapshot_window_selects_inclusive_chronological_frames() -> None:
    ring = AnalysisFrameRing()
    for seconds in [0, 2, 4, 6, 8, 10, 12]:
        ring.add(frame(seconds))

    selected = ring.snapshot_window(
        start_at=NOW + timedelta(seconds=2),
        end_at=NOW + timedelta(seconds=10),
    )

    assert [item.jpeg for item in selected] == [
        b"frame-2",
        b"frame-4",
        b"frame-6",
        b"frame-8",
        b"frame-10",
    ]
    assert len(ring) == 7


def test_snapshot_window_returns_empty_outside_retained_history() -> None:
    ring = AnalysisFrameRing()
    ring.add(frame(10))

    assert ring.snapshot_window(
        start_at=NOW,
        end_at=NOW + timedelta(seconds=8),
    ) == ()


@pytest.mark.parametrize(
    ("start_at", "end_at"),
    [
        (NOW.replace(tzinfo=None), NOW),
        (NOW, NOW.replace(tzinfo=None)),
        (NOW + timedelta(seconds=1), NOW),
    ],
)
def test_snapshot_window_rejects_invalid_time_bounds(
    start_at: datetime,
    end_at: datetime,
) -> None:
    ring = AnalysisFrameRing()

    with pytest.raises(ValueError):
        ring.snapshot_window(start_at=start_at, end_at=end_at)


@pytest.mark.parametrize(
    ("count", "spacing_seconds"),
    [(0, 2), (4, 0), (22, 2), (4, 41)],
)
def test_selection_rejects_unbounded_requests(
    count: int, spacing_seconds: int
) -> None:
    ring = AnalysisFrameRing()

    with pytest.raises(ValueError):
        ring.select_review_frames(count=count, spacing_seconds=spacing_seconds)
