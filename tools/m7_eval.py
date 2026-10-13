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
    split: str = "test"


@dataclass(frozen=True, slots=True)
class EvalReport:
    total: int
    intent_correct: int
    parameter_correct: int
    parameter_total: int
    latency_p50_ms: float | None
    latency_p95_ms: float | None
    error_execution_count: int
    private_text_persisted: bool = False

    @property
    def intent_accuracy(self) -> float:
        return self.intent_correct / self.total if self.total else 0.0

    @property
    def parameter_accuracy(self) -> float:
        return self.parameter_correct / self.parameter_total if self.parameter_total else 0.0

    def as_dict(self) -> dict[str, object]:
        return {
            "total": self.total,
            "intent_accuracy": self.intent_accuracy,
            "parameter_accuracy": self.parameter_accuracy,
            "parameter_total": self.parameter_total,
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
    parameter_total = 0
    responded = tool_legal = clarification_correct = wrong_amount = failures = 0
    amount_error_reasons: dict[str, int] = {}
    failure_stages: dict[str, int] = {}
    by_category: dict[str, dict[str, int]] = {}
    failure_reasons: dict[str, int] = {}
    by_split: dict[str, dict[str, int]] = {}
    for sample, result, _ in rows:
        category = by_category.setdefault(
            sample.category, {"total": 0, "responded": 0, "failures": 0, "intent_correct": 0, "parameter_correct": 0, "tool_legal": 0}
        )
        category["total"] += 1
        split = by_split.setdefault(sample.split, {"total": 0, "responded": 0, "failures": 0, "intent_correct": 0, "parameter_correct": 0, "tool_legal": 0})
        split["total"] += 1
        params_applicable = sample.expected_amount_ml is not None
        parameter_total += int(params_applicable)
        if isinstance(result, LlmUnavailable):
            failures += 1
            category["failures"] += 1
            split["failures"] += 1
            failure_reasons[result.reason] = failure_reasons.get(result.reason, 0) + 1
            stage = (
                "schema_output_failure"
                if result.reason in {"invalid_json", "invalid_response", "schema_mismatch", "unknown_tool"}
                or result.reason.startswith("schema_")
                else "model_unavailable"
            )
            failure_stages[stage] = failure_stages.get(stage, 0) + 1
            if sample.expected_amount_ml is not None:
                wrong_amount += 1
                amount_error_reasons["missing_or_invalid_candidate"] = (
                    amount_error_reasons.get("missing_or_invalid_candidate", 0) + 1
                )
            continue
        responded += 1
        category["responded"] += 1
        split["responded"] += 1
        validation = validate_candidate(result, identity_bound=True)
        intent_ok = _canonical_intent(result) == sample.expected_intent or (
            sample.expected_intent is None and validation.clarification is not None
        )
        amount = _candidate_amount(result)
        params_ok = params_applicable and amount == sample.expected_amount_ml
        if validation.rejection_reason is not None:
            failure_stages["tool_selection_failure"] = failure_stages.get("tool_selection_failure", 0) + 1
        elif sample.expected_intent is None and validation.clarification is not None:
            failure_stages["correct_rejection"] = failure_stages.get("correct_rejection", 0) + 1
        elif not intent_ok:
            failure_stages["intent_failure"] = failure_stages.get("intent_failure", 0) + 1
        elif params_applicable and not params_ok:
            failure_stages["amount_failure"] = failure_stages.get("amount_failure", 0) + 1
        pure_intent += int(intent_ok)
        pure_params += int(params_ok)
        category["intent_correct"] += int(intent_ok)
        category["parameter_correct"] += int(params_ok)
        split["intent_correct"] += int(intent_ok)
        split["parameter_correct"] += int(params_ok)
        if sample.expected_amount_ml is not None and amount != sample.expected_amount_ml:
            wrong_amount += 1
            reason = "missing_or_invalid_candidate" if amount is None else "wrong_numeric_amount"
            amount_error_reasons[reason] = amount_error_reasons.get(reason, 0) + 1
        legal = validation.rejection_reason is None and (
            validation.clarification is not None or bool(validation.calls)
        )
        tool_legal += int(legal)
        category["tool_legal"] += int(legal)
        split["tool_legal"] += int(legal)
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
        "parameter_total": parameter_total,
        "pure_llm": {
            "intent_correct": pure_intent,
            "parameter_correct": pure_params,
            "intent_accuracy": pure_intent / total if total else 0.0,
            "parameter_accuracy": pure_params / parameter_total if parameter_total else None,
        },
        "hybrid": {
            "intent_correct": hybrid_intent,
            "parameter_correct": hybrid_params,
            "intent_accuracy": hybrid_intent / total if total else 0.0,
            "parameter_accuracy": hybrid_params / parameter_total if parameter_total else None,
            "tool_legal": tool_legal,
            "tool_legal_rate": tool_legal / total if total else 0.0,
            "clarification_correct": clarification_correct,
        },
        "wrong_amount_count": wrong_amount,
        "amount_error_reasons": amount_error_reasons,
        "failure_stages": failure_stages,
        "by_category": by_category,
        "by_split": by_split,
        "failure_reasons": failure_reasons,
        "latency_p50_ms": percentile(0.50),
        "latency_p95_ms": percentile(0.95),
        "latency_max_ms": round(max(latencies), 1) if latencies else None,
        "private_text_persisted": False,
    }


def build_samples() -> tuple[EvalSample, ...]:
    def variants(roots: tuple[str, ...], endings: tuple[str, ...]) -> tuple[str, ...]:
        return tuple(root + ending for root in roots for ending in endings)

    templates = (
        ("standard", variants(("开始喂奶", "现在开始喂奶", "给宝宝开始喂奶", "我们开始喂宝宝", "准备开始记录喂奶", "请开始这次喂奶"), ("。", "！", "，帮我记下", "，现在开始")), "feeding_start", None),
        ("colloquial", variants(("宝宝要吃奶了", "我准备给宝宝喂奶", "可以喂宝宝了", "宝宝现在要吃了", "我来给宝宝喂一顿", "这会儿开始喂"), ("。", "呀", "，你记一下", "，先开始")), "feeding_start", None),
        ("asr_noise", variants(("母乳60毫升", "母乳六十毫升", "刚喝母乳六十", "母乳喝了60ml", "记母乳六十毫升", "母乳六十毫升记一下"), ("。", "", "了", "请记录")), "feeding_update", 60),
        ("mixed_feeding", variants(("配方奶30毫升", "奶粉三十毫升", "补了配方奶30", "再加三十毫升奶粉", "配方三十毫升记下", "又补30ml配方奶", "补充奶粉三十毫升", "奶粉加三十毫升"), ("。", "", "了", "请记录")), "feeding_update", 30),
        ("correction", variants(("改成配方奶20毫升", "刚才奶粉是二十毫升", "更正配方奶20", "把奶粉改为20ml", "说错了配方奶二十", "配方奶实际二十毫升"), ("。", "", "请修改", "记为这个数")), "feeding_update", 20),
        ("query", variants(("查询记录", "今天喝了多少奶", "看看喂奶记录", "帮我查今天的奶量", "最近一次喂奶是什么时候", "统计一下今天喂奶"), ("。", "？", "请告诉我", "帮我看看")), "query", None),
        ("ambiguous", variants(("再补一点", "宝宝还没吃饱", "再加一些吧", "要不要再补", "还想再喂一点", "再来一点奶"), ("。", "？", "，你问我", "，但我没说多少")), None, None),
        ("negative", variants(("喂药五毫升", "给宝宝吃药", "记录药物剂量", "吃五毫升药", "帮我记药", "药物五毫升"), ("。", "", "请执行", "记下来")), None, None),
        ("fault", variants(("确认保存", "嗯就这样保存", "帮我保存这次", "保存记录吧", "确认提交", "可以记入了"), ("。", "", "请处理", "现在保存")), "confirm", None),
    )
    samples: list[EvalSample] = []
    for category, texts, intent, amount in templates:
        for index, text in enumerate(texts):
            split = "dev" if index % 4 == 0 else "test"
            samples.append(EvalSample(f"{category}-{index:03d}", category, text, intent, amount, split))
    return tuple(samples)


def build_closed_samples() -> tuple[EvalSample, ...]:
    """Frozen, separately authored set; never used for prompt selection."""
    rows = (
        ("closed-001", "natural", "小小，今天开始给宝宝喂奶", "feeding_start", None),
        ("closed-002", "natural", "刚刚喝了母乳六十五毫升", "feeding_update", 65),
        ("closed-003", "natural", "又添了四十毫升配方奶", "feeding_update", 40),
        ("closed-004", "natural", "奶粉那项改成二十五毫升", "feeding_update", 25),
        ("closed-005", "natural", "母乳不改，奶粉还是二十五", "feeding_update", 25),
        ("closed-006", "natural", "亲喂了十二分钟", "feeding_update", None),
        ("closed-007", "natural", "先别保存，取消这次", "care_cancel", None),
        ("closed-008", "natural", "结束喂奶但暂时不要保存", "feeding_end", None),
        ("closed-009", "natural", "我确认保存刚才那一单", "confirm", None),
        ("closed-010", "query", "今天一共喝了多少", "query", None),
        ("closed-011", "query", "查一下最近的喂奶", "query", None),
        ("closed-012", "ambiguous", "再喝一点点", None, None),
        ("closed-013", "ambiguous", "大概半瓶吧", None, None),
        ("closed-014", "negative", "帮我记录五毫升药", None, None),
        ("closed-015", "negative", "把刚才的奶删掉", "care_cancel", None),
        ("closed-016", "natural", "恢复刚才没结束的喂奶", "feeding_resume", None),
        ("closed-017", "natural", "配方奶从三十改四十五毫升", "feeding_update", 45),
        ("closed-018", "natural", "这次只亲喂八分钟", "feeding_update", None),
        ("closed-019", "natural", "母乳七十，另外奶粉二十", "feeding_update", 70),
        ("closed-020", "natural", "我说错了，母乳是六十毫升", "feeding_update", 60),
        ("closed-021", "query", "昨天比今天少喝多少", "query", None),
        ("closed-022", "ambiguous", "补一点奶粉就好", None, None),
        ("closed-023", "natural", "喂完啦", "feeding_end", None),
        ("closed-024", "natural", "好，保存这次喂奶", "confirm", None),
    )
    return tuple(EvalSample(*row, split="closed") for row in rows)


def evaluate_rule_only(samples: tuple[EvalSample, ...]) -> EvalReport:
    intent_correct = 0
    parameter_correct = 0
    parameter_total = 0
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
        if sample.expected_amount_ml is not None:
            parameter_total += 1
        if sample.expected_amount_ml is not None and amount == sample.expected_amount_ml:
            parameter_correct += 1
    return EvalReport(
        total=len(samples),
        intent_correct=intent_correct,
        parameter_correct=parameter_correct,
        parameter_total=parameter_total,
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
    "build_closed_samples",
    "evaluate_live_modes",
    "evaluate_modes",
    "evaluate_rule_only",
]
