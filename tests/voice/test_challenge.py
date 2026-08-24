from __future__ import annotations

import pytest

from services.voice.challenge import (
    CHALLENGE_FAILED,
    EnrollmentChallenge,
    EnrollmentChallengeSession,
)


class Clock:
    def __init__(self) -> None:
        self.value = 100.0

    def __call__(self) -> float:
        return self.value


def session(clock: Clock | None = None) -> EnrollmentChallengeSession:
    selected = iter(("三", "五", "七", "九", "一", "二", "四", "八"))
    return EnrollmentChallengeSession(
        clock=clock or Clock(),
        token_factory=lambda: "a" * 32,
        digit_choice=lambda _digits: next(selected),
    )


def test_challenge_is_one_time_and_accepts_only_its_normalized_phrase() -> None:
    challenges = session()

    issued = challenges.issue()

    assert issued == EnrollmentChallenge(
        challenge_id="a" * 32,
        phrase="小小，我要说口令三五七九",
    )
    assert challenges.consume(issued.challenge_id, " 小小 我要说口令 3 5 7 9。") is True
    assert challenges.consume(issued.challenge_id, issued.phrase) is False


def test_wrong_attempt_consumes_the_challenge_before_comparison() -> None:
    challenges = session()
    issued = challenges.issue()

    assert challenges.consume(issued.challenge_id, "小小，我要说口令一二三四") is False
    assert challenges.consume(issued.challenge_id, issued.phrase) is False


def test_new_issue_invalidates_old_challenge_and_expiry_is_closed() -> None:
    clock = Clock()
    selected = iter(("一", "二", "三", "四", "五", "六", "七", "八"))
    tokens = iter(("a" * 32, "b" * 32))
    challenges = EnrollmentChallengeSession(
        clock=clock,
        token_factory=lambda: next(tokens),
        digit_choice=lambda _digits: next(selected),
    )
    old = challenges.issue()
    current = challenges.issue()

    assert challenges.consume(old.challenge_id, old.phrase) is False
    clock.value = 161.0
    assert challenges.consume(current.challenge_id, current.phrase) is False


@pytest.mark.parametrize(
    "token",
    ("", "A" * 32, "private-token", "a" * 31, "a" * 33),
)
def test_invalid_generator_output_fails_with_one_stable_reason(token: str) -> None:
    challenges = EnrollmentChallengeSession(token_factory=lambda: token)

    with pytest.raises(ValueError, match=f"^{CHALLENGE_FAILED}$") as error:
        challenges.issue()

    if token:
        assert token not in str(error.value)


def test_challenge_refuses_repeated_or_unknown_digit_generator_output() -> None:
    challenges = EnrollmentChallengeSession(
        token_factory=lambda: "a" * 32,
        digit_choice=lambda _digits: "一",
    )

    with pytest.raises(ValueError, match=f"^{CHALLENGE_FAILED}$"):
        challenges.issue()
