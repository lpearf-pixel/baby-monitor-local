"""Aggregate-only M7 end-to-end task evaluation over an isolated synthetic gateway."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from time import perf_counter
from typing import Iterable

from services.voice.m7_llm import LanguageCandidate, LlmUnavailable, M7ToolCall
from services.voice.m7_orchestrator import M7Orchestrator
from services.voice.m7_session import M6ToolExecutor, M7SessionBridge


@dataclass(frozen=True, slots=True)
class TaskScenario:
    name: str
    turns: tuple[str, ...]
    expected_codes: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class TaskEvaluation:
    total: int
    completed: int
    model_successes: int
    tool_successes: int
    confirmation_successes: int
    authoritative_records: int
    rejected: int
    failed: int
    duplicate_records: int
    p50_ms: float | None
    p95_ms: float | None

    def as_dict(self) -> dict[str, object]:
        return {
            "total": self.total,
            "completed": self.completed,
            "completion_rate": self.completed / self.total if self.total else 0.0,
            "model_successes": self.model_successes,
            "tool_successes": self.tool_successes,
            "confirmation_successes": self.confirmation_successes,
            "authoritative_records": self.authoritative_records,
            "rejected": self.rejected,
            "failed": self.failed,
            "duplicate_records": self.duplicate_records,
            "latency_p50_ms": self.p50_ms,
            "latency_p95_ms": self.p95_ms,
            "private_text_persisted": False,
        }


class SyntheticGateway:
    """Isolated in-memory stand-in for the signed Baby Care gateway boundary."""

    def __init__(self) -> None:
        self.components: tuple[dict[str, object], ...] = ()
        self.saved = 0
        self.calls: list[str] = []

    def start(self, *, occurred_at: datetime) -> str:
        self.calls.append("start")
        return "synthetic-session"

    def update(self, *, session_id: str, components: tuple[dict[str, object], ...]) -> None:
        self.calls.append("update")
        self.components = components

    def end(self, *, session_id: str, components: tuple[dict[str, object], ...]) -> str:
        self.calls.append("end")
        self.components = components
        return "synthetic-proposal"

    def confirm(self, *, session_id: str, proposal_id: str) -> str:
        self.calls.append("confirm")
        if self.saved:
            return "state_conflict"
        self.saved += 1
        return "saved"

    def cancel(self, *, session_id: str) -> str:
        self.calls.append("cancel")
        self.components = ()
        return "cancelled"

    def query(self) -> tuple[dict[str, object], ...]:
        self.calls.append("query")
        return self.components


class SyntheticQuery:
    def get_recent_feedings(self, _at: datetime, *, from_time=None, limit: int = 20):
        return ({"id": "synthetic-event", "components": ()},)

    def get_feeding_summary(self, _at: datetime):
        return {"bottleTotalMl": 0, "directBreastfeedingMinutes": 0}


def default_task_scenarios() -> tuple[TaskScenario, ...]:
    return (
        TaskScenario("start", ("开始喂奶",), ("accepted_pending",)),
        TaskScenario("breast_60", ("开始喂奶", "母乳60毫升"), ("accepted_pending", "accepted_pending")),
        TaskScenario("formula_30", ("开始喂奶", "配方奶30毫升"), ("accepted_pending", "accepted_pending")),
        TaskScenario("mixed_60_30", ("开始喂奶", "母乳60毫升", "配方奶30毫升", "喂完了", "帮我保存"), ("accepted_pending", "accepted_pending", "accepted_pending", "needs_confirmation", "saved")),
        TaskScenario("correction", ("开始喂奶", "配方奶30毫升", "奶粉改成40毫升", "喂完了", "帮我保存"), ("accepted_pending", "accepted_pending", "accepted_pending", "needs_confirmation", "saved")),
        TaskScenario("cancel_then_confirm", ("开始喂奶", "配方奶30毫升", "取消这次记录", "确认保存"), ("accepted_pending", "accepted_pending", "cancelled", "state_conflict")),
        TaskScenario("clarify_amount", ("开始喂奶", "再补一点"), ("accepted_pending", "clarification")),
        TaskScenario("query_recent", ("最近一次喂奶",), ("query_result",)),
        TaskScenario("direct_15", ("开始喂奶", "亲喂15分钟"), ("accepted_pending", "accepted_pending")),
        TaskScenario("end", ("开始喂奶", "母乳60毫升", "喂完了"), ("accepted_pending", "accepted_pending", "needs_confirmation")),
        TaskScenario("duplicate_confirm", ("开始喂奶", "母乳60毫升", "喂完了", "帮我保存", "再次确认"), ("accepted_pending", "accepted_pending", "needs_confirmation", "saved", "state_conflict")),
        TaskScenario("cancel", ("开始喂奶", "取消这次记录"), ("accepted_pending", "cancelled")),
    )


def evaluate_task_scenarios(client, scenarios: Iterable[TaskScenario] | None = None) -> TaskEvaluation:
    scenarios = tuple(scenarios or default_task_scenarios())
    latencies: list[float] = []
    completed = model_successes = tool_successes = confirmation_successes = 0
    authoritative_records = rejected = failed = duplicate_records = 0
    for scenario in scenarios:
        gateway = SyntheticGateway()
        bridge = M7SessionBridge(gateway)
        executor = M6ToolExecutor(
            bridge,
            clock=lambda: datetime(2026, 10, 14, tzinfo=timezone.utc),
            query_client=SyntheticQuery(),
        )
        orchestrator = M7Orchestrator(client, executor, fallback=lambda _text: "fallback")
        actual_codes: list[str] = []
        scenario_ok = True
        for text, expected in zip(scenario.turns, scenario.expected_codes):
            started = perf_counter()
            result = orchestrator.handle(text, {}, identity_bound=True)
            latencies.append((perf_counter() - started) * 1000)
            actual_codes.append(result.code)
            scenario_ok = scenario_ok and result.code == expected
            model_successes += int(result.code not in {"llm_unavailable", "invalid_candidate"})
            tool_successes += int(result.code not in {"intent_tool_mismatch", "no_tool_call", "unknown_tool"})
            confirmation_successes += int(result.code in {"needs_confirmation", "saved", "state_conflict"})
            rejected += int(result.code in {"clarification", "intent_tool_mismatch", "rejected", "state_conflict"})
            failed += int(result.code in {"llm_unavailable", "temporarily_unavailable", "invalid_candidate"})
        if scenario_ok:
            completed += 1
        authoritative_records += gateway.saved
        duplicate_records += max(0, gateway.saved - 1)
    ordered = sorted(latencies)
    p50 = ordered[len(ordered) // 2] if ordered else None
    p95 = ordered[min(len(ordered) - 1, int(round((len(ordered) - 1) * 0.95)))] if ordered else None
    return TaskEvaluation(
        len(scenarios), completed, model_successes, tool_successes,
        confirmation_successes, authoritative_records, rejected, failed,
        duplicate_records, p50, p95,
    )


__all__ = ["TaskEvaluation", "TaskScenario", "default_task_scenarios", "evaluate_task_scenarios"]
