from __future__ import annotations

from services.voice.m7_llm import LanguageCandidate, LlmUnavailable, M7ToolCall
from services.voice.m7_orchestrator import M7Orchestrator, M7Outcome
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
