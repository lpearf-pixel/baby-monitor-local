from __future__ import annotations

from tools.m7_eval import build_samples, evaluate_rule_only


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


def test_rule_baseline_reports_aggregate_metrics_without_transcripts() -> None:
    report = evaluate_rule_only(build_samples())

    assert report.total >= 200
    assert report.intent_accuracy >= 0
    assert report.parameter_accuracy >= 0
    assert report.private_text_persisted is False
    assert "text" not in report.as_dict()
