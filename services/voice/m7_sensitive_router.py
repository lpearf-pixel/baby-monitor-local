"""Opt-in, state-aware routing for explicit confirmation and cancellation phrases."""

from __future__ import annotations

import re
from dataclasses import dataclass

from services.voice.m7_llm import M7ToolCall
from services.voice.m6_feeding import parse_m6_utterance


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


def route_deterministic_intent(text: str, context: dict[str, object]) -> SensitiveRoute | None:
    """Convert only exact, bounded M6 grammar forms into safe tool candidates."""
    if not isinstance(text, str) or any(mark in text for mark in _QUOTE_MARKS):
        return None
    normalized = _normalized(text)
    if not normalized or any(token in normalized for token in ("不要", "先别", "不是", "他说", "有人说", "大概", "左右", "一点", "一些", "又补", "总共")):
        return None
    if normalized in {"查询当前草稿", "查看当前草稿"}:
        return SensitiveRoute(M7ToolCall(name="get_active_feeding", arguments={}))
    parse_text = normalized
    correction_match = re.fullmatch(r"(母乳|奶粉)改成(.+)", normalized)
    if correction_match is not None:
        liquid = "配方奶" if correction_match.group(1) == "奶粉" else correction_match.group(1)
        parse_text = f"改成{liquid}{correction_match.group(2)}"
    elif normalized.startswith("奶粉"):
        parse_text = f"配方奶{normalized[2:]}"
    parsed = parse_m6_utterance(parse_text)
    if parsed.kind == "feeding_start":
        return SensitiveRoute(M7ToolCall(name="start_feeding", arguments={}))
    if parsed.kind == "feeding_end":
        return SensitiveRoute(M7ToolCall(name="end_feeding", arguments={}))
    if parsed.kind == "confirm":
        return route_sensitive_intent(normalized, context)
    if parsed.kind == "cancel":
        return route_sensitive_intent(normalized, context)
    if parsed.kind != "feeding_component" or parsed.component is None:
        return None
    component = parsed.component
    if parsed.correction:
        if component.get("kind") != "bottle":
            return None
        return SensitiveRoute(M7ToolCall(name="correct_feeding_component", arguments={
            "target": component["liquidType"], "amount_ml": component["amountMl"],
        }))
    if component.get("kind") == "direct_breastfeeding":
        return SensitiveRoute(M7ToolCall(name="add_feeding_component", arguments={
            "kind": "direct_breastfeeding", "duration_minutes": component["durationMinutes"],
        }))
    return SensitiveRoute(M7ToolCall(name="add_feeding_component", arguments={
        "kind": "bottle", "liquid_type": component["liquidType"], "amount_ml": component["amountMl"],
    }))


__all__ = ["SensitiveRoute", "route_deterministic_intent", "route_sensitive_intent"]
