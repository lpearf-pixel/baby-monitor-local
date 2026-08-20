from __future__ import annotations

import pytest

from services.voice.wake import validate_wake_prefix


@pytest.mark.parametrize("text", ["小小，我是爸爸", "  小小 我要喂奶了。"])
def test_exact_xiaoxiao_prefix_is_accepted(text: str) -> None:
    assert validate_wake_prefix(text).accepted is True


@pytest.mark.parametrize("text", ["嘿，小小，我是爸爸", "晓晓，我是爸爸", "我叫小小"])
def test_non_exact_prefix_fails_closed(text: str) -> None:
    result = validate_wake_prefix(text)

    assert result.accepted is False
    assert result.reason == "wake_not_detected"
    assert result.command is None


def test_success_exposes_only_the_post_prefix_command() -> None:
    result = validate_wake_prefix(" \t，小小： 我要喂奶了。 \n")

    assert result.accepted is True
    assert result.command == "我要喂奶了"
    assert result.reason is None


def test_missing_post_prefix_command_fails_without_exposing_text() -> None:
    result = validate_wake_prefix("。小小。")

    assert result.accepted is False
    assert result.command is None
    assert result.reason == "wake_command_missing"


@pytest.mark.parametrize("text", ["", "  ，。  "])
def test_empty_normalized_text_is_not_a_wake(text: str) -> None:
    result = validate_wake_prefix(text)

    assert result.accepted is False
    assert result.command is None
    assert result.reason == "wake_not_detected"
