from __future__ import annotations

from itertools import count
from pathlib import Path
from threading import Event

from packages.contracts.offline_application_rehearsal import load_rehearsal_suite
from services.voice.asr import AsrResult
from services.offline_application_sinks import RecordingReplySink


SUITE = Path(__file__).parents[1] / "fixtures/offline_application_rehearsal/scenarios.v1.json"


def ids(prefix: str):
    values = count(1)
    return lambda: f"{prefix}-{next(values):04d}"


def test_six_application_oracles_match_exact_fixture_counts(tmp_path: Path) -> None:
    from services.offline_application_rehearsal import run_application_oracle_scenario

    suite = load_rehearsal_suite(SUITE)
    scenarios = [item for item in suite.scenarios if item.lane == "application_oracle"]
    results = [
        run_application_oracle_scenario(
            scenario,
            tmp_path / scenario.scenario_id,
            event_id_factory=ids(f"event-{index}"),
            notification_id_factory=ids(f"notification-{index}"),
        )
        for index, scenario in enumerate(scenarios, 1)
    ]

    assert len(results) == 6
    assert all(item.status == "PASS" and item.reason == "ok" for item in results)
    assert [item.counts for item in results] == [item.expected_counts for item in scenarios]
    assert results[0].event_ids == ()
    assert results[1].counts["notification.risk_recovered"] == 1
    assert results[2].counts["face.output"] == 0
    assert results[3].counts["transition.adult_intervention.none"] == 1
    assert results[4].counts["semantic_conflict.face_without_subject"] == 1
    assert results[5].counts["resolution.subject_outside"] == 1
    assert results[5].counts["notification.risk_recovered"] == 0


def test_runner_preserves_fixture_order_for_application_lane(tmp_path: Path) -> None:
    from services.offline_application_rehearsal import OfflineApplicationRehearsalRunner

    suite = load_rehearsal_suite(SUITE)
    runner = OfflineApplicationRehearsalRunner(tmp_path)
    results = runner.run_functional_pack(suite)
    assert [item.scenario_id for item in results] == [
        item.scenario_id for item in suite.scenarios if item.lane == "application_oracle"
    ]


TEXT = {
    "wake": "小小",
    "feeding_exact": "开始喂奶",
    "diaper_start_exact": "开始换尿布",
    "diaper_complete_exact": "换好尿布了",
    "burping_start_exact": "开始拍嗝",
    "burping_complete_exact": "拍嗝结束",
    "ambiguous_multi": "小小开始换尿布然后开始拍嗝",
}
PCM = {key: (index + 1).to_bytes(2, "little") * 3200 for index, key in enumerate(TEXT)}


class FixedAsr:
    def transcribe(self, pcm: bytes) -> AsrResult:
        key = next(key for key, value in PCM.items() if value == pcm)
        return AsrResult(TEXT[key], "zh", 1)


def voice_components():
    reply_ids = count(1)
    return (
        PCM.__getitem__,
        FixedAsr,
        lambda behavior: RecordingReplySink(
            behavior=behavior,
            id_factory=lambda: f"reply-{next(reply_ids):08d}",
        ),
    )


def test_three_voice_and_three_joined_scenarios_match_exact_counts(tmp_path: Path) -> None:
    from services.offline_application_rehearsal import (
        run_joined_application_scenario,
        run_voice_application_scenario,
    )

    suite = load_rehearsal_suite(SUITE)
    provider, asr_factory, reply_factory = voice_components()
    event_ids = ids("event")
    notification_ids = ids("notification")
    results = []
    for scenario in suite.scenarios[6:]:
        if scenario.lane == "voice_application":
            result = run_voice_application_scenario(
                scenario, tmp_path / scenario.scenario_id,
                voice_fixture_provider=provider, asr_factory=asr_factory,
                reply_sink_factory=reply_factory,
            )
        else:
            result = run_joined_application_scenario(
                scenario, tmp_path / scenario.scenario_id,
                voice_fixture_provider=provider, asr_factory=asr_factory,
                reply_sink_factory=reply_factory,
                event_id_factory=event_ids,
                notification_id_factory=notification_ids,
            )
        results.append(result)

    assert len(results) == 6
    assert all(item.status == "PASS" for item in results)
    assert [item.counts for item in results] == [
        item.expected_counts for item in suite.scenarios[6:]
    ]
    assert all(item.counts["medication.output"] == 0 for item in results)
    assert all(item.counts["residual_reply_sessions"] == 0 for item in results)
    assert results[4].counts["face.output"] == 0
    assert results[5].counts["notification.risk_recovered"] == 0
    all_ids = [value for item in results for value in (*item.event_ids, *item.reply_ids)]
    assert len(all_ids) == len(set(all_ids))


def test_voice_asr_failure_is_closed_and_leaves_no_reply_session(tmp_path: Path) -> None:
    from services.offline_application_rehearsal import run_voice_application_scenario

    class BrokenAsr:
        def transcribe(self, _pcm: bytes) -> object:
            raise RuntimeError("private exception")

    scenario = load_rehearsal_suite(SUITE).scenarios[6]
    result = run_voice_application_scenario(
        scenario, tmp_path / "broken",
        voice_fixture_provider=PCM.__getitem__, asr_factory=BrokenAsr,
        reply_sink_factory=voice_components()[2],
    )
    assert result.status == "FAIL"
    assert result.reason == "voice_source_failed"
    assert "private" not in result.model_dump_json()
    assert result.counts["residual_reply_sessions"] == 0
