from __future__ import annotations

import threading

import pytest

from services.voice.asr import AsrResult
from services.voice.stability import (
    VoiceStabilityController,
    VoicePhase,
    VoicePlaybackStatus,
    VoiceStabilitySession,
)
from services.voice.tts import PlaybackResult, PlaybackStatus


PCM = b"p" * 32_000


class Asr:
    def __init__(self, results: list[str | Exception]) -> None:
        self.results = results

    def transcribe(self, pcm: bytes) -> AsrResult:
        assert pcm == PCM
        result = self.results.pop(0)
        if isinstance(result, Exception):
            raise result
        return AsrResult(result, "zh", 80)


class Output:
    def __init__(self, results: list[bool] | None = None) -> None:
        self.results = results or [True] * 8
        self.codes: list[str] = []

    def speak_code(self, code: str, _cancelled) -> bool:
        self.codes.append(code)
        return self.results.pop(0)


class AmbiguousOutput:
    def speak_code_result(self, _code: str, _cancelled) -> PlaybackResult:
        return PlaybackResult(PlaybackStatus.AMBIGUOUS)


def test_wake_commands_use_fixed_replies_and_return_to_idle() -> None:
    output = Output()
    session = VoiceStabilitySession(
        asr=Asr([
            "嘿，小小",
            "小小，你能听见吗",
            "小小，测试语音回复",
            "小小，停止",
        ]),
        output=output,
    )

    states = [
        session.handle_pcm(PCM, threading.Event())
        for _ in range(4)
    ]

    assert [state.response_code for state in states] == [
        "voice_test_ready",
        "voice_test_heard",
        "voice_test_ok",
        "voice_test_stopped",
    ]
    assert all(state.phase is VoicePhase.IDLE for state in states)
    assert all(
        state.playback_status is VoicePlaybackStatus.COMPLETE for state in states
    )
    assert output.codes == [
        "voice_test_ready",
        "voice_test_heard",
        "voice_test_ok",
        "voice_test_stopped",
    ]


def test_push_to_talk_uses_the_same_deterministic_command_surface() -> None:
    output = Output()
    session = VoiceStabilitySession(
        asr=Asr(["你能听见吗", "测试语音回复", "停止"]),
        output=output,
    )

    states = [
        session.handle_pcm(PCM, threading.Event(), push_to_talk=True)
        for _ in range(3)
    ]

    assert [state.response_code for state in states] == [
        "voice_test_heard",
        "voice_test_ok",
        "voice_test_stopped",
    ]
    assert all(state.phase is VoicePhase.IDLE for state in states)


def test_wake_arms_one_followup_and_returns_idle_after_reply() -> None:
    output = Output()
    session = VoiceStabilitySession(
        asr=Asr(["嘿，小小", "测试语音回复"]),
        output=output,
    )

    wake = session.handle_pcm(PCM, threading.Event())
    followup = session.handle_pcm(PCM, threading.Event())

    assert wake.response_code == "voice_test_ready"
    assert followup.response_code == "voice_test_ok"
    assert followup.phase is VoicePhase.IDLE
    assert output.codes == ["voice_test_ready", "voice_test_ok"]


def test_asr_failure_is_bounded_and_next_turn_can_start() -> None:
    output = Output()
    session = VoiceStabilitySession(
        asr=Asr([RuntimeError("private transcript"), "测试语音回复"]),
        output=output,
    )

    failed = session.handle_pcm(PCM, threading.Event(), push_to_talk=True)
    recovered = session.handle_pcm(PCM, threading.Event(), push_to_talk=True)

    assert failed.phase is VoicePhase.FAILED
    assert failed.error_code == "asr_failed"
    assert failed.playback_status is VoicePlaybackStatus.COMPLETE
    assert recovered.phase is VoicePhase.IDLE
    assert recovered.response_code == "voice_test_ok"
    assert output.codes == ["voice_test_failed", "voice_test_ok"]


def test_cancelled_session_does_not_start_playback_and_is_recoverable() -> None:
    output = Output()
    session = VoiceStabilitySession(
        asr=Asr(["测试语音回复", "停止"]),
        output=output,
    )
    cancelled = threading.Event()
    cancelled.set()

    state = session.handle_pcm(PCM, cancelled, push_to_talk=True)
    recovered = session.handle_pcm(PCM, threading.Event(), push_to_talk=True)

    assert state.phase is VoicePhase.CANCELLED
    assert state.playback_status is VoicePlaybackStatus.NOT_ATTEMPTED
    assert recovered.phase is VoicePhase.IDLE
    assert output.codes == ["voice_test_ok"]


def test_unknown_command_fails_closed_without_speaking() -> None:
    output = Output()
    session = VoiceStabilitySession(
        asr=Asr(["小小，随便聊聊"]),
        output=output,
    )

    state = session.handle_pcm(PCM, threading.Event())

    assert state.phase is VoicePhase.IDLE
    assert state.response_code is None
    assert state.playback_status is VoicePlaybackStatus.NOT_ATTEMPTED
    assert output.codes == []


def test_ambiguous_playback_is_not_reported_as_a_complete_reply() -> None:
    session = VoiceStabilitySession(
        asr=Asr(["测试语音回复"]),
        output=AmbiguousOutput(),
    )

    state = session.handle_pcm(PCM, threading.Event(), push_to_talk=True)

    assert state.phase is VoicePhase.FAILED
    assert state.error_code == "playback_failed"
    assert state.playback_status is VoicePlaybackStatus.AMBIGUOUS


def test_stability_controller_matches_the_existing_worker_controller_contract() -> None:
    controller = VoiceStabilityController(
        asr=Asr(["测试语音回复"]),
        output=Output(),
        push_to_talk=True,
    )

    outcome = controller.handle(PCM, threading.Event())

    assert outcome.reason == "listen_only_acknowledged"
    assert outcome.response_code == "voice_test_ok"
    assert outcome.phase == "idle"


def test_wake_followup_timeout_is_explicit_and_recoverable() -> None:
    now = [0]
    controller = VoiceStabilityController(
        asr=Asr(["嘿，小小", "测试语音回复"]),
        output=Output(),
        monotonic_ns=lambda: now[0],
    )

    armed = controller.handle(PCM, threading.Event())
    now[0] = 8_000_000_001
    timed_out = controller.expire(now[0])

    assert armed.reason == "listen_only_armed"
    assert timed_out.reason == "listen_only_timeout"
    assert controller.phase == "idle"
    assert controller._session.state.phase is VoicePhase.TIMED_OUT

    recovered = controller.handle(PCM, threading.Event(), from_replay=False)
    assert recovered.reason == "listen_only_ignored"
    assert controller._session.state.phase is VoicePhase.IDLE


@pytest.mark.parametrize(
    ("code", "phrase"),
    [
        ("voice_test_ready", "我在"),
        ("voice_test_heard", "能听见"),
        ("voice_test_ok", "语音回复正常"),
        ("voice_test_stopped", "已停止"),
        ("voice_test_failed", "语音识别失败"),
    ],
)
def test_stability_reply_codes_are_fixed(code: str, phrase: str) -> None:
    from services.voice.tts import phrase_for_semantic_code

    assert phrase_for_semantic_code(code) == phrase
