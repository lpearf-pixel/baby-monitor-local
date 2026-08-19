from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from packages.contracts.events import EventSeverity
from services.audio.events import AudioEventPipeline
from services.audio.state import (
    AUDIO_RULE_VERSION,
    AudioAlertState,
    AudioStateTransition,
    AudioTransitionKind,
)
from services.events.store import EventStore


NOW = datetime(2026, 8, 17, 13, tzinfo=UTC)


def transition(kind: AudioTransitionKind) -> AudioStateTransition:
    states = {
        AudioTransitionKind.OPENED: (AudioAlertState.CANDIDATE, AudioAlertState.NORMAL),
        AudioTransitionKind.ESCALATED: (AudioAlertState.NORMAL, AudioAlertState.HIGH),
        AudioTransitionKind.MERGED_ESCALATION: (AudioAlertState.IDLE, AudioAlertState.HIGH),
        AudioTransitionKind.RECOVERED: (AudioAlertState.HIGH, AudioAlertState.IDLE),
    }
    previous, current = states[kind]
    return AudioStateTransition(
        kind=kind,
        previous_state=previous,
        current_state=current,
        severity=(
            EventSeverity.INFO
            if kind is AudioTransitionKind.RECOVERED
            else EventSeverity.NORMAL
            if kind is AudioTransitionKind.OPENED
            else EventSeverity.HIGH
        ),
        occurred_at=NOW,
        confidence=None if kind is AudioTransitionKind.RECOVERED else 0.91,
    )


def pipeline(tmp_path: Path) -> tuple[EventStore, AudioEventPipeline]:
    store = EventStore(tmp_path / "events.sqlite3")
    store.migrate()
    return store, AudioEventPipeline(store=store)


def test_open_transition_atomically_queues_fixed_text_event(tmp_path: Path) -> None:
    store, sink = pipeline(tmp_path)

    event = sink.handle(transition(AudioTransitionKind.OPENED))

    assert event.kind == "audio_cry_candidate"
    assert event.summary == "持续哭声候选"
    assert event.severity is EventSeverity.NORMAL
    assert event.confidence == 0.91
    assert event.rule_version == AUDIO_RULE_VERSION
    assert event.metadata == {"transition": "opened"}
    assert store.get_event(event.event_id) == event
    pending = store.list_pending_event_notifications()
    assert [(item.event_id, item.stage) for item in pending] == [
        (event.event_id, "audio_opened")
    ]


def test_duplicate_transition_is_idempotent_for_event_and_outbox(tmp_path: Path) -> None:
    store, sink = pipeline(tmp_path)
    item = transition(AudioTransitionKind.ESCALATED)

    first = sink.handle(item)
    second = sink.handle(item)

    assert second == first
    assert store.count_events(kind="audio_cry_candidate") == 1
    assert len(store.list_pending_event_notifications()) == 1


def test_each_transition_uses_closed_summary_stage_and_scalar_metadata(
    tmp_path: Path,
) -> None:
    store, sink = pipeline(tmp_path)

    results = [
        sink.handle(transition(kind))
        for kind in (
            AudioTransitionKind.OPENED,
            AudioTransitionKind.ESCALATED,
            AudioTransitionKind.MERGED_ESCALATION,
            AudioTransitionKind.RECOVERED,
        )
    ]

    assert [item.summary for item in results] == [
        "持续哭声候选",
        "哭声候选升级",
        "重复哭声候选合并升级",
        "哭声候选已恢复",
    ]
    assert [item.metadata for item in results] == [
        {"transition": "opened"},
        {"transition": "escalated"},
        {"transition": "merged_escalation"},
        {"transition": "recovered"},
    ]
    assert [item.stage for item in store.list_pending_event_notifications()] == [
        "audio_opened",
        "audio_escalated",
        "audio_merged",
        "audio_recovered",
    ]
