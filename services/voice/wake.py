from __future__ import annotations

import unicodedata
from dataclasses import dataclass
from typing import Literal


WAKE_PREFIX = "小小"
_OPTIONAL_WAKE_LEAD = "嘿"
WAKE_NOT_DETECTED = "wake_not_detected"
WAKE_COMMAND_MISSING = "wake_command_missing"
_PUNCTUATION_FREE_COMMAND_PREFIXES = (
    "我是爸爸",
    "我是妈妈",
    "宝宝喝了",
    "我要开始",
    "我要喂奶了",
    "开始喂",
    "开始亲喂",
    "喂奶结束",
    "喂完了",
    "喝了",
    "亲喂",
    "开始换尿布",
    "换好尿布了",
    "开始拍嗝",
    "拍嗝结束",
    "确认",
    "保存记录",
    "取消",
)


@dataclass(frozen=True)
class WakeResult:
    accepted: bool
    command: str | None
    reason: str | None


@dataclass(frozen=True)
class WakeClassification:
    kind: Literal["standalone_wake", "wake_with_command", "not_wake"]
    command: str | None


def classify_wake(text: str) -> WakeClassification:
    """Classify the exact listen-only wake without changing full-care validation."""

    if not isinstance(text, str):
        return WakeClassification("not_wake", None)
    normalized = _normalize_wake_entry(text)
    if normalized is None:
        return WakeClassification("not_wake", None)
    if normalized == WAKE_PREFIX:
        return WakeClassification("standalone_wake", None)
    validated = validate_wake_prefix(text)
    if validated.accepted and validated.command is not None:
        return WakeClassification("wake_with_command", validated.command)
    return WakeClassification("not_wake", None)


def validate_wake_prefix(text: str) -> WakeResult:
    """Accept only the exact normalized 小小 prefix and return its command."""

    if not isinstance(text, str):
        return WakeResult(False, None, WAKE_NOT_DETECTED)
    normalized = _normalize_wake_entry(text)
    if normalized is None:
        return WakeResult(False, None, WAKE_NOT_DETECTED)
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


def _normalize_wake_entry(value: str) -> str | None:
    normalized = _strip_boundary_characters(value)
    if not normalized.startswith(_OPTIONAL_WAKE_LEAD):
        return normalized
    remainder = normalized[len(_OPTIONAL_WAKE_LEAD) :]
    if remainder.startswith(WAKE_PREFIX):
        return remainder
    if not remainder or not _is_boundary_character(remainder[0]):
        return None
    return _strip_boundary_characters(remainder)


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
