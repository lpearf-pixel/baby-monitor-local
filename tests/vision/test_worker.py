from __future__ import annotations

from dataclasses import FrozenInstanceError, fields
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from services.stream.frame_source import CapturedFrame, FrameSourceUnavailable
from services.vision.frame_health import (
    FrameHealthCode,
    FrameHealthState,
    FrameHealthTransition,
)
from services.vision.frame_policy import PreparedAnalysisFrame
from services.vision.review_scheduler import ReviewScheduleDecision
from packages.contracts.vision import (
    RealtimeCandidateKind,
    RealtimeCandidateTransition,
    RealtimeCandidateTransitionKind,
    RealtimeObservation,
)
from services.vision.realtime_load import (
    RealtimeLoadStatus,
    RealtimeLoadTransitionCode,
)


NOW = datetime(2026, 8, 5, 12, 0, tzinfo=UTC)


def captured(seconds: float, payload: bytes | None = None) -> CapturedFrame:
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
    def __init__(
        self,
        *,
        request_reconnect: bool = False,
        observed_transition: FrameHealthTransition | None = None,
    ) -> None:
        self.request_reconnect = request_reconnect
        self.observed_transition = observed_transition
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
        transition = self.observed_transition
        self.observed_transition = None
        return transition

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


class RecordingRealtimeAnalyzer:
    def __init__(self) -> None:
        self.calls: list[PreparedAnalysisFrame] = []
        self.model_state = "available"
        self._health_transition: str | None = None

    def analyze(
        self,
        frame: PreparedAnalysisFrame,
        *,
        monotonic_now: float,
    ) -> RealtimeObservation:
        self.calls.append(frame)
        return RealtimeObservation(
            motion_ratio=0.0,
            scene_quality="usable",
            pose_count=1,
            face_count=1,
            bed_subject_track="inside",
            adult_track="absent",
            head_face_state="visible",
            processing_ms=10.0,
        )

    def pop_health_transition(self) -> str | None:
        transition = self._health_transition
        self._health_transition = None
        return transition


class RecordingCandidateMachine:
    def __init__(self, *, open_at: float | None = None) -> None:
        self.open_at = open_at
        self.calls: list[float] = []

    def evaluate(
        self,
        observation: RealtimeObservation,
        *,
        monotonic_now: float,
    ) -> tuple[RealtimeCandidateTransition, ...]:
        self.calls.append(monotonic_now)
        if self.open_at is not None and abs(monotonic_now - self.open_at) < 1e-6:
            return (
                RealtimeCandidateTransition(
                    transition_kind=RealtimeCandidateTransitionKind.WATCH_OPENED,
                    candidate_kind=RealtimeCandidateKind.POSSIBLE_FACE_OBSTRUCTION,
                    monotonic_at=monotonic_now,
                ),
            )
        return ()


class FixedLoadController:
    def __init__(
        self,
        target_fps: int = 5,
        transition_code: RealtimeLoadTransitionCode | None = None,
        *,
        sample_count: int = 1,
        p50_ms: float = 10.0,
        p95_ms: float = 10.0,
        max_ms: float = 10.0,
    ) -> None:
        self.target_fps = target_fps
        self.transition_code = transition_code
        self.sample_count = sample_count
        self.p50_ms = p50_ms
        self.p95_ms = p95_ms
        self.max_ms = max_ms

    def observe(
        self,
        processing_ms: float,
        *,
        monotonic_now: float,
    ) -> RealtimeLoadStatus:
        transition = self.transition_code
        self.transition_code = None
        return RealtimeLoadStatus(
            target_fps=self.target_fps,
            sample_count=self.sample_count,
            p50_ms=self.p50_ms,
            p95_ms=self.p95_ms,
            max_ms=self.max_ms,
            transition_code=transition,
        )


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
    frame_health_callback: object | None = None,
    realtime_analyzer: object | None = None,
    candidate_machine: object | None = None,
    load_controller: object | None = None,
    candidate_transitions: list[RealtimeCandidateTransition] | None = None,
    realtime_health: list[str] | None = None,
    realtime_status: object | None = None,
    safe_frame_callback: object | None = None,
):
    module = worker_module()
    transition_sink = transitions if transitions is not None else []
    realtime_status_kwargs = (
        {"on_realtime_status": realtime_status}
        if realtime_status is not None
        else {}
    )
    return module.VisualWorker(
        stream_factory=stream_factory or (lambda: iter(())),
        frame_policy=policy or RecordingPolicy(),
        frame_ring=ring or RecordingRing(),
        frame_health=health or RecordingHealth(),
        review_scheduler=scheduler or RecordingScheduler(),
        monotonic=monotonic or (lambda: 0.0),
        on_frame_health=frame_health_callback or transition_sink.append,
        on_safe_frame=safe_frame_callback,
        realtime_analyzer=realtime_analyzer,
        candidate_machine=candidate_machine,
        load_controller=load_controller,
        on_realtime_candidate=(
            candidate_transitions.append
            if candidate_transitions is not None
            else None
        ),
        on_realtime_health=(
            realtime_health.append if realtime_health is not None else None
        ),
        **realtime_status_kwargs,
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


def test_realtime_worker_analyzes_five_fps_but_samples_ring_every_two_seconds() -> None:
    policy = RecordingPolicy()
    ring = RecordingRing()
    scheduler = RecordingScheduler()
    analyzer = RecordingRealtimeAnalyzer()
    candidates = RecordingCandidateMachine()
    worker = build_worker(
        policy=policy,
        ring=ring,
        scheduler=scheduler,
        realtime_analyzer=analyzer,
        candidate_machine=candidates,
        load_controller=FixedLoadController(),
    )

    for tick in range(51):
        second = tick / 5
        worker.run_frame(captured(second), monotonic_now=second)

    assert len(analyzer.calls) == 51
    assert len(ring.frames) == 6
    assert [round((item.captured_at - NOW).total_seconds()) for item in ring.frames] == [
        0,
        2,
        4,
        6,
        8,
        10,
    ]
    assert [(call[1], call[2]) for call in scheduler.calls] == [(10.0, False)]


def test_semantic_watch_uses_warm_ring_for_immediate_urgent_review() -> None:
    ring = RecordingRing()
    scheduler = RecordingScheduler()
    analyzer = RecordingRealtimeAnalyzer()
    transitions: list[RealtimeCandidateTransition] = []
    worker = build_worker(
        ring=ring,
        scheduler=scheduler,
        realtime_analyzer=analyzer,
        candidate_machine=RecordingCandidateMachine(open_at=6.0),
        load_controller=FixedLoadController(),
        candidate_transitions=transitions,
    )

    for tick in range(31):
        second = tick / 5
        worker.run_frame(captured(second), monotonic_now=second)

    assert len(transitions) == 1
    assert scheduler.calls[-1][1:] == (6.0, True)
    assert len(scheduler.calls[-1][0]) == 4


def test_load_shedding_preserves_every_frame_health_observation() -> None:
    health = RecordingHealth()
    analyzer = RecordingRealtimeAnalyzer()
    worker = build_worker(
        health=health,
        realtime_analyzer=analyzer,
        candidate_machine=RecordingCandidateMachine(),
        load_controller=FixedLoadController(target_fps=1),
    )

    for tick in range(6):
        second = tick / 5
        worker.run_frame(captured(second), monotonic_now=second)

    assert len(health.observe_calls) == 6
    assert len(analyzer.calls) == 2
    assert worker.health().realtime_fps == 1


def test_model_and_load_health_transitions_are_published_and_redacted() -> None:
    analyzer = RecordingRealtimeAnalyzer()
    analyzer.model_state = "degraded"
    analyzer._health_transition = "realtime_model_degraded"
    health_codes: list[str] = []
    worker = build_worker(
        realtime_analyzer=analyzer,
        candidate_machine=RecordingCandidateMachine(),
        load_controller=FixedLoadController(
            target_fps=3,
            transition_code=RealtimeLoadTransitionCode.DEGRADED,
        ),
        realtime_health=health_codes,
    )

    worker.run_frame(captured(0), monotonic_now=0.0)

    assert health_codes == ["realtime_model_degraded", "realtime_degraded"]
    assert worker.health().realtime_model_state == "degraded"
    assert worker.health().realtime_fps == 3
    assert "/private" not in repr(worker.health())


def test_successful_analysis_publishes_only_redacted_aggregate_status() -> None:
    snapshots: list[object] = []
    worker = build_worker(
        realtime_analyzer=RecordingRealtimeAnalyzer(),
        candidate_machine=RecordingCandidateMachine(),
        load_controller=FixedLoadController(
            target_fps=3,
            sample_count=7,
            p50_ms=101.125,
            p95_ms=202.25,
            max_ms=303.375,
        ),
        realtime_status=snapshots.append,
    )

    worker.run_frame(captured(0), monotonic_now=0.0)

    assert len(snapshots) == 1
    snapshot = snapshots[0]
    assert {field.name for field in fields(snapshot)} == {
        "realtime_fps",
        "sample_count",
        "processing_p50_ms",
        "processing_p95_ms",
        "processing_max_ms",
        "realtime_model_state",
    }
    assert snapshot.realtime_fps == 3
    assert snapshot.sample_count == 7
    assert snapshot.processing_p50_ms == 101.125
    assert snapshot.processing_p95_ms == 202.25
    assert snapshot.processing_max_ms == 303.375
    assert snapshot.realtime_model_state == "available"
    with pytest.raises(FrozenInstanceError):
        snapshot.sample_count = 8


def test_status_callback_failure_does_not_interrupt_candidate_analysis() -> None:
    health_codes: list[str] = []
    candidates = RecordingCandidateMachine()

    def fail_status(_snapshot: object) -> None:
        raise RuntimeError("/private/household/status.json")

    worker = build_worker(
        realtime_analyzer=RecordingRealtimeAnalyzer(),
        candidate_machine=candidates,
        load_controller=FixedLoadController(),
        realtime_health=health_codes,
        realtime_status=fail_status,
    )

    worker.run_frame(captured(0), monotonic_now=0.0)

    assert candidates.calls == [0.0]
    assert health_codes == ["realtime_status_write_failed"]
    assert worker.health().code == "ok"
    assert "/private" not in repr(worker.health())


def test_three_fps_deadline_carries_forward_on_five_fps_input() -> None:
    analyzer = RecordingRealtimeAnalyzer()
    worker = build_worker(
        realtime_analyzer=analyzer,
        candidate_machine=RecordingCandidateMachine(),
        load_controller=FixedLoadController(target_fps=3),
    )

    for tick in range(11):
        second = tick / 5
        worker.run_frame(captured(second), monotonic_now=second)

    assert len(analyzer.calls) == 7


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


def test_safe_frame_callback_runs_only_after_prepared_frame_enters_ring() -> None:
    ring = RecordingRing()
    received: list[tuple[PreparedAnalysisFrame, int]] = []

    def record(frame: PreparedAnalysisFrame) -> None:
        received.append((frame, len(ring.frames)))

    worker = build_worker(ring=ring, safe_frame_callback=record)

    prepared = worker.run_frame(captured(0), monotonic_now=0.0)

    assert prepared is not None
    assert received == [(prepared, 1)]


def test_safe_frame_callback_failure_does_not_remove_frame_or_escape() -> None:
    ring = RecordingRing()

    def fail(_frame: PreparedAnalysisFrame) -> None:
        raise RuntimeError("token at /private/family/evidence")

    worker = build_worker(ring=ring, safe_frame_callback=fail)

    prepared = worker.run_frame(captured(0), monotonic_now=0.0)

    assert prepared is not None
    assert ring.frames == [prepared]
    assert worker.health().state == "degraded"
    assert worker.health().code == "safe_frame_callback_failed"
    assert "/private" not in repr(worker.health())


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


def test_frame_health_callback_failure_does_not_interrupt_capture_state() -> None:
    offline = FrameHealthTransition(
        state=FrameHealthState.DEGRADED,
        code=FrameHealthCode.SOURCE_OFFLINE,
        duration_seconds=60.0,
    )
    health = RecordingHealth(observed_transition=offline)
    ring = RecordingRing()

    def fail_callback(_transition: FrameHealthTransition) -> None:
        raise RuntimeError("secret at /private/household/visual-health.sqlite3")

    worker = build_worker(
        health=health,
        ring=ring,
        frame_health_callback=fail_callback,
    )

    prepared = worker.run_frame(captured(0), monotonic_now=0.0)

    assert prepared is not None
    assert len(ring.frames) == 1
    assert worker.health().state == "degraded"
    assert worker.health().code == "source_offline"
    assert "/private" not in repr(worker.health())


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
