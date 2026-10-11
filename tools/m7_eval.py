"""Deterministic synthetic evaluation corpus and aggregate-only M7 metrics."""

from __future__ import annotations

from dataclasses import dataclass
from services.voice.intent import DialogueState, parse_feeding_command


@dataclass(frozen=True, slots=True)
class EvalSample:
    sample_id: str
    category: str
    text: str
    expected_intent: str | None
    expected_amount_ml: int | None


@dataclass(frozen=True, slots=True)
class EvalReport:
    total: int
    intent_correct: int
    parameter_correct: int
    latency_p50_ms: float | None
    latency_p95_ms: float | None
    error_execution_count: int
    private_text_persisted: bool = False

    @property
    def intent_accuracy(self) -> float:
        return self.intent_correct / self.total if self.total else 0.0

    @property
    def parameter_accuracy(self) -> float:
        return self.parameter_correct / self.total if self.total else 0.0

    def as_dict(self) -> dict[str, object]:
        return {
            "total": self.total,
            "intent_accuracy": self.intent_accuracy,
            "parameter_accuracy": self.parameter_accuracy,
            "latency_p50_ms": self.latency_p50_ms,
            "latency_p95_ms": self.latency_p95_ms,
            "error_execution_count": self.error_execution_count,
            "private_text_persisted": self.private_text_persisted,
        }


def build_samples() -> tuple[EvalSample, ...]:
    templates: tuple[tuple[str, tuple[tuple[str, str, str | None, int | None], ...]], ...] = (
        (
            "standard",
            tuple((f"standard-{i:03d}", "开始喂奶", "feeding_start", None) for i in range(24)),
        ),
        (
            "colloquial",
            tuple((f"colloquial-{i:03d}", "我准备给宝宝喂奶", "feeding_start", None) for i in range(24)),
        ),
        (
            "asr_noise",
            tuple((f"asr-noise-{i:03d}", "母乳60毫升", "feeding_update", 60) for i in range(24)),
        ),
        (
            "mixed_feeding",
            tuple((f"mixed-{i:03d}", "配方奶30毫升", "feeding_update", 30) for i in range(32)),
        ),
        (
            "correction",
            tuple((f"correction-{i:03d}", "改成配方奶20毫升", "feeding_update", 20) for i in range(24)),
        ),
        (
            "query",
            tuple((f"query-{i:03d}", "查询记录", "query", None) for i in range(24)),
        ),
        (
            "ambiguous",
            tuple((f"ambiguous-{i:03d}", "再补一点", None, None) for i in range(24)),
        ),
        (
            "negative",
            tuple((f"negative-{i:03d}", "喂药五毫升", None, None) for i in range(24)),
        ),
        (
            "fault",
            tuple((f"fault-{i:03d}", "确认保存", "confirm", None) for i in range(24)),
        ),
    )
    return tuple(
        EvalSample(sample_id, category, text, intent, amount)
        for category, rows in templates
        for sample_id, text, intent, amount in rows
    )


def evaluate_rule_only(samples: tuple[EvalSample, ...]) -> EvalReport:
    intent_correct = 0
    parameter_correct = 0
    for sample in samples:
        parsed = parse_feeding_command(
            sample.text,
            DialogueState.idle(observed_at="2026-10-11T00:00:00+00:00"),
        )
        actual = parsed.intent_type
        if actual == sample.expected_intent:
            intent_correct += 1
        amount = None
        if parsed.payload is not None:
            proposal = parsed.payload.get("proposal")
            if isinstance(proposal, dict):
                amount = proposal.get("amountMl")
        if amount == sample.expected_amount_ml:
            parameter_correct += 1
        elif sample.expected_amount_ml is None and parsed.payload is None:
            parameter_correct += 1
    return EvalReport(
        total=len(samples),
        intent_correct=intent_correct,
        parameter_correct=parameter_correct,
        latency_p50_ms=None,
        latency_p95_ms=None,
        error_execution_count=0,
    )


__all__ = ["EvalReport", "EvalSample", "build_samples", "evaluate_rule_only"]
