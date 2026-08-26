from __future__ import annotations

import threading

from services.voice.asr import AsrResult
from services.voice.listen_only import ListenOnlyController


PCM = b"p" * 32_000


class Asr:
    def __init__(self, texts: list[str | Exception]) -> None:
        self.texts = texts

    def transcribe(self, pcm: bytes) -> AsrResult:
        assert pcm == PCM
        value = self.texts.pop(0)
        if isinstance(value, Exception):
            raise value
        return AsrResult(value, "zh", 80)


class Synth:
    def __init__(self, results: list[bool] | None = None) -> None:
        self.results = results or [True] * 8
        self.codes: list[str] = []

    def speak_code(self, code: str, cancelled) -> bool:
        self.codes.append(code)
        return self.results.pop(0)


class Clock:
    def __init__(self, values: list[int]) -> None:
        self.values = values

    def __call__(self) -> int:
        return self.values.pop(0)


def test_standalone_wake_acknowledges_then_accepts_only_one_closed_command() -> None:
    synth = Synth()
    controller = ListenOnlyController(
        asr=Asr(["小小", "我是爸爸，开始喂奶", "喝了90毫升配方奶"]),
        synthesizer=synth,
        monotonic_ns=Clock([1_000_000_000, 2_000_000_000, 3_000_000_000]),
    )

    wake = controller.handle(PCM, threading.Event())
    command = controller.handle(PCM, threading.Event())
    later = controller.handle(PCM, threading.Event())

    assert (wake.reason, wake.response_code, wake.phase) == (
        "listen_only_armed", "listen_only_ready", "armed"
    )
    assert (command.reason, command.response_code, command.phase) == (
        "listen_only_acknowledged", "listen_only_received", "idle"
    )
    assert (later.reason, later.response_code, later.phase) == (
        "listen_only_ignored", None, "idle"
    )
    assert synth.codes == ["listen_only_ready", "listen_only_received"]


def test_wake_with_closed_command_acknowledges_once_without_arming() -> None:
    synth = Synth()
    controller = ListenOnlyController(
        asr=Asr(["小小，开始喂奶"]),
        synthesizer=synth,
        monotonic_ns=Clock([1_000_000_000]),
    )

    outcome = controller.handle(PCM, threading.Event())

    assert outcome.reason == "listen_only_acknowledged"
    assert outcome.phase == "idle"
    assert synth.codes == ["listen_only_received"]


def test_armed_timeout_is_silent_and_later_command_requires_new_wake() -> None:
    synth = Synth()
    controller = ListenOnlyController(
        asr=Asr(["小小", "开始喂奶"]),
        synthesizer=synth,
        monotonic_ns=Clock([1_000_000_000, 10_000_000_001]),
    )
    controller.handle(PCM, threading.Event())

    expired = controller.expire(9_000_000_001)
    command = controller.handle(PCM, threading.Event())

    assert expired.reason == "listen_only_timeout"
    assert expired.phase == "idle"
    assert command.reason == "listen_only_ignored"
    assert synth.codes == ["listen_only_ready"]


def test_speech_started_before_deadline_may_finish_after_deadline() -> None:
    synth = Synth()
    controller = ListenOnlyController(
        asr=Asr(["小小", "开始喂奶"]),
        synthesizer=synth,
        monotonic_ns=Clock([1_000_000_000, 12_000_000_000]),
    )
    controller.handle(PCM, threading.Event())

    assert controller.on_speech_started(8_999_999_999) is True
    result = controller.handle(PCM, threading.Event())

    assert result.reason == "listen_only_acknowledged"
    assert synth.codes == ["listen_only_ready", "listen_only_received"]


def test_unknown_or_incomplete_followup_returns_silently_to_idle() -> None:
    synth = Synth()
    controller = ListenOnlyController(
        asr=Asr(["小小", "今天天气如何"]),
        synthesizer=synth,
        monotonic_ns=Clock([1_000_000_000, 2_000_000_000]),
    )
    controller.handle(PCM, threading.Event())

    result = controller.handle(PCM, threading.Event())

    assert result.reason == "listen_only_ignored"
    assert result.phase == "idle"
    assert synth.codes == ["listen_only_ready"]


def test_model_or_tts_failure_resets_to_idle_without_reprompt() -> None:
    model_failure = ListenOnlyController(
        asr=Asr([RuntimeError("private transcript")]),
        synthesizer=Synth(),
        monotonic_ns=Clock([1]),
    )
    failed_synth = Synth([False])
    output_failure = ListenOnlyController(
        asr=Asr(["小小"]),
        synthesizer=failed_synth,
        monotonic_ns=Clock([1]),
    )

    assert model_failure.handle(PCM, threading.Event()).reason == "voice_model_unavailable"
    result = output_failure.handle(PCM, threading.Event())

    assert result.reason == "voice_output_unavailable"
    assert result.phase == "idle"


def test_fixed_reply_echoes_never_wake_arm_or_generate_output() -> None:
    texts = [
        "我在请说",
        "我听到了",
        "我在请说开始喂奶",
        "我听到了开始喂奶",
    ]
    synth = Synth()
    controller = ListenOnlyController(
        asr=Asr(texts.copy()),
        synthesizer=synth,
        monotonic_ns=Clock([1, 2, 3, 4]),
    )

    outcomes = [controller.handle(PCM, threading.Event()) for _ in texts]

    assert [outcome.reason for outcome in outcomes] == [
        "listen_only_ignored"
    ] * 4
    assert [outcome.phase for outcome in outcomes] == ["idle"] * 4
    assert synth.codes == []
    assert controller.expire(10_000_000_000).reason == "listen_only_idle"
