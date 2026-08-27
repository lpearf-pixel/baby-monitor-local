"""Independent memory-only Voice Care worker orchestration and bounded status."""

from __future__ import annotations

import json
import os
import re
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Protocol

from packages.contracts.settings import VoiceCareSettings
from services.audio.source import DecoderRead
from services.voice.artifacts import (
    VoiceArtifactSpec,
    validate_voice_artifact,
    voice_artifact_spec,
)
from services.voice.asr_corpus import ASR_CORPUS_KEY_ACCOUNT
from services.voice.capture import UtteranceResult
from services.voice.client import VoiceSemanticResponse
from services.voice.intent import DialogueState, ParsedIntent, parse_feeding_command
from services.voice.outbox import VoiceIntentOutbox
from services.voice.signing import DeviceIdentity
from services.voice.speaker import SpeakerVerification
from services.voice.vad import VadResult
from services.voice.wake import validate_wake_prefix
from services.voice.helper_keychain import keychain_for_runtime


VOICE_WORKER_UNAVAILABLE = "voice_worker_unavailable"
VOICE_TRANSITION_KEYS = (
    "armed_timeouts",
    "ignored_followups",
    "output_failures",
    "replay_frames",
    "replay_ignored",
    "replay_utterances",
    "reply_echo_ignored",
    "utterances",
    "vad_speech_frames",
)
_MAX_STATUS_COUNT = 9_007_199_254_740_991
_STATUS_REASONS = {
    "accepted_pending",
    "saved",
    "needs_identity",
    "needs_confirmation",
    "identity_mismatch",
    "state_conflict",
    "temporarily_unavailable",
    "rejected",
    "voice_disabled",
    "voice_runtime_unavailable",
    "voice_startup_failed",
    "voice_worker_unavailable",
    "voice_audio_unavailable",
    "voice_model_unavailable",
    "voice_output_unavailable",
    "idle",
    "ignored",
    "listen_only_idle",
    "listen_only_ignored",
    "listen_only_acknowledging",
    "listen_only_armed",
    "listen_only_acknowledged",
    "listen_only_timeout",
    "listen_only_replay_ignored",
    "listen_only_reply_echo_ignored",
}
_FRAME_BYTES = 3_200
_CLAIM = re.compile(r"^我是(爸爸|妈妈)[,，、\s]+(.+)$")
_SELECTED_ASR_ARTIFACT = "sherpa-onnx-paraformer-zh-2023-09-14"
_SELECTED_ASR_PROFILE = "paraformer"
_SILERO_ARTIFACT = "silero-vad-v6.2"


class PreflightKeychain(Protocol):
    def read(self, account: str, *, size: int) -> bytes | None: ...


PreflightKeychainFactory = Callable[[Path], PreflightKeychain]
ArtifactValidator = Callable[[VoiceArtifactSpec, Path], object]


@dataclass(frozen=True)
class VoicePreflightReport:
    available: bool
    reason: str
    asr_profile: str | None

    def __post_init__(self) -> None:
        valid = (
            self.available is True
            and self.reason == "voice_preflight_available"
            and self.asr_profile == _SELECTED_ASR_PROFILE
        ) or (
            self.available is False
            and self.reason
            in {
                "voice_preflight_unavailable",
                "voice_keychain_unavailable",
                "voice_model_unavailable",
            }
            and self.asr_profile is None
        )
        if not valid:
            raise ValueError(VOICE_WORKER_UNAVAILABLE)


def run_voice_preflight(
    settings: VoiceCareSettings,
    project_root: Path,
    *,
    keychain_factory: PreflightKeychainFactory = keychain_for_runtime,
    artifact_validator: ArtifactValidator = validate_voice_artifact,
) -> VoicePreflightReport:
    """Validate the fixed disabled Voice runtime without opening audio or models."""

    if settings.enabled:
        return VoicePreflightReport(False, "voice_preflight_unavailable", None)
    try:
        root = Path(project_root).resolve(strict=True)
        key = keychain_factory(root).read(ASR_CORPUS_KEY_ACCOUNT, size=32)
        if type(key) is not bytes or len(key) != 32:
            raise ValueError
    except Exception:
        return VoicePreflightReport(False, "voice_keychain_unavailable", None)
    try:
        for artifact_id in (_SELECTED_ASR_ARTIFACT, _SILERO_ARTIFACT):
            artifact_validator(voice_artifact_spec(settings, artifact_id), root)
    except Exception:
        return VoicePreflightReport(False, "voice_model_unavailable", None)
    return VoicePreflightReport(
        True, "voice_preflight_available", _SELECTED_ASR_PROFILE
    )


class StopEvent(Protocol):
    def is_set(self) -> bool: ...

    def wait(self, timeout: float) -> bool: ...


class Decoder(Protocol):
    def read(self, max_bytes: int) -> DecoderRead: ...

    def close(self) -> None: ...


class Vad(Protocol):
    def observe(self, frame: bytes) -> VadResult: ...


class Collector(Protocol):
    def push(self, frame: bytes, vad: VadResult) -> UtteranceResult | None: ...

    def reset(self) -> None: ...

    def close(self) -> None: ...


class CommandProcessor(Protocol):
    def process(
        self, pcm: bytes, observed_at: datetime
    ) -> VoiceSemanticResponse | None: ...


class Synthesizer(Protocol):
    def speak_code(self, code: str, cancelled: StopEvent) -> bool: ...


class Asr(Protocol):
    def transcribe(self, pcm: bytes) -> object: ...


class SpeakerVerificationFunction(Protocol):
    def __call__(
        self, claimed_profile_id: str | None, pcm: bytes
    ) -> SpeakerVerification: ...


class VoiceCommandProcessor:
    """Compose the closed post-capture Voice Care pipeline without retaining text."""

    def __init__(
        self,
        *,
        asr: Asr,
        speaker_verifier: SpeakerVerificationFunction,
        profile_claims: Mapping[str, str],
        identity: DeviceIdentity,
        outbox: VoiceIntentOutbox,
        client: object,
        device_id: str,
        lease_id: str,
        model_version: str,
        request_id_factory: Callable[[], str],
    ) -> None:
        if set(profile_claims) - {"dad", "mom"}:
            raise ValueError(VOICE_WORKER_UNAVAILABLE)
        self._asr = asr
        self._speaker_verifier = speaker_verifier
        self._profile_claims = dict(profile_claims)
        self._identity = identity
        self._outbox = outbox
        self._client = client
        self._device_id = device_id
        self._lease_id = lease_id
        self._model_version = model_version
        self._request_id_factory = request_id_factory
        self._dialogue = DialogueState.idle(observed_at="1970-01-01T00:00:00+00:00")
        self._care_session_id: str | None = None

    def process(self, pcm: bytes, observed_at: datetime) -> VoiceSemanticResponse | None:
        try:
            if observed_at.tzinfo is None or observed_at.utcoffset() is None:
                raise ValueError
            asr = self._asr.transcribe(pcm)
            text = getattr(asr, "text")
            wake = validate_wake_prefix(text)
            if not wake.accepted or wake.command is None:
                return None
            claimed_profile_id, command = self._extract_claim(wake.command)
            verification = self._speaker_verifier(claimed_profile_id, pcm)
            dialogue = _dialogue_at(self._dialogue, observed_at.isoformat())
            parsed = parse_feeding_command(command, dialogue)
            if parsed.intent_type is None or parsed.payload is None:
                return _closed_response(
                    "state_conflict" if parsed.reason == "state_conflict" else "rejected"
                )
            if parsed.intent_type != "feeding_start" and self._care_session_id is None:
                return _closed_response("state_conflict")
            request_id = self._request_id_factory()
            value = {
                "schemaVersion": 1,
                "requestId": request_id,
                "deviceId": self._device_id,
                "leaseId": self._lease_id,
                "issuedAt": observed_at.isoformat(),
                "occurredAt": observed_at.isoformat(),
                "deliveryMode": "live",
                "speakerState": verification.state,
                "source": "voice",
                "modelVersion": self._model_version,
                "intentType": parsed.intent_type,
                "careSessionId": (
                    None if parsed.intent_type == "feeding_start" else self._care_session_id
                ),
                "payload": parsed.payload,
            }
            signed = self._identity.sign_intent(value)
            entry = self._outbox.enqueue(signed)
            results = self._outbox.deliver(self._client)
            delivered = next(
                (result for result in results if result.request_id == entry.request_id),
                None,
            )
            if delivered is None or delivered.response is None:
                return VoiceSemanticResponse.temporarily_unavailable()
            self._advance(parsed, delivered.response, observed_at.isoformat())
            return delivered.response
        except Exception:
            return VoiceSemanticResponse.temporarily_unavailable()

    def _extract_claim(self, command: str) -> tuple[str | None, str]:
        match = _CLAIM.fullmatch(command)
        if match is None:
            return None, command
        label = "dad" if match.group(1) == "爸爸" else "mom"
        return self._profile_claims.get(label), match.group(2)

    def _advance(
        self,
        parsed: ParsedIntent,
        response: VoiceSemanticResponse,
        observed_at: str,
    ) -> None:
        if response.code == "accepted_pending" and response.care_session_id is not None:
            self._care_session_id = response.care_session_id
            if parsed.intent_type == "care_cancel":
                self._dialogue = DialogueState.idle(observed_at=observed_at)
                self._care_session_id = None
                return
            if parsed.intent_type == "feeding_start":
                self._dialogue = DialogueState.pending(
                    observed_at=observed_at,
                    started_at=str(parsed.payload["startedAt"]),
                    expected_version=int(response.session_version),
                    mode=str(parsed.payload["mode"]),
                )
            elif parsed.intent_type == "feeding_update":
                proposal = parsed.payload["proposal"]
                self._dialogue = DialogueState.pending(
                    observed_at=observed_at,
                    started_at=str(proposal["startedAt"]),
                    expected_version=int(response.session_version),
                    mode=str(proposal["mode"]),
                    bottle_capacity_ml=proposal.get("bottleCapacityMl"),
                )
            return
        if response.code == "needs_confirmation" and response.proposal_digest is not None:
            self._dialogue = DialogueState.needs_confirmation(
                observed_at=observed_at,
                started_at=str(self._dialogue.started_at),
                expected_version=int(response.session_version),
                mode=str(self._dialogue.mode),
                bottle_capacity_ml=self._dialogue.bottle_capacity_ml,
                proposal_digest=response.proposal_digest,
                warning_digest=response.warning_digest,
                warning_codes=response.warning_codes,
            )
            return
        if response.code == "saved":
            self._dialogue = DialogueState.idle(observed_at=observed_at)
            self._care_session_id = None


class VoiceStatusWriter:
    def __init__(self, path: Path, *, clock: Callable[[], datetime] | None = None) -> None:
        self._path = Path(path)
        self._clock = clock or (lambda: datetime.now().astimezone())

    def write(
        self,
        *,
        mode: str,
        worker_state: str,
        reason: str,
        processed_count: int,
        last_latency_ms: int | None,
        transition_counts: Mapping[str, int] | None = None,
    ) -> None:
        if (
            mode not in {"disabled", "listen_only", "care"}
            or worker_state not in {"disabled", "healthy", "degraded"}
            or reason not in _STATUS_REASONS
            or type(processed_count) is not int
            or not 0 <= processed_count <= _MAX_STATUS_COUNT
            or (
                last_latency_ms is not None
                and (type(last_latency_ms) is not int or not 0 <= last_latency_ms <= 30_000)
            )
        ):
            raise ValueError(VOICE_WORKER_UNAVAILABLE)
        if transition_counts is not None and (
            mode != "listen_only"
            or not isinstance(transition_counts, Mapping)
            or set(transition_counts) != set(VOICE_TRANSITION_KEYS)
            or any(
                type(transition_counts[key]) is not int
                or not 0 <= transition_counts[key] <= _MAX_STATUS_COUNT
                for key in VOICE_TRANSITION_KEYS
            )
        ):
            raise ValueError(VOICE_WORKER_UNAVAILABLE)
        checked_at = self._clock()
        if checked_at.tzinfo is None or checked_at.utcoffset() is None:
            raise ValueError(VOICE_WORKER_UNAVAILABLE)
        payload = {
            "schema_version": 2,
            "checked_at": checked_at.isoformat(),
            "mode": mode,
            "worker_state": worker_state,
            "reason": reason,
            "processed_count": processed_count,
            "last_latency_ms": last_latency_ms,
        }
        if transition_counts is not None:
            payload["transition_counts"] = {
                key: transition_counts[key] for key in VOICE_TRANSITION_KEYS
            }
        self._path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self._path.with_name(f".{self._path.name}.{os.getpid()}.tmp")
        try:
            temporary.write_text(
                json.dumps(payload, ensure_ascii=True, sort_keys=True) + "\n",
                encoding="ascii",
            )
            os.chmod(temporary, 0o600)
            os.replace(temporary, self._path)
        finally:
            try:
                temporary.unlink()
            except FileNotFoundError:
                pass


class VoiceWorker:
    def __init__(
        self,
        *,
        decoder: Decoder,
        vad: Vad,
        collector: Collector,
        processor: CommandProcessor,
        synthesizer: Synthesizer,
        status_writer: VoiceStatusWriter,
        clock: Callable[[], datetime] | None = None,
        monotonic_ns: Callable[[], int] = time.monotonic_ns,
        mode: str = "care",
    ) -> None:
        if mode not in {"listen_only", "care"}:
            raise ValueError(VOICE_WORKER_UNAVAILABLE)
        self._decoder = decoder
        self._vad = vad
        self._collector = collector
        self._processor = processor
        self._synthesizer = synthesizer
        self._status_writer = status_writer
        self._clock = clock or (lambda: datetime.now().astimezone())
        self._monotonic_ns = monotonic_ns
        self._mode = mode
        self._processed_count = 0

    def step(self, cancelled: StopEvent) -> None:
        observed_at = self._clock()
        try:
            read = self._decoder.read(_FRAME_BYTES)
            if read.failure_reason is not None or len(read.pcm) != _FRAME_BYTES:
                self._collector.reset()
                self._write("degraded", "voice_audio_unavailable", None)
                return
            vad = self._vad.observe(read.pcm)
            if vad.reason is not None:
                self._collector.reset()
                self._write("degraded", "voice_model_unavailable", None)
                return
            utterance = self._collector.push(read.pcm, vad)
            if utterance is None:
                self._write("healthy", "idle", None)
                return
            started = self._monotonic_ns()
            response = self._processor.process(utterance.pcm, observed_at)
            if response is None:
                latency = _latency_ms(started, self._monotonic_ns())
                self._write("healthy", "ignored", latency)
                return
            spoken = self._synthesizer.speak_code(response.code, cancelled)
            latency = _latency_ms(started, self._monotonic_ns())
            self._processed_count += 1
            self._collector.reset()
            if not spoken:
                self._write("degraded", "voice_output_unavailable", latency)
                return
            self._write("healthy", response.code, latency)
        except Exception:
            self._collector.reset()
            self._write("degraded", VOICE_WORKER_UNAVAILABLE, None)

    def run(self, stop_event: StopEvent) -> None:
        try:
            while not stop_event.is_set():
                self.step(stop_event)
                stop_event.wait(0.1)
        finally:
            self._collector.close()
            self._decoder.close()

    def _write(self, state: str, reason: str, latency: int | None) -> None:
        self._status_writer.write(
            mode=self._mode,
            worker_state=state,
            reason=reason,
            processed_count=self._processed_count,
            last_latency_ms=latency,
        )


def _latency_ms(started_ns: int, finished_ns: int) -> int:
    return min(30_000, max(0, (finished_ns - started_ns) // 1_000_000))


def _dialogue_at(state: DialogueState, observed_at: str) -> DialogueState:
    return DialogueState(
        phase=state.phase,
        observed_at=observed_at,
        started_at=state.started_at,
        expected_version=state.expected_version,
        mode=state.mode,
        bottle_capacity_ml=state.bottle_capacity_ml,
        proposal_digest=state.proposal_digest,
        warning_digest=state.warning_digest,
        warning_codes=state.warning_codes,
    )


def _closed_response(code: str) -> VoiceSemanticResponse:
    return VoiceSemanticResponse(1, code, None, None, None, None, None, (), None)


__all__ = [
    "VOICE_WORKER_UNAVAILABLE",
    "VoiceCommandProcessor",
    "VoicePreflightReport",
    "VoiceStatusWriter",
    "VOICE_TRANSITION_KEYS",
    "VoiceWorker",
    "run_voice_preflight",
]
