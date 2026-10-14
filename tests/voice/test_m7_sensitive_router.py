from services.voice.m7_llm import LlmUnavailable
from services.voice.m7_orchestrator import M7Orchestrator
from services.voice.m7_sensitive_router import route_sensitive_intent


class FakeLanguage:
    def __init__(self):
        self.calls = []

    def complete(self, text, context):
        self.calls.append(text)
        return LlmUnavailable()


class FakeExecutor:
    def __init__(self):
        self.calls = []

    def execute(self, call):
        self.calls.append(call)
        return "saved" if call.name == "confirm_feeding" else "cancelled"


def _orchestrator():
    language = FakeLanguage()
    executor = FakeExecutor()
    return M7Orchestrator(language, executor, fallback=lambda _text: "fallback", sensitive_routing=True), language, executor


def test_explicit_confirmation_requires_current_proposal():
    orchestrator, language, executor = _orchestrator()

    outcome = orchestrator.handle("确认保存这次喂奶", {"phase": "needs_confirmation", "proposal_version": 3}, identity_bound=True)

    assert outcome.code == "saved"
    assert [call.name for call in executor.calls] == ["confirm_feeding"]
    assert language.calls == []


def test_confirmation_without_proposal_never_calls_executor():
    orchestrator, language, executor = _orchestrator()

    outcome = orchestrator.handle("确认保存这次喂奶", {"phase": "pending"}, identity_bound=True)

    assert outcome.code == "state_conflict"
    assert executor.calls == []
    assert language.calls == []


def test_explicit_cancel_and_refusal_cancel_current_draft():
    for text in ("取消当前待保存记录", "先不要保存"):
        orchestrator, language, executor = _orchestrator()
        outcome = orchestrator.handle(text, {"phase": "needs_confirmation"}, identity_bound=True)
        assert outcome.code == "cancelled"
        assert [call.name for call in executor.calls] == ["cancel_feeding"]
        assert language.calls == []


def test_ambiguous_short_acknowledgement_is_not_confirmation():
    orchestrator, language, executor = _orchestrator()

    outcome = orchestrator.handle("嗯", {"phase": "needs_confirmation"}, identity_bound=True)

    assert outcome.code == "llm_unavailable"
    assert executor.calls == []
    assert language.calls == ["嗯"]


def test_quoted_confirmation_and_mixed_intent_are_not_sensitive_routes():
    for text in ('他说“确认保存这次喂奶”', "确认保存这次喂奶，但是先不要保存"):
        route = route_sensitive_intent(text, {"phase": "needs_confirmation"})
        assert route is None


def test_end_is_not_confirmation_and_needs_pending_draft():
    route = route_sensitive_intent("喂完了，结束喂奶", {"phase": "pending"})
    assert route is not None
    assert route.call.name == "end_feeding"


def test_query_and_correction_are_not_sensitive_routes():
    assert route_sensitive_intent("最近一次喂奶记录", {"phase": "needs_confirmation"}) is None
    assert route_sensitive_intent("奶粉改成四十毫升", {"phase": "needs_confirmation"}) is None
