from __future__ import annotations

from datetime import datetime, timezone

from services.voice.m6_feeding import M6SessionGateway
from services.voice.m7_session import M7SessionBridge


class Gateway(M6SessionGateway):
    def __init__(self) -> None:
        self.calls: list[str] = []
        self.components: tuple[dict[str, object], ...] = ()

    def start(self, *, occurred_at: datetime) -> str:
        self.calls.append("start")
        return "session-1"

    def update(self, *, session_id: str, components: tuple[dict[str, object], ...]) -> None:
        self.calls.append("update")
        self.components = components

    def end(self, *, session_id: str, components: tuple[dict[str, object], ...]) -> str:
        self.calls.append("end")
        return "proposal-1"

    def confirm(self, *, session_id: str, proposal_id: str) -> str:
        self.calls.append("confirm")
        return "saved"

    def cancel(self, *, session_id: str) -> str:
        self.calls.append("cancel")
        return "cancelled"

    def query(self) -> tuple[dict[str, object], ...]:
        self.calls.append("query")
        return self.components


def at(second: int) -> datetime:
    return datetime(2026, 10, 11, 0, 0, second, tzinfo=timezone.utc)


def test_language_context_expiry_keeps_gateway_task_recoverable() -> None:
    gateway = Gateway()
    bridge = M7SessionBridge(gateway, context_seconds=8)

    assert bridge.process("开始喂奶", at(0), request_id="start").code == "accepted_pending"
    assert bridge.process("母乳60毫升", at(1), request_id="component").code == "accepted_pending"
    assert bridge.process("配方奶30毫升", at(10), request_id="expired").code == "context_expired"
    assert bridge.resume(at(11), request_id="resume").code == "task_resumed"
    assert bridge.process("配方奶30毫升", at(12), request_id="retry").code == "accepted_pending"
    assert gateway.calls == ["start", "update", "update"]


def test_query_cancel_and_duplicate_are_delegated_without_new_state_store() -> None:
    gateway = Gateway()
    bridge = M7SessionBridge(gateway)
    first = bridge.process("开始喂奶", at(0), request_id="same")
    assert bridge.process("开始喂奶", at(0), request_id="same") == first
    assert bridge.query(at(1), request_id="query").code == "query_result"
    assert bridge.cancel(at(2), request_id="cancel").code == "cancelled"
    assert gateway.calls == ["start", "query", "cancel"]
