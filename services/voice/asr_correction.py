"""Source-controlled correction for one exact-wake armed Voice follow-up."""

from __future__ import annotations

import unicodedata
from dataclasses import dataclass
from types import MappingProxyType
from typing import Literal

from services.voice.care_action import classify_exact_action


@dataclass(frozen=True, slots=True)
class CorrectionResult:
    canonical_command: str
    action_family: Literal["feeding"]


_CORRECTIONS = MappingProxyType(
    {"开始为奶": CorrectionResult("开始喂奶", "feeding")}
)
_BLOCKED_MARKERS = (
    "不",
    "别",
    "不要",
    "未",
    "没",
    "否",
    "停止",
    "停",
    "结束",
    "取消",
    "吗",
    "嘛",
    "么",
    "呢",
    "要不要",
    "是不是",
)
_SEMANTIC_NEIGHBORS = ("断奶", "泡奶", "热奶")
_OTHER_ACTION_MARKERS = ("喂药", "药", "换尿布", "尿布", "拍嗝")
_QUESTION_MARKS = frozenset({"?", "？"})


def correct_armed_followup(command: str) -> CorrectionResult | None:
    """Return one reviewed correction; callers own the armed-state precondition."""

    if not isinstance(command, str) or any(mark in command for mark in _QUESTION_MARKS):
        return None
    normalized = _normalize(command)
    if (
        not normalized
        or len(normalized) > 64
        or any(marker in normalized for marker in _BLOCKED_MARKERS)
        or any(marker in normalized for marker in _SEMANTIC_NEIGHBORS)
        or any(marker in normalized for marker in _OTHER_ACTION_MARKERS)
    ):
        return None
    correction = _CORRECTIONS.get(normalized)
    if correction is None:
        return None
    exact = classify_exact_action(correction.canonical_command)
    if (
        exact is None
        or exact.action_code != "feeding_command"
        or exact.risk != "low"
        or not exact.allow_ack
    ):
        return None
    return correction


def _normalize(value: str) -> str:
    return "".join(
        character
        for character in value.strip()
        if not character.isspace()
        and not unicodedata.category(character).startswith("P")
    )


__all__ = ["CorrectionResult", "correct_armed_followup"]
