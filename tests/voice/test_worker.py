from __future__ import annotations

import json
import threading
from datetime import UTC, datetime
from pathlib import Path

import pytest

from packages.contracts.audio import AudioFailureReason
from services.audio.source import DecoderRead
from services.voice.capture import UtteranceResult
from services.voice.client import VoiceSemanticResponse
from services.voice.outbox import DeliveryResult, OutboxEntry
from services.voice.speaker import SpeakerVerification
from services.voice.vad import VadResult
from packages.contracts.settings import VoiceCareSettings
from services.voice.worker import (
    VoiceCommandProcessor,
    VoiceStatusWriter,
    VoiceWorker,
    run_voice_preflight,
)
from services.voice.asr import AsrResult


class Decoder:
    def __init__(self, reads: list[DecoderRead]) -> None:
        self.reads = reads
        self.closed = False

    def read(self, max_bytes: int) -> DecoderRead:
        assert max_bytes == 3_200
        return self.reads.pop(0)

    def close(self) -> None:
        self.closed = True


class Vad:
    def __init__(self, result: VadResult) -> None:
        self.result = result

    def observe(self, frame: bytes) -> VadResult:
        return self.result


class Collector:
    def __init__(self, result: UtteranceResult | None) -> None:
        self.result = result
        self.reset_count = 0
        self.closed = False

    def push(self, frame: bytes, vad: VadResult) -> UtteranceResult | None:
        result, self.result = self.result, None
        return result

    def reset(self) -> None:
        self.reset_count += 1

    def close(self) -> None:
        self.closed = True


class Processor:
    def __init__(self, result: VoiceSemanticResponse | None | Exception) -> None:
        self.result = result
        self.calls: list[tuple[bytes, datetime]] = []

    def process(self, pcm: bytes, observed_at: datetime):
        self.calls.append((pcm, observed_at))
        if isinstance(self.result, Exception):
            raise self.result
        return self.result


class Synth:
    def __init__(self, result: bool = True) -> None:
        self.result = result
        self.codes: list[str] = []

    def speak_code(self, code: str, cancelled) -> bool:
        self.codes.append(code)
        return self.result


def saved_response() -> VoiceSemanticResponse:
    return VoiceSemanticResponse(
        1,
        "saved",
        "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
        "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb",
        1,
        "a" * 64,
        None,
        (),
        None,
    )


def worker(tmp_path: Path, *, processor_result=saved_response(), synth_result=True):
    observed = datetime(2026, 8, 24, 1, tzinfo=UTC)
    decoder = Decoder([DecoderRead(b"p" * 3_200)])
    collector = Collector(UtteranceResult(b"u" * 32_000, "terminal_silence"))
    processor = Processor(processor_result)
    synth = Synth(synth_result)
    status = VoiceStatusWriter(tmp_path / "voice.json", clock=lambda: observed)
    instance = VoiceWorker(
        decoder=decoder,
        vad=Vad(VadResult(True, 0.9)),
        collector=collector,
        processor=processor,
        synthesizer=synth,
        status_writer=status,
        clock=lambda: observed,
        monotonic_ns=iter((1_000_000_000, 1_080_000_000)).__next__,
    )
    return instance, decoder, collector, processor, synth, tmp_path / "voice.json"


def test_worker_processes_one_memory_only_utterance_and_writes_bounded_status(tmp_path: Path) -> None:
    instance, _decoder, _collector, processor, synth, status_path = worker(tmp_path)

    instance.step(threading.Event())

    assert len(processor.calls) == 1
    assert synth.codes == ["saved"]
    payload = json.loads(status_path.read_text(encoding="ascii"))
    assert payload == {
        "checked_at": "2026-08-24T01:00:00+00:00",
        "last_latency_ms": 80,
        "mode": "care",
        "processed_count": 1,
        "reason": "saved",
        "schema_version": 2,
        "worker_state": "healthy",
    }
    serialized = status_path.read_bytes().lower()
    for forbidden in (b"transcript", b"embedding", b"profile", b"path", b"pcm"):
        assert forbidden not in serialized


def test_worker_failure_is_closed_and_does_not_speak_or_raise(tmp_path: Path) -> None:
    instance, _decoder, collector, _processor, synth, status_path = worker(
        tmp_path,
        processor_result=RuntimeError("token /private/family"),
    )

    instance.step(threading.Event())

    payload = json.loads(status_path.read_text(encoding="ascii"))
    assert payload["worker_state"] == "degraded"
    assert payload["reason"] == "voice_worker_unavailable"
    assert synth.codes == []
    assert collector.reset_count == 1
    assert "private" not in status_path.read_text(encoding="ascii")


def test_worker_source_or_model_failure_does_not_invoke_the_pipeline(tmp_path: Path) -> None:
    instance, decoder, collector, processor, synth, status_path = worker(tmp_path)
    decoder.reads[:] = [DecoderRead(b"", AudioFailureReason.AUDIO_SOURCE_UNAVAILABLE)]
    instance.step(threading.Event())
    assert processor.calls == []
    assert synth.codes == []
    assert collector.reset_count == 1
    assert json.loads(status_path.read_text())["reason"] == "voice_audio_unavailable"

    instance, _decoder, collector, processor, synth, status_path = worker(tmp_path)
    instance._vad = Vad(VadResult(False, 0.0, "voice_model_unavailable"))
    instance.step(threading.Event())
    assert processor.calls == []
    assert synth.codes == []
    assert collector.reset_count == 1
    assert json.loads(status_path.read_text())["reason"] == "voice_model_unavailable"


def test_worker_run_closes_only_its_decoder_and_collector(tmp_path: Path) -> None:
    instance, decoder, collector, _processor, _synth, _status = worker(tmp_path)
    stop = threading.Event()
    stop.set()

    instance.run(stop)

    assert decoder.closed is True
    assert collector.closed is True


class _PreflightKeychain:
    def __init__(self, value: bytes | None) -> None:
        self.value = value
        self.calls: list[tuple[str, int]] = []

    def read(self, account: str, *, size: int) -> bytes | None:
        self.calls.append((account, size))
        return self.value


def _voice_model_settings(*, enabled: bool = False) -> VoiceCareSettings:
    return VoiceCareSettings(
        enabled=enabled,
        silero_vad_manifest_sha256="a" * 64,
        whisper_base_manifest_sha256="c" * 64,
        whisper_small_manifest_sha256="d" * 64,
        paraformer_zh_manifest_sha256="b" * 64,
        speechbrain_ecapa_manifest_sha256="e" * 64,
    )


def test_preflight_reads_one_fixed_key_and_validates_only_selected_models(
    tmp_path: Path,
) -> None:
    keychain = _PreflightKeychain(b"k" * 32)
    validated: list[str] = []

    report = run_voice_preflight(
        _voice_model_settings(),
        tmp_path,
        keychain_factory=lambda _root: keychain,
        artifact_validator=lambda spec, _root: validated.append(spec.artifact_id),
    )

    assert report.available is True
    assert report.reason == "voice_preflight_available"
    assert report.asr_profile == "paraformer"
    assert keychain.calls == [("voice-asr-calibration-key.v2", 32)]
    assert validated == [
        "sherpa-onnx-paraformer-zh-2023-09-14",
        "silero-vad-v6.2",
    ]


def test_preflight_keychain_failure_does_not_open_models(tmp_path: Path) -> None:
    validated: list[str] = []

    report = run_voice_preflight(
        _voice_model_settings(),
        tmp_path,
        keychain_factory=lambda _root: _PreflightKeychain(None),
        artifact_validator=lambda spec, _root: validated.append(spec.artifact_id),
    )

    assert report.available is False
    assert report.reason == "voice_keychain_unavailable"
    assert report.asr_profile is None
    assert validated == []


def test_preflight_model_failure_is_bounded_and_keeps_voice_disabled(
    tmp_path: Path,
) -> None:
    keychain = _PreflightKeychain(b"k" * 32)

    def reject_model(_spec, _root) -> None:
        raise RuntimeError("private path or model exception")

    report = run_voice_preflight(
        _voice_model_settings(),
        tmp_path,
        keychain_factory=lambda _root: keychain,
        artifact_validator=reject_model,
    )
    enabled_report = run_voice_preflight(
        _voice_model_settings(enabled=True),
        tmp_path,
        keychain_factory=lambda _root: keychain,
        artifact_validator=lambda _spec, _root: None,
    )

    assert report.available is False
    assert report.reason == "voice_model_unavailable"
    assert enabled_report.available is False
    assert enabled_report.reason == "voice_preflight_unavailable"


def test_status_writer_rejects_unlisted_reason_instead_of_echoing_it(tmp_path: Path) -> None:
    writer = VoiceStatusWriter(
        tmp_path / "voice.json",
        clock=lambda: datetime(2026, 8, 24, 1, tzinfo=UTC),
    )
    with pytest.raises(ValueError, match="^voice_worker_unavailable$"):
        writer.write(
            mode="listen_only",
            worker_state="degraded",
            reason="private_password",
            processed_count=0,
            last_latency_ms=None,
        )
    assert not (tmp_path / "voice.json").exists()


def test_status_writer_emits_closed_schema_v2_listen_only_status(tmp_path: Path) -> None:
    writer = VoiceStatusWriter(
        tmp_path / "voice.json",
        clock=lambda: datetime(2026, 8, 24, 1, tzinfo=UTC),
    )

    writer.write(
        mode="listen_only",
        worker_state="healthy",
        reason="listen_only_idle",
        processed_count=3,
        last_latency_ms=80,
    )

    assert json.loads((tmp_path / "voice.json").read_text(encoding="ascii")) == {
        "checked_at": "2026-08-24T01:00:00+00:00",
        "last_latency_ms": 80,
        "mode": "listen_only",
        "processed_count": 3,
        "reason": "listen_only_idle",
        "schema_version": 2,
        "worker_state": "healthy",
    }


def test_status_writer_accepts_only_fixed_bounded_transition_counts(tmp_path: Path) -> None:
    writer = VoiceStatusWriter(
        tmp_path / "voice.json",
        clock=lambda: datetime(2026, 8, 24, 1, tzinfo=UTC),
    )
    counts = {
        "armed_timeouts": 1,
        "ignored_followups": 2,
        "ignored_far": 3,
        "ignored_near_reply_echo": 4,
        "ignored_near_start": 5,
        "output_failures": 6,
        "replay_frames": 7,
        "replay_ignored": 8,
        "replay_utterances": 9,
        "reply_echo_ignored": 10,
        "utterances": 11,
        "vad_speech_frames": 12,
    }

    writer.write(
        mode="listen_only",
        worker_state="healthy",
        reason="listen_only_idle",
        processed_count=3,
        last_latency_ms=80,
        transition_counts=counts,
    )

    payload = json.loads((tmp_path / "voice.json").read_text(encoding="ascii"))
    assert payload["transition_counts"] == counts
    counts["private_text"] = 1
    with pytest.raises(ValueError, match="^voice_worker_unavailable$"):
        writer.write(
            mode="listen_only",
            worker_state="healthy",
            reason="listen_only_idle",
            processed_count=3,
            last_latency_ms=80,
            transition_counts=counts,
        )


class Asr:
    def __init__(self, texts: list[str]) -> None:
        self.texts = texts

    def transcribe(self, pcm: bytes) -> AsrResult:
        return AsrResult(self.texts.pop(0), "zh", 30)


class Identity:
    def __init__(self) -> None:
        self.values: list[dict[str, object]] = []

    def sign_intent(self, value) -> bytes:
        self.values.append(dict(value))
        return json.dumps(value, sort_keys=True, separators=(",", ":")).encode()


class Outbox:
    def __init__(self, responses: list[VoiceSemanticResponse]) -> None:
        self.responses = responses
        self.enqueued: list[bytes] = []

    def enqueue(self, signed: bytes) -> OutboxEntry:
        self.enqueued.append(signed)
        request_id = str(json.loads(signed)["requestId"])
        observed = datetime(2026, 8, 24, 1, tzinfo=UTC)
        return OutboxEntry(request_id, "pending", observed, observed)

    def deliver(self, _client) -> tuple[DeliveryResult, ...]:
        request_id = str(json.loads(self.enqueued[-1])["requestId"])
        response = self.responses.pop(0)
        state = "awaiting_confirmation" if response.code != "saved" else "delivered"
        return (DeliveryResult(request_id, state, response.code, response),)


def pending_response() -> VoiceSemanticResponse:
    return VoiceSemanticResponse(
        1,
        "accepted_pending",
        "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
        None,
        1,
        None,
        None,
        (),
        None,
    )


def pending_update_response() -> VoiceSemanticResponse:
    return VoiceSemanticResponse(
        1,
        "accepted_pending",
        "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
        None,
        2,
        None,
        None,
        (),
        None,
    )


def confirmation_response() -> VoiceSemanticResponse:
    return VoiceSemanticResponse(
        1,
        "needs_confirmation",
        "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
        None,
        3,
        "b" * 64,
        None,
        (),
        {
            "templateId": "feeding_bottle_readback",
            "liquidType": "formula",
            "amountMl": 90,
            "bottleCapacityMl": None,
        },
    )


def test_command_processor_composes_claim_parser_signing_and_delivery() -> None:
    identity = Identity()
    outbox = Outbox(
        [pending_response(), pending_update_response(), confirmation_response()]
    )
    claims: list[str | None] = []

    def verify(claimed_profile_id: str | None, pcm: bytes) -> SpeakerVerification:
        claims.append(claimed_profile_id)
        return SpeakerVerification("verified", "speaker_verified")

    request_ids = iter(
        (
            "33333333-3333-4333-8333-333333333333",
            "44444444-4444-4444-8444-444444444444",
            "55555555-5555-4555-8555-555555555555",
        )
    )
    processor = VoiceCommandProcessor(
        asr=Asr(
            [
                "小小，我是爸爸，开始喂配方奶",
                "小小，我是爸爸，喝了90毫升配方奶",
                "小小，我是爸爸，喂完了喝了90毫升配方奶",
            ]
        ),
        speaker_verifier=verify,
        profile_claims={"dad": "dddddddd-dddd-4ddd-8ddd-dddddddddddd"},
        identity=identity,
        outbox=outbox,
        client=object(),
        device_id="11111111-1111-4111-8111-111111111111",
        lease_id="22222222-2222-4222-8222-222222222222",
        model_version="voice-v1",
        request_id_factory=request_ids.__next__,
    )
    first_at = datetime(2026, 8, 24, 1, tzinfo=UTC)

    first = processor.process(b"p" * 32_000, first_at)
    second = processor.process(b"p" * 32_000, first_at.replace(minute=3))
    third = processor.process(b"p" * 32_000, first_at.replace(minute=5))

    assert first == pending_response()
    assert second == pending_update_response()
    assert third == confirmation_response()
    assert claims == ["dddddddd-dddd-4ddd-8ddd-dddddddddddd"] * 3
    start, update, end = identity.values
    assert start["intentType"] == "feeding_start"
    assert start["careSessionId"] is None
    assert start["speakerState"] == "verified"
    assert update["intentType"] == "feeding_update"
    assert update["payload"]["expectedVersion"] == 1
    assert end["intentType"] == "feeding_end"
    assert end["careSessionId"] == "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
    assert end["payload"]["expectedVersion"] == 2
    for value in identity.values:
        assert "transcript" not in value
        assert "profileId" not in value


def test_command_processor_ignores_missing_wake_without_signing() -> None:
    identity = Identity()
    outbox = Outbox([])
    processor = VoiceCommandProcessor(
        asr=Asr(["我是爸爸，开始喂奶"]),
        speaker_verifier=lambda _claim, _pcm: SpeakerVerification(
            "verified", "speaker_verified"
        ),
        profile_claims={"dad": "dddddddd-dddd-4ddd-8ddd-dddddddddddd"},
        identity=identity,
        outbox=outbox,
        client=object(),
        device_id="11111111-1111-4111-8111-111111111111",
        lease_id="22222222-2222-4222-8222-222222222222",
        model_version="voice-v1",
        request_id_factory=lambda: "33333333-3333-4333-8333-333333333333",
    )

    assert processor.process(
        b"p" * 32_000, datetime(2026, 8, 24, 1, tzinfo=UTC)
    ) is None
    assert identity.values == []
    assert outbox.enqueued == []
