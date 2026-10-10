from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from services.voice.m6_feeding import (
    M6FeedingCoordinator,
    M6Result,
    M6SessionGateway,
    parse_m6_utterance,
)


UTC = timezone.utc


class Gateway(M6SessionGateway):
    def __init__(self) -> None:
        self.calls: list[tuple[str, object]] = []
        self.components: tuple[dict[str, object], ...] = ()

    def start(self, *, occurred_at: datetime) -> str:
        self.calls.append(("feeding_start", occurred_at))
        return "session-1"

    def update(self, *, session_id: str, components: tuple[dict[str, object], ...]) -> None:
        self.calls.append(("feeding_update", components))
        self.components = components

    def end(self, *, session_id: str, components: tuple[dict[str, object], ...]) -> str:
        self.calls.append(("feeding_end", components))
        self.components = components
        return "proposal-1"

    def confirm(self, *, session_id: str, proposal_id: str) -> str:
        self.calls.append(("care_confirm", proposal_id))
        return "saved"

    def cancel(self, *, session_id: str) -> str:
        self.calls.append(("care_cancel", session_id))
        return "cancelled"

    def query(self) -> tuple[dict[str, object], ...]:
        self.calls.append(("query", None))
        return self.components


def at(seconds: int) -> datetime:
    return datetime(2026, 10, 10, 0, 0, seconds, tzinfo=UTC)


def test_parser_accepts_mixed_components_without_converting_direct_feed() -> None:
    assert parse_m6_utterance("开始喂奶").kind == "feeding_start"
    breast = parse_m6_utterance("母乳60毫升")
    assert breast.kind == "feeding_component"
    assert breast.component == {
        "kind": "bottle",
        "liquidType": "expressed_breast_milk",
        "amountMl": 60,
    }
    formula = parse_m6_utterance("补充配方奶30毫升")
    assert formula.component == {
        "kind": "bottle",
        "liquidType": "formula",
        "amountMl": 30,
    }
    direct = parse_m6_utterance("亲喂十分钟")
    assert direct.component == {"kind": "direct_breastfeeding", "durationMinutes": 10}


def test_mixed_flow_end_confirm_query_and_duplicate_are_idempotent() -> None:
    gateway = Gateway()
    coordinator = M6FeedingCoordinator(gateway, context_seconds=8)
    assert coordinator.process("开始喂奶", at(0), request_id="r1").code == "accepted_pending"
    assert coordinator.process("母乳60毫升", at(1), request_id="r2").code == "accepted_pending"
    assert coordinator.process("补充配方奶30毫升", at(2), request_id="r3").code == "accepted_pending"
    duplicate = coordinator.process("补充配方奶30毫升", at(2), request_id="r3")
    assert duplicate.code == "accepted_pending"
    assert len([call for call in gateway.calls if call[0] == "feeding_update"]) == 2
    assert coordinator.process("结束", at(3), request_id="r4").code == "needs_confirmation"
    assert coordinator.process("确认保存", at(4), request_id="r5").code == "saved"
    assert coordinator.process("查询记录", at(5), request_id="r6").records == gateway.components
    assert gateway.components == (
        {"kind": "bottle", "liquidType": "expressed_breast_milk", "amountMl": 60},
        {"kind": "bottle", "liquidType": "formula", "amountMl": 30},
    )


def test_expired_context_clears_without_resuming_old_session() -> None:
    gateway = Gateway()
    coordinator = M6FeedingCoordinator(gateway, context_seconds=8)
    coordinator.process("开始喂奶", at(0), request_id="r1")
    result = coordinator.process("母乳60毫升", at(9), request_id="r2")
    assert result.code == "context_expired"
    assert result.phase == "pending"
    assert [call[0] for call in gateway.calls] == ["feeding_start"]


def test_expiry_preserves_server_task_for_explicit_resume_query_and_cancel() -> None:
    gateway = Gateway()
    coordinator = M6FeedingCoordinator(gateway, context_seconds=8)
    coordinator.process("开始喂奶", at(0), request_id="r1")
    coordinator.process("母乳60毫升", at(1), request_id="r2")
    expired = coordinator.process("配方奶30毫升", at(10), request_id="r3")
    assert expired.code == "context_expired"
    assert coordinator.process("查询记录", at(10), request_id="r4").code == "query_result"
    assert coordinator.process("继续喂奶", at(11), request_id="r5").code == "task_resumed"
    assert coordinator.process("配方奶30毫升", at(12), request_id="r6").code == "accepted_pending"
    assert coordinator.process("取消", at(13), request_id="r7").code == "cancelled"
    assert [call[0] for call in gateway.calls] == [
        "feeding_start", "feeding_update", "query", "feeding_update", "care_cancel"
    ]


def test_expired_confirmation_can_retry_after_gateway_failure_without_losing_task() -> None:
    class ConfirmOnceGateway(Gateway):
        def __init__(self) -> None:
            super().__init__()
            self.fail = True

        def confirm(self, *, session_id: str, proposal_id: str) -> str:
            if self.fail:
                self.fail = False
                raise RuntimeError("database unavailable")
            return super().confirm(session_id=session_id, proposal_id=proposal_id)

    gateway = ConfirmOnceGateway()
    coordinator = M6FeedingCoordinator(gateway, context_seconds=8)
    coordinator.process("开始喂奶", at(0), request_id="r1")
    coordinator.process("母乳60毫升", at(1), request_id="r2")
    coordinator.process("结束", at(2), request_id="r3")
    assert coordinator.process("确认保存", at(12), request_id="r4").code == "temporarily_unavailable"
    assert coordinator.process("确认保存", at(13), request_id="r5").code == "saved"


def test_gateway_failure_and_audio_failure_are_closed_and_retryable() -> None:
    class FailingGateway(Gateway):
        def update(self, **kwargs: object) -> None:
            raise RuntimeError("database unavailable")

    gateway = FailingGateway()
    coordinator = M6FeedingCoordinator(gateway, context_seconds=8)
    coordinator.process("开始喂奶", at(0), request_id="r1")
    assert coordinator.process("母乳60毫升", at(1), request_id="r2").code == "temporarily_unavailable"
    assert coordinator.process("母乳60毫升", at(2), request_id="r3").code == "temporarily_unavailable"


def test_output_failure_does_not_change_gateway_state_and_correction_replaces_last() -> None:
    class BrokenOutput:
        def speak_code(self, code: str) -> bool:
            raise OSError(code)

    gateway = Gateway()
    coordinator = M6FeedingCoordinator(gateway, output=BrokenOutput())
    assert coordinator.process("开始喂奶", at(0), request_id="r1").audio_output_ok is False
    coordinator.process("母乳60毫升", at(1), request_id="r2")
    corrected = coordinator.process("改成母乳50毫升", at(2), request_id="r3")
    assert corrected.code == "accepted_pending"
    assert gateway.components == (
        {"kind": "bottle", "liquidType": "expressed_breast_milk", "amountMl": 50},
    )


def test_direct_breastfeeding_remains_duration_only() -> None:
    gateway = Gateway()
    coordinator = M6FeedingCoordinator(gateway)
    coordinator.process("开始喂奶", at(0), request_id="r1")
    coordinator.process("亲喂十分钟", at(1), request_id="r2")
    assert gateway.components == ({"kind": "direct_breastfeeding", "durationMinutes": 10},)


def test_saved_session_can_start_a_new_session_and_empty_correction_conflicts() -> None:
    gateway = Gateway()
    coordinator = M6FeedingCoordinator(gateway)
    assert coordinator.process("改成母乳50毫升", at(0), request_id="bad").code == "state_conflict"
    coordinator.process("开始喂奶", at(1), request_id="r1")
    coordinator.process("母乳60毫升", at(2), request_id="r2")
    coordinator.process("结束", at(3), request_id="r3")
    assert coordinator.process("确认保存", at(4), request_id="r4").code == "saved"
    assert coordinator.process("开始喂奶", at(5), request_id="r5").code == "accepted_pending"


@pytest.mark.parametrize("text", ["喝一点", "配方奶", "喂药五毫升", "母乳0毫升", "母乳6000毫升"])
def test_ambiguous_or_unsafe_text_fails_closed(text: str) -> None:
    assert parse_m6_utterance(text).kind == "uncertain"
