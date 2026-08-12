from __future__ import annotations

import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from pydantic import ValidationError

from packages.contracts.vision import VisualRiskKind
from services.storage.visual_risk import (
    StoredVisualRiskEvent,
    StoredVisualRiskEvidence,
    StoredVisualRiskNotification,
    VisualRiskEventStore,
)


NOW = datetime(2026, 8, 11, 12, 0, tzinfo=UTC)
DIGEST = "a" * 64
SNAPSHOT_KEY = f"visual-risk/{DIGEST}/snapshot.jpg"
CLIP_KEY = f"visual-risk/{DIGEST}/clip.webp"


def test_event_contract_rejects_naive_or_incoherent_recovery() -> None:
    with pytest.raises(ValidationError, match="timezone-aware"):
        StoredVisualRiskEvent(
            event_id="event-1",
            risk_kind=VisualRiskKind.FACE_NOT_VISIBLE,
            state="open",
            severity="high",
            opened_at=datetime(2026, 8, 11, 12, 0),
            updated_at=NOW,
            confidence=0.82,
            rule_version="visual-risk-v1",
        )

    with pytest.raises(ValidationError, match="recovered_at"):
        StoredVisualRiskEvent(
            event_id="event-1",
            risk_kind=VisualRiskKind.FACE_NOT_VISIBLE,
            state="recovered",
            severity="high",
            opened_at=NOW,
            updated_at=NOW,
            confidence=0.82,
            rule_version="visual-risk-v1",
        )


def test_migration_is_repeatable_and_enforces_one_open_event_per_risk(
    tmp_path: Path,
) -> None:
    database = tmp_path / "events.sqlite3"
    store = VisualRiskEventStore(database)

    store.migrate()
    store.migrate()

    assert store.integrity_check() == "ok"
    with sqlite3.connect(database) as connection:
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute(
            """
            INSERT INTO visual_risk_events (
                event_id, risk_kind, state, severity, opened_at, updated_at,
                recovered_at, confidence, rule_version,
                adult_intervention_count
            ) VALUES (?, ?, 'open', 'high', ?, ?, NULL, ?, ?, 0)
            """,
            (
                "event-1",
                "face_not_visible",
                NOW.isoformat(),
                NOW.isoformat(),
                0.82,
                "visual-risk-v1",
            ),
        )
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute(
                """
                INSERT INTO visual_risk_events (
                    event_id, risk_kind, state, severity, opened_at,
                    updated_at, recovered_at, confidence, rule_version,
                    adult_intervention_count
                ) VALUES (?, ?, 'open', 'high', ?, ?, NULL, ?, ?, 0)
                """,
                (
                    "event-2",
                    "face_not_visible",
                    NOW.isoformat(),
                    NOW.isoformat(),
                    0.85,
                    "visual-risk-v1",
                ),
            )


def test_open_recover_and_list_three_independent_risks(tmp_path: Path) -> None:
    store = VisualRiskEventStore(tmp_path / "events.sqlite3")
    store.migrate()

    face = store.open_event(
        event_id="event-face",
        risk_kind=VisualRiskKind.FACE_NOT_VISIBLE,
        opened_at=NOW,
        confidence=0.82,
        rule_version="visual-risk-v1",
    )
    prone = store.open_event(
        event_id="event-prone",
        risk_kind=VisualRiskKind.PRONE_CANDIDATE,
        opened_at=NOW + timedelta(seconds=1),
        confidence=0.84,
        rule_version="visual-risk-v1",
    )
    outside = store.open_event(
        event_id="event-outside",
        risk_kind=VisualRiskKind.OUTSIDE_CANDIDATE,
        opened_at=NOW + timedelta(seconds=2),
        confidence=0.86,
        rule_version="visual-risk-v1",
    )
    repeated = store.open_event(
        event_id="event-face-duplicate",
        risk_kind=VisualRiskKind.FACE_NOT_VISIBLE,
        opened_at=NOW + timedelta(seconds=3),
        confidence=0.99,
        rule_version="visual-risk-v1",
    )

    recovered = store.recover_event(
        risk_kind=VisualRiskKind.FACE_NOT_VISIBLE,
        recovered_at=NOW + timedelta(seconds=10),
        confidence=0.91,
        rule_version="visual-risk-v1",
    )

    assert repeated == face
    assert recovered is not None
    assert recovered.event_id == "event-face"
    assert recovered.state == "recovered"
    assert recovered.recovered_at == NOW + timedelta(seconds=10)
    assert store.load_open() == (outside, prone)
    assert [event.event_id for event in store.list_events()] == [
        "event-face",
        "event-outside",
        "event-prone",
    ]


def test_recovery_before_open_is_rejected_without_mutation(tmp_path: Path) -> None:
    store = VisualRiskEventStore(tmp_path / "events.sqlite3")
    store.migrate()
    opened = store.open_event(
        event_id="event-face",
        risk_kind=VisualRiskKind.FACE_NOT_VISIBLE,
        opened_at=NOW,
        confidence=0.82,
        rule_version="visual-risk-v1",
    )

    with pytest.raises(ValueError, match="precede"):
        store.recover_event(
            risk_kind=VisualRiskKind.FACE_NOT_VISIBLE,
            recovered_at=NOW - timedelta(seconds=1),
            confidence=0.91,
            rule_version="visual-risk-v1",
        )

    assert store.load_open() == (opened,)


def test_intervention_is_idempotent_and_links_every_open_event(
    tmp_path: Path,
) -> None:
    store = VisualRiskEventStore(tmp_path / "events.sqlite3")
    store.migrate()
    for event_id, risk_kind in (
        ("event-face", VisualRiskKind.FACE_NOT_VISIBLE),
        ("event-prone", VisualRiskKind.PRONE_CANDIDATE),
    ):
        store.open_event(
            event_id=event_id,
            risk_kind=risk_kind,
            opened_at=NOW,
            confidence=0.82,
            rule_version="visual-risk-v1",
        )

    first = store.record_intervention(
        intervention_id="intervention-1",
        observed_at=NOW + timedelta(seconds=5),
        confidence=0.9,
        rule_version="visual-risk-v1",
    )
    repeated = store.record_intervention(
        intervention_id="intervention-1",
        observed_at=NOW + timedelta(seconds=5),
        confidence=0.9,
        rule_version="visual-risk-v1",
    )

    assert repeated == first
    assert store.intervention_event_ids("intervention-1") == (
        "event-face",
        "event-prone",
    )
    assert [event.adult_intervention_count for event in store.load_open()] == [1, 1]


def test_intervention_without_open_risk_is_still_retained(tmp_path: Path) -> None:
    store = VisualRiskEventStore(tmp_path / "events.sqlite3")
    store.migrate()

    intervention = store.record_intervention(
        intervention_id="intervention-standalone",
        observed_at=NOW,
        confidence=0.77,
        rule_version="visual-risk-v1",
    )

    assert intervention.intervention_id == "intervention-standalone"
    assert store.intervention_event_ids(intervention.intervention_id) == ()


def open_face_event(store: VisualRiskEventStore) -> None:
    store.open_event(
        event_id="event-face",
        risk_kind=VisualRiskKind.FACE_NOT_VISIBLE,
        opened_at=NOW,
        confidence=0.82,
        rule_version="visual-risk-v1",
    )


def test_evidence_contract_rejects_unsafe_keys_and_oversized_frame_count() -> None:
    base = {
        "event_id": "event-face",
        "state": "ready",
        "started_at": NOW,
        "updated_at": NOW + timedelta(seconds=30),
        "capture_deadline": NOW + timedelta(seconds=30),
        "snapshot_key": SNAPSHOT_KEY,
        "clip_key": CLIP_KEY,
        "frame_count": 16,
    }

    with pytest.raises(ValidationError):
        StoredVisualRiskEvidence(**{**base, "clip_key": "../clip.webp"})
    with pytest.raises(ValidationError):
        StoredVisualRiskEvidence(**{**base, "frame_count": 22})


def test_evidence_lifecycle_is_idempotent_and_ready_is_terminal(
    tmp_path: Path,
) -> None:
    store = VisualRiskEventStore(tmp_path / "events.sqlite3")
    store.migrate()
    store.migrate()
    open_face_event(store)

    started = store.begin_evidence(
        event_id="event-face",
        started_at=NOW,
        capture_deadline=NOW + timedelta(seconds=30),
        snapshot_key=SNAPSHOT_KEY,
        frame_count=6,
    )
    repeated = store.begin_evidence(
        event_id="event-face",
        started_at=NOW + timedelta(seconds=1),
        capture_deadline=NOW + timedelta(seconds=31),
        snapshot_key=f"visual-risk/{'b' * 64}/snapshot.jpg",
        frame_count=1,
    )
    ready = store.complete_evidence(
        event_id="event-face",
        completed_at=NOW + timedelta(seconds=30),
        clip_key=CLIP_KEY,
        frame_count=21,
    )

    assert repeated == started
    assert ready.state == "ready"
    assert ready.frame_count == 21
    assert store.get_evidence("event-face") == ready
    with pytest.raises(ValueError, match="collecting"):
        store.fail_evidence(
            event_id="event-face",
            failed_at=NOW + timedelta(seconds=31),
            failure_code="media_write_failed",
            frame_count=21,
        )


def test_evidence_requires_existing_event_and_fixed_failure_code(
    tmp_path: Path,
) -> None:
    store = VisualRiskEventStore(tmp_path / "events.sqlite3")
    store.migrate()

    with pytest.raises(sqlite3.IntegrityError):
        store.begin_evidence(
            event_id="missing-event",
            started_at=NOW,
            capture_deadline=NOW + timedelta(seconds=30),
            snapshot_key=None,
            frame_count=0,
        )

    open_face_event(store)
    store.begin_evidence(
        event_id="event-face",
        started_at=NOW,
        capture_deadline=NOW + timedelta(seconds=30),
        snapshot_key=None,
        frame_count=0,
    )
    with pytest.raises(ValueError):
        store.fail_evidence(
            event_id="event-face",
            failed_at=NOW,
            failure_code="/private/family/error",
            frame_count=0,
        )


def test_restart_interrupts_only_collecting_evidence(tmp_path: Path) -> None:
    store = VisualRiskEventStore(tmp_path / "events.sqlite3")
    store.migrate()
    open_face_event(store)
    store.begin_evidence(
        event_id="event-face",
        started_at=NOW,
        capture_deadline=NOW + timedelta(seconds=30),
        snapshot_key=SNAPSHOT_KEY,
        frame_count=5,
    )

    interrupted = store.interrupt_collecting_evidence(
        interrupted_at=NOW + timedelta(seconds=8)
    )

    assert len(interrupted) == 1
    assert interrupted[0].state == "interrupted"
    assert interrupted[0].failure_code == "worker_restarted"
    assert store.interrupt_collecting_evidence(
        interrupted_at=NOW + timedelta(seconds=9)
    ) == ()


def test_notification_contract_rejects_naive_time_and_incoherent_retry() -> None:
    base = {
        "notification_id": "notification-open",
        "event_id": "event-face",
        "stage": "risk_opened",
        "state": "pending",
        "queued_at": NOW,
        "updated_at": NOW,
        "next_attempt_at": NOW,
        "dispatch_count": 0,
    }

    with pytest.raises(ValidationError, match="timezone-aware"):
        StoredVisualRiskNotification(
            **{**base, "queued_at": datetime(2026, 8, 11, 12, 0)}
        )
    with pytest.raises(ValidationError, match="terminal notification"):
        StoredVisualRiskNotification(
            **{**base, "state": "delivered", "result_code": None}
        )


def test_notification_queue_is_idempotent_by_event_stage_and_intervention(
    tmp_path: Path,
) -> None:
    store = VisualRiskEventStore(tmp_path / "events.sqlite3")
    store.migrate()
    open_face_event(store)

    opened = store.queue_notification(
        notification_id="notification-open",
        event_id="event-face",
        stage="risk_opened",
        queued_at=NOW,
    )
    duplicate = store.queue_notification(
        notification_id="notification-duplicate",
        event_id="event-face",
        stage="risk_opened",
        queued_at=NOW + timedelta(seconds=1),
    )
    intervention = store.queue_notification(
        notification_id="notification-intervention",
        event_id="event-face",
        stage="adult_intervention",
        queued_at=NOW + timedelta(seconds=2),
        intervention_id="intervention-1",
    )

    assert duplicate == opened
    assert intervention.notification_id == "notification-intervention"
    assert store.next_pending_notification(NOW) == opened
    assert store.next_pending_notification(NOW + timedelta(seconds=2)) == opened


def test_notification_results_are_bounded_and_terminal_rows_are_immutable(
    tmp_path: Path,
) -> None:
    store = VisualRiskEventStore(tmp_path / "events.sqlite3")
    store.migrate()
    open_face_event(store)
    pending = store.queue_notification(
        notification_id="notification-open",
        event_id="event-face",
        stage="risk_opened",
        queued_at=NOW,
    )

    first_retry = store.record_notification_result(
        notification_id=pending.notification_id,
        attempted_at=NOW,
        result_code="ntfy_unavailable",
        retry_at=NOW + timedelta(seconds=5),
    )
    second_retry = store.record_notification_result(
        notification_id=pending.notification_id,
        attempted_at=NOW + timedelta(seconds=5),
        result_code="ntfy_unavailable",
        retry_at=NOW + timedelta(seconds=35),
    )
    exhausted = store.record_notification_result(
        notification_id=pending.notification_id,
        attempted_at=NOW + timedelta(seconds=35),
        result_code="ntfy_unavailable",
        retry_at=NOW + timedelta(seconds=335),
    )
    repeated = store.record_notification_result(
        notification_id=pending.notification_id,
        attempted_at=NOW + timedelta(seconds=40),
        result_code="ok",
    )

    assert first_retry.state == "pending"
    assert first_retry.dispatch_count == 1
    assert second_retry.dispatch_count == 2
    assert exhausted.state == "rejected"
    assert exhausted.dispatch_count == 3
    assert exhausted.result_code == "retry_exhausted"
    assert repeated == exhausted
    assert store.next_pending_notification(NOW + timedelta(days=1)) is None


def test_notification_delivery_and_rejection_are_terminal(tmp_path: Path) -> None:
    store = VisualRiskEventStore(tmp_path / "events.sqlite3")
    store.migrate()
    open_face_event(store)
    delivered = store.queue_notification(
        notification_id="notification-open",
        event_id="event-face",
        stage="risk_opened",
        queued_at=NOW,
    )
    rejected = store.queue_notification(
        notification_id="notification-recovered",
        event_id="event-face",
        stage="risk_recovered",
        queued_at=NOW + timedelta(seconds=1),
    )

    delivered = store.record_notification_result(
        notification_id=delivered.notification_id,
        attempted_at=NOW + timedelta(seconds=2),
        result_code="ok",
    )
    rejected = store.record_notification_result(
        notification_id=rejected.notification_id,
        attempted_at=NOW + timedelta(seconds=3),
        result_code="ntfy_rejected",
    )

    assert delivered.state == "delivered"
    assert delivered.result_code == "ok"
    assert rejected.state == "rejected"
    assert rejected.result_code == "ntfy_rejected"
    assert rejected.dispatch_count == 1


def test_later_stage_waits_for_earlier_pending_stage_of_same_event(
    tmp_path: Path,
) -> None:
    store = VisualRiskEventStore(tmp_path / "events.sqlite3")
    store.migrate()
    open_face_event(store)
    opened = store.queue_notification(
        notification_id="notification-open",
        event_id="event-face",
        stage="risk_opened",
        queued_at=NOW,
    )
    store.record_notification_result(
        notification_id=opened.notification_id,
        attempted_at=NOW,
        result_code="ntfy_unavailable",
        retry_at=NOW + timedelta(seconds=5),
    )
    store.queue_notification(
        notification_id="notification-recovered",
        event_id="event-face",
        stage="risk_recovered",
        queued_at=NOW + timedelta(seconds=1),
    )

    assert store.next_pending_notification(NOW + timedelta(seconds=1)) is None
    assert store.next_pending_notification(
        NOW + timedelta(seconds=5)
    ).notification_id == "notification-open"
    store.record_notification_result(
        notification_id=opened.notification_id,
        attempted_at=NOW + timedelta(seconds=5),
        result_code="ok",
    )
    assert store.next_pending_notification(
        NOW + timedelta(seconds=5)
    ).notification_id == "notification-recovered"
