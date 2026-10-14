"""Opt-in, state-aware routing for explicit confirmation and cancellation phrases."""

from __future__ import annotations

import re
from dataclasses import dataclass

from services.voice.m7_llm import M7ToolCall


@dataclass(frozen=True, slots=True)
class SensitiveRoute:
    call: M7ToolCall
    requires_current_proposal: bool = False


_CONFIRM = re.compile(r"^(?:确认保存(?:这次(?:喂奶|记录)|当前草稿)?|确认记录当前草稿)$")
_CANCEL = re.compile(r"^(?:取消(?:当前待保存记录|这次(?:喂奶|记录)|当前草稿)|先不要保存|不要记录)$")
_END = re.compile(r"^(?:喂完了|喂奶结束|结束喂奶|喂完了结束喂奶|好了结束吧)$")
_QUOTE_MARKS = "\"'“”‘’《》"


def _normalized(text: str) -> str:
    return "".join(character for character in text.strip() if not character.isspace() and character not in "，。！？、；：")


def _has_current_draft(context: dict[str, object], *, proposal: bool = False) -> bool:
    phase = context.get("phase")
    if proposal:
        return phase == "needs_confirmation" and bool(context.get("proposal_version") or context.get("proposal_id"))
    return phase in {"pending", "needs_confirmation"}


def route_sensitive_intent(text: str, context: dict[str, object]) -> SensitiveRoute | None:
    """Return a route only for an exact, unquoted, single explicit phrase."""
    if not isinstance(text, str) or any(mark in text for mark in _QUOTE_MARKS):
        return None
    normalized = _normalized(text)
    if not normalized or ("确认" in normalized and "不要" in normalized) or ("取消" in normalized and "确认" in normalized):
        return None
    if _CONFIRM.fullmatch(normalized):
        if not _has_current_draft(context, proposal=True):
            return SensitiveRoute(M7ToolCall(name="confirm_feeding", arguments={}), True)
        return SensitiveRoute(M7ToolCall(name="confirm_feeding", arguments={}), True)
    if _CANCEL.fullmatch(normalized):
        return SensitiveRoute(M7ToolCall(name="cancel_feeding", arguments={}))
    if _END.fullmatch(normalized):
        return SensitiveRoute(M7ToolCall(name="end_feeding", arguments={}))
    return None


__all__ = ["SensitiveRoute", "route_sensitive_intent"]
