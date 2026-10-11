"""Model-first feeding orchestration with deterministic safety gates."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Protocol

from services.voice.m7_llm import LanguageCandidate, LlmUnavailable, M7ToolCall
from services.voice.m7_tools import validate_candidate


class LanguageClient(Protocol):
    def complete(self, text: str, context: dict[str, object]) -> LanguageCandidate | LlmUnavailable: ...


class ToolExecutor(Protocol):
    def execute(self, call: object) -> str: ...


@dataclass(frozen=True, slots=True)
class M7Outcome:
    code: str
    reply: str
    used_fallback: bool = False
    clarification: str | None = None


class M7Orchestrator:
    def __init__(
        self,
        language: LanguageClient,
        executor: ToolExecutor,
        *,
        fallback: Callable[[str], str],
    ) -> None:
        self._language = language
        self._executor = executor
        self._fallback = fallback

    def handle(
        self,
        text: str,
        context: dict[str, object],
        *,
        identity_bound: bool,
    ) -> M7Outcome:
        normalized = "".join(text.split())
        if normalized in {"取消", "取消这次记录", "停止记录"}:
            if not identity_bound:
                return M7Outcome("identity_unavailable", "无法确认照护人身份。")
            code = self._executor.execute(M7ToolCall(name="cancel_feeding", arguments={}))
            return self._outcome_for_code(code)
        result = self._language.complete(text, context)
        if isinstance(result, LlmUnavailable):
            return M7Outcome("llm_unavailable", self._fallback(text), used_fallback=True)
        validation = validate_candidate(result, identity_bound=identity_bound)
        if validation.clarification is not None:
            return M7Outcome("clarification", validation.clarification, clarification=validation.clarification)
        if validation.rejection_reason is not None:
            return M7Outcome(validation.rejection_reason, "这句话暂时无法安全记录。")
        last_code = "accepted_pending"
        for call in validation.calls:
            last_code = self._executor.execute(call)
            if last_code in {"temporarily_unavailable", "rejected", "state_conflict"}:
                break
        return self._outcome_for_code(last_code)

    @staticmethod
    def _outcome_for_code(code: str) -> M7Outcome:
        replies = {
            "accepted_pending": "记下了，记录仍待确认。",
            "needs_confirmation": "请确认是否保存这次喂养记录。",
            "saved": "已经保存。",
            "cancelled": "已取消这次记录。",
            "query_result": "我会查询 Baby Care 的记录。",
            "temporarily_unavailable": "暂时无法完成，请稍后重试。",
            "state_conflict": "当前喂养记录状态不允许这个操作。",
            "rejected": "这句话暂时无法安全记录。",
        }
        return M7Outcome(code, replies.get(code, "我需要再确认一下。"))


__all__ = ["M7Orchestrator", "M7Outcome"]
