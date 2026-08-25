from __future__ import annotations

import unicodedata
from dataclasses import dataclass


WAKE_PREFIX = "小小"
WAKE_NOT_DETECTED = "wake_not_detected"
WAKE_COMMAND_MISSING = "wake_command_missing"
_PUNCTUATION_FREE_COMMAND_PREFIXES = (
    "我是爸爸",
    "我是妈妈",
    "宝宝喝了",
    "我要开始",
    "开始喂",
    "开始亲喂",
    "喂奶结束",
    "喂完了",
    "喝了",
    "亲喂",
    "确认",
    "保存记录",
    "取消",
)


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
    remainder = normalized[len(WAKE_PREFIX) :]
    command = _strip_boundary_characters(remainder)
    if WAKE_PREFIX in command:
        return WakeResult(False, None, WAKE_NOT_DETECTED)
    punctuation_free = remainder and not _is_boundary_character(remainder[0])
    if punctuation_free and not remainder.startswith(
        _PUNCTUATION_FREE_COMMAND_PREFIXES
    ):
        return WakeResult(False, None, WAKE_NOT_DETECTED)
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
