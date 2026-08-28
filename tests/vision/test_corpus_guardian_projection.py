from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

from packages.contracts.vision import VisualReview
from services.vision.corpus_replay import (
    GuardianReplayReview,
    GuardianReplayProjector,
)


NOW = datetime(2026, 8, 28, 12, 0, tzinfo=UTC)


def review(*, hidden: bool) -> VisualReview:
    return VisualReview.model_validate(
        {
            "baby_visibility": "visible",
            "face_visibility": "not_visible" if hidden else "clear",
            "posture": "supine",
            "bed_state": "inside",
            "adult_presence": "absent",
            "image_quality": "usable",
            "risk": "high" if hidden else "none",
            "reason_codes": ["face_not_visible"] if hidden else [],
            "confidence": 0.9,
        }
    )


def sample(seconds: int, *, hidden: bool) -> GuardianReplayReview:
    return GuardianReplayReview(
        observed_at=NOW + timedelta(seconds=seconds),
        review=review(hidden=hidden),
    )


def test_synthetic_profile_uses_only_ephemeral_store_and_dashboard_query(
    tmp_path: Path,
) -> None:
    database = tmp_path / "isolated" / "events.sqlite3"

    result = GuardianReplayProjector(database_path=database).run(
        semantic_profile="synthetic_test",
        reviews=(sample(0, hidden=True), sample(10, hidden=True)),
    )

    assert result.status == "PASS"
    assert result.reason == "ok"
    assert result.semantic_profile == "synthetic_test"
    assert result.transition_counts == {
        "alert_opened.face_not_visible": 1,
        "watch_started.face_not_visible": 1,
    }
    assert result.event_counts == {"face_not_visible.open": 1}
    assert result.dashboard_event_count == 1
    assert result.dashboard_open_event_count == 1
    assert result.production_state_touched is False
    assert result.notification_dispatch_attempted is False
    assert result.evidence_persisted is False
    assert database.is_file()


def test_confirmation_dedup_and_recovery_share_one_event(tmp_path: Path) -> None:
    result = GuardianReplayProjector(
        database_path=tmp_path / "events.sqlite3"
    ).run(
        semantic_profile="synthetic_test",
        reviews=(
            sample(0, hidden=True),
            sample(10, hidden=True),
            sample(20, hidden=True),
            sample(30, hidden=False),
            sample(40, hidden=False),
        ),
    )

    assert result.status == "PASS"
    assert result.transition_counts["alert_opened.face_not_visible"] == 1
    assert result.transition_counts["recovered.face_not_visible"] == 1
    assert result.event_counts == {"face_not_visible.recovered": 1}
    assert result.dashboard_event_count == 1
    assert result.dashboard_open_event_count == 0


def test_realtime_only_never_invents_guardian_events(tmp_path: Path) -> None:
    database = tmp_path / "events.sqlite3"

    result = GuardianReplayProjector(database_path=database).run(
        semantic_profile="realtime_only",
    )

    assert result.status == "PASS"
    assert result.reason == "ok"
    assert result.transition_counts == {}
    assert result.event_counts == {}
    assert result.dashboard_event_count == 0
    assert not database.exists()


def test_semantic_existing_skips_before_store_when_reviewer_unavailable(
    tmp_path: Path,
) -> None:
    database = tmp_path / "events.sqlite3"

    result = GuardianReplayProjector(database_path=database).run(
        semantic_profile="semantic_existing",
    )

    assert result.status == "SKIP"
    assert result.reason == "semantic_reviewer_unavailable"
    assert result.semantic_profile == "semantic_existing"
    assert not database.exists()


class Provider:
    def __init__(self, values: tuple[GuardianReplayReview, ...]) -> None:
        self.values = values
        self.closed = False

    def collect(self) -> tuple[GuardianReplayReview, ...]:
        return self.values

    def close(self) -> None:
        self.closed = True


def test_semantic_existing_closes_provider_on_success(tmp_path: Path) -> None:
    provider = Provider((sample(0, hidden=True), sample(10, hidden=True)))

    result = GuardianReplayProjector(
        database_path=tmp_path / "events.sqlite3",
        semantic_provider=provider,
    ).run(semantic_profile="semantic_existing")

    assert result.status == "PASS"
    assert result.semantic_profile == "semantic_existing"
    assert result.event_counts == {"face_not_visible.open": 1}
    assert provider.closed is True


def test_existing_database_is_refused_before_read_or_write(tmp_path: Path) -> None:
    database = tmp_path / "events.sqlite3"
    database.write_bytes(b"private-existing-state")

    result = GuardianReplayProjector(database_path=database).run(
        semantic_profile="synthetic_test",
        reviews=(sample(0, hidden=True), sample(10, hidden=True)),
    )

    assert result.status == "FAIL"
    assert result.reason == "guardian_store_not_empty"
    assert database.read_bytes() == b"private-existing-state"


def test_invalid_review_order_fails_closed_without_raw_review(tmp_path: Path) -> None:
    result = GuardianReplayProjector(
        database_path=tmp_path / "events.sqlite3"
    ).run(
        semantic_profile="synthetic_test",
        reviews=(sample(10, hidden=True), sample(0, hidden=True)),
    )

    assert result.status == "FAIL"
    assert result.reason == "guardian_review_sequence_invalid"
    assert "face_visibility" not in repr(result)
