from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from packages.contracts.vision import VisualReview
from services.vision.frame_policy import PreparedAnalysisFrame
from services.vision.review_scheduler import ReviewCompletionCode
from services.vision.recent_observation import (
    RecentObservationStatus,
    RecentObservationStatusWriter,
    read_recent_observation_status,
)


NOW = datetime(2026, 10, 9, 12, 0, tzinfo=UTC)


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


def frame(seconds: int) -> PreparedAnalysisFrame:
    return PreparedAnalysisFrame(
        jpeg=b"synthetic",
        captured_at=NOW + timedelta(seconds=seconds),
        width=960,
        height=540,
        crop_box=(0, 0, 960, 540),
    )


def frames() -> tuple[PreparedAnalysisFrame, ...]:
    return tuple(frame(value) for value in (0, 2, 4, 6))


def test_success_publishes_closed_recent_visibility_state(tmp_path: Path) -> None:
    status = RecentObservationStatus(
        writer=RecentObservationStatusWriter(tmp_path / "visual-observation.json"),
        wall_clock=lambda: NOW + timedelta(seconds=7),
        worker_generation="generation-a",
    )

    status.record_request(frames(), monotonic_now=0.0)
    status.record_completion(
        code=ReviewCompletionCode.OK,
        review=review("partial"),
        monotonic_now=7.0,
        late=False,
    )

    payload = read_recent_observation_status(
        tmp_path / "visual-observation.json",
        now=NOW + timedelta(seconds=8),
    )
    assert payload["state"] == "available"
    assert payload["baby_visibility"] == "partial"
    assert payload["freshness"] == "fresh"
    assert payload["input_frame_captured_at"] == (NOW + timedelta(seconds=6)).isoformat()
    assert payload["result_completed_at"] == (NOW + timedelta(seconds=7)).isoformat()


def test_failed_or_timed_out_completion_cannot_reuse_previous_visibility(tmp_path: Path) -> None:
    path = tmp_path / "visual-observation.json"
    status = RecentObservationStatus(
        writer=RecentObservationStatusWriter(path),
        wall_clock=lambda: NOW,
        worker_generation="generation-a",
    )
    status.record_request(frames(), monotonic_now=0.0)
    status.record_completion(
        code=ReviewCompletionCode.OK,
        review=review(),
        monotonic_now=0.0,
        late=False,
    )
    status.record_request(frames(), monotonic_now=1.0)
    status.record_timeout(monotonic_now=1.0)
    payload = read_recent_observation_status(path, now=NOW + timedelta(seconds=1))
    assert payload["state"] == "failed"
    assert payload["reason_code"] == "review_timeout"
    assert payload["baby_visibility"] is None


def test_old_result_becomes_stale_without_becoming_not_visible(tmp_path: Path) -> None:
    path = tmp_path / "visual-observation.json"
    status = RecentObservationStatus(
        writer=RecentObservationStatusWriter(path),
        wall_clock=lambda: NOW,
        worker_generation="generation-a",
    )
    status.record_request(frames(), monotonic_now=0.0)
    status.record_completion(
        code=ReviewCompletionCode.OK,
        review=review(),
        monotonic_now=0.0,
        late=False,
    )
    payload = read_recent_observation_status(path, now=NOW + timedelta(seconds=37))
    assert payload["state"] == "stale"
    assert payload["freshness"] == "stale"
    assert payload["baby_visibility"] == "visible"


def test_restart_marker_rejects_late_previous_generation_result(tmp_path: Path) -> None:
    path = tmp_path / "visual-observation.json"
    writer = RecentObservationStatusWriter(path)
    old = RecentObservationStatus(writer=writer, wall_clock=lambda: NOW, worker_generation="old")
    old.mark_worker_restarted(at=NOW)
    new = RecentObservationStatus(writer=writer, wall_clock=lambda: NOW, worker_generation="new")
    new.mark_worker_restarted(at=NOW + timedelta(seconds=1))
    old.record_request(frames(), monotonic_now=2.0)
    old.record_completion(
        code=ReviewCompletionCode.OK,
        review=review(),
        monotonic_now=2.0,
        late=False,
    )
    payload = read_recent_observation_status(path, now=NOW + timedelta(seconds=2))
    assert payload["state"] == "worker_restarted"
    assert payload["baby_visibility"] is None


def test_repeated_older_result_cannot_refresh_capture_time(tmp_path: Path) -> None:
    path = tmp_path / "visual-observation.json"
    status = RecentObservationStatus(
        writer=RecentObservationStatusWriter(path),
        wall_clock=lambda: NOW + timedelta(seconds=10),
        worker_generation="generation-a",
    )
    status.record_request(frames(), monotonic_now=0.0)
    status.record_completion(code=ReviewCompletionCode.OK, review=review(), monotonic_now=1.0)
    first = read_recent_observation_status(path, now=NOW + timedelta(seconds=10))
    old_frames = tuple(frame(value) for value in (-8, -6, -4, -2))
    status.record_request(old_frames, monotonic_now=2.0)
    status.record_completion(code=ReviewCompletionCode.OK, review=review("partial"), monotonic_now=3.0)
    second = read_recent_observation_status(path, now=NOW + timedelta(seconds=10))
    assert second == first


def test_invalid_state_combinations_are_rejected(tmp_path: Path) -> None:
    writer = RecentObservationStatusWriter(tmp_path / "visual-observation.json")
    with pytest.raises(ValueError, match="closed recent observation state"):
        writer.write(
            {
                "schema_version": 1,
                "state": "failed",
                "baby_visibility": "visible",
                "input_frame_captured_at": None,
                "result_completed_at": None,
                "freshness": "unknown",
                "reason_code": "review_failed",
                "written_at": NOW.isoformat(),
                "worker_generation": "generation-a",
            }
        )
