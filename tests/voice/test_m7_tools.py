from __future__ import annotations

import pytest

from services.voice.m7_llm import LanguageCandidate, M7ToolCall
from services.voice.m7_tools import ToolValidation, validate_candidate


def candidate(*calls: M7ToolCall, intent: str = "feeding_update", clarification: str | None = None) -> LanguageCandidate:
    return LanguageCandidate(
        intent=intent,
        tool_calls=list(calls),
        clarification=clarification,
        confidence=0.9,
        context_key="test-conversation",
    )


def test_accepts_mixed_bottle_components_without_converting_direct_breastfeeding() -> None:
    result = validate_candidate(
        candidate(
            M7ToolCall(
                name="add_feeding_component",
                arguments={"kind": "bottle", "liquid_type": "expressed_breast_milk", "amount_ml": 60},
            ),
            M7ToolCall(
                name="add_feeding_component",
                arguments={"kind": "bottle", "liquid_type": "formula", "amount_ml": 30},
            ),
        ),
        identity_bound=True,
    )

    assert isinstance(result, ToolValidation)
    assert [call.name for call in result.calls] == ["add_feeding_component", "add_feeding_component"]
    assert result.requires_confirmation is True
    assert result.calls[0].arguments["amount_ml"] == 60
    assert result.calls[1].arguments["amount_ml"] == 30


def test_direct_breastfeeding_requires_duration_and_never_amount_ml() -> None:
    result = validate_candidate(
        candidate(
            M7ToolCall(
                name="add_feeding_component",
                arguments={"kind": "direct_breastfeeding", "duration_minutes": 12},
            )
        ),
        identity_bound=True,
    )

    assert result.calls[0].arguments == {"kind": "direct_breastfeeding", "duration_minutes": 12}


def test_ambiguous_quantity_returns_clarification_without_tool_call() -> None:
    result = validate_candidate(
        candidate(intent="clarification", clarification="准备补多少毫升？是配方奶吗？"),
        identity_bound=True,
    )

    assert result.calls == ()
    assert result.clarification == "准备补多少毫升？是配方奶吗？"


def test_correction_requires_unique_uncommitted_target() -> None:
    result = validate_candidate(
        candidate(
            M7ToolCall(
                name="correct_feeding_component",
                arguments={"target": "formula", "amount_ml": 20},
            )
        ),
        identity_bound=True,
        unique_uncommitted_target=False,
    )

    assert result.calls == ()
    assert result.clarification is not None


def test_identity_or_permission_spoof_is_rejected() -> None:
    result = validate_candidate(
        candidate(
            M7ToolCall(
                name="confirm_feeding",
                arguments={"claimed_actor": "dad", "saved": True},
            ),
            intent="care_confirm",
        ),
        identity_bound=False,
    )

    assert result.calls == ()
    assert result.rejection_reason == "identity_unavailable"


@pytest.mark.parametrize(
    ("intent", "tool"),
    [
        ("feeding_query", "add_feeding_component"),
        ("care_confirm", "add_feeding_component"),
        ("care_cancel", "confirm_feeding"),
        ("feeding_update", "get_recent_feedings"),
    ],
)
def test_intent_and_tool_family_must_agree(intent: str, tool: str) -> None:
    result = validate_candidate(
        candidate(
            M7ToolCall(name=tool, arguments={}),
            intent=intent,
        ),
        identity_bound=True,
    )

    assert result.calls == ()
    assert result.rejection_reason == "intent_tool_mismatch"
