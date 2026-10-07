from __future__ import annotations

from concurrent.futures import Future
from datetime import UTC, datetime, timedelta
from pathlib import Path

from packages.contracts.vision import RiskTransition, VisualReview
from services.vision.frame_policy import PreparedAnalysisFrame
from services.vision.review_scheduler import (
    ReviewCompletionCode,
    VisualReviewScheduler,
)
from services.vision.semantic_observation import (
    SemanticObservationSession,
    write_semantic_observation_report,
)


NOW = datetime(2026, 10, 8, 12, 0, tzinfo=UTC)


def review(visibility: str = "visible") -> VisualReview:
    return VisualReview.model_validate(
        {
            "baby_visibility": visibility,
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


def frames(*seconds: int) -> tuple[PreparedAnalysisFrame, ...]:
    return tuple(
        PreparedAnalysisFrame(
            jpeg=f"frame-{second}".encode(),
            captured_at=NOW + timedelta(seconds=second),
            width=960,
            height=540,
            crop_box=(0, 0, 960, 540),
        )
        for second in seconds
    )


class Executor:
    def __init__(self) -> None:
        self.future: Future[VisualReview] = Future()

    def submit(self, function: object, value: tuple[PreparedAnalysisFrame, ...]) -> Future[VisualReview]:
        return self.future


def test_disabled_session_has_no_observation_and_no_report() -> None:
    session = SemanticObservationSession(enabled=False)

    session.record_request(frames(0, 2, 4, 6), monotonic_now=0.0)

    assert session.snapshot() == {"enabled": False, "state": "disabled"}


def test_session_counts_visibility_latency_and_transitions_only_after_start() -> None:
    session = SemanticObservationSession(
        enabled=True,
        deployment_version="abcdef1",
        wall_clock=lambda: NOW,
    )
    session.record_request(frames(0, 2, 4, 6), monotonic_now=0.0)
    session.record_transition(object(), monotonic_now=0.0)
    session.start(monotonic_now=10.0)
    session.record_request(frames(0, 2, 4, 6), monotonic_now=11.0)
    session.record_completion(
        code=ReviewCompletionCode.OK,
        review=review(),
        monotonic_now=11.25,
    )
    session.record_request(frames(0, 2, 4, 6), monotonic_now=20.0)
    session.record_completion(
        code=ReviewCompletionCode.OK,
        review=review("partial"),
        monotonic_now=20.5,
    )
    session.record_transition(object(), monotonic_now=21.0)

    snapshot = session.stop(monotonic_now=22.0)

    assert snapshot["deployment_version"] == "abcdef1"
    assert snapshot["request_count"] == 2
    assert snapshot["success_count"] == 2
    assert snapshot["baby_visibility"] == {
        "visible": 1,
        "partial": 1,
        "not_visible": 0,
        "uncertain": 0,
    }
    assert snapshot["fresh_frame_requests"] == 2
    assert snapshot["distinct_timestamp_requests"] == 2
    assert snapshot["latency_ms"] == {"p50": 250.0, "p95": 500.0, "max": 500.0}
    assert snapshot["guardian_transition_count"] == 1
    assert snapshot["bridge_failures"] is None


def test_duplicate_frames_are_not_counted_as_fresh() -> None:
    session = SemanticObservationSession(enabled=True)
    session.start(monotonic_now=0.0)
    session.record_request(frames(0, 0, 2, 4), monotonic_now=1.0)

    snapshot = session.stop(monotonic_now=2.0)

    assert snapshot["request_count"] == 1
    assert snapshot["distinct_timestamp_requests"] == 0
    assert snapshot["fresh_frame_requests"] == 0


def test_timeout_and_late_completion_are_separate_and_stop_freezes_state() -> None:
    session = SemanticObservationSession(enabled=True, max_duration_seconds=60)
    session.start(monotonic_now=0.0)
    session.record_request(frames(0, 2, 4, 6), monotonic_now=1.0)
    session.record_timeout(monotonic_now=22.0)
    session.record_completion(
        code=ReviewCompletionCode.OK,
        review=review(),
        monotonic_now=23.0,
        late=True,
    )
    stopped = session.stop(monotonic_now=24.0)
    session.record_request(frames(0, 2, 4, 6), monotonic_now=25.0)

    assert stopped["timeout_count"] == 1
    assert stopped["late_response_count"] == 1
    assert stopped["success_count"] == 0
    assert stopped["state"] == "stopped"
    assert session.snapshot() == stopped


def test_session_auto_expires_at_ten_minutes_and_uses_unknown_for_bridge() -> None:
    session = SemanticObservationSession(enabled=True, max_duration_seconds=600)
    session.start(monotonic_now=100.0)
    snapshot = session.tick(monotonic_now=700.0)

    assert snapshot["state"] == "expired"
    assert snapshot["bridge_failures"] is None
    assert snapshot["bridge_reconnects"] is None
    assert snapshot["bridge_recoveries"] is None


def test_report_is_bounded_private_and_rejects_non_opaque_version(tmp_path: Path) -> None:
    import pytest

    with pytest.raises(ValueError, match="opaque"):
        SemanticObservationSession(enabled=True, deployment_version="private-path")

    session = SemanticObservationSession(enabled=True, deployment_version="1ff8cd8")
    session.start(monotonic_now=0.0)
    report = tmp_path / "semantic-observation.json"
    write_semantic_observation_report(report, session.stop(monotonic_now=1.0))

    assert report.stat().st_mode & 0o777 == 0o600
    text = report.read_text()
    assert "/private" not in text
    assert "baby_visibility" in text


def test_scheduler_reports_request_completion_and_timeout_to_session() -> None:
    executor = Executor()
    clock = iter([2.0, 3.0, 22.0, 23.0])
    session = SemanticObservationSession(enabled=True, max_duration_seconds=60)
    session.start(monotonic_now=0.0)
    scheduler = VisualReviewScheduler(
        reviewer=lambda _frames: review(),
        executor=executor,
        observer=session,
        monotonic=lambda: next(clock),
    )

    scheduler.try_submit(frames(0, 2, 4, 6), monotonic_now=1.0)
    assert scheduler.poll() is None
    assert scheduler.poll() is None
    assert scheduler.poll() is None
    executor.future.set_result(review())
    completion = scheduler.poll()

    assert completion is not None
    assert session.snapshot()["request_count"] == 1
    assert session.snapshot()["timeout_count"] == 1
    assert session.snapshot()["late_response_count"] == 1
