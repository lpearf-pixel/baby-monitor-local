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


def _open_ready_and_recover(
    store: VisualRiskEventStore,
    *,
    event_id: str,
    opened_at: datetime,
    evidence_updated_at: datetime,
    recovered_at: datetime,
    recovery_notification_state: str = "delivered",
) -> None:
    store.open_event(
        event_id=event_id,
        risk_kind=VisualRiskKind.FACE_NOT_VISIBLE,
        opened_at=opened_at,
        confidence=0.82,
        rule_version="visual-risk-v1",
    )
    store.begin_evidence(
        event_id=event_id,
        started_at=opened_at,
        capture_deadline=opened_at + timedelta(seconds=30),
        snapshot_key=SNAPSHOT_KEY,
        frame_count=6,
    )
    store.complete_evidence(
        event_id=event_id,
        completed_at=evidence_updated_at,
        clip_key=CLIP_KEY,
        frame_count=21,
    )
    store.recover_event(
        risk_kind=VisualRiskKind.FACE_NOT_VISIBLE,
        recovered_at=recovered_at,
        confidence=0.91,
        rule_version="visual-risk-v1",
    )
    if recovery_notification_state != "missing":
        notification = store.queue_notification(
            notification_id=f"retention-{event_id}",
            event_id=event_id,
            stage="risk_recovered",
            queued_at=recovered_at,
        )
        if recovery_notification_state == "delivered":
            store.record_notification_result(
                notification_id=notification.notification_id,
                attempted_at=recovered_at + timedelta(microseconds=1),
                result_code="ok",
            )


def test_retention_projection_uses_later_terminal_time_and_protects_pending(
    tmp_path: Path,
) -> None:
    store = VisualRiskEventStore(tmp_path / "events.sqlite3")
    store.migrate()
    _open_ready_and_recover(
        store,
        event_id="old-by-recovery",
        opened_at=NOW,
        evidence_updated_at=NOW + timedelta(seconds=30),
        recovered_at=NOW + timedelta(seconds=40),
    )
    _open_ready_and_recover(
        store,
        event_id="old-by-evidence",
        opened_at=NOW + timedelta(minutes=1),
        evidence_updated_at=NOW + timedelta(minutes=3),
        recovered_at=NOW + timedelta(minutes=2),
    )
    _open_ready_and_recover(
        store,
        event_id="pending-notification",
        opened_at=NOW + timedelta(minutes=4),
        evidence_updated_at=NOW + timedelta(minutes=5),
        recovered_at=NOW + timedelta(minutes=6),
        recovery_notification_state="pending",
    )
    _open_ready_and_recover(
        store,
        event_id="missing-recovery-notification",
        opened_at=NOW + timedelta(minutes=6, seconds=10),
        evidence_updated_at=NOW + timedelta(minutes=6, seconds=40),
        recovered_at=NOW + timedelta(minutes=6, seconds=50),
        recovery_notification_state="missing",
    )
    store.open_event(
        event_id="open-collecting",
        risk_kind=VisualRiskKind.PRONE_CANDIDATE,
        opened_at=NOW + timedelta(minutes=7),
        confidence=0.83,
        rule_version="visual-risk-v1",
    )
    store.begin_evidence(
        event_id="open-collecting",
        started_at=NOW + timedelta(minutes=7),
        capture_deadline=NOW + timedelta(minutes=8),
        snapshot_key=SNAPSHOT_KEY,
        frame_count=4,
    )

    entries = store.list_evidence_retention_entries()

    assert [entry.event_id for entry in entries] == [
        "old-by-recovery",
        "old-by-evidence",
        "pending-notification",
        "missing-recovery-notification",
        "open-collecting",
    ]
    assert [entry.retention_at for entry in entries] == [
        NOW + timedelta(seconds=40),
        NOW + timedelta(minutes=3),
        NOW + timedelta(minutes=6),
        NOW + timedelta(minutes=6, seconds=50),
        NOW + timedelta(minutes=7),
    ]
    assert [entry.deletable for entry in entries] == [
        True,
        True,
        False,
        False,
        False,
    ]


def test_guarded_retention_delete_preserves_event_audit_and_notification(
    tmp_path: Path,
) -> None:
    store = VisualRiskEventStore(tmp_path / "events.sqlite3")
    store.migrate()
    store.open_event(
        event_id="retained-event",
        risk_kind=VisualRiskKind.FACE_NOT_VISIBLE,
        opened_at=NOW,
        confidence=0.82,
        rule_version="visual-risk-v1",
    )
    store.record_intervention(
        intervention_id="retained-intervention",
        observed_at=NOW + timedelta(seconds=5),
        confidence=0.9,
        rule_version="visual-risk-v1",
    )
    store.begin_evidence(
        event_id="retained-event",
        started_at=NOW,
        capture_deadline=NOW + timedelta(seconds=30),
        snapshot_key=SNAPSHOT_KEY,
        frame_count=6,
    )
    store.complete_evidence(
        event_id="retained-event",
        completed_at=NOW + timedelta(seconds=30),
        clip_key=CLIP_KEY,
        frame_count=21,
    )
    store.recover_event(
        risk_kind=VisualRiskKind.FACE_NOT_VISIBLE,
        recovered_at=NOW + timedelta(seconds=40),
        confidence=0.91,
        rule_version="visual-risk-v1",
    )
    notification = store.queue_notification(
        notification_id="retained-notification",
        event_id="retained-event",
        stage="risk_recovered",
        queued_at=NOW + timedelta(seconds=40),
    )
    store.record_notification_result(
        notification_id=notification.notification_id,
        attempted_at=NOW + timedelta(seconds=41),
        result_code="ok",
    )

    entry = next(
        entry
        for entry in store.list_evidence_retention_entries()
        if entry.event_id == "retained-event"
    )
    file_deletes: list[str] = []
    assert store.delete_evidence_if_eligible(
        entry,
        lambda: file_deletes.append(entry.event_id) or 123,
    ) == 123

    assert store.get_evidence("retained-event") is None
    assert file_deletes == ["retained-event"]
    assert store.get_event("retained-event") is not None
    assert store.intervention_event_ids("retained-intervention") == (
        "retained-event",
    )
    assert store.get_notification("retained-notification") is not None
    assert store.delete_evidence_if_eligible(entry, lambda: 456) is None
    assert store.integrity_check() == "ok"


def test_guarded_retention_delete_refuses_pending_notification(
    tmp_path: Path,
) -> None:
    store = VisualRiskEventStore(tmp_path / "events.sqlite3")
    store.migrate()
    _open_ready_and_recover(
        store,
        event_id="pending-event",
        opened_at=NOW,
        evidence_updated_at=NOW + timedelta(seconds=30),
        recovered_at=NOW + timedelta(seconds=40),
        recovery_notification_state="pending",
    )
    entry = next(
        entry
        for entry in store.list_evidence_retention_entries()
        if entry.event_id == "pending-event"
    )
    callback_called = False

    def delete_files() -> int:
        nonlocal callback_called
        callback_called = True
        return 123

    assert store.delete_evidence_if_eligible(entry, delete_files) is None
    assert callback_called is False
    assert store.get_evidence("pending-event") is not None


def test_guarded_retention_delete_rechecks_exact_selected_record(
    tmp_path: Path,
) -> None:
    store = VisualRiskEventStore(tmp_path / "events.sqlite3")
    store.migrate()
    _open_ready_and_recover(
        store,
        event_id="changed-selection",
        opened_at=NOW,
        evidence_updated_at=NOW + timedelta(seconds=30),
        recovered_at=NOW + timedelta(seconds=40),
    )
    entry = store.list_evidence_retention_entries()[0]
    stale_entry = entry.model_copy(
        update={"retention_at": entry.retention_at - timedelta(microseconds=1)}
    )
    callback_called = False

    def delete_files() -> int:
        nonlocal callback_called
        callback_called = True
        return 123

    assert store.delete_evidence_if_eligible(stale_entry, delete_files) is None
    assert callback_called is False
    assert store.get_evidence("changed-selection") is not None


def test_guarded_retention_delete_holds_writer_lock_during_file_callback(
    tmp_path: Path,
) -> None:
    database = tmp_path / "events.sqlite3"
    store = VisualRiskEventStore(database)
    store.migrate()
    _open_ready_and_recover(
        store,
        event_id="locked-delete",
        opened_at=NOW,
        evidence_updated_at=NOW + timedelta(seconds=30),
        recovered_at=NOW + timedelta(seconds=40),
    )
    entry = store.list_evidence_retention_entries()[0]

    def delete_files() -> int:
        with sqlite3.connect(database, timeout=0) as competing_writer:
            with pytest.raises(sqlite3.OperationalError, match="locked"):
                competing_writer.execute(
                    "UPDATE visual_risk_events SET confidence = confidence"
                )
        return 123

    assert store.delete_evidence_if_eligible(entry, delete_files) == 123
    assert store.get_evidence("locked-delete") is None


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
