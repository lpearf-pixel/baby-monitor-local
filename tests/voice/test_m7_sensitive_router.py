from services.voice.m7_llm import LlmUnavailable
from services.voice.m7_orchestrator import M7Orchestrator
from services.voice.m7_sensitive_router import route_deterministic_intent, route_sensitive_intent


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
        return {
            "add_feeding_component": "accepted_pending",
            "correct_feeding_component": "accepted_pending",
            "start_feeding": "accepted_pending",
            "end_feeding": "needs_confirmation",
            "confirm_feeding": "saved",
            "cancel_feeding": "cancelled",
            "get_active_feeding": "query_result",
        }.get(call.name, "state_conflict")


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


def test_deterministic_fast_path_covers_only_exact_safe_forms():
    assert route_deterministic_intent("开始喂奶", {"phase": "idle"}).call.name == "start_feeding"
    component = route_deterministic_intent("母乳六十毫升", {"phase": "pending"})
    assert component is not None
    assert component.call.name == "add_feeding_component"
    assert component.call.arguments["amount_ml"] == 60
    assert route_deterministic_intent("查询当前草稿", {"phase": "pending"}).call.name == "get_active_feeding"


def test_fast_path_does_not_guess_increment_or_ambiguous_amount():
    assert route_deterministic_intent("又补了三十", {"phase": "pending"}) is None
    assert route_deterministic_intent("奶粉大概三十毫升", {"phase": "pending"}) is None
    assert route_deterministic_intent("他说母乳六十毫升", {"phase": "pending"}) is None


def test_fast_path_reuses_existing_m6_parser_for_correction_and_direct_breastfeeding():
    correction = route_deterministic_intent("奶粉改成四十毫升", {"phase": "pending"})
    assert correction is not None
    assert correction.call.name == "correct_feeding_component"
    assert correction.call.arguments == {"target": "formula", "amount_ml": 40}
    direct = route_deterministic_intent("亲喂十五分钟", {"phase": "pending"})
    assert direct is not None
    assert direct.call.arguments == {"kind": "direct_breastfeeding", "duration_minutes": 15}


def test_opt_in_fast_path_executes_through_registry_and_leaves_default_off():
    language = FakeLanguage()
    executor = FakeExecutor()
    from services.voice.m7_orchestrator import M7Orchestrator

    fast = M7Orchestrator(language, executor, fallback=lambda _text: "fallback", deterministic_routing=True)
    outcome = fast.handle("母乳六十毫升", {"phase": "pending"}, identity_bound=True)
    assert outcome.code == "accepted_pending"
    assert executor.calls[0].name == "add_feeding_component"
    assert language.calls == []

    default_executor = FakeExecutor()
    default = M7Orchestrator(language, default_executor, fallback=lambda _text: "fallback")
    default.handle("母乳六十毫升", {"phase": "pending"}, identity_bound=True)
    assert default_executor.calls == []
