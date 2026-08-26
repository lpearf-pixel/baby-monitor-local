"""Closed deterministic parser for post-wake Voice Care feeding commands."""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from datetime import datetime
from typing import Literal


INTENT_UNCERTAIN = "intent_uncertain"
STATE_CONFLICT = "state_conflict"
_DIGEST = re.compile(r"^[a-f0-9]{64}$")
_NUMBER = r"(?:[0-9]+|[零一二三四五六七八九两十百千]+)"
_BOTTLE_COMMAND = re.compile(
    rf"(?P<finished>喂完了)?喝了(?P<amount>{_NUMBER})毫升(?P<liquid>配方奶|母乳)"
)
_DIRECT_COMMAND = re.compile(
    rf"(?P<finished>喂完了)?亲喂(?:了)?(?P<duration>{_NUMBER})分钟"
)
_CHINESE_DIGITS = {
    "零": 0,
    "一": 1,
    "二": 2,
    "两": 2,
    "三": 3,
    "四": 4,
    "五": 5,
    "六": 6,
    "七": 7,
    "八": 8,
    "九": 9,
}
_CHINESE_UNITS = {"十": 10, "百": 100, "千": 1_000}
_CANONICAL_CHINESE_DIGITS = "零一二三四五六七八九"

DialoguePhase = Literal["idle", "pending", "needs_confirmation"]
FeedingMode = Literal["unknown", "bottle", "direct_breastfeeding"]
IntentType = Literal[
    "feeding_start", "feeding_update", "feeding_end", "care_confirm", "care_cancel"
]


@dataclass(frozen=True)
class DialogueState:
    phase: DialoguePhase
    observed_at: str
    started_at: str | None = None
    expected_version: int | None = None
    mode: FeedingMode | None = None
    bottle_capacity_ml: int | None = None
    proposal_digest: str | None = None
    warning_digest: str | None = None
    warning_codes: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        _require_offset_time(self.observed_at)
        if self.phase == "idle":
            if any(
                value is not None
                for value in (
                    self.started_at,
                    self.expected_version,
                    self.mode,
                    self.bottle_capacity_ml,
                    self.proposal_digest,
                    self.warning_digest,
                )
            ) or self.warning_codes:
                raise ValueError(STATE_CONFLICT)
            return
        if (
            self.started_at is None
            or self.expected_version is None
            or self.expected_version < 1
            or self.mode not in {"unknown", "bottle", "direct_breastfeeding"}
        ):
            raise ValueError(STATE_CONFLICT)
        _require_offset_time(self.started_at)
        if self.bottle_capacity_ml is not None and not 1 <= self.bottle_capacity_ml <= 2_000:
            raise ValueError(STATE_CONFLICT)
        if self.phase == "pending":
            if self.proposal_digest is not None or self.warning_digest is not None or self.warning_codes:
                raise ValueError(STATE_CONFLICT)
            return
        if self.proposal_digest is None or _DIGEST.fullmatch(self.proposal_digest) is None:
            raise ValueError(STATE_CONFLICT)
        if self.warning_digest is not None and _DIGEST.fullmatch(self.warning_digest) is None:
            raise ValueError(STATE_CONFLICT)
        if len(self.warning_codes) > 4 or (self.warning_codes and self.warning_digest is None):
            raise ValueError(STATE_CONFLICT)

    @classmethod
    def idle(cls, *, observed_at: str) -> "DialogueState":
        return cls(phase="idle", observed_at=observed_at)

    @classmethod
    def pending(
        cls,
        *,
        observed_at: str,
        started_at: str,
        expected_version: int,
        mode: FeedingMode,
        bottle_capacity_ml: int | None = None,
    ) -> "DialogueState":
        return cls(
            phase="pending",
            observed_at=observed_at,
            started_at=started_at,
            expected_version=expected_version,
            mode=mode,
            bottle_capacity_ml=bottle_capacity_ml,
        )

    @classmethod
    def needs_confirmation(
        cls,
        *,
        observed_at: str,
        started_at: str,
        expected_version: int,
        mode: FeedingMode,
        proposal_digest: str,
        warning_digest: str | None,
        warning_codes: tuple[str, ...],
        bottle_capacity_ml: int | None = None,
    ) -> "DialogueState":
        return cls(
            phase="needs_confirmation",
            observed_at=observed_at,
            started_at=started_at,
            expected_version=expected_version,
            mode=mode,
            bottle_capacity_ml=bottle_capacity_ml,
            proposal_digest=proposal_digest,
            warning_digest=warning_digest,
            warning_codes=warning_codes,
        )


@dataclass(frozen=True)
class ParsedIntent:
    intent_type: IntentType | None
    payload: dict[str, object] | None
    reason: Literal["intent_uncertain", "state_conflict"] | None

    def as_pair(self) -> tuple[IntentType | None, dict[str, object] | None]:
        return self.intent_type, self.payload


def parse_feeding_command(command: str, state: DialogueState) -> ParsedIntent:
    """Return one closed typed intent or a transcript-free failure reason."""

    if not isinstance(command, str) or not isinstance(state, DialogueState):
        return _failed(INTENT_UNCERTAIN)
    normalized = _normalize(command)
    if not normalized or len(normalized) > 64:
        return _failed(INTENT_UNCERTAIN)

    start_modes: dict[str, FeedingMode] = {
        "我要开始喂奶": "unknown",
        "我要喂奶了": "unknown",
        "开始喂奶": "unknown",
        "开始喂配方奶": "bottle",
        "开始喂母乳": "bottle",
        "开始亲喂": "direct_breastfeeding",
    }
    if normalized in start_modes:
        if state.phase != "idle":
            return _failed(STATE_CONFLICT)
        return ParsedIntent(
            "feeding_start",
            {"mode": start_modes[normalized], "startedAt": state.observed_at},
            None,
        )

    if normalized in {"确认", "确认保存", "保存记录"}:
        if state.phase != "needs_confirmation":
            return _failed(STATE_CONFLICT)
        return ParsedIntent(
            "care_confirm",
            {
                "proposalDigest": state.proposal_digest,
                "expectedVersion": state.expected_version,
                "warningDigest": state.warning_digest,
                "confirmedWarningCodes": list(state.warning_codes),
            },
            None,
        )

    if normalized in {"取消", "取消记录"}:
        if state.phase not in {"pending", "needs_confirmation"}:
            return _failed(STATE_CONFLICT)
        return ParsedIntent(
            "care_cancel",
            {"expectedVersion": state.expected_version, "reason": "caregiver_cancelled"},
            None,
        )

    bottle = _BOTTLE_COMMAND.fullmatch(normalized)
    if bottle is not None:
        if state.phase != "pending" or state.mode not in {"unknown", "bottle"}:
            return _failed(STATE_CONFLICT)
        amount = _parse_bounded_number(bottle.group("amount"), maximum=2_000)
        if amount is None:
            return _failed(INTENT_UNCERTAIN)
        liquid_type = (
            "formula" if bottle.group("liquid") == "配方奶" else "expressed_breast_milk"
        )
        proposal = {
            "mode": "bottle",
            "startedAt": state.started_at,
            "endedAt": state.observed_at if bottle.group("finished") else None,
            "liquidType": liquid_type,
            "amountMl": amount,
            "bottleCapacityMl": state.bottle_capacity_ml,
        }
        if bottle.group("finished"):
            return ParsedIntent(
                "feeding_end",
                {"expectedVersion": state.expected_version, "finalProposal": proposal},
                None,
            )
        return ParsedIntent(
            "feeding_update",
            {"expectedVersion": state.expected_version, "proposal": proposal},
            None,
        )

    direct = _DIRECT_COMMAND.fullmatch(normalized)
    if direct is not None:
        if (
            state.phase != "pending"
            or state.mode not in {"unknown", "direct_breastfeeding"}
            or direct.group("finished") is None
        ):
            return _failed(STATE_CONFLICT)
        duration = _parse_bounded_number(direct.group("duration"), maximum=720)
        if duration is None:
            return _failed(INTENT_UNCERTAIN)
        return ParsedIntent(
            "feeding_end",
            {
                "expectedVersion": state.expected_version,
                "finalProposal": {
                    "mode": "direct_breastfeeding",
                    "startedAt": state.started_at,
                    "endedAt": state.observed_at,
                    "durationMinutes": duration,
                },
            },
            None,
        )

    return _failed(INTENT_UNCERTAIN)


def _normalize(value: str) -> str:
    return "".join(
        character
        for character in value.strip()
        if not character.isspace() and not unicodedata.category(character).startswith("P")
    )


def _parse_bounded_number(value: str, *, maximum: int) -> int | None:
    if value.isascii() and value.isdigit():
        parsed = int(value)
    else:
        normalized = value.replace("两", "二")
        total = 0
        current: int | None = None
        for character in normalized:
            if character in _CHINESE_DIGITS:
                current = _CHINESE_DIGITS[character]
            elif character in _CHINESE_UNITS:
                unit = _CHINESE_UNITS[character]
                total += (1 if current is None else current) * unit
                current = None
            else:
                return None
        parsed = total + (0 if current is None else current)
        if _format_chinese_number(parsed) != normalized:
            return None
    return parsed if 1 <= parsed <= maximum else None


def _format_chinese_number(value: int) -> str:
    result: list[str] = []
    zero_pending = False
    for divisor, suffix in ((1_000, "千"), (100, "百"), (10, "十"), (1, "")):
        digit = (value // divisor) % 10
        remainder = value % divisor
        if digit == 0:
            if result and remainder:
                zero_pending = True
            continue
        if zero_pending:
            result.append("零")
            zero_pending = False
        if divisor != 10 or digit != 1 or result:
            result.append(_CANONICAL_CHINESE_DIGITS[digit])
        result.append(suffix)
    return "".join(result)


def _require_offset_time(value: str) -> None:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (TypeError, ValueError):
        raise ValueError(STATE_CONFLICT) from None
    if parsed.tzinfo is None:
        raise ValueError(STATE_CONFLICT)


def _failed(reason: str) -> ParsedIntent:
    if reason == STATE_CONFLICT:
        return ParsedIntent(None, None, STATE_CONFLICT)
    return ParsedIntent(None, None, INTENT_UNCERTAIN)


__all__ = [
    "DialogueState",
    "INTENT_UNCERTAIN",
    "ParsedIntent",
    "STATE_CONFLICT",
    "parse_feeding_command",
]
