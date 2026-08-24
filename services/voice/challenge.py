"""One-time in-memory phrase freshness for private adult enrollment."""

from __future__ import annotations

import math
import re
import secrets
import time
import unicodedata
from collections.abc import Callable, Sequence
from dataclasses import dataclass


CHALLENGE_FAILED = "voice_enrollment_challenge_failed"
CHALLENGE_TTL_SECONDS = 60.0
_DIGITS = ("零", "一", "二", "三", "四", "五", "六", "七", "八", "九")
_ASCII_DIGITS = str.maketrans("0123456789", "零一二三四五六七八九")
_TOKEN = re.compile(r"^[0-9a-f]{32}$")


@dataclass(frozen=True)
class EnrollmentChallenge:
    challenge_id: str
    phrase: str


class EnrollmentChallengeSession:
    """Own at most one short-lived enrollment challenge and consume every attempt."""

    def __init__(
        self,
        *,
        clock: Callable[[], float] = time.monotonic,
        token_factory: Callable[[], str] = lambda: secrets.token_hex(16),
        digit_choice: Callable[[Sequence[str]], str] = secrets.choice,
    ) -> None:
        self._clock = clock
        self._token_factory = token_factory
        self._digit_choice = digit_choice
        self._active: tuple[str, str, float] | None = None

    def issue(self) -> EnrollmentChallenge:
        try:
            token = self._token_factory()
            now = float(self._clock())
            available = list(_DIGITS)
            selected: list[str] = []
            for _index in range(4):
                digit = self._digit_choice(tuple(available))
                if digit not in available:
                    raise ValueError(CHALLENGE_FAILED)
                available.remove(digit)
                selected.append(digit)
            digits = "".join(selected)
            if (
                type(token) is not str
                or _TOKEN.fullmatch(token) is None
                or not math.isfinite(now)
                or len(digits) != 4
                or any(digit not in _DIGITS for digit in digits)
            ):
                raise ValueError(CHALLENGE_FAILED)
            phrase = f"小小，我要说口令{digits}"
            self._active = (
                token,
                _normalize(phrase),
                now + CHALLENGE_TTL_SECONDS,
            )
            return EnrollmentChallenge(challenge_id=token, phrase=phrase)
        except Exception:
            self._active = None
            raise ValueError(CHALLENGE_FAILED) from None

    def consume(self, challenge_id: str, transcript: str) -> bool:
        active = self._active
        self._active = None
        try:
            now = float(self._clock())
            return bool(
                active is not None
                and math.isfinite(now)
                and now <= active[2]
                and type(challenge_id) is str
                and challenge_id == active[0]
                and type(transcript) is str
                and _normalize(transcript) == active[1]
            )
        except Exception:
            return False


def _normalize(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", value).translate(_ASCII_DIGITS)
    return "".join(
        character
        for character in normalized
        if not character.isspace()
        and not unicodedata.category(character).startswith(("P", "Z"))
    )


__all__ = [
    "CHALLENGE_FAILED",
    "EnrollmentChallenge",
    "EnrollmentChallengeSession",
]
