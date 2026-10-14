from __future__ import annotations

from services.voice.m7_llm import LanguageCandidate, LlmUnavailable, M7ToolCall
from services.voice.m7_orchestrator import M7Orchestrator, M7Outcome, M7VoiceProcessor
from services.voice.m7_session import M6ToolExecutor, M7SessionBridge


class FakeLanguage:
    def __init__(self, result: LanguageCandidate | LlmUnavailable) -> None:
        self.result = result
        self.calls: list[str] = []

    def complete(self, text: str, context: dict[str, object]) -> LanguageCandidate | LlmUnavailable:
        self.calls.append(text)
        return self.result


class FakeExecutor:
    def __init__(self, result: str = "accepted_pending") -> None:
        self.calls: list[tuple[str, dict[str, object]]] = []
        self.result = result

    def execute(self, call: object) -> str:
        self.calls.append((call.name, call.arguments))
        return self.result


def candidate(*calls: M7ToolCall, intent: str = "feeding_update", clarification: str | None = None) -> LanguageCandidate:
    return LanguageCandidate(
        intent=intent,
        tool_calls=list(calls),
        clarification=clarification,
        confidence=0.9,
        context_key="test-conversation",
    )


def test_ordinary_natural_language_reaches_llm_before_tool_execution() -> None:
    language = FakeLanguage(
        candidate(
            M7ToolCall(
                name="add_feeding_component",
                arguments={"kind": "bottle", "liquid_type": "formula", "amount_ml": 30},
            )
        )
    )
    executor = FakeExecutor()
    orchestrator = M7Orchestrator(language, executor, fallback=lambda text: "规则回退")

    outcome = orchestrator.handle("又补了三十毫升奶粉", {}, identity_bound=True)

    assert isinstance(outcome, M7Outcome)
    assert language.calls == ["又补了三十毫升奶粉"]
    assert executor.calls == [("add_feeding_component", {"kind": "bottle", "liquid_type": "formula", "amount_ml": 30})]
    assert outcome.code == "accepted_pending"


def test_cancel_uses_fast_path_without_llm() -> None:
    language = FakeLanguage(LlmUnavailable())
    executor = FakeExecutor("cancelled")
    orchestrator = M7Orchestrator(language, executor, fallback=lambda text: "规则回退")

    outcome = orchestrator.handle("取消这次记录", {}, identity_bound=True)

    assert language.calls == []
    assert executor.calls[0][0] == "cancel_feeding"
    assert outcome.code == "cancelled"


def test_llm_failure_uses_existing_rule_fallback() -> None:
    language = FakeLanguage(LlmUnavailable())
    executor = FakeExecutor()
    orchestrator = M7Orchestrator(language, executor, fallback=lambda text: "规则回退")

    outcome = orchestrator.handle("开始喂奶", {}, identity_bound=True)

    assert outcome.reply == "规则回退"
    assert outcome.used_fallback is True
    assert executor.calls == []


def test_confirmation_reply_is_saved_only_when_gateway_says_saved() -> None:
    language = FakeLanguage(
        candidate(M7ToolCall(name="confirm_feeding", arguments={}), intent="care_confirm")
    )
    executor = FakeExecutor("temporarily_unavailable")
    orchestrator = M7Orchestrator(language, executor, fallback=lambda text: "规则回退")

    outcome = orchestrator.handle("帮我保存", {}, identity_bound=True)

    assert outcome.code == "temporarily_unavailable"
    assert "保存" not in outcome.reply
    assert outcome.used_fallback is False


def test_mismatched_query_write_candidate_is_rejected_before_executor() -> None:
    language = FakeLanguage(
        candidate(
            M7ToolCall(name="add_feeding_component", arguments={"kind": "bottle", "liquid_type": "formula", "amount_ml": 30}),
            intent="feeding_query",
        )
    )
    executor = FakeExecutor()
    orchestrator = M7Orchestrator(language, executor, fallback=lambda text: "规则回退")

    outcome = orchestrator.handle("今天喝了多少", {}, identity_bound=True)

    assert outcome.code == "intent_tool_mismatch"
    assert executor.calls == []


def test_synthetic_mixed_feeding_reaches_one_authoritative_saved_session() -> None:
    class Gateway:
        def __init__(self) -> None:
            self.components: tuple[dict[str, object], ...] = ()
            self.saved = 0

        def start(self, *, occurred_at):
            return "session-1"

        def update(self, *, session_id, components):
            self.components = components

        def end(self, *, session_id, components):
            self.components = components
            return "proposal-1"

        def confirm(self, *, session_id, proposal_id):
            self.saved += 1
            return "saved"

        def cancel(self, *, session_id):
            return "cancelled"

        def query(self):
            return self.components

    class SequenceLanguage:
        def __init__(self, results):
            self.results = iter(results)

        def complete(self, text, context):
            return next(self.results)

    from datetime import datetime, timezone

    gateway = Gateway()
    bridge = M7SessionBridge(gateway)
    executor = M6ToolExecutor(bridge, clock=lambda: datetime(2026, 10, 11, tzinfo=timezone.utc))
    language = SequenceLanguage(
        [
            candidate(M7ToolCall(name="start_feeding", arguments={}), intent="feeding_start"),
            candidate(M7ToolCall(name="add_feeding_component", arguments={"kind": "bottle", "liquid_type": "expressed_breast_milk", "amount_ml": 60})),
            candidate(M7ToolCall(name="add_feeding_component", arguments={"kind": "bottle", "liquid_type": "formula", "amount_ml": 30})),
            candidate(M7ToolCall(name="end_feeding", arguments={}), intent="feeding_end"),
            candidate(M7ToolCall(name="confirm_feeding", arguments={}), intent="care_confirm"),
        ]
    )
    orchestrator = M7Orchestrator(language, executor, fallback=lambda text: "规则回退")

    texts = ["开始喂奶", "母乳60毫升", "配方奶30毫升", "喂完了", "帮我保存"]
    outcomes = [orchestrator.handle(text, {}, identity_bound=True) for text in texts]

    assert [outcome.code for outcome in outcomes] == [
        "accepted_pending", "accepted_pending", "accepted_pending", "needs_confirmation", "saved"
    ]
    assert gateway.saved == 1
    assert gateway.components == (
        {"kind": "bottle", "liquidType": "expressed_breast_milk", "amountMl": 60},
        {"kind": "bottle", "liquidType": "formula", "amountMl": 30},
    )


def test_synthetic_task_flow_correction_duplicate_cancel_query_and_direct_breastfeeding() -> None:
    class Gateway:
        def __init__(self) -> None:
            self.components: tuple[dict[str, object], ...] = ()
            self.saved = 0
            self.calls: list[str] = []

        def start(self, *, occurred_at):
            self.calls.append("start")
            return "session-1"

        def update(self, *, session_id, components):
            self.calls.append("update")
            self.components = components

        def end(self, *, session_id, components):
            self.calls.append("end")
            self.components = components
            return "proposal-1"

        def confirm(self, *, session_id, proposal_id):
            self.calls.append("confirm")
            self.saved += 1
            return "saved"

        def cancel(self, *, session_id):
            self.calls.append("cancel")
            return "cancelled"

        def query(self):
            self.calls.append("query")
            return self.components

    class SequenceLanguage:
        def __init__(self, results):
            self.results = iter(results)

        def complete(self, text, context):
            return next(self.results)

    from datetime import datetime, timezone

    gateway = Gateway()
    bridge = M7SessionBridge(gateway)
    executor = M6ToolExecutor(bridge, clock=lambda: datetime(2026, 10, 11, tzinfo=timezone.utc))
    language = SequenceLanguage(
        [
            candidate(M7ToolCall(name="start_feeding", arguments={}), intent="feeding_start"),
            candidate(M7ToolCall(name="add_feeding_component", arguments={"kind": "bottle", "liquid_type": "expressed_breast_milk", "amount_ml": 60})),
            candidate(M7ToolCall(name="add_feeding_component", arguments={"kind": "bottle", "liquid_type": "formula", "amount_ml": 30})),
            candidate(M7ToolCall(name="correct_feeding_component", arguments={"target": "formula", "amount_ml": 40})),
            candidate(M7ToolCall(name="end_feeding", arguments={}), intent="feeding_end"),
            candidate(M7ToolCall(name="confirm_feeding", arguments={}), intent="care_confirm"),
            candidate(M7ToolCall(name="confirm_feeding", arguments={}), intent="care_confirm"),
        ]
    )
    orchestrator = M7Orchestrator(language, executor, fallback=lambda text: "规则回退")

    outcomes = [
        orchestrator.handle(text, {}, identity_bound=True)
        for text in ["开始喂奶", "母乳60毫升", "配方奶30毫升", "奶粉改成40毫升", "喂完了", "帮我保存", "再次确认"]
    ]

    assert [outcome.code for outcome in outcomes] == [
        "accepted_pending", "accepted_pending", "accepted_pending", "accepted_pending",
        "needs_confirmation", "saved", "state_conflict",
    ]
    assert gateway.saved == 1
    assert gateway.components == (
        {"kind": "bottle", "liquidType": "expressed_breast_milk", "amountMl": 60},
        {"kind": "bottle", "liquidType": "formula", "amountMl": 40},
    )

    class Query:
        def get_recent_feedings(self, _at, *, from_time=None, limit=20):
            return ({"id": "event-1", "bottleTotalMl": 100},)

    query_executor = M6ToolExecutor(
        bridge,
        clock=lambda: datetime(2026, 10, 11, tzinfo=timezone.utc),
        query_client=Query(),
    )
    query_language = FakeLanguage(
        candidate(M7ToolCall(name="get_recent_feedings", arguments={}), intent="feeding_query")
    )
    query_orchestrator = M7Orchestrator(query_language, query_executor, fallback=lambda text: "规则回退")
    calls_before_query = list(gateway.calls)
    assert query_orchestrator.handle("今天喝了多少", {}, identity_bound=True).code == "query_result"
    assert gateway.calls == calls_before_query

    cancel_language = FakeLanguage(
        candidate(M7ToolCall(name="cancel_feeding", arguments={}), intent="care_cancel")
    )
    cancel_orchestrator = M7Orchestrator(cancel_language, executor, fallback=lambda text: "规则回退")
    assert cancel_orchestrator.handle("取消这次记录", {}, identity_bound=True).code == "state_conflict"

    direct_language = FakeLanguage(
        candidate(M7ToolCall(name="add_feeding_component", arguments={"kind": "direct_breastfeeding", "duration_minutes": 15}))
    )
    direct_orchestrator = M7Orchestrator(direct_language, executor, fallback=lambda text: "规则回退")
    assert direct_orchestrator.handle("亲喂15分钟", {}, identity_bound=True).code == "state_conflict"


def test_voice_processor_adapts_only_authoritative_code_to_existing_worker_response() -> None:
    language = FakeLanguage(candidate(M7ToolCall(name="confirm_feeding", arguments={}), intent="care_confirm"))
    executor = FakeExecutor("temporarily_unavailable")
    processor = M7VoiceProcessor(
        M7Orchestrator(language, executor, fallback=lambda text: "规则回退")
    )

    response = processor.process("帮我保存", {}, identity_bound=True)

    assert response.schema_version == 2
    assert response.code == "temporarily_unavailable"
    assert response.care_event_id is None
