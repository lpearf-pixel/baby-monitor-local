from __future__ import annotations

import time
from collections.abc import Callable, Iterator
from dataclasses import dataclass, replace
from typing import Literal, Protocol

from services.stream.frame_source import CapturedFrame, FrameSourceUnavailable
from services.vision.frame_health import (
    FrameHealthCode,
    FrameHealthTransition,
    VisualFrameHealthMonitor,
)
from services.vision.frame_policy import PreparedAnalysisFrame, VisionFramePolicy
from services.vision.frame_ring import AnalysisFrameRing
from services.vision.review_scheduler import (
    ReviewCompletion,
    VisualReviewScheduler,
)


SAMPLE_INTERVAL_SECONDS = 2.0
REVIEW_INTERVAL_SECONDS = 10.0
RECONNECT_BACKOFF_SECONDS = (1.0, 2.0, 4.0, 8.0)


class StopEvent(Protocol):
    def is_set(self) -> bool: ...

    def wait(self, timeout: float) -> bool: ...


class FramePolicyLike(Protocol):
    def prepare(self, frame: CapturedFrame) -> PreparedAnalysisFrame: ...


class FrameRingLike(Protocol):
    def add(self, frame: PreparedAnalysisFrame) -> None: ...

    def select_review_frames(
        self,
        *,
        count: int = 4,
        spacing_seconds: int = 2,
    ) -> tuple[PreparedAnalysisFrame, ...]: ...


class FrameHealthLike(Protocol):
    def observe(
        self,
        frame: PreparedAnalysisFrame,
        *,
        monotonic_now: float,
    ) -> FrameHealthTransition | None: ...

    def confirm_reconnect(
        self,
        frame: PreparedAnalysisFrame,
        *,
        monotonic_now: float,
    ) -> FrameHealthTransition | None: ...

    def source_failed(
        self,
        *,
        monotonic_now: float,
    ) -> FrameHealthTransition | None: ...


class ReviewSchedulerLike(Protocol):
    def poll(self) -> ReviewCompletion | None: ...

    def try_submit(
        self,
        frames: tuple[PreparedAnalysisFrame, ...],
        *,
        monotonic_now: float,
        urgent: bool = False,
    ) -> object: ...

    def close(self) -> None: ...


@dataclass(frozen=True)
class VisualWorkerHealth:
    state: Literal["healthy", "degraded", "reconnecting"]
    code: str
    accepted_frames: int = 0
    skipped_frames: int = 0
    reconnects: int = 0


class VisualWorker:
    def __init__(
        self,
        *,
        stream_factory: Callable[[], Iterator[CapturedFrame]],
        frame_policy: FramePolicyLike | VisionFramePolicy,
        frame_ring: FrameRingLike | AnalysisFrameRing,
        frame_health: FrameHealthLike | VisualFrameHealthMonitor,
        review_scheduler: ReviewSchedulerLike | VisualReviewScheduler,
        monotonic: Callable[[], float] = time.monotonic,
        on_frame_health: Callable[[FrameHealthTransition], None] | None = None,
        on_review_completion: Callable[[ReviewCompletion], None] | None = None,
    ) -> None:
        self._stream_factory = stream_factory
        self._frame_policy = frame_policy
        self._frame_ring = frame_ring
        self._frame_health = frame_health
        self._review_scheduler = review_scheduler
        self._monotonic = monotonic
        self._on_frame_health = on_frame_health or (lambda _transition: None)
        self._on_review_completion = (
            on_review_completion or (lambda _completion: None)
        )
        self._health = VisualWorkerHealth(state="degraded", code="not_started")
        self._last_monotonic: float | None = None
        self._next_sample_at: float | None = None
        self._next_review_at: float | None = None
        self._reconnect_requested = False
        self._confirm_next_frame = False
        self._frame_incident_open = False

    def health(self) -> VisualWorkerHealth:
        return self._health

    def run_frame(
        self,
        frame: CapturedFrame,
        *,
        monotonic_now: float,
    ) -> PreparedAnalysisFrame | None:
        self._require_monotonic(monotonic_now)
        completion = self._review_scheduler.poll()
        if completion is not None:
            self._on_review_completion(completion)

        if (
            self._next_sample_at is not None
            and monotonic_now < self._next_sample_at
        ):
            self._health = replace(
                self._health,
                skipped_frames=self._health.skipped_frames + 1,
            )
            return None
        self._next_sample_at = monotonic_now + SAMPLE_INTERVAL_SECONDS

        try:
            prepared = self._frame_policy.prepare(frame)
        except Exception:
            self._health = VisualWorkerHealth(
                state="degraded",
                code="frame_policy_failed",
                accepted_frames=self._health.accepted_frames,
                skipped_frames=self._health.skipped_frames + 1,
                reconnects=self._health.reconnects,
            )
            return None

        if self._confirm_next_frame:
            transition = self._frame_health.confirm_reconnect(
                prepared,
                monotonic_now=monotonic_now,
            )
            self._confirm_next_frame = False
        else:
            transition = self._frame_health.observe(
                prepared,
                monotonic_now=monotonic_now,
            )
        self._handle_frame_transition(transition)
        self._frame_ring.add(prepared)
        self._health = replace(
            self._health,
            accepted_frames=self._health.accepted_frames + 1,
        )
        if not self._frame_incident_open and not self._reconnect_requested:
            self._health = replace(self._health, state="healthy", code="ok")

        if self._next_review_at is None:
            self._next_review_at = monotonic_now + REVIEW_INTERVAL_SECONDS
        elif monotonic_now >= self._next_review_at:
            review_frames = self._frame_ring.select_review_frames(
                count=4,
                spacing_seconds=2,
            )
            self._review_scheduler.try_submit(
                review_frames,
                monotonic_now=monotonic_now,
            )
            self._next_review_at = monotonic_now + REVIEW_INTERVAL_SECONDS
        return prepared

    def run(self, stop_event: StopEvent) -> None:
        backoff_index = 0
        iterator: Iterator[CapturedFrame] | None = None
        try:
            while not stop_event.is_set():
                intentional_reconnect = False
                try:
                    iterator = iter(self._stream_factory())
                    for frame in iterator:
                        if stop_event.is_set():
                            break
                        self.run_frame(
                            frame,
                            monotonic_now=self._monotonic(),
                        )
                        backoff_index = 0
                        if self._reconnect_requested:
                            self._reconnect_requested = False
                            self._confirm_next_frame = True
                            intentional_reconnect = True
                            self._health = replace(
                                self._health,
                                reconnects=self._health.reconnects + 1,
                            )
                            break
                    else:
                        if not stop_event.is_set():
                            raise FrameSourceUnavailable(
                                "frame_source_unavailable"
                            )
                except Exception:
                    if stop_event.is_set():
                        break
                    transition = self._frame_health.source_failed(
                        monotonic_now=self._monotonic()
                    )
                    self._handle_frame_transition(transition)
                    self._health = VisualWorkerHealth(
                        state="degraded",
                        code="frame_source_unavailable",
                        accepted_frames=self._health.accepted_frames,
                        skipped_frames=self._health.skipped_frames,
                        reconnects=self._health.reconnects,
                    )
                finally:
                    self._close_iterator(iterator)
                    iterator = None

                if stop_event.is_set():
                    break
                if intentional_reconnect:
                    continue
                delay = RECONNECT_BACKOFF_SECONDS[
                    min(backoff_index, len(RECONNECT_BACKOFF_SECONDS) - 1)
                ]
                backoff_index += 1
                if stop_event.wait(delay):
                    break
        finally:
            self._close_iterator(iterator)
            self._review_scheduler.close()

    def _handle_frame_transition(
        self,
        transition: FrameHealthTransition | None,
    ) -> None:
        if transition is None:
            return
        self._on_frame_health(transition)
        if transition.code is FrameHealthCode.RECONNECT_REQUIRED:
            self._reconnect_requested = True
            self._health = replace(
                self._health,
                state="reconnecting",
                code=transition.code.value,
            )
        elif transition.code in {
            FrameHealthCode.FRAME_FROZEN,
            FrameHealthCode.SOURCE_OFFLINE,
        }:
            self._frame_incident_open = True
            self._health = replace(
                self._health,
                state="degraded",
                code=transition.code.value,
            )
        elif transition.code is FrameHealthCode.RECOVERED:
            self._frame_incident_open = False
            self._health = replace(self._health, state="healthy", code="ok")

    def _require_monotonic(self, value: float) -> None:
        if value < 0:
            raise ValueError("monotonic time must be non-negative")
        if self._last_monotonic is not None and value < self._last_monotonic:
            raise ValueError("monotonic time cannot decrease")
        self._last_monotonic = value

    @staticmethod
    def _close_iterator(iterator: Iterator[CapturedFrame] | None) -> None:
        if iterator is None:
            return
        close = getattr(iterator, "close", None)
        if close is not None:
            close()
