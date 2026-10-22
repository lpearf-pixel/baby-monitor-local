"""Bounded local Voice P0 session handling.

This module deliberately handles only deterministic stability probes. It does not
create or save Baby Care records and does not know about the Camera Reply adapter.
"""

from __future__ import annotations

import re
import threading
import time
import unicodedata
import uuid
from dataclasses import dataclass
from enum import StrEnum
from typing import Callable, Protocol

from services.voice.listen_only import ListenOnlyOutcome


class VoicePhase(StrEnum):
    IDLE = "IDLE"
    LISTENING = "LISTENING"
    RECOGNIZING = "RECOGNIZING"
    PROCESSING = "PROCESSING"
    SPEAKING = "SPEAKING"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"
    TIMED_OUT = "TIMED_OUT"


class VoicePlaybackStatus(StrEnum):
    NOT_ATTEMPTED = "NOT_ATTEMPTED"
    COMPLETE = "COMPLETE"
    FAILED = "FAILED"
    AMBIGUOUS = "AMBIGUOUS"


@dataclass(frozen=True, slots=True)
class VoiceSessionState:
    session_id: str
    phase: VoicePhase
    generation: int
    response_code: str | None = None
    error_code: str | None = None
    playback_status: VoicePlaybackStatus = VoicePlaybackStatus.NOT_ATTEMPTED


class Asr(Protocol):
    def transcribe(self, pcm: bytes) -> object: ...


class VoiceOutput(Protocol):
    def speak_code(self, code: str, cancelled: object) -> bool: ...


_WAKE_PREFIXES = ("嘿小小", "小小")
_PUNCTUATION = re.compile(r"[\s,，。！？!?:：、；;‘’“”\"'（）()【】\[\]{}]+")
_COMMANDS = {
    "": "voice_test_ready",
    "你能听见吗": "voice_test_heard",
    "能听见吗": "voice_test_heard",
    "测试语音回复": "voice_test_ok",
    "停止": "voice_test_stopped",
    "停止当前会话": "voice_test_stopped",
}


class VoiceStabilitySession:
    """Run one bounded local test interaction at a time.

    The caller owns audio collection. This object owns the session phase and the
    deterministic ASR -> command -> output transition. A fresh call can always
    start after a terminal state; no prior failure is silently resumed.
    """

    def __init__(
        self,
        *,
        asr: Asr,
        output: VoiceOutput,
        session_id_factory: Callable[[], str] = lambda: str(uuid.uuid4()),
    ) -> None:
        self._asr = asr
        self._output = output
        self._session_id_factory = session_id_factory
        self._lock = threading.Lock()
        self._generation = 0
        self._armed = False
        self._state = VoiceSessionState(
            session_id="idle",
            phase=VoicePhase.IDLE,
            generation=0,
        )
        self._history: list[VoiceSessionState] = [self._state]

    @property
    def state(self) -> VoiceSessionState:
        return self._state

    @property
    def history(self) -> tuple[VoiceSessionState, ...]:
        return tuple(self._history)

    @property
    def armed(self) -> bool:
        return self._armed

    def reset(self) -> None:
        with self._lock:
            self._armed = False

    def timeout(self) -> VoiceSessionState:
        with self._lock:
            self._armed = False
            return self._transition(
                self._state.session_id,
                VoicePhase.TIMED_OUT,
                error_code="followup_timeout",
            )

    def handle_pcm(
        self,
        pcm: bytes,
        cancelled: object,
        *,
        push_to_talk: bool = False,
    ) -> VoiceSessionState:
        with self._lock:
            self._generation += 1
            session_id = self._session_id_factory()
            self._transition(session_id, VoicePhase.LISTENING)
            if _cancelled(cancelled):
                return self._transition(session_id, VoicePhase.CANCELLED)

            self._transition(session_id, VoicePhase.RECOGNIZING)
            try:
                result = self._asr.transcribe(pcm)
                text = getattr(result, "text")
                if not isinstance(text, str):
                    raise ValueError("asr_text_invalid")
            except Exception:
                self._armed = False
                return self._speak_failure(session_id, cancelled)

            if _cancelled(cancelled):
                return self._transition(session_id, VoicePhase.CANCELLED)

            self._transition(session_id, VoicePhase.PROCESSING)
            was_armed = self._armed
            response_code = _classify_command(
                text,
                push_to_talk=push_to_talk,
                armed=was_armed,
            )
            if response_code is None:
                self._armed = False
                return self._transition(session_id, VoicePhase.IDLE)
            if _cancelled(cancelled):
                self._armed = False
                return self._transition(session_id, VoicePhase.CANCELLED)

            self._transition(
                session_id,
                VoicePhase.SPEAKING,
                response_code=response_code,
            )
            playback = self._play(response_code, cancelled)
            if playback is VoicePlaybackStatus.COMPLETE:
                self._armed = response_code == "voice_test_ready" and not push_to_talk
                return self._transition(
                    session_id,
                    VoicePhase.IDLE,
                    response_code=response_code,
                    playback_status=playback,
                )
            terminal = (
                VoicePhase.CANCELLED
                if _cancelled(cancelled)
                else VoicePhase.FAILED
            )
            self._armed = False
            return self._transition(
                session_id,
                terminal,
                response_code=response_code,
                error_code=(
                    "cancelled"
                    if terminal is VoicePhase.CANCELLED
                    else "playback_failed"
                ),
                playback_status=playback,
            )

    def _speak_failure(self, session_id: str, cancelled: object) -> VoiceSessionState:
        self._armed = False
        self._transition(
            session_id,
            VoicePhase.FAILED,
            error_code="asr_failed",
        )
        if _cancelled(cancelled):
            return self._transition(session_id, VoicePhase.CANCELLED)
        playback = self._play("voice_test_failed", cancelled)
        return self._transition(
            session_id,
            VoicePhase.FAILED,
            response_code="voice_test_failed",
            error_code="asr_failed",
            playback_status=playback,
        )

    def _play(self, code: str, cancelled: object) -> VoicePlaybackStatus:
        try:
            detailed = getattr(self._output, "speak_code_result", None)
            if callable(detailed):
                result = detailed(code, cancelled)
                status = getattr(result, "status", None)
                value = getattr(status, "value", status)
                if value == "COMPLETE":
                    return VoicePlaybackStatus.COMPLETE
                if value == "AMBIGUOUS":
                    return VoicePlaybackStatus.AMBIGUOUS
                if value == "CANCELLED":
                    return VoicePlaybackStatus.FAILED
                return VoicePlaybackStatus.FAILED
            return (
                VoicePlaybackStatus.COMPLETE
                if self._output.speak_code(code, cancelled)
                else VoicePlaybackStatus.FAILED
            )
        except Exception:
            return VoicePlaybackStatus.FAILED

    def _transition(
        self,
        session_id: str,
        phase: VoicePhase,
        *,
        response_code: str | None = None,
        error_code: str | None = None,
        playback_status: VoicePlaybackStatus = VoicePlaybackStatus.NOT_ATTEMPTED,
    ) -> VoiceSessionState:
        state = VoiceSessionState(
            session_id=session_id,
            phase=phase,
            generation=self._generation,
            response_code=response_code,
            error_code=error_code,
            playback_status=playback_status,
        )
        self._state = state
        self._history.append(state)
        return state


def _classify_command(text: str, *, push_to_talk: bool, armed: bool) -> str | None:
    normalized = _normalize(text)
    command = normalized
    if not push_to_talk:
        for prefix in _WAKE_PREFIXES:
            if normalized.startswith(prefix):
                command = normalized[len(prefix) :]
                break
        else:
            if not armed:
                return None
    else:
        for prefix in _WAKE_PREFIXES:
            if command.startswith(prefix):
                command = command[len(prefix) :]
                break
    return _COMMANDS.get(command)


def _normalize(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", value)
    return _PUNCTUATION.sub("", normalized)


def _cancelled(value: object) -> bool:
    try:
        return bool(value.is_set())
    except AttributeError:
        return False


class VoiceStabilityController:
    """Adapt the P0 session to the existing listen-only worker contract."""

    def __init__(
        self,
        *,
        asr: Asr,
        output: VoiceOutput,
        push_to_talk: bool = False,
        monotonic_ns: Callable[[], int] = time.monotonic_ns,
    ) -> None:
        self._session = VoiceStabilitySession(asr=asr, output=output)
        self._push_to_talk = push_to_talk
        self._monotonic_ns = monotonic_ns
        self._deadline_ns: int | None = None

    @property
    def phase(self) -> str:
        return "armed" if self._session.armed else "idle"

    def expire(self, now_ns: int) -> ListenOnlyOutcome:
        if (
            self._session.armed
            and self._deadline_ns is not None
            and now_ns > self._deadline_ns
        ):
            self._session.timeout()
            self._deadline_ns = None
            return ListenOnlyOutcome("listen_only_timeout", None, "idle")
        return ListenOnlyOutcome(
            "listen_only_armed" if self._session.armed else "listen_only_idle",
            None,
            self.phase,
        )

    def on_speech_started(self, _now_ns: int) -> bool:
        return self._session.armed

    def handle(
        self,
        pcm: bytes,
        cancelled: object,
        *,
        from_replay: bool = False,
    ) -> ListenOnlyOutcome:
        if from_replay:
            return ListenOnlyOutcome("listen_only_replay_ignored", None, self.phase)
        state = self._session.handle_pcm(
            pcm,
            cancelled,
            push_to_talk=self._push_to_talk,
        )
        if state.response_code is None:
            reason = (
                "voice_model_unavailable"
                if state.error_code == "asr_failed"
                else "listen_only_ignored"
            )
        elif state.error_code == "asr_failed":
            reason = "voice_model_unavailable"
        elif state.playback_status in {
            VoicePlaybackStatus.FAILED,
            VoicePlaybackStatus.AMBIGUOUS,
        }:
            reason = "voice_output_unavailable"
        elif state.response_code == "voice_test_ready":
            reason = "listen_only_armed"
            self._deadline_ns = self._monotonic_ns() + 8_000_000_000
        else:
            reason = "listen_only_acknowledged"
            self._deadline_ns = None
        return ListenOnlyOutcome(reason, state.response_code, self.phase)

    def reset(self) -> None:
        self._session.reset()
        self._deadline_ns = None


__all__ = [
    "VoicePhase",
    "VoicePlaybackStatus",
    "VoiceSessionState",
    "VoiceStabilityController",
    "VoiceStabilitySession",
]
