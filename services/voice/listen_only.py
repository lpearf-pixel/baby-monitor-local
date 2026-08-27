"""Memory-only exact-wake dialogue for the listen-only Voice mode."""

from __future__ import annotations

import re
import time
import unicodedata
from dataclasses import dataclass
from typing import Literal, Protocol

from services.voice.intent import DialogueState, parse_feeding_command
from services.voice.wake import classify_wake


ARMED_TIMEOUT_NS = 8_000_000_000
_REFERENCE_TIME = "2026-01-01T00:00:00+00:00"
_CLAIM = re.compile(r"^我是(?:爸爸|妈妈)[,，、\s]+(.+)$")
_REPLY_ECHOES = (
    re.compile(r"^我在[\s,，。！？、；;:：]*请说[\s,，。！？、；;:：]*(.*)$"),
    re.compile(r"^我听到了[\s,，。！？、；;:：]*(.*)$"),
)
_BOUNDARY = " \t\r\n,，。！？、；;:："
_START_DIAGNOSTIC_TARGETS = ("开始喂奶", "我要开始喂奶", "现在开始喂奶")
_REPLY_DIAGNOSTIC_TARGETS = ("我在请说", "我听到了")


class Asr(Protocol):
    def transcribe(self, pcm: bytes) -> object: ...


class StopEvent(Protocol):
    def is_set(self) -> bool: ...


class Synthesizer(Protocol):
    def speak_code(self, code: str, cancelled: StopEvent) -> bool: ...


@dataclass(frozen=True)
class ListenOnlyOutcome:
    reason: str
    response_code: str | None
    phase: Literal["idle", "armed"]


class ListenOnlyController:
    """Accept one exact wake interaction and retain no transcript or PCM."""

    def __init__(
        self,
        *,
        asr: Asr,
        synthesizer: Synthesizer,
        monotonic_ns=time.monotonic_ns,
    ) -> None:
        self._asr = asr
        self._synthesizer = synthesizer
        self._monotonic_ns = monotonic_ns
        self._phase: Literal["idle", "armed"] = "idle"
        self._armed_deadline_ns: int | None = None
        self._armed_speech_started = False

    @property
    def phase(self) -> Literal["idle", "armed"]:
        return self._phase

    def handle(
        self,
        pcm: bytes,
        cancelled: StopEvent,
        *,
        from_replay: bool = False,
    ) -> ListenOnlyOutcome:
        was_armed = self._phase == "armed"
        if was_armed:
            now_ns = self._monotonic_ns()
            may_finish = self._armed_speech_started or (
                self._armed_deadline_ns is not None
                and now_ns <= self._armed_deadline_ns
            )
            if not may_finish:
                self._reset()
                return self._outcome("listen_only_timeout")
        try:
            result = self._asr.transcribe(pcm)
            text = getattr(result, "text")
            if not isinstance(text, str):
                raise ValueError
            if was_armed:
                command = _command_without_optional_wake(text)
                reply_echo = False
                if command is not None:
                    command, reply_echo = _strip_reply_echo(command)
                if command is None or not _is_closed_command(command):
                    if reply_echo:
                        return self._outcome("listen_only_reply_echo_ignored")
                    if from_replay:
                        return self._outcome("listen_only_replay_ignored")
                    self._reset()
                    return self._outcome(_rejected_followup_reason(command))
                return self._acknowledge(cancelled)

            wake = classify_wake(text)
            if wake.kind == "standalone_wake":
                if not self._synthesizer.speak_code("listen_only_ready", cancelled):
                    self._reset()
                    return self._outcome("voice_output_unavailable")
                self._phase = "armed"
                self._armed_deadline_ns = self._monotonic_ns() + ARMED_TIMEOUT_NS
                self._armed_speech_started = False
                return self._outcome("listen_only_armed", "listen_only_ready")
            if (
                wake.kind == "wake_with_command"
                and wake.command is not None
                and _is_closed_command(wake.command)
            ):
                return self._acknowledge(cancelled)
            return self._outcome("listen_only_ignored")
        except Exception:
            self._reset()
            return self._outcome("voice_model_unavailable")

    def on_speech_started(self, now_ns: int) -> bool:
        if (
            self._phase != "armed"
            or self._armed_deadline_ns is None
            or now_ns > self._armed_deadline_ns
        ):
            return False
        self._armed_speech_started = True
        return True

    def expire(self, now_ns: int) -> ListenOnlyOutcome:
        if (
            self._phase == "armed"
            and not self._armed_speech_started
            and self._armed_deadline_ns is not None
            and now_ns > self._armed_deadline_ns
        ):
            self._reset()
            return self._outcome("listen_only_timeout")
        return self._outcome(
            "listen_only_armed" if self._phase == "armed" else "listen_only_idle"
        )

    def reset(self) -> None:
        self._reset()

    def _acknowledge(self, cancelled: StopEvent) -> ListenOnlyOutcome:
        self._reset()
        if not self._synthesizer.speak_code("listen_only_received", cancelled):
            return self._outcome("voice_output_unavailable")
        return self._outcome("listen_only_acknowledged", "listen_only_received")

    def _reset(self) -> None:
        self._phase = "idle"
        self._armed_deadline_ns = None
        self._armed_speech_started = False

    def _outcome(
        self, reason: str, response_code: str | None = None
    ) -> ListenOnlyOutcome:
        return ListenOnlyOutcome(reason, response_code, self._phase)


def _command_without_optional_wake(text: str) -> str | None:
    wake = classify_wake(text)
    if wake.kind == "standalone_wake":
        return None
    if wake.kind == "wake_with_command":
        return wake.command
    return text


def _is_closed_command(command: str) -> bool:
    claim = _CLAIM.fullmatch(command)
    if claim is not None:
        command = claim.group(1)
    states = (
        DialogueState.idle(observed_at=_REFERENCE_TIME),
        DialogueState.pending(
            observed_at=_REFERENCE_TIME,
            started_at=_REFERENCE_TIME,
            expected_version=1,
            mode="unknown",
        ),
        DialogueState.pending(
            observed_at=_REFERENCE_TIME,
            started_at=_REFERENCE_TIME,
            expected_version=1,
            mode="direct_breastfeeding",
        ),
        DialogueState.needs_confirmation(
            observed_at=_REFERENCE_TIME,
            started_at=_REFERENCE_TIME,
            expected_version=1,
            mode="unknown",
            proposal_digest="a" * 64,
            warning_digest=None,
            warning_codes=(),
        ),
    )
    return any(parse_feeding_command(command, state).intent_type is not None for state in states)


def _strip_reply_echo(command: str) -> tuple[str, bool]:
    for pattern in _REPLY_ECHOES:
        matched = pattern.fullmatch(command)
        if matched is not None:
            return matched.group(1).strip(_BOUNDARY), True
    return command, False


def _rejected_followup_reason(command: str | None) -> str:
    if command is None:
        return "listen_only_followup_far"
    normalized = "".join(
        character
        for character in unicodedata.normalize("NFKC", command).strip()
        if not character.isspace()
        and not unicodedata.category(character).startswith("P")
    )
    if not normalized or len(normalized) > 64:
        return "listen_only_followup_far"
    start_distance = min(
        _edit_distance(normalized, target) for target in _START_DIAGNOSTIC_TARGETS
    )
    reply_distance = min(
        _edit_distance(normalized, target) for target in _REPLY_DIAGNOSTIC_TARGETS
    )
    if start_distance <= 2 and start_distance < reply_distance:
        return "listen_only_followup_near_start"
    if reply_distance <= 2 and reply_distance < start_distance:
        return "listen_only_followup_near_reply_echo"
    return "listen_only_followup_far"


def _edit_distance(left: str, right: str) -> int:
    previous = list(range(len(right) + 1))
    for left_index, left_character in enumerate(left, start=1):
        current = [left_index]
        for right_index, right_character in enumerate(right, start=1):
            current.append(
                min(
                    current[-1] + 1,
                    previous[right_index] + 1,
                    previous[right_index - 1]
                    + int(left_character != right_character),
                )
            )
        previous = current
    return previous[-1]


__all__ = ["ListenOnlyController", "ListenOnlyOutcome"]
