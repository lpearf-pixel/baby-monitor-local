"""Closed memory-only care-action classification for listen-only Voice."""

from __future__ import annotations

import unicodedata
from dataclasses import dataclass
from types import MappingProxyType
from typing import Literal

from services.voice.intent import DialogueState, parse_feeding_command


ActionCode = Literal[
    "feeding_command",
    "diaper_change_start",
    "diaper_change_complete",
    "burping_start",
    "burping_complete",
    "medication_start_candidate",
    "medication_complete_candidate",
]
Risk = Literal["low", "high"]

_REFERENCE_TIME = "2026-01-01T00:00:00+00:00"
_QUESTION_MARKS = frozenset({"?", "？"})
_ACTION_DOMAINS = (
    ("喂奶", "配方奶", "母乳", "亲喂", "喝了"),
    ("换尿布", "尿布"),
    ("拍嗝",),
    ("喂药",),
)
_POLICIES: dict[ActionCode, tuple[Risk, bool]] = {
    "feeding_command": ("low", True),
    "diaper_change_start": ("low", True),
    "diaper_change_complete": ("low", True),
    "burping_start": ("low", True),
    "burping_complete": ("low", True),
    "medication_start_candidate": ("high", False),
    "medication_complete_candidate": ("high", False),
}


@dataclass(frozen=True, slots=True)
class CareActionMatch:
    action_code: ActionCode
    risk: Risk
    allow_ack: bool

    def __post_init__(self) -> None:
        if _POLICIES.get(self.action_code) != (self.risk, self.allow_ack):
            raise ValueError("invalid_care_action")


_EXACT_ACTIONS = MappingProxyType(
    {
        "开始换尿布": CareActionMatch("diaper_change_start", "low", True),
        "换好尿布了": CareActionMatch("diaper_change_complete", "low", True),
        "开始拍嗝": CareActionMatch("burping_start", "low", True),
        "拍嗝结束": CareActionMatch("burping_complete", "low", True),
        "开始喂药": CareActionMatch("medication_start_candidate", "high", False),
        "喂药完成": CareActionMatch("medication_complete_candidate", "high", False),
    }
)
_FEEDING_MATCH = CareActionMatch("feeding_command", "low", True)
_FEEDING_STATES = (
    DialogueState.idle(observed_at=_REFERENCE_TIME),
    DialogueState.pending(
        observed_at=_REFERENCE_TIME,
        started_at=_REFERENCE_TIME,
        expected_version=1,
        mode="unknown",
    ),
    DialogueState.pending(
        observed_at=_REFERENCE_TIME,
        started_at=_REFERENCE_TIME,
        expected_version=1,
        mode="direct_breastfeeding",
    ),
    DialogueState.needs_confirmation(
        observed_at=_REFERENCE_TIME,
        started_at=_REFERENCE_TIME,
        expected_version=1,
        mode="unknown",
        proposal_digest="a" * 64,
        warning_digest=None,
        warning_codes=(),
    ),
)


def classify_exact_action(command: str) -> CareActionMatch | None:
    """Return one exact closed action without retaining or exposing input text."""

    if not isinstance(command, str) or any(mark in command for mark in _QUESTION_MARKS):
        return None
    normalized = _normalize(command)
    if not normalized or len(normalized) > 64 or _domain_count(normalized) > 1:
        return None

    exact = _EXACT_ACTIONS.get(normalized)
    if exact is not None:
        return exact
    if any(
        parse_feeding_command(normalized, state).intent_type is not None
        for state in _FEEDING_STATES
    ):
        return _FEEDING_MATCH
    return None


def _normalize(value: str) -> str:
    return "".join(
        character
        for character in value.strip()
        if not character.isspace()
        and not unicodedata.category(character).startswith("P")
    )


def _domain_count(command: str) -> int:
    return sum(any(marker in command for marker in domain) for domain in _ACTION_DOMAINS)


__all__ = ["ActionCode", "CareActionMatch", "Risk", "classify_exact_action"]
