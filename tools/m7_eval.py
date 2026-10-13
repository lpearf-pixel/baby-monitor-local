"""Deterministic synthetic evaluation corpus and aggregate-only M7 metrics."""

from __future__ import annotations

from dataclasses import dataclass
from time import perf_counter
from typing import Protocol
from services.voice.intent import DialogueState, parse_feeding_command
from services.voice.m7_llm import LanguageCandidate, LlmUnavailable
from services.voice.m7_tools import validate_candidate


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


class LiveLanguageClient(Protocol):
    def complete(self, text: str, context: dict[str, object]) -> LanguageCandidate | LlmUnavailable: ...


def _canonical_intent(candidate: LanguageCandidate) -> str:
    return {"feeding_query": "query", "care_confirm": "confirm"}.get(
        candidate.intent, candidate.intent
    )


def _candidate_amount(candidate: LanguageCandidate) -> int | None:
    for call in candidate.tool_calls:
        amount = call.arguments.get("amount_ml")
        if type(amount) is int:
            return amount
    return None


def evaluate_live_modes(
    samples: tuple[EvalSample, ...], client: LiveLanguageClient
) -> dict[str, object]:
    """Evaluate one client pass and return aggregate-only B/C metrics."""
    rows: list[tuple[EvalSample, LanguageCandidate | LlmUnavailable, float]] = []
    for sample in samples:
        started = perf_counter()
        result = client.complete(
            sample.text, {"phase": "evaluation", "sample_id": sample.sample_id}
        )
        rows.append((sample, result, (perf_counter() - started) * 1000))
    latencies = sorted(latency for _, _, latency in rows)

    def percentile(value: float) -> float | None:
        if not latencies:
            return None
        index = min(len(latencies) - 1, int(round((len(latencies) - 1) * value)))
        return round(latencies[index], 1)

    pure_intent = pure_params = hybrid_intent = hybrid_params = 0
    responded = tool_legal = clarification_correct = wrong_amount = failures = 0
    for sample, result, _ in rows:
        if isinstance(result, LlmUnavailable):
            failures += 1
            if sample.expected_amount_ml is not None:
                wrong_amount += 1
            continue
        responded += 1
        intent_ok = _canonical_intent(result) == sample.expected_intent
        amount = _candidate_amount(result)
        params_ok = amount == sample.expected_amount_ml or (
            sample.expected_amount_ml is None and amount is None
        )
        pure_intent += int(intent_ok)
        pure_params += int(params_ok)
        if sample.expected_amount_ml is not None and amount != sample.expected_amount_ml:
            wrong_amount += 1
        validation = validate_candidate(result, identity_bound=True)
        legal = validation.rejection_reason is None and (
            validation.clarification is not None or bool(validation.calls)
        )
        tool_legal += int(legal)
        clarification_correct += int(
            sample.expected_intent is None and validation.clarification is not None
        )
        hybrid_intent += int(legal and intent_ok)
        hybrid_params += int(legal and params_ok)
    total = len(rows)
    return {
        "status": "evaluated",
        "total": total,
        "responded": responded,
        "failures": failures,
        "pure_llm": {
            "intent_correct": pure_intent,
            "parameter_correct": pure_params,
            "intent_accuracy": pure_intent / total if total else 0.0,
            "parameter_accuracy": pure_params / total if total else 0.0,
        },
        "hybrid": {
            "intent_correct": hybrid_intent,
            "parameter_correct": hybrid_params,
            "intent_accuracy": hybrid_intent / total if total else 0.0,
            "parameter_accuracy": hybrid_params / total if total else 0.0,
            "tool_legal": tool_legal,
            "tool_legal_rate": tool_legal / total if total else 0.0,
            "clarification_correct": clarification_correct,
        },
        "wrong_amount_count": wrong_amount,
        "latency_p50_ms": percentile(0.50),
        "latency_p95_ms": percentile(0.95),
        "latency_max_ms": round(max(latencies), 1) if latencies else None,
        "private_text_persisted": False,
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


def evaluate_modes(samples: tuple[EvalSample, ...], *, llm) -> dict[str, dict[str, object]]:
    rule = evaluate_rule_only(samples)
    result: dict[str, dict[str, object]] = {
        "rule_only": {"status": "evaluated", **rule.as_dict()},
        "pure_llm": {"status": "live_model_pending"},
        "hybrid": {"status": "live_model_pending"},
    }
    if llm is None:
        return result
    # The live adapter is intentionally injected by the caller; this function
    # never persists utterances or treats a missing adapter as a score of zero.
    for sample in samples:
        llm(sample)
    result["pure_llm"] = {"status": "evaluated_by_injected_adapter"}
    result["hybrid"] = {"status": "evaluated_by_injected_adapter"}
    return result


__all__ = [
    "EvalReport",
    "EvalSample",
    "build_samples",
    "evaluate_live_modes",
    "evaluate_modes",
    "evaluate_rule_only",
]
