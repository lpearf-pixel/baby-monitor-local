from __future__ import annotations

import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from pydantic import ValidationError

from packages.contracts.vision import VisualRiskKind
from services.storage.visual_risk import (
    StoredVisualRiskEvent,
    VisualRiskEventStore,
)


NOW = datetime(2026, 8, 11, 12, 0, tzinfo=UTC)


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
