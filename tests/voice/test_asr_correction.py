from __future__ import annotations

from types import MappingProxyType

import pytest

import services.voice.asr_correction as correction_module
from services.voice.asr_correction import CorrectionResult, correct_armed_followup


def test_reviewed_synthetic_feeding_confusion_is_correctable() -> None:
    result = correct_armed_followup("开始为奶")

    assert result is not None
    assert result.canonical_command == "开始喂奶"
    assert result.action_family == "feeding"


@pytest.mark.parametrize(
    "command",
    [
        "不要开始喂奶",
        "还没开始喂奶",
        "不喂奶",
        "停止喂奶",
        "结束喂奶",
        "取消开始喂奶",
        "开始喂奶吗",
        "要不要开始喂奶",
        "是不是开始喂奶",
        "开始断奶",
        "开始泡奶",
        "开始热奶",
        "开始喂药",
        "开始换尿布",
        "开始拍嗝",
        "宝宝刚才喝了奶",
        "开始喂耐",
        "开始给奶",
        "开始吃奶",
        "开始未来",
    ],
)
def test_correction_rejects_every_unreviewed_or_unsafe_form(command: str) -> None:
    assert correct_armed_followup(command) is None


@pytest.mark.parametrize(
    "command",
    [
        "开时喂奶",
        "开始围奶",
        "开始喂耐",
        "开始喂",
        "开始喂牛奶",
        "现在开始喂奶",
    ],
)
def test_unreviewed_nearby_strings_do_not_gain_generic_fuzzy_acceptance(
    command: str,
) -> None:
    assert correct_armed_followup(command) is None


def test_stale_mapping_must_reenter_exact_low_risk_feeding_classifier(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        correction_module,
        "_CORRECTIONS",
        MappingProxyType(
            {"synthetic": CorrectionResult("开始喂药", "feeding")}
        ),
    )

    assert correct_armed_followup("synthetic") is None
