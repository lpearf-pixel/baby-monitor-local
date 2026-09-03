from __future__ import annotations

from itertools import count
from pathlib import Path

import pytest

from packages.contracts.offline_application_rehearsal import load_rehearsal_suite
from services.offline_application_sinks import RecordingReplySink
from services.voice.asr import AsrResult


SUITE_PATH = Path(__file__).parents[1] / "fixtures/offline_application_rehearsal/scenarios.v1.json"
TEXT = {
    "wake": "小小", "feeding_exact": "开始喂奶",
    "diaper_start_exact": "开始换尿布", "diaper_complete_exact": "换好尿布了",
    "burping_start_exact": "开始拍嗝", "burping_complete_exact": "拍嗝结束",
    "ambiguous_multi": "小小开始换尿布然后开始拍嗝",
}
PCM = {key: (index + 1).to_bytes(2, "little") * 3200 for index, key in enumerate(TEXT)}


class Asr:
    def transcribe(self, pcm: bytes) -> AsrResult:
        key = next(key for key, value in PCM.items() if value == pcm)
        return AsrResult(TEXT[key], "zh", 1)


def runner_factory(tmp_path: Path):
    from services.offline_application_rehearsal import OfflineApplicationRehearsalRunner

    reply_number = count(1)
    return lambda iteration: OfflineApplicationRehearsalRunner(
        tmp_path / f"iteration-{iteration}",
        voice_fixture_provider=PCM.__getitem__,
        asr_factory=Asr,
        reply_sink_factory=lambda behavior: RecordingReplySink(
            behavior=behavior,
            id_factory=lambda: f"reply-{next(reply_number):08d}",
        ),
    )


def test_repetition_gate_runs_ten_fresh_packs_and_fifty_instances(tmp_path: Path) -> None:
    from services.offline_application_rehearsal import run_repetition_gate

    result = run_repetition_gate(runner_factory(tmp_path), load_rehearsal_suite(SUITE_PATH))
    assert result.status == "PASS"
    assert result.reason == "ok"
    assert len(result.iterations) == 10
    assert all(item.counts == {"functional_pass": 12} for item in result.iterations)
    assert len({item.stable_digest for item in result.iterations}) == 1
    assert result.cross_risk_instances == result.cross_risk_pass == 50


@pytest.mark.parametrize(
    ("mutation", "reason"),
    [("duplicate", "duplicate_generated_id"),
     ("residual", "residual_reply_session"),
     ("face", "no_baby_face_output")],
)
def test_repetition_gate_fails_closed_on_invariant_break(
    tmp_path: Path, mutation: str, reason: str
) -> None:
    from services.offline_application_rehearsal import run_repetition_gate

    base_factory = runner_factory(tmp_path)

    class MutatingRunner:
        def __init__(self, iteration: int) -> None:
            self.inner = base_factory(iteration)

        def run_functional_pack(self, suite):
            results = list(self.inner.run_functional_pack(suite))
            if mutation == "duplicate":
                first = next(index for index, item in enumerate(results) if item.event_ids)
                second = next(index for index, item in enumerate(results[first + 1:], first + 1) if item.event_ids)
                results[second] = results[second].model_copy(
                    update={"event_ids": (results[first].event_ids[0],)}
                )
            elif mutation == "residual":
                index = next(i for i, item in enumerate(results) if "residual_reply_sessions" in item.counts)
                counts = dict(results[index].counts)
                counts["residual_reply_sessions"] = 1
                results[index] = results[index].model_copy(update={"counts": counts})
            else:
                index = next(i for i, item in enumerate(results) if item.scenario_id == "APP-EMPTY-BED-01")
                counts = dict(results[index].counts)
                counts["face.output"] = 1
                results[index] = results[index].model_copy(update={"counts": counts})
            return tuple(results)

    result = run_repetition_gate(
        lambda iteration: MutatingRunner(iteration), load_rehearsal_suite(SUITE_PATH)
    )
    assert result.status == "FAIL"
    assert result.reason == reason
