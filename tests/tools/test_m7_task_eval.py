from __future__ import annotations

from services.voice.m7_llm import LanguageCandidate, M7ToolCall
from tools.m7_task_eval import TaskScenario, evaluate_task_scenarios


def candidate(intent: str, name: str, arguments: dict[str, object] | None = None) -> LanguageCandidate:
    return LanguageCandidate(
        intent=intent,
        tool_calls=[M7ToolCall(name=name, arguments=arguments or {})],
        confidence=1.0,
        context_key="synthetic",
    )


class MappingClient:
    def complete(self, text: str, context: dict[str, object]):
        values = {
            "开始喂奶": candidate("feeding_start", "start_feeding"),
            "母乳60毫升": candidate("feeding_update", "add_feeding_component", {"kind": "bottle", "liquid_type": "expressed_breast_milk", "amount_ml": 60}),
            "喂完了": candidate("feeding_end", "end_feeding"),
            "帮我保存": candidate("care_confirm", "confirm_feeding"),
            "再次确认": candidate("care_confirm", "confirm_feeding"),
            "取消这次记录": candidate("care_cancel", "cancel_feeding"),
            "再补一点": LanguageCandidate(intent="clarification", tool_calls=[], clarification="请补充明确数量", confidence=0.0, context_key="synthetic"),
        }
        return values[text]


def test_task_evaluator_counts_completion_and_safe_duplicate_confirmation() -> None:
    report = evaluate_task_scenarios(
        MappingClient(),
        (
            TaskScenario(
                "duplicate-confirm",
                ("开始喂奶", "母乳60毫升", "喂完了", "帮我保存", "再次确认"),
                ("accepted_pending", "accepted_pending", "needs_confirmation", "saved", "state_conflict"),
            ),
            TaskScenario("clarify", ("开始喂奶", "再补一点"), ("accepted_pending", "clarification")),
        ),
    )

    assert report.total == 2
    assert report.completed == 2
    assert report.authoritative_records == 1
    assert report.duplicate_records == 0
    assert report.failed == 0
    assert report.p50_ms is not None
    assert report.p95_ms is not None
