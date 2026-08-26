from __future__ import annotations

import pytest

from services.voice.wake import classify_wake, validate_wake_prefix


@pytest.mark.parametrize("text", ["小小，我是爸爸", "  小小 我要喂奶了。"])
def test_exact_xiaoxiao_prefix_is_accepted(text: str) -> None:
    assert validate_wake_prefix(text).accepted is True


@pytest.mark.parametrize(
    "text",
    [
        "小小我是爸爸现在开始喂奶",
        "小小我是妈妈现在开始喂奶",
        "小小宝宝喝了九十毫升配方奶",
        "小小喂奶结束",
        "小小取消这次记录",
        "小小开始喂配方奶",
        "小小开始亲喂",
        "小小喂完了喝了九十毫升配方奶",
        "小小亲喂了十分钟",
        "小小确认保存",
    ],
)
def test_fixed_care_vocabulary_proves_a_punctuation_free_boundary(text: str) -> None:
    result = validate_wake_prefix(text)

    assert result.accepted is True
    assert result.command == text.removeprefix("小小")


@pytest.mark.parametrize(
    "text",
    [
        "你好，小小，我是爸爸",
        "晓晓，我是爸爸",
        "我叫小小",
        "小小鸟飞走了",
        "小小小心一点",
        "小小小小取消记录",
        "小小取消小小记录",
        "小小，取消小小记录",
        "小小我是叔叔开始喂奶",
        "小小今天天气不错",
        "小小打开摄像头",
    ],
)
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


@pytest.mark.parametrize(
    ("text", "kind", "command"),
    [
        ("小小", "standalone_wake", None),
        ("嘿，小小", "standalone_wake", None),
        ("嘿小小", "standalone_wake", None),
        (" 。小小， ", "standalone_wake", None),
        ("小小，开始喂奶", "wake_with_command", "开始喂奶"),
        ("嘿，小小，我要喂奶了", "wake_with_command", "我要喂奶了"),
        ("嘿小小我要喂奶了", "wake_with_command", "我要喂奶了"),
        ("小小今天天气", "not_wake", None),
        ("你好小小", "not_wake", None),
        ("嘿嘿，小小，我要喂奶了", "not_wake", None),
        ("我说嘿，小小，我要喂奶了", "not_wake", None),
        ("嘿，小小，小小，我要喂奶了", "not_wake", None),
    ],
)
def test_listen_only_wake_classifier_is_exact_and_closed(
    text: str, kind: str, command: str | None
) -> None:
    result = classify_wake(text)

    assert result.kind == kind
    assert result.command == command


@pytest.mark.parametrize("text", ["", "  ，。  "])
def test_empty_normalized_text_is_not_a_wake(text: str) -> None:
    result = validate_wake_prefix(text)

    assert result.accepted is False
    assert result.command is None
    assert result.reason == "wake_not_detected"
