from __future__ import annotations

from services.voice.m7_llm import LlmUnavailable
from tools.m7_eval import build_closed_samples, build_samples, evaluate_live_modes, evaluate_modes, evaluate_rule_only


def test_m7_eval_contains_at_least_200_categorized_synthetic_samples() -> None:
    samples = build_samples()

    assert len(samples) >= 200
    categories = {sample.category for sample in samples}
    assert {
        "standard",
        "colloquial",
        "asr_noise",
        "mixed_feeding",
        "correction",
        "query",
        "ambiguous",
        "negative",
        "fault",
    } <= categories
    assert len({sample.sample_id for sample in samples}) == len(samples)
    assert len({sample.text for sample in samples}) == len(samples)
    assert {sample.split for sample in samples} == {"dev", "test"}


def test_closed_corpus_is_frozen_and_disjoint() -> None:
    samples = build_closed_samples()
    assert len(samples) == 24
    assert len({sample.sample_id for sample in samples}) == 24
    assert len({sample.text for sample in samples}) == 24
    assert all(sample.split == "closed" for sample in samples)
    assert {sample.text for sample in samples}.isdisjoint({sample.text for sample in build_samples()})


def test_rule_baseline_reports_aggregate_metrics_without_transcripts() -> None:
    report = evaluate_rule_only(build_samples())

    assert report.total >= 200
    assert report.intent_accuracy >= 0
    assert report.parameter_accuracy >= 0
    assert report.as_dict()["parameter_total"] == 80
    assert report.private_text_persisted is False
    assert "text" not in report.as_dict()


def test_a_b_c_comparison_marks_unavailable_live_modes_without_fabricating_metrics() -> None:
    comparison = evaluate_modes(build_samples(), llm=None)

    assert comparison["rule_only"]["status"] == "evaluated"
    assert comparison["pure_llm"]["status"] == "live_model_pending"
    assert comparison["hybrid"]["status"] == "live_model_pending"
    assert "accuracy" not in comparison["pure_llm"]


def test_live_report_exposes_per_category_and_failure_reason_counts() -> None:
    class UnavailableClient:
        def complete(self, text: str, context: dict[str, object]) -> LlmUnavailable:
            return LlmUnavailable("timeout")

    report = evaluate_live_modes(build_samples()[:1], UnavailableClient())

    assert report["status"] == "evaluated"
    assert "by_category" in report
    assert "failure_reasons" in report
