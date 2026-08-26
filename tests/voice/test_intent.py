from __future__ import annotations

import pytest

from services.voice.intent import DialogueState, parse_feeding_command


STARTED_AT = "2026-08-23T08:00:00.000Z"
OBSERVED_AT = "2026-08-23T08:20:00.000Z"


def test_idle_state_accepts_only_closed_feeding_starts() -> None:
    state = DialogueState.idle(observed_at=STARTED_AT)
    assert parse_feeding_command("开始喂配方奶", state).as_pair() == (
        "feeding_start",
        {"mode": "bottle", "startedAt": STARTED_AT},
    )
    assert parse_feeding_command("开始亲喂", state).as_pair() == (
        "feeding_start",
        {"mode": "direct_breastfeeding", "startedAt": STARTED_AT},
    )
    assert parse_feeding_command("我要开始喂奶", state).as_pair() == (
        "feeding_start",
        {"mode": "unknown", "startedAt": STARTED_AT},
    )
    assert parse_feeding_command("我要喂奶了", state).as_pair() == (
        "feeding_start",
        {"mode": "unknown", "startedAt": STARTED_AT},
    )


def test_feeding_start_alias_conflicts_outside_idle() -> None:
    pending = DialogueState.pending(
        observed_at=OBSERVED_AT,
        started_at=STARTED_AT,
        expected_version=1,
        mode="unknown",
    )

    result = parse_feeding_command("我要喂奶了", pending)

    assert result.intent_type is None
    assert result.payload is None
    assert result.reason == "state_conflict"


@pytest.mark.parametrize(
    "command",
    ["我要喂奶", "我准备喂奶了", "我要去喂奶了"],
)
def test_unapproved_feeding_start_near_matches_remain_uncertain(command: str) -> None:
    result = parse_feeding_command(command, DialogueState.idle(observed_at=STARTED_AT))

    assert result.intent_type is None
    assert result.payload is None
    assert result.reason == "intent_uncertain"


def test_formula_finish_requires_actual_consumed_ml() -> None:
    state = DialogueState.pending(
        observed_at=OBSERVED_AT,
        started_at=STARTED_AT,
        expected_version=2,
        mode="bottle",
    )
    result = parse_feeding_command("喂完了，喝了六十毫升配方奶", state)
    assert result.as_pair() == (
        "feeding_end",
        {
            "expectedVersion": 2,
            "finalProposal": {
                "mode": "bottle",
                "startedAt": STARTED_AT,
                "endedAt": OBSERVED_AT,
                "liquidType": "formula",
                "amountMl": 60,
                "bottleCapacityMl": None,
            },
        },
    )


def test_pending_bottle_update_remains_nonterminal() -> None:
    state = DialogueState.pending(
        observed_at=OBSERVED_AT,
        started_at=STARTED_AT,
        expected_version=1,
        mode="bottle",
        bottle_capacity_ml=150,
    )
    result = parse_feeding_command("喝了90毫升母乳", state)
    assert result.as_pair() == (
        "feeding_update",
        {
            "expectedVersion": 1,
            "proposal": {
                "mode": "bottle",
                "startedAt": STARTED_AT,
                "endedAt": None,
                "liquidType": "expressed_breast_milk",
                "amountMl": 90,
                "bottleCapacityMl": 150,
            },
        },
    )


def test_direct_finish_requires_explicit_minutes() -> None:
    state = DialogueState.pending(
        observed_at=OBSERVED_AT,
        started_at=STARTED_AT,
        expected_version=3,
        mode="direct_breastfeeding",
    )
    result = parse_feeding_command("喂完了，亲喂二十分钟", state)
    assert result.as_pair() == (
        "feeding_end",
        {
            "expectedVersion": 3,
            "finalProposal": {
                "mode": "direct_breastfeeding",
                "startedAt": STARTED_AT,
                "endedAt": OBSERVED_AT,
                "durationMinutes": 20,
            },
        },
    )


def test_confirmation_and_cancel_use_only_server_state() -> None:
    confirmation = DialogueState.needs_confirmation(
        observed_at=OBSERVED_AT,
        started_at=STARTED_AT,
        expected_version=4,
        mode="bottle",
        proposal_digest="a" * 64,
        warning_digest=None,
        warning_codes=(),
    )
    assert parse_feeding_command("确认保存", confirmation).as_pair() == (
        "care_confirm",
        {
            "proposalDigest": "a" * 64,
            "expectedVersion": 4,
            "warningDigest": None,
            "confirmedWarningCodes": [],
        },
    )
    pending = DialogueState.pending(
        observed_at=OBSERVED_AT,
        started_at=STARTED_AT,
        expected_version=2,
        mode="bottle",
    )
    assert parse_feeding_command("取消记录", pending).as_pair() == (
        "care_cancel",
        {"expectedVersion": 2, "reason": "caregiver_cancelled"},
    )


@pytest.mark.parametrize(
    "command",
    [
        "喂完了，喝了一些",
        "喂完了，喝了六十克配方奶",
        "记录维生素D",
        "宝宝刚才喝了奶",
        "喂完了，喝了零毫升配方奶",
        "喂完了，喝了两千零一毫升配方奶",
        "喂完了，喝了一二毫升配方奶",
        "喂完了，喝了十百毫升配方奶",
    ],
)
def test_ambiguous_or_unsupported_commands_fail_closed(command: str) -> None:
    state = DialogueState.pending(
        observed_at=OBSERVED_AT,
        started_at=STARTED_AT,
        expected_version=2,
        mode="bottle",
    )
    result = parse_feeding_command(command, state)
    assert result.intent_type is None
    assert result.payload is None
    assert result.reason == "intent_uncertain"


def test_command_state_conflicts_fail_closed() -> None:
    idle = DialogueState.idle(observed_at=OBSERVED_AT)
    assert parse_feeding_command("喂完了，喝了60毫升配方奶", idle).reason == "state_conflict"
    pending = DialogueState.pending(
        observed_at=OBSERVED_AT,
        started_at=STARTED_AT,
        expected_version=2,
        mode="direct_breastfeeding",
    )
    assert parse_feeding_command("喝了60毫升配方奶", pending).reason == "state_conflict"
