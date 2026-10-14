"""Model-first feeding orchestration with deterministic safety gates."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Protocol

from services.voice.client import VoiceSemanticResponse
from services.voice.m7_llm import LanguageCandidate, LlmUnavailable, M7ToolCall
from services.voice.m7_tools import validate_candidate
from services.voice.m7_sensitive_router import route_sensitive_intent


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
        sensitive_routing: bool = False,
    ) -> None:
        self._language = language
        self._executor = executor
        self._fallback = fallback
        self._sensitive_routing = sensitive_routing

    def handle(
        self,
        text: str,
        context: dict[str, object],
        *,
        identity_bound: bool,
    ) -> M7Outcome:
        normalized = "".join(text.split())
        if self._sensitive_routing:
            sensitive = route_sensitive_intent(text, context)
            if sensitive is not None:
                if not identity_bound:
                    return M7Outcome("identity_unavailable", "无法确认照护人身份。")
                if sensitive.requires_current_proposal and context.get("phase") != "needs_confirmation":
                    return M7Outcome("state_conflict", "当前没有可确认的待保存喂养记录。")
                if sensitive.requires_current_proposal and not (context.get("proposal_version") or context.get("proposal_id")):
                    return M7Outcome("state_conflict", "当前确认摘要已失效，请重新结束并确认。")
                validation = validate_candidate(
                    LanguageCandidate(
                        intent=("care_confirm" if sensitive.call.name == "confirm_feeding" else "care_cancel" if sensitive.call.name == "cancel_feeding" else "feeding_end"),
                        tool_calls=[sensitive.call], confidence=1.0, context_key="sensitive-router",
                    ), identity_bound=identity_bound,
                )
                if validation.clarification is not None or validation.rejection_reason is not None:
                    return M7Outcome(validation.rejection_reason or "clarification", validation.clarification or "这句话暂时无法安全记录。")
                return self._outcome_for_code(self._executor.execute(validation.calls[0]))
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


class M7VoiceProcessor:
    """Adapt an M7 outcome to the existing Voice Worker response envelope."""

    def __init__(self, orchestrator: M7Orchestrator) -> None:
        self._orchestrator = orchestrator

    def process(
        self,
        command: str,
        context: object,
        *,
        identity_bound: bool,
    ) -> VoiceSemanticResponse:
        safe_context = context if isinstance(context, dict) else {}
        outcome = self._orchestrator.handle(command, safe_context, identity_bound=identity_bound)
        return VoiceSemanticResponse(
            2, outcome.code, None, None, None, None, None, (), None
        )


__all__ = ["M7Orchestrator", "M7Outcome", "M7VoiceProcessor"]
