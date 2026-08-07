from __future__ import annotations

import time
from collections.abc import Callable, Iterator
from dataclasses import dataclass, replace
from typing import Literal, Protocol

from packages.contracts.vision import (
    RealtimeCandidateTransition,
    RealtimeCandidateTransitionKind,
    RealtimeObservation,
)
from services.stream.frame_source import CapturedFrame
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
from services.vision.realtime_status import RealtimeVisualMetricsSnapshot


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


class RealtimeAnalyzerLike(Protocol):
    model_state: str

    def analyze(
        self,
        frame: PreparedAnalysisFrame,
        *,
        monotonic_now: float,
    ) -> RealtimeObservation: ...

    def pop_health_transition(self) -> str | None: ...


class CandidateMachineLike(Protocol):
    def evaluate(
        self,
        observation: RealtimeObservation,
        *,
        monotonic_now: float,
    ) -> tuple[RealtimeCandidateTransition, ...]: ...


class LoadStatusLike(Protocol):
    target_fps: Literal[1, 3, 5]
    sample_count: int
    p50_ms: float
    p95_ms: float
    max_ms: float
    transition_code: object | None


class LoadControllerLike(Protocol):
    def observe(
        self,
        processing_ms: float,
        *,
        monotonic_now: float,
    ) -> LoadStatusLike: ...


@dataclass(frozen=True)
class VisualWorkerHealth:
    state: Literal["healthy", "degraded", "reconnecting"]
    code: str
    accepted_frames: int = 0
    skipped_frames: int = 0
    reconnects: int = 0
    realtime_model_state: Literal["disabled", "available", "degraded"] = (
        "disabled"
    )
    realtime_fps: Literal[1, 3, 5] | None = None


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
        realtime_analyzer: RealtimeAnalyzerLike | None = None,
        candidate_machine: CandidateMachineLike | None = None,
        load_controller: LoadControllerLike | None = None,
        on_realtime_candidate: Callable[[RealtimeCandidateTransition], None]
        | None = None,
        on_realtime_health: Callable[[str], None] | None = None,
        on_realtime_status: Callable[[RealtimeVisualMetricsSnapshot], None]
        | None = None,
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
        self._realtime_analyzer = realtime_analyzer
        self._candidate_machine = candidate_machine
        self._load_controller = load_controller
        self._on_realtime_candidate = (
            on_realtime_candidate or (lambda _transition: None)
        )
        self._on_realtime_health = on_realtime_health or (lambda _code: None)
        self._on_realtime_status = on_realtime_status or (lambda _status: None)
        self._realtime_enabled = all(
            component is not None
            for component in (realtime_analyzer, candidate_machine, load_controller)
        )
        if any(
            component is not None
            for component in (realtime_analyzer, candidate_machine, load_controller)
        ) and not self._realtime_enabled:
            raise ValueError("realtime visual components must be configured together")
        initial_model_state = (
            getattr(realtime_analyzer, "model_state", "degraded")
            if self._realtime_enabled
            else "disabled"
        )
        self._health = VisualWorkerHealth(
            state="degraded",
            code="not_started",
            realtime_model_state=initial_model_state,
            realtime_fps=5 if self._realtime_enabled else None,
        )
        self._last_monotonic: float | None = None
        self._next_sample_at: float | None = None
        self._next_analysis_at: float | None = None
        self._next_ring_at: float | None = None
        self._target_realtime_fps: Literal[1, 3, 5] = 5
        self._next_review_at: float | None = None
        self._reconnect_requested = False
        self._confirm_next_frame = False
        self._frame_incident_open = False
        self._urgent_pending = False

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
            not self._realtime_enabled
            and self._next_sample_at is not None
            and monotonic_now + 1e-9 < self._next_sample_at
        ):
            self._health = replace(
                self._health,
                skipped_frames=self._health.skipped_frames + 1,
            )
            return None
        if not self._realtime_enabled:
            self._next_sample_at = monotonic_now + SAMPLE_INTERVAL_SECONDS

        try:
            prepared = self._frame_policy.prepare(frame)
        except Exception:
            self._health = replace(
                self._health,
                state="degraded",
                code="frame_policy_failed",
                skipped_frames=self._health.skipped_frames + 1,
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
        ring_added = False
        if not self._realtime_enabled or (
            self._next_ring_at is None or monotonic_now + 1e-9 >= self._next_ring_at
        ):
            self._frame_ring.add(prepared)
            ring_added = True
            if self._realtime_enabled:
                self._next_ring_at = monotonic_now + SAMPLE_INTERVAL_SECONDS
        self._health = replace(
            self._health,
            accepted_frames=self._health.accepted_frames + 1,
        )
        if not self._frame_incident_open and not self._reconnect_requested:
            self._health = replace(self._health, state="healthy", code="ok")

        analysis_due = (
            self._realtime_enabled
            and (
                self._next_analysis_at is None
                or monotonic_now + 1e-9 >= self._next_analysis_at
            )
        )
        if analysis_due:
            assert self._realtime_analyzer is not None
            assert self._candidate_machine is not None
            assert self._load_controller is not None
            try:
                observation = self._realtime_analyzer.analyze(
                    prepared,
                    monotonic_now=monotonic_now,
                )
                load_status = self._load_controller.observe(
                    observation.processing_ms,
                    monotonic_now=monotonic_now,
                )
                previous_target_fps = self._target_realtime_fps
                self._target_realtime_fps = load_status.target_fps
                realtime_model_state = getattr(
                    self._realtime_analyzer,
                    "model_state",
                    "degraded",
                )
                self._health = replace(
                    self._health,
                    realtime_model_state=realtime_model_state,
                    realtime_fps=self._target_realtime_fps,
                )
                self._publish_realtime_health(
                    self._realtime_analyzer.pop_health_transition()
                )
                transition_code = getattr(load_status, "transition_code", None)
                self._publish_realtime_health(
                    getattr(transition_code, "value", transition_code)
                )
                try:
                    self._on_realtime_status(
                        RealtimeVisualMetricsSnapshot(
                            realtime_fps=self._target_realtime_fps,
                            sample_count=load_status.sample_count,
                            processing_p50_ms=load_status.p50_ms,
                            processing_p95_ms=load_status.p95_ms,
                            processing_max_ms=load_status.max_ms,
                            realtime_model_state=realtime_model_state,
                        )
                    )
                except Exception:
                    self._publish_realtime_health(
                        "realtime_status_write_failed"
                    )
                self._schedule_next_analysis(
                    monotonic_now,
                    target_changed=(
                        previous_target_fps != self._target_realtime_fps
                    ),
                )
                candidate_transitions = self._candidate_machine.evaluate(
                    observation,
                    monotonic_now=monotonic_now,
                )
            except Exception:
                candidate_transitions = ()
                self._next_analysis_at = (
                    monotonic_now + 1.0 / self._target_realtime_fps
                )
                self._health = replace(
                    self._health,
                    state="degraded",
                    code="realtime_analysis_failed",
                )
            for candidate_transition in candidate_transitions:
                try:
                    self._on_realtime_candidate(candidate_transition)
                except Exception:
                    self._health = replace(
                        self._health,
                        state="degraded",
                        code="realtime_callback_failed",
                    )
                if (
                    candidate_transition.transition_kind
                    is RealtimeCandidateTransitionKind.WATCH_OPENED
                ):
                    self._submit_urgent(monotonic_now)

        if self._urgent_pending and ring_added:
            self._submit_urgent(monotonic_now)

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

    def _schedule_next_analysis(
        self,
        monotonic_now: float,
        *,
        target_changed: bool,
    ) -> None:
        interval = 1.0 / self._target_realtime_fps
        if self._next_analysis_at is None or target_changed:
            self._next_analysis_at = monotonic_now + interval
            return
        next_at = self._next_analysis_at + interval
        while next_at <= monotonic_now + 1e-9:
            next_at += interval
        self._next_analysis_at = next_at

    def _publish_realtime_health(self, code: object | None) -> None:
        if not isinstance(code, str) or not code:
            return
        try:
            self._on_realtime_health(code)
        except Exception:
            self._health = replace(
                self._health,
                state="degraded",
                code="realtime_health_callback_failed",
            )

    def _submit_urgent(self, monotonic_now: float) -> None:
        review_frames = self._frame_ring.select_review_frames(
            count=4,
            spacing_seconds=2,
        )
        if len(review_frames) != 4:
            self._urgent_pending = True
            return
        self._urgent_pending = False
        self._review_scheduler.try_submit(
            review_frames,
            monotonic_now=monotonic_now,
            urgent=True,
        )

    def run(self, stop_event: StopEvent) -> None:
        backoff_index = 0
        iterator: Iterator[CapturedFrame] | None = None
        try:
            while not stop_event.is_set():
                intentional_reconnect = False
                failure_kind: Literal["source", "internal"] | None = None
                try:
                    iterator = iter(self._stream_factory())
                except Exception:
                    failure_kind = "source"
                else:
                    while not stop_event.is_set():
                        try:
                            frame = next(iterator)
                        except StopIteration:
                            if not stop_event.is_set():
                                failure_kind = "source"
                            break
                        except Exception:
                            failure_kind = "source"
                            break
                        try:
                            self.run_frame(
                                frame,
                                monotonic_now=self._monotonic(),
                            )
                        except Exception:
                            failure_kind = "internal"
                            break
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
                finally:
                    self._close_iterator(iterator)
                    iterator = None

                if stop_event.is_set():
                    break
                if intentional_reconnect:
                    continue
                if failure_kind == "source":
                    transition = self._frame_health.source_failed(
                        monotonic_now=self._monotonic()
                    )
                    self._handle_frame_transition(transition)
                    self._health = replace(
                        self._health,
                        state="degraded",
                        code="frame_source_unavailable",
                    )
                elif failure_kind == "internal":
                    self._health = replace(
                        self._health,
                        state="degraded",
                        code="worker_internal_error",
                    )
                else:
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
            try:
                close()
            except Exception:
                return
