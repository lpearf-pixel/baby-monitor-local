from __future__ import annotations

import unicodedata
from dataclasses import dataclass


WAKE_PREFIX = "小小"
WAKE_NOT_DETECTED = "wake_not_detected"
WAKE_COMMAND_MISSING = "wake_command_missing"


@dataclass(frozen=True)
class WakeResult:
    accepted: bool
    command: str | None
    reason: str | None


def validate_wake_prefix(text: str) -> WakeResult:
    """Accept only the exact normalized 小小 prefix and return its command."""

    if not isinstance(text, str):
        return WakeResult(False, None, WAKE_NOT_DETECTED)
    normalized = _strip_boundary_characters(text)
    if not normalized.startswith(WAKE_PREFIX):
        return WakeResult(False, None, WAKE_NOT_DETECTED)
    command = _strip_boundary_characters(normalized[len(WAKE_PREFIX) :])
    if not command:
        return WakeResult(False, None, WAKE_COMMAND_MISSING)
    return WakeResult(True, command, None)


def _strip_boundary_characters(value: str) -> str:
    start = 0
    end = len(value)
    while start < end and _is_boundary_character(value[start]):
        start += 1
    while end > start and _is_boundary_character(value[end - 1]):
        end -= 1
    return value[start:end]


def _is_boundary_character(character: str) -> bool:
    return character.isspace() or unicodedata.category(character).startswith("P")
