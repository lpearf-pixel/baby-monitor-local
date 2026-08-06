from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

from services.stream.frame_source import CapturedFrame, FrameSourceUnavailable
from services.vision.frame_health import (
    FrameHealthCode,
    FrameHealthState,
    FrameHealthTransition,
)
from services.vision.frame_policy import PreparedAnalysisFrame
from services.vision.review_scheduler import ReviewScheduleDecision


NOW = datetime(2026, 8, 5, 12, 0, tzinfo=UTC)


def captured(seconds: int, payload: bytes | None = None) -> CapturedFrame:
    return CapturedFrame(
        jpeg=payload if payload is not None else f"original-{seconds}".encode(),
        captured_at=NOW + timedelta(seconds=seconds),
        width=1280,
        height=720,
    )


class RecordingPolicy:
    def __init__(self, *, fail: bool = False) -> None:
        self.fail = fail
        self.calls: list[CapturedFrame] = []

    def prepare(self, frame: CapturedFrame) -> PreparedAnalysisFrame:
        self.calls.append(frame)
        if self.fail:
            raise RuntimeError("credential at /private/family/frame")
        return PreparedAnalysisFrame(
            jpeg=b"prepared-" + frame.jpeg,
            captured_at=frame.captured_at,
            width=960,
            height=540,
            crop_box=(0, 0, 960, 540),
        )


class RecordingRing:
    def __init__(self) -> None:
        self.frames: list[PreparedAnalysisFrame] = []

    def add(self, frame: PreparedAnalysisFrame) -> None:
        self.frames.append(frame)

    def select_review_frames(
        self,
        *,
        count: int,
        spacing_seconds: int,
    ) -> tuple[PreparedAnalysisFrame, ...]:
        assert count == 4
        assert spacing_seconds == 2
        if len(self.frames) < count:
            return ()
        return tuple(self.frames[-count:])


class RecordingHealth:
    def __init__(self, *, request_reconnect: bool = False) -> None:
        self.request_reconnect = request_reconnect
        self.observe_calls: list[PreparedAnalysisFrame] = []
        self.confirm_calls: list[PreparedAnalysisFrame] = []
        self.failure_times: list[float] = []

    def observe(
        self,
        frame: PreparedAnalysisFrame,
        *,
        monotonic_now: float,
    ) -> FrameHealthTransition | None:
        self.observe_calls.append(frame)
        if self.request_reconnect:
            self.request_reconnect = False
            return FrameHealthTransition(
                state=FrameHealthState.RECONNECTING,
                code=FrameHealthCode.RECONNECT_REQUIRED,
                duration_seconds=60.0,
            )
        return None

    def confirm_reconnect(
        self,
        frame: PreparedAnalysisFrame,
        *,
        monotonic_now: float,
    ) -> FrameHealthTransition | None:
        self.confirm_calls.append(frame)
        return None

    def source_failed(
        self,
        *,
        monotonic_now: float,
    ) -> FrameHealthTransition | None:
        self.failure_times.append(monotonic_now)
        return None


class RecordingScheduler:
    def __init__(self, *, decision: ReviewScheduleDecision = ReviewScheduleDecision.SUBMITTED) -> None:
        self.decision = decision
        self.calls: list[tuple[tuple[PreparedAnalysisFrame, ...], float, bool]] = []
        self.closed = False

    def poll(self) -> None:
        return None

    def try_submit(
        self,
        frames: tuple[PreparedAnalysisFrame, ...],
        *,
        monotonic_now: float,
        urgent: bool = False,
    ) -> ReviewScheduleDecision:
        self.calls.append((frames, monotonic_now, urgent))
        return self.decision

    def close(self) -> None:
        self.closed = True


class FakeStopEvent:
    def __init__(self) -> None:
        self.stopped = False
        self.waits: list[float] = []

    def is_set(self) -> bool:
        return self.stopped

    def wait(self, timeout: float) -> bool:
        self.waits.append(timeout)
        return self.stopped


class StopOnWaitEvent(FakeStopEvent):
    def wait(self, timeout: float) -> bool:
        self.waits.append(timeout)
        self.stopped = True
        return True


class ClosingIterator:
    def __init__(
        self,
        frames: list[CapturedFrame],
        *,
        stop_after: FakeStopEvent | None = None,
        failure: Exception | None = None,
    ) -> None:
        self.frames = iter(frames)
        self.stop_after = stop_after
        self.failure = failure
        self.closed = False

    def __iter__(self) -> "ClosingIterator":
        return self

    def __next__(self) -> CapturedFrame:
        try:
            return next(self.frames)
        except StopIteration:
            if self.stop_after is not None:
                self.stop_after.stopped = True
            if self.failure is not None:
                raise self.failure
            raise

    def close(self) -> None:
        self.closed = True


def worker_module():
    from services.vision import worker

    return worker


def build_worker(
    *,
    policy: RecordingPolicy | None = None,
    ring: RecordingRing | None = None,
    health: RecordingHealth | None = None,
    scheduler: RecordingScheduler | None = None,
    stream_factory: object | None = None,
    monotonic: object | None = None,
    transitions: list[FrameHealthTransition] | None = None,
):
    module = worker_module()
    transition_sink = transitions if transitions is not None else []
    return module.VisualWorker(
        stream_factory=stream_factory or (lambda: iter(())),
        frame_policy=policy or RecordingPolicy(),
        frame_ring=ring or RecordingRing(),
        frame_health=health or RecordingHealth(),
        review_scheduler=scheduler or RecordingScheduler(),
        monotonic=monotonic or (lambda: 0.0),
        on_frame_health=transition_sink.append,
    )


def test_worker_samples_every_two_seconds_and_reviews_first_at_ten() -> None:
    policy = RecordingPolicy()
    ring = RecordingRing()
    scheduler = RecordingScheduler()
    worker = build_worker(policy=policy, ring=ring, scheduler=scheduler)

    for second in range(10):
        worker.run_frame(captured(second), monotonic_now=float(second))

    assert len(ring.frames) == 5
    assert scheduler.calls == []

    worker.run_frame(captured(10), monotonic_now=10.0)

    assert len(ring.frames) == 6
    assert len(scheduler.calls) == 1
    submitted, submitted_at, urgent = scheduler.calls[0]
    assert [item.captured_at.second for item in submitted] == [4, 6, 8, 10]
    assert submitted_at == 10.0
    assert urgent is False


def test_only_prepared_frames_enter_ring_and_scheduler() -> None:
    ring = RecordingRing()
    scheduler = RecordingScheduler()
    worker = build_worker(ring=ring, scheduler=scheduler)

    for second in range(0, 11, 2):
        worker.run_frame(
            captured(second, payload=f"private-{second}".encode()),
            monotonic_now=float(second),
        )

    assert all(item.jpeg.startswith(b"prepared-") for item in ring.frames)
    assert all(item.jpeg.startswith(b"prepared-") for item in scheduler.calls[0][0])
    assert all(item.jpeg != f"private-{item.captured_at.second}".encode() for item in ring.frames)


def test_busy_reviews_do_not_block_capture_or_create_extra_attempts() -> None:
    ring = RecordingRing()
    scheduler = RecordingScheduler(decision=ReviewScheduleDecision.SKIPPED_BUSY)
    worker = build_worker(ring=ring, scheduler=scheduler)

    for second in range(0, 21, 2):
        worker.run_frame(captured(second), monotonic_now=float(second))

    assert len(ring.frames) == 11
    assert [call[1] for call in scheduler.calls] == [10.0, 20.0]


def test_policy_failure_degrades_without_leaking_exception() -> None:
    policy = RecordingPolicy(fail=True)
    worker = build_worker(policy=policy)

    assert worker.run_frame(captured(0), monotonic_now=0.0) is None

    health = worker.health()
    assert health.state == "degraded"
    assert health.code == "frame_policy_failed"
    assert "/private" not in repr(health)


def test_run_reconnects_after_failure_with_bounded_backoff() -> None:
    stop = FakeStopEvent()
    first = ClosingIterator(
        [],
        failure=FrameSourceUnavailable("frame_source_unavailable"),
    )
    second = ClosingIterator([captured(2)], stop_after=stop)
    streams = iter([first, second])
    ticks = iter([0.0, 2.0, 3.0])
    health = RecordingHealth()
    scheduler = RecordingScheduler()
    worker = build_worker(
        health=health,
        scheduler=scheduler,
        stream_factory=lambda: next(streams),
        monotonic=lambda: next(ticks),
    )

    worker.run(stop)

    assert health.failure_times == [0.0]
    assert stop.waits == [1.0]
    assert first.closed is True
    assert second.closed is True
    assert scheduler.closed is True


def test_reconnect_required_confirms_the_first_frame_from_new_stream() -> None:
    stop = FakeStopEvent()
    first = ClosingIterator([captured(0)])
    second = ClosingIterator([captured(2)], stop_after=stop)
    streams = iter([first, second])
    ticks = iter([0.0, 2.0, 3.0])
    health = RecordingHealth(request_reconnect=True)
    transitions: list[FrameHealthTransition] = []
    worker = build_worker(
        health=health,
        stream_factory=lambda: next(streams),
        monotonic=lambda: next(ticks),
        transitions=transitions,
    )

    worker.run(stop)

    assert len(health.observe_calls) == 1
    assert len(health.confirm_calls) == 1
    assert transitions[0].code is FrameHealthCode.RECONNECT_REQUIRED
    assert first.closed is True
    assert second.closed is True


def test_internal_worker_failure_is_not_reported_as_camera_offline() -> None:
    class BrokenHealth(RecordingHealth):
        def observe(
            self,
            frame: PreparedAnalysisFrame,
            *,
            monotonic_now: float,
        ) -> FrameHealthTransition | None:
            raise RuntimeError("credential at /private/family/internal")

    stop = StopOnWaitEvent()
    stream = ClosingIterator([captured(0)])
    health = BrokenHealth()
    ticks = iter([0.0, 0.0])
    worker = build_worker(
        health=health,
        stream_factory=lambda: stream,
        monotonic=lambda: next(ticks),
    )

    worker.run(stop)

    assert health.failure_times == []
    assert worker.health().code == "worker_internal_error"
    assert "/private" not in repr(worker.health())
    assert stream.closed is True


def test_worker_module_has_no_r3_or_r4_side_effect_imports() -> None:
    content = Path("services/vision/worker.py").read_text(encoding="utf-8")

    for forbidden in (
        "services.storage",
        "services.notifications",
        "apps.api",
        "ollama",
        "subprocess",
        "sqlite3",
    ):
        assert forbidden not in content
