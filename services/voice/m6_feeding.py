"""Bounded offline M6 feeding conversation orchestration.

This module deliberately stops at a typed gateway boundary.  It does not write a
Baby Care database and it never sends a mixed proposal to the v1 endpoint.
"""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from datetime import datetime
from typing import Callable, Literal, Protocol


M6_MAX_TURNS = 16
_NUMBER = r"(?:[0-9]+|[零一二三四五六七八九两十百千]+)"
_COMPONENT = re.compile(rf"(?P<correction>改成|更正|补充)?(?P<liquid>母乳|配方奶)(?P<amount>{_NUMBER})毫升")
_DIRECT = re.compile(rf"(?P<correction>改成|更正)?亲喂(?P<duration>{_NUMBER})分钟")
_DIGITS = {"零": 0, "一": 1, "二": 2, "两": 2, "三": 3, "四": 4, "五": 5,
           "六": 6, "七": 7, "八": 8, "九": 9}
_UNITS = {"十": 10, "百": 100, "千": 1_000}


class M6SessionGateway(Protocol):
    """Typed Baby Care boundary; production implementations own auth and commits."""

    def start(self, *, occurred_at: datetime) -> str: ...

    def update(self, *, session_id: str, components: tuple[dict[str, object], ...]) -> None: ...

    def end(self, *, session_id: str, components: tuple[dict[str, object], ...]) -> str: ...

    def confirm(self, *, session_id: str, proposal_id: str) -> str: ...

    def cancel(self, *, session_id: str) -> str: ...

    def query(self) -> tuple[dict[str, object], ...]: ...


class M6Output(Protocol):
    def speak_code(self, code: str) -> bool: ...


@dataclass(frozen=True, slots=True)
class M6ParsedUtterance:
    kind: Literal["feeding_start", "feeding_component", "feeding_end", "confirm", "cancel", "query", "resume", "uncertain"]
    component: dict[str, object] | None = None
    correction: bool = False


@dataclass(frozen=True, slots=True)
class M6Result:
    code: str
    phase: Literal["idle", "pending", "needs_confirmation", "saved", "uncertain"]
    records: tuple[dict[str, object], ...] = ()
    audio_output_ok: bool | None = None


class M6FeedingCoordinator:
    """In-memory eight-second turn window with idempotent gateway calls."""

    def __init__(
        self,
        gateway: M6SessionGateway,
        *,
        context_seconds: float = 8.0,
        output: M6Output | None = None,
        max_turns: int = M6_MAX_TURNS,
    ) -> None:
        if type(context_seconds) not in (int, float) or not 1 <= context_seconds <= 30:
            raise ValueError("m6_invalid_context_window")
        if type(max_turns) is not int or not 1 <= max_turns <= M6_MAX_TURNS:
            raise ValueError("m6_invalid_turn_limit")
        self._gateway = gateway
        self._context_seconds = float(context_seconds)
        self._output = output
        self._max_turns = max_turns
        self._session_id: str | None = None
        self._components: tuple[dict[str, object], ...] = ()
        self._proposal_id: str | None = None
        self._phase: Literal["idle", "pending", "needs_confirmation", "saved"] = "idle"
        self._last_at: datetime | None = None
        self._context_expired = False
        self._seen: dict[str, M6Result] = {}

    def process(self, text: str, observed_at: datetime, *, request_id: str) -> M6Result:
        if observed_at.tzinfo is None or observed_at.utcoffset() is None:
            return self._result("uncertain", "uncertain")
        if not isinstance(request_id, str) or not request_id or len(request_id) > 128:
            return self._result("uncertain", "uncertain")
        prior = self._seen.get(request_id)
        if prior is not None:
            return prior
        if self._last_at is not None and (observed_at - self._last_at).total_seconds() > self._context_seconds:
            self._context_expired = True
            self._last_at = None
        parsed = parse_m6_utterance(text)
        if self._context_expired and parsed.kind not in {"resume", "query", "cancel", "confirm"}:
            result = self._result("context_expired", self._phase)
            self._remember(request_id, result)
            return result
        result = self._apply(parsed, observed_at)
        if result.code != "context_expired" and parsed.kind not in {"query", "cancel"}:
            self._last_at = observed_at
        self._remember(request_id, result)
        return result

    def _apply(self, parsed: M6ParsedUtterance, observed_at: datetime) -> M6Result:
        if parsed.kind == "uncertain":
            return self._result("uncertain", "uncertain")
        try:
            if parsed.kind == "feeding_start":
                if self._phase == "saved":
                    self._clear()
                if self._phase != "idle":
                    return self._result("state_conflict", self._phase)
                session_id = self._gateway.start(occurred_at=observed_at)
                if not isinstance(session_id, str) or not 0 < len(session_id) <= 128:
                    raise ValueError("m6_gateway_invalid_session")
                self._session_id = session_id
                self._components = ()
                self._proposal_id = None
                self._phase = "pending"
                self._context_expired = False
                return self._result("accepted_pending", "pending")
            if parsed.kind == "resume":
                if self._session_id is None or self._phase not in {"pending", "needs_confirmation"}:
                    return self._result("state_conflict", self._phase)
                self._context_expired = False
                return self._result("task_resumed", self._phase)
            if parsed.kind == "feeding_component":
                if self._context_expired:
                    return self._result("context_expired", self._phase)
                if self._phase != "pending" or self._session_id is None or parsed.component is None:
                    return self._result("state_conflict", self._phase)
                if parsed.correction and not self._components:
                    return self._result("state_conflict", "pending")
                next_components = self._components[:-1] + (parsed.component,) if parsed.correction else self._components + (parsed.component,)
                if len(next_components) > self._max_turns:
                    return self._result("too_many_turns", "pending")
                self._gateway.update(session_id=self._session_id, components=next_components)
                self._components = next_components
                return self._result("accepted_pending", "pending")
            if parsed.kind == "feeding_end":
                if self._context_expired:
                    return self._result("context_expired", self._phase)
                if self._phase != "pending" or self._session_id is None or not self._components:
                    return self._result("state_conflict", self._phase)
                proposal_id = self._gateway.end(session_id=self._session_id, components=self._components)
                if not isinstance(proposal_id, str) or not 0 < len(proposal_id) <= 128:
                    raise ValueError("m6_gateway_invalid_proposal")
                self._proposal_id = proposal_id
                self._phase = "needs_confirmation"
                return self._result("needs_confirmation", "needs_confirmation")
            if parsed.kind == "confirm":
                if self._phase != "needs_confirmation" or self._session_id is None or self._proposal_id is None:
                    return self._result("state_conflict", self._phase)
                code = self._gateway.confirm(session_id=self._session_id, proposal_id=self._proposal_id)
                if code == "saved":
                    self._phase = "saved"
                    self._context_expired = False
                return self._result(code, "saved" if code == "saved" else "needs_confirmation")
            if parsed.kind == "cancel":
                if self._session_id is None or self._phase not in {"pending", "needs_confirmation"}:
                    return self._result("state_conflict", self._phase)
                code = self._gateway.cancel(session_id=self._session_id)
                self._clear()
                return self._result(code, "idle")
            if parsed.kind == "query":
                return self._result("query_result", self._phase, self._gateway.query())
        except Exception:
            return self._result("temporarily_unavailable", self._phase)
        return self._result("uncertain", "uncertain")

    def _result(
        self,
        code: str,
        phase: Literal["idle", "pending", "needs_confirmation", "saved", "uncertain"],
        records: tuple[dict[str, object], ...] = (),
    ) -> M6Result:
        audio_output_ok: bool | None = None
        if self._output is not None:
            try:
                audio_output_ok = bool(self._output.speak_code(code))
            except Exception:
                audio_output_ok = False
        return M6Result(code, phase, records, audio_output_ok)

    def _remember(self, request_id: str, result: M6Result) -> None:
        self._seen[request_id] = result
        if len(self._seen) > 128:
            self._seen.pop(next(iter(self._seen)))

    def _clear(self) -> None:
        self._session_id = None
        self._components = ()
        self._proposal_id = None
        self._phase = "idle"
        self._last_at = None
        self._context_expired = False


def parse_m6_utterance(text: str) -> M6ParsedUtterance:
    if not isinstance(text, str):
        return M6ParsedUtterance("uncertain")
    normalized = "".join(
        character for character in text.strip()
        if not character.isspace() and not unicodedata.category(character).startswith("P")
    )
    if not normalized or len(normalized) > 64:
        return M6ParsedUtterance("uncertain")
    if normalized in {"开始喂奶", "我要喂奶了", "开始喂配方奶", "开始喂母乳"}:
        return M6ParsedUtterance("feeding_start")
    if normalized in {"结束", "喂奶结束", "结束喂奶"}:
        return M6ParsedUtterance("feeding_end")
    if normalized in {"确认", "确认保存", "保存记录"}:
        return M6ParsedUtterance("confirm")
    if normalized in {"取消", "取消记录"}:
        return M6ParsedUtterance("cancel")
    if normalized in {"查询记录", "最近记录", "查喂奶记录"}:
        return M6ParsedUtterance("query")
    if normalized in {"继续喂奶", "恢复喂奶", "继续记录"}:
        return M6ParsedUtterance("resume")
    match = _COMPONENT.fullmatch(normalized)
    if match is not None:
        amount = _parse_number(match.group("amount"), maximum=2_000)
        if amount is None:
            return M6ParsedUtterance("uncertain")
        return M6ParsedUtterance(
            "feeding_component",
            {"kind": "bottle", "liquidType": "formula" if match.group("liquid") == "配方奶" else "expressed_breast_milk", "amountMl": amount},
            match.group("correction") in {"改成", "更正"},
        )
    direct = _DIRECT.fullmatch(normalized)
    if direct is not None:
        duration = _parse_number(direct.group("duration"), maximum=720)
        if duration is None:
            return M6ParsedUtterance("uncertain")
        return M6ParsedUtterance("feeding_component", {"kind": "direct_breastfeeding", "durationMinutes": duration}, bool(direct.group("correction")))
    return M6ParsedUtterance("uncertain")


def _parse_number(value: str, *, maximum: int) -> int | None:
    if value.isascii() and value.isdigit():
        number = int(value)
    else:
        total = 0
        current: int | None = None
        for char in value.replace("两", "二"):
            if char in _DIGITS:
                current = _DIGITS[char]
            elif char in _UNITS:
                total += (current if current is not None else 1) * _UNITS[char]
                current = None
            else:
                return None
        number = total + (current or 0)
    return number if 1 <= number <= maximum else None


__all__ = ["M6FeedingCoordinator", "M6Output", "M6ParsedUtterance", "M6Result", "M6SessionGateway", "parse_m6_utterance"]
