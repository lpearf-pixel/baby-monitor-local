from __future__ import annotations

from collections.abc import Callable
from concurrent.futures import Future
import time
from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol

from packages.contracts.vision import VisualReview
from services.vision.frame_policy import PreparedAnalysisFrame


REGULAR_REVIEW_INTERVAL_SECONDS = 10.0
URGENT_REVIEW_INTERVAL_SECONDS = 5.0
REVIEW_FRAME_COUNT = 4
REVIEW_TIMEOUT_SECONDS = 20.0


class ReviewScheduleDecision(StrEnum):
    SUBMITTED = "submitted"
    SKIPPED_BUSY = "skipped_busy"
    SKIPPED_NOT_DUE = "skipped_not_due"
    SKIPPED_INSUFFICIENT_FRAMES = "skipped_insufficient_frames"


class ReviewCompletionCode(StrEnum):
    OK = "ok"
    REVIEW_FAILED = "review_failed"


@dataclass(frozen=True)
class ReviewCompletion:
    code: ReviewCompletionCode
    review: VisualReview | None = None


Reviewer = Callable[[tuple[PreparedAnalysisFrame, ...]], VisualReview]


class ExecutorLike(Protocol):
    def submit(
        self,
        function: Reviewer,
        frames: tuple[PreparedAnalysisFrame, ...],
    ) -> Future[VisualReview]: ...


class ReviewObserverLike(Protocol):
    def record_request(
        self,
        frames: tuple[PreparedAnalysisFrame, ...],
        *,
        monotonic_now: float,
    ) -> None: ...

    def record_timeout(self, *, monotonic_now: float) -> None: ...

    def record_completion(
        self,
        *,
        code: ReviewCompletionCode,
        review: VisualReview | None,
        monotonic_now: float,
        late: bool = False,
    ) -> None: ...

    def tick(self, *, monotonic_now: float) -> dict[str, object]: ...


class VisualReviewScheduler:
    def __init__(
        self,
        *,
        reviewer: Reviewer,
        executor: ExecutorLike,
        observer: ReviewObserverLike | None = None,
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        self._reviewer = reviewer
        self._executor = executor
        self._future: Future[VisualReview] | None = None
        self._submitted_at: float | None = None
        self._timed_out = False
        self._last_submitted: float | None = None
        self._last_monotonic: float | None = None
        self._closed = False
        self._observer = observer
        self._monotonic = monotonic

    def try_submit(
        self,
        frames: tuple[PreparedAnalysisFrame, ...],
        *,
        monotonic_now: float,
        urgent: bool = False,
    ) -> ReviewScheduleDecision:
        if self._closed:
            raise RuntimeError("review scheduler is closed")
        self._require_monotonic(monotonic_now)
        self._notify_tick(monotonic_now)
        if len(frames) != REVIEW_FRAME_COUNT:
            self._last_monotonic = monotonic_now
            return ReviewScheduleDecision.SKIPPED_INSUFFICIENT_FRAMES
        self._require_valid_frames(frames)
        self._last_monotonic = monotonic_now

        if self._future is not None:
            return ReviewScheduleDecision.SKIPPED_BUSY

        interval = (
            URGENT_REVIEW_INTERVAL_SECONDS
            if urgent
            else REGULAR_REVIEW_INTERVAL_SECONDS
        )
        if (
            self._last_submitted is not None
            and monotonic_now - self._last_submitted < interval
        ):
            return ReviewScheduleDecision.SKIPPED_NOT_DUE

        self._future = self._executor.submit(self._reviewer, frames)
        self._submitted_at = monotonic_now
        self._timed_out = False
        self._last_submitted = monotonic_now
        self._notify_request(frames, monotonic_now)
        return ReviewScheduleDecision.SUBMITTED

    def poll(self, *, monotonic_now: float | None = None) -> ReviewCompletion | None:
        if monotonic_now is None:
            monotonic_now = self._monotonic()
        self._notify_tick(monotonic_now)
        future = self._future
        if future is None:
            return None
        if (
            not future.done()
            and self._submitted_at is not None
            and monotonic_now - self._submitted_at >= REVIEW_TIMEOUT_SECONDS
            and not self._timed_out
        ):
            self._timed_out = True
            self._notify_timeout(monotonic_now)
        if not future.done():
            return None
        self._future = None
        self._submitted_at = None
        try:
            result = future.result()
        except Exception:
            completion = ReviewCompletion(code=ReviewCompletionCode.REVIEW_FAILED)
            self._notify_completion(
                completion,
                monotonic_now=monotonic_now,
                late=self._timed_out,
            )
            self._timed_out = False
            return completion
        if not isinstance(result, VisualReview):
            completion = ReviewCompletion(code=ReviewCompletionCode.REVIEW_FAILED)
        else:
            completion = ReviewCompletion(code=ReviewCompletionCode.OK, review=result)
        self._notify_completion(
            completion,
            monotonic_now=monotonic_now,
            late=self._timed_out,
        )
        self._timed_out = False
        return completion

    def close(self) -> None:
        self._closed = True
        if self._future is not None:
            self._future.cancel()
            self._future = None
        self._submitted_at = None

    def _notify_tick(self, monotonic_now: float) -> None:
        if self._observer is None:
            return
        try:
            self._observer.tick(monotonic_now=monotonic_now)
        except Exception:
            pass

    def _notify_request(
        self,
        frames: tuple[PreparedAnalysisFrame, ...],
        monotonic_now: float,
    ) -> None:
        if self._observer is None:
            return
        try:
            self._observer.record_request(frames, monotonic_now=monotonic_now)
        except Exception:
            pass

    def _notify_timeout(self, monotonic_now: float) -> None:
        if self._observer is None:
            return
        try:
            self._observer.record_timeout(monotonic_now=monotonic_now)
        except Exception:
            pass

    def _notify_completion(
        self,
        completion: ReviewCompletion,
        *,
        monotonic_now: float,
        late: bool,
    ) -> None:
        if self._observer is None:
            return
        try:
            self._observer.record_completion(
                code=completion.code,
                review=completion.review,
                monotonic_now=monotonic_now,
                late=late,
            )
        except Exception:
            pass

    def _require_monotonic(self, value: float) -> None:
        if value < 0:
            raise ValueError("monotonic time must be non-negative")
        if self._last_monotonic is not None and value < self._last_monotonic:
            raise ValueError("monotonic time cannot decrease")

    @staticmethod
    def _require_valid_frames(
        frames: tuple[PreparedAnalysisFrame, ...],
    ) -> None:
        for frame in frames:
            if (
                frame.captured_at.tzinfo is None
                or frame.captured_at.utcoffset() is None
            ):
                raise ValueError("review frame times must be timezone-aware")
        if any(
            current.captured_at <= previous.captured_at
            for previous, current in zip(frames, frames[1:])
        ):
            raise ValueError("review frames must be chronological")
