from __future__ import annotations

import json
import wave
from dataclasses import dataclass
from pathlib import Path

import pytest
from services.voice.asr import AsrResult
from services.voice.tts import PlaybackResult, PlaybackStatus
from tools.voice_stability_runner import (
    VoiceRegressionCase,
    VoiceRegressionRunner,
    load_voice_manifest,
)


PCM = b"p" * 32_000


class Asr:
    def __init__(self, text: str) -> None:
        self.text = text

    def transcribe(self, pcm: bytes) -> AsrResult:
        assert pcm == PCM
        return AsrResult(self.text, "zh", 80)


@dataclass
class Output:
    status: PlaybackStatus = PlaybackStatus.COMPLETE
    active: int = 0
    max_active: int = 0

    def speak_code_result(self, _code: str, _cancelled) -> PlaybackResult:
        self.active += 1
        self.max_active = max(self.max_active, self.active)
        self.active -= 1
        return PlaybackResult(self.status)


def test_runner_repeats_a_fixed_audio_case_and_reports_latency_percentiles() -> None:
    case = VoiceRegressionCase(
        test_id="voice-ok",
        pcm=PCM,
        expected_response="voice_test_ok",
        push_to_talk=True,
    )
    outputs: list[Output] = []
    runner = VoiceRegressionRunner(
        cases=(case,),
        asr_factory=lambda _case: Asr("测试语音回复"),
        output_factory=lambda _case: outputs.append(Output()) or outputs[-1],
    )

    report = runner.run(repetitions=1_000)

    assert report.total == 1_000
    assert report.passed == 1_000
    assert report.failed == 0
    assert report.ambiguous == 0
    assert report.software_test_pass is True
    assert report.p50_ms >= 0
    assert report.p95_ms >= report.p50_ms
    assert report.p99_ms >= report.p95_ms
    assert max(output.max_active for output in outputs) == 1


def test_runner_keeps_ambiguous_playback_out_of_reliable_pass_count() -> None:
    case = VoiceRegressionCase(
        test_id="voice-ambiguous",
        pcm=PCM,
        expected_response="voice_test_ok",
        push_to_talk=True,
    )
    runner = VoiceRegressionRunner(
        cases=(case,),
        asr_factory=lambda _case: Asr("测试语音回复"),
        output_factory=lambda _case: Output(PlaybackStatus.AMBIGUOUS),
    )

    report = runner.run(repetitions=3)

    assert report.total == 3
    assert report.passed == 0
    assert report.failed == 0
    assert report.ambiguous == 3
    assert report.software_test_pass is False


def _write_wav(path: Path, *, channels: int = 1, rate: int = 16_000) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as output:
        output.setnchannels(channels)
        output.setsampwidth(2)
        output.setframerate(rate)
        output.writeframes((1).to_bytes(2, "little", signed=True) * channels * 8)


def test_manifest_loads_bounded_public_audio_without_retaining_paths(
    tmp_path: Path,
) -> None:
    audio = tmp_path / "samples" / "ready.wav"
    _write_wav(audio)
    manifest = tmp_path / "manifest.json"
    manifest.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "source_kind": "public",
                "license": "CC0",
                "samples": [
                    {
                        "test_id": "ready",
                        "audio_file": "samples/ready.wav",
                        "expected_text": "测试语音回复",
                        "expected_response": "voice_test_ok",
                        "push_to_talk": True,
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    loaded = load_voice_manifest(manifest)

    assert loaded.source_kind == "public"
    assert loaded.license == "CC0"
    assert loaded.cases[0].pcm == (1).to_bytes(2, "little", signed=True) * 8
    assert not hasattr(loaded.cases[0], "audio_file")


@pytest.mark.parametrize(
    "mutator",
    [
        lambda payload: payload["samples"][0].update({"audio_file": "../outside.wav"}),
        lambda payload: payload["samples"][0].update({"push_to_talk": "yes"}),
        lambda payload: payload.update({"source_kind": "private"}),
    ],
)
def test_manifest_rejects_unbounded_or_private_inputs(
    tmp_path: Path, mutator
) -> None:
    audio = tmp_path / "ready.wav"
    _write_wav(audio)
    payload = {
        "schema_version": 1,
        "source_kind": "public",
        "license": "CC0",
        "samples": [
            {
                "test_id": "ready",
                "audio_file": "ready.wav",
                "expected_text": "测试语音回复",
                "expected_response": "voice_test_ok",
                "push_to_talk": True,
            }
        ],
    }
    mutator(payload)
    manifest = tmp_path / "manifest.json"
    manifest.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(ValueError, match="voice_stability_runner_invalid"):
        load_voice_manifest(manifest)


def test_manifest_rejects_symlink_audio(tmp_path: Path) -> None:
    target = tmp_path / "target.wav"
    _write_wav(target)
    linked = tmp_path / "linked.wav"
    linked.symlink_to(target)
    manifest = tmp_path / "manifest.json"
    manifest.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "source_kind": "generated",
                "license": "GENERATED",
                "samples": [
                    {
                        "test_id": "linked",
                        "audio_file": "linked.wav",
                        "expected_text": "测试语音回复",
                        "expected_response": "voice_test_ok",
                        "push_to_talk": True,
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="voice_stability_runner_invalid"):
        load_voice_manifest(manifest)
