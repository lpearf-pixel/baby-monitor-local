from __future__ import annotations

from services.voice.m7_llm import LanguageCandidate, LlmUnavailable, M7ToolCall
from services.voice.m7_orchestrator import M7Orchestrator, M7Outcome


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
