from __future__ import annotations

from concurrent.futures import Future
from datetime import UTC, datetime, timedelta

import pytest

from packages.contracts.vision import VisualReview
from services.vision.frame_policy import PreparedAnalysisFrame


NOW = datetime(2026, 8, 5, 12, 0, tzinfo=UTC)


def review() -> VisualReview:
    return VisualReview.model_validate(
        {
            "baby_visibility": "visible",
            "face_visibility": "clear",
            "posture": "supine",
            "bed_state": "inside",
            "adult_presence": "absent",
            "image_quality": "usable",
            "risk": "none",
            "reason_codes": [],
            "confidence": 0.9,
        }
    )


def frame(seconds: int, *, aware: bool = True) -> PreparedAnalysisFrame:
    captured_at = NOW + timedelta(seconds=seconds)
    if not aware:
        captured_at = captured_at.replace(tzinfo=None)
    return PreparedAnalysisFrame(
        jpeg=f"frame-{seconds}".encode(),
        captured_at=captured_at,
        width=960,
        height=540,
        crop_box=(0, 0, 960, 540),
    )


def four_frames() -> tuple[PreparedAnalysisFrame, ...]:
    return tuple(frame(seconds) for seconds in (0, 2, 4, 6))


class FakeExecutor:
    def __init__(self) -> None:
        self.futures: list[Future[VisualReview]] = []
        self.calls: list[tuple[object, tuple[PreparedAnalysisFrame, ...]]] = []

    def submit(
        self,
        function: object,
        frames: tuple[PreparedAnalysisFrame, ...],
    ) -> Future[VisualReview]:
        future: Future[VisualReview] = Future()
        self.calls.append((function, frames))
        self.futures.append(future)
        return future


def scheduler_module():
    from services.vision import review_scheduler

    return review_scheduler


def test_first_complete_batch_submits_once_and_busy_batch_is_skipped() -> None:
    module = scheduler_module()
    executor = FakeExecutor()
    scheduler = module.VisualReviewScheduler(reviewer=lambda _frames: review(), executor=executor)

    first = scheduler.try_submit(four_frames(), monotonic_now=10.0)
    busy = scheduler.try_submit(four_frames(), monotonic_now=20.0)

    assert first is module.ReviewScheduleDecision.SUBMITTED
    assert busy is module.ReviewScheduleDecision.SKIPPED_BUSY
    assert len(executor.calls) == 1


def test_incomplete_batch_is_not_submitted() -> None:
    module = scheduler_module()
    executor = FakeExecutor()
    scheduler = module.VisualReviewScheduler(reviewer=lambda _frames: review(), executor=executor)

    decision = scheduler.try_submit(four_frames()[:3], monotonic_now=0.0)

    assert decision is module.ReviewScheduleDecision.SKIPPED_INSUFFICIENT_FRAMES
    assert executor.calls == []


def test_regular_submissions_are_at_least_ten_seconds_apart() -> None:
    module = scheduler_module()
    executor = FakeExecutor()
    scheduler = module.VisualReviewScheduler(reviewer=lambda _frames: review(), executor=executor)
    scheduler.try_submit(four_frames(), monotonic_now=0.0)
    executor.futures[0].set_result(review())
    assert scheduler.poll().code is module.ReviewCompletionCode.OK

    early = scheduler.try_submit(four_frames(), monotonic_now=9.9)
    due = scheduler.try_submit(four_frames(), monotonic_now=10.0)

    assert early is module.ReviewScheduleDecision.SKIPPED_NOT_DUE
    assert due is module.ReviewScheduleDecision.SUBMITTED
    assert len(executor.calls) == 2


def test_urgent_submission_is_allowed_after_five_seconds() -> None:
    module = scheduler_module()
    executor = FakeExecutor()
    scheduler = module.VisualReviewScheduler(reviewer=lambda _frames: review(), executor=executor)
    scheduler.try_submit(four_frames(), monotonic_now=0.0)
    executor.futures[0].set_result(review())
    scheduler.poll()

    early = scheduler.try_submit(four_frames(), monotonic_now=4.9, urgent=True)
    due = scheduler.try_submit(four_frames(), monotonic_now=5.0, urgent=True)

    assert early is module.ReviewScheduleDecision.SKIPPED_NOT_DUE
    assert due is module.ReviewScheduleDecision.SUBMITTED


def test_poll_returns_one_strict_success_completion() -> None:
    module = scheduler_module()
    executor = FakeExecutor()
    expected = review()
    scheduler = module.VisualReviewScheduler(reviewer=lambda _frames: expected, executor=executor)
    scheduler.try_submit(four_frames(), monotonic_now=0.0)
    executor.futures[0].set_result(expected)

    completion = scheduler.poll()

    assert completion.code is module.ReviewCompletionCode.OK
    assert completion.review == expected
    assert scheduler.poll() is None


def test_review_exception_returns_only_stable_failure_code() -> None:
    module = scheduler_module()
    executor = FakeExecutor()
    scheduler = module.VisualReviewScheduler(reviewer=lambda _frames: review(), executor=executor)
    scheduler.try_submit(four_frames(), monotonic_now=0.0)
    executor.futures[0].set_exception(
        RuntimeError("credential at /private/family/model")
    )

    completion = scheduler.poll()

    assert completion.code is module.ReviewCompletionCode.REVIEW_FAILED
    assert completion.review is None
    assert "/private" not in repr(completion)


def test_invalid_reviewer_result_is_a_stable_failure() -> None:
    module = scheduler_module()
    executor = FakeExecutor()
    scheduler = module.VisualReviewScheduler(reviewer=lambda _frames: review(), executor=executor)
    scheduler.try_submit(four_frames(), monotonic_now=0.0)
    executor.futures[0].set_result("not-a-review")  # type: ignore[arg-type]

    completion = scheduler.poll()

    assert completion.code is module.ReviewCompletionCode.REVIEW_FAILED
    assert completion.review is None


def test_close_cancels_pending_future_and_rejects_later_submission() -> None:
    module = scheduler_module()
    executor = FakeExecutor()
    scheduler = module.VisualReviewScheduler(reviewer=lambda _frames: review(), executor=executor)
    scheduler.try_submit(four_frames(), monotonic_now=0.0)

    scheduler.close()

    assert executor.futures[0].cancelled() is True
    with pytest.raises(RuntimeError, match="scheduler is closed"):
        scheduler.try_submit(four_frames(), monotonic_now=10.0)


def test_scheduler_rejects_naive_decreasing_or_nonchronological_input() -> None:
    module = scheduler_module()
    executor = FakeExecutor()
    scheduler = module.VisualReviewScheduler(reviewer=lambda _frames: review(), executor=executor)

    invalid_aware = (*four_frames()[:3], frame(6, aware=False))
    with pytest.raises(ValueError, match="timezone-aware"):
        scheduler.try_submit(invalid_aware, monotonic_now=0.0)

    invalid_order = tuple(frame(seconds) for seconds in (0, 4, 2, 6))
    with pytest.raises(ValueError, match="chronological"):
        scheduler.try_submit(invalid_order, monotonic_now=0.0)

    scheduler.try_submit(four_frames(), monotonic_now=10.0)
    with pytest.raises(ValueError, match="monotonic"):
        scheduler.try_submit(four_frames(), monotonic_now=9.0)
