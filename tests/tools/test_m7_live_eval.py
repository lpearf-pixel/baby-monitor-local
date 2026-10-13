from __future__ import annotations

from services.voice.m7_llm import LanguageCandidate, LlmUnavailable, M7ToolCall
from tools.m7_eval import build_samples, evaluate_live_modes


class FakeClient:
    def __init__(self, result: LanguageCandidate | LlmUnavailable) -> None:
        self.result = result

    def complete(self, text: str, context: dict[str, object]):
        return self.result


def candidate() -> LanguageCandidate:
    return LanguageCandidate(
        intent="feeding_update",
        tool_calls=[M7ToolCall(
            name="add_feeding_component",
            arguments={"kind": "bottle", "liquid_type": "formula", "amount_ml": 30},
        )],
        clarification=None,
        confidence=0.9,
        context_key="evaluation",
    )


def test_live_evaluation_keeps_pure_and_hybrid_metrics_separate() -> None:
    samples = build_samples()[:1]
    result = evaluate_live_modes(samples, FakeClient(candidate()))

    assert result["total"] == 1
    assert result["private_text_persisted"] is False
    assert result["pure_llm"]["intent_correct"] == 0
    assert result["hybrid"]["tool_legal"] == 1


def test_live_evaluation_counts_transport_failures_without_fabricating_scores() -> None:
    result = evaluate_live_modes(build_samples()[:1], FakeClient(LlmUnavailable()))

    assert result["responded"] == 0
    assert result["failures"] == 1
    assert result["pure_llm"]["intent_accuracy"] == 0.0
    assert result["latency_max_ms"] is not None


def test_live_evaluation_counts_missing_amount_as_wrong_for_amount_samples() -> None:
    sample = next(sample for sample in build_samples() if sample.expected_amount_ml == 30)
    result = evaluate_live_modes((sample,), FakeClient(LlmUnavailable()))

    assert result["wrong_amount_count"] == 1


def test_live_evaluation_does_not_score_non_amount_samples_as_parameter_accuracy() -> None:
    sample = build_samples()[0]
    result = evaluate_live_modes((sample,), FakeClient(LlmUnavailable()))

    assert result["parameter_total"] == 0
    assert result["pure_llm"]["parameter_accuracy"] is None
