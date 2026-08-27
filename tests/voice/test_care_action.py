from __future__ import annotations

import pytest

from services.voice.care_action import CareActionMatch, classify_exact_action


@pytest.mark.parametrize(
    ("command", "code", "risk", "allow_ack"),
    [
        ("开始喂奶", "feeding_command", "low", True),
        ("开始换尿布", "diaper_change_start", "low", True),
        ("换好尿布了", "diaper_change_complete", "low", True),
        ("开始拍嗝", "burping_start", "low", True),
        ("拍嗝结束", "burping_complete", "low", True),
        ("开始喂药", "medication_start_candidate", "high", False),
        ("喂药完成", "medication_complete_candidate", "high", False),
    ],
)
def test_exact_closed_actions(
    command: str,
    code: str,
    risk: str,
    allow_ack: bool,
) -> None:
    result = classify_exact_action(command)

    assert result is not None
    assert (result.action_code, result.risk, result.allow_ack) == (
        code,
        risk,
        allow_ack,
    )


@pytest.mark.parametrize(
    "command",
    [
        " 开始 换尿布。 ",
        "拍嗝，结束。",
        "开始\t喂药。",
    ],
)
def test_exact_actions_normalize_only_space_and_punctuation(command: str) -> None:
    assert classify_exact_action(command) is not None


@pytest.mark.parametrize(
    "command",
    [
        "宝宝刚才喝了奶",
        "刚换过尿布",
        "开始换尿布然后开始拍嗝",
        "开始喂奶并开始喂药",
        "开始断奶",
        "开始泡奶",
        "开始热奶",
        "开始喂药？",
        "开始换尿布吗",
        "拍嗝结束吗",
        "",
        "普" * 65,
    ],
)
def test_exact_actions_reject_unknown_ordinary_or_multiple_domains(command: str) -> None:
    assert classify_exact_action(command) is None


def test_high_risk_action_can_never_allow_acknowledgement() -> None:
    with pytest.raises(ValueError, match="invalid_care_action"):
        CareActionMatch(
            action_code="medication_start_candidate",
            risk="high",
            allow_ack=True,
        )
