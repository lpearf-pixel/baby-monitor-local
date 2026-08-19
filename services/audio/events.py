from __future__ import annotations

import hashlib

from packages.contracts.events import CandidateEvent
from services.audio.state import AudioStateTransition, AudioTransitionKind
from services.events.store import EventStore


_EVENT_KIND = "audio_cry_candidate"
_SUMMARIES = {
    AudioTransitionKind.OPENED: "持续哭声候选",
    AudioTransitionKind.ESCALATED: "哭声候选升级",
    AudioTransitionKind.MERGED_ESCALATION: "重复哭声候选合并升级",
    AudioTransitionKind.RECOVERED: "哭声候选已恢复",
}
_STAGES = {
    AudioTransitionKind.OPENED: "audio_opened",
    AudioTransitionKind.ESCALATED: "audio_escalated",
    AudioTransitionKind.MERGED_ESCALATION: "audio_merged",
    AudioTransitionKind.RECOVERED: "audio_recovered",
}


class AudioEventPipeline:
    def __init__(self, *, store: EventStore) -> None:
        self._store = store

    def handle(self, transition: AudioStateTransition) -> CandidateEvent:
        event_id = self._stable_id(transition)
        event = CandidateEvent(
            event_id=event_id,
            kind=_EVENT_KIND,
            severity=transition.severity,
            occurred_at=transition.occurred_at,
            summary=_SUMMARIES[transition.kind],
            confidence=transition.confidence,
            rule_version=transition.rule_version,
            metadata={"transition": transition.kind.value},
        )
        self._store.add_event_with_notification(
            event,
            notification_id=f"notify-{event_id}",
            stage=_STAGES[transition.kind],
        )
        return event

    @staticmethod
    def _stable_id(transition: AudioStateTransition) -> str:
        value = "|".join(
            (
                transition.rule_version,
                transition.kind.value,
                transition.occurred_at.isoformat(),
            )
        )
        return "audio-" + hashlib.sha256(value.encode("ascii")).hexdigest()[:32]
