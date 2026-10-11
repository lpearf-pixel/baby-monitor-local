"""Closed feeding-only validation for M7 language candidates."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping

from services.voice.m7_llm import LanguageCandidate, M7ToolCall


@dataclass(frozen=True, slots=True)
class ValidatedToolCall:
    name: str
    arguments: dict[str, object]


@dataclass(frozen=True, slots=True)
class ToolValidation:
    calls: tuple[ValidatedToolCall, ...] = ()
    clarification: str | None = None
    rejection_reason: str | None = None
    requires_confirmation: bool = False


_READ_TOOLS = {"get_active_feeding", "get_recent_feedings", "get_feeding_summary"}
_WRITE_TOOLS = {
    "start_feeding",
    "add_feeding_component",
    "correct_feeding_component",
    "end_feeding",
    "request_feeding_confirmation",
    "confirm_feeding",
    "cancel_feeding",
}


def validate_candidate(
    candidate: LanguageCandidate,
    *,
    identity_bound: bool,
    unique_uncommitted_target: bool = True,
) -> ToolValidation:
    if not identity_bound and any(call.name not in _READ_TOOLS for call in candidate.tool_calls):
        return ToolValidation(rejection_reason="identity_unavailable")
    if candidate.intent == "clarification":
        return ToolValidation(clarification=candidate.clarification)
    if not candidate.tool_calls:
        return ToolValidation(rejection_reason="no_tool_call")
    validated: list[ValidatedToolCall] = []
    needs_confirmation = False
    for call in candidate.tool_calls:
        checked = _validate_call(call, unique_uncommitted_target=unique_uncommitted_target)
        if isinstance(checked, str):
            if checked == "ambiguous_correction":
                return ToolValidation(clarification="要修改哪一项奶量？")
            return ToolValidation(rejection_reason=checked)
        validated.append(checked)
        if checked.name in _WRITE_TOOLS:
            needs_confirmation = True
    return ToolValidation(tuple(validated), requires_confirmation=needs_confirmation)


def _validate_call(call: M7ToolCall, *, unique_uncommitted_target: bool) -> ValidatedToolCall | str:
    args: Mapping[str, object] = call.arguments
    if call.name not in _READ_TOOLS | _WRITE_TOOLS:
        return "unknown_tool"
    if call.name == "add_feeding_component":
        kind = args.get("kind")
        if kind == "bottle":
            if set(args) != {"kind", "liquid_type", "amount_ml"}:
                return "invalid_bottle_component"
            if args.get("liquid_type") not in {"expressed_breast_milk", "formula"}:
                return "invalid_bottle_component"
            amount = args.get("amount_ml")
            if type(amount) is not int or not 0 < amount <= 2_000:
                return "invalid_bottle_component"
        elif kind == "direct_breastfeeding":
            if set(args) != {"kind", "duration_minutes"}:
                return "invalid_direct_component"
            duration = args.get("duration_minutes")
            if type(duration) is not int or not 0 < duration <= 720:
                return "invalid_direct_component"
        else:
            return "invalid_component_kind"
    elif call.name == "correct_feeding_component":
        if set(args) != {"target", "amount_ml"}:
            return "invalid_correction"
        if args.get("target") not in {"formula", "expressed_breast_milk"}:
            return "invalid_correction"
        if type(args.get("amount_ml")) is not int or not 0 < int(args["amount_ml"]) <= 2_000:
            return "invalid_correction"
        if not unique_uncommitted_target:
            return "ambiguous_correction"
    elif call.name == "confirm_feeding":
        if set(args) != set():
            return "model_cannot_assert_confirmation"
    elif call.name in _READ_TOOLS:
        if args:
            return "invalid_query_arguments"
    return ValidatedToolCall(call.name, dict(args))


__all__ = ["ToolValidation", "ValidatedToolCall", "validate_candidate"]
