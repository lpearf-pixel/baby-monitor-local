from __future__ import annotations

import base64
import json
import os
import sqlite3
import threading
from datetime import UTC, datetime
from pathlib import Path

from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

from packages.contracts.voice_care import verify_vendored_voice_care_contract
from services.audio.source import DecoderRead
from services.voice.asr import AsrResult
from services.voice.capture import UtteranceResult
from services.voice.client import VoiceSemanticResponse
from services.voice.keychain import KeychainSecretStore
from services.voice.outbox import VoiceIntentOutbox
from services.voice.signing import DeviceIdentity, canonical_json_bytes
from services.voice.speaker import SpeakerVerification
from services.voice.vad import VadResult
from services.voice.worker import VoiceCommandProcessor, VoiceStatusWriter, VoiceWorker


NOW = datetime(2026, 8, 24, 1, tzinfo=UTC)
DEVICE_ID = "11111111-1111-4111-8111-111111111111"
LEASE_ID = "22222222-2222-4222-8222-222222222222"
PROFILE_ID = "dddddddd-dddd-4ddd-8ddd-dddddddddddd"
SESSION_IDS = (
    "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaa1",
    "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaa2",
    "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaa3",
    "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaa4",
)


class MemoryKeychain:
    def __init__(self) -> None:
        self.values: dict[tuple[str, str], bytes] = {}

    def read(self, service: str, account: str) -> bytes | None:
        return self.values.get((service, account))

    def write(self, service: str, account: str, secret: bytes) -> None:
        self.values.setdefault((service, account), bytes(secret))

    def delete(self, service: str, account: str) -> None:
        self.values.pop((service, account), None)


class SyntheticAsr:
    def __init__(self, texts: list[str]) -> None:
        self.texts = list(texts)

    def transcribe(self, _pcm: bytes) -> AsrResult:
        return AsrResult(self.texts.pop(0), "zh", 20)


class SyntheticDecoder:
    def read(self, max_bytes: int) -> DecoderRead:
        return DecoderRead(b"p" * max_bytes)

    def close(self) -> None:
        pass


class SyntheticVad:
    def observe(self, _frame: bytes) -> VadResult:
        return VadResult(True, 0.95)


class SyntheticCollector:
    def __init__(self, count: int) -> None:
        self.remaining = count

    def push(self, _frame: bytes, _vad: VadResult) -> UtteranceResult | None:
        if self.remaining == 0:
            return None
        self.remaining -= 1
        return UtteranceResult(b"u" * 32_000, "terminal_silence")

    def reset(self) -> None:
        pass

    def close(self) -> None:
        pass


class RecordingSynthesizer:
    def __init__(self) -> None:
        self.codes: list[str] = []

    def speak_code(self, code: str, _cancelled: threading.Event) -> bool:
        self.codes.append(code)
        return True


class SyntheticBabyCare:
    """Small semantic double; the real PostgreSQL side is tested in Baby Care."""

    def __init__(self, public_key: bytes) -> None:
        self.public_key = Ed25519PublicKey.from_public_bytes(public_key)
        self.intents: list[dict[str, object]] = []
        self.session_index = 0
        self.active_session: str | None = None
        self.version = 0
        self.proposal_digest = "b" * 64
        self.care_events: list[str] = []

    def send(self, raw: bytes) -> VoiceSemanticResponse:
        signed = json.loads(raw)
        signature = signed.pop("signature")
        self.public_key.verify(
            base64.urlsafe_b64decode(signature + "=="),
            canonical_json_bytes(signed),
        )
        self.intents.append(dict(signed))
        if signed["speakerState"] == "mismatch":
            return response("identity_mismatch")
        intent_type = signed["intentType"]
        if intent_type == "feeding_start":
            self.active_session = SESSION_IDS[self.session_index]
            self.session_index += 1
            self.version = 1
            return response(
                "accepted_pending",
                care_session_id=self.active_session,
                session_version=self.version,
            )
        assert signed["careSessionId"] == self.active_session
        if intent_type == "feeding_update":
            self.version += 1
            return response(
                "accepted_pending",
                care_session_id=self.active_session,
                session_version=self.version,
            )
        if intent_type == "feeding_end":
            self.version += 1
            proposal = signed["payload"]["finalProposal"]
            readback = (
                {
                    "templateId": "feeding_bottle_readback",
                    "liquidType": proposal["liquidType"],
                    "amountMl": proposal["amountMl"],
                    "bottleCapacityMl": proposal["bottleCapacityMl"],
                }
                if proposal["mode"] == "bottle"
                else {
                    "templateId": "feeding_direct_readback",
                    "durationMinutes": proposal["durationMinutes"],
                }
            )
            return response(
                "needs_confirmation",
                care_session_id=self.active_session,
                session_version=self.version,
                proposal_digest=self.proposal_digest,
                readback=readback,
            )
        if intent_type == "care_confirm":
            assert signed["payload"]["proposalDigest"] == self.proposal_digest
            self.version += 1
            event_id = f"bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbb{len(self.care_events) + 1}"
            self.care_events.append(event_id)
            result = response(
                "saved",
                care_session_id=self.active_session,
                care_event_id=event_id,
                session_version=self.version,
                proposal_digest=self.proposal_digest,
            )
            self.active_session = None
            return result
        if intent_type == "care_cancel":
            self.version += 1
            session_id = self.active_session
            self.active_session = None
            return response(
                "accepted_pending",
                care_session_id=session_id,
                session_version=self.version,
            )
        raise AssertionError("unexpected synthetic intent")


class OutageThenServer:
    def __init__(self, server: SyntheticBabyCare) -> None:
        self.server = server
        self.failed = False
        self.raw: list[bytes] = []

    def send(self, raw: bytes) -> VoiceSemanticResponse:
        self.raw.append(raw)
        if not self.failed:
            self.failed = True
            raise OSError("synthetic outage")
        return self.server.send(raw)


def response(
    code: str,
    *,
    care_session_id: str | None = None,
    care_event_id: str | None = None,
    session_version: int | None = None,
    proposal_digest: str | None = None,
    readback: dict[str, object] | None = None,
) -> VoiceSemanticResponse:
    return VoiceSemanticResponse(
        1,
        code,
        care_session_id,
        care_event_id,
        session_version,
        proposal_digest,
        None,
        (),
        readback,
    )


def make_pipeline(tmp_path: Path, texts: list[str]):
    keychain = MemoryKeychain()
    store = KeychainSecretStore(keychain, random_bytes=lambda size: b"s" * size)
    identity = DeviceIdentity(store)
    outbox = VoiceIntentOutbox(
        tmp_path / "private" / "voice-outbox.sqlite3",
        store,
        now=lambda: NOW,
        random_bytes=os.urandom,
    )
    server = SyntheticBabyCare(identity.public_key_bytes())
    processor = VoiceCommandProcessor(
        asr=SyntheticAsr(texts),
        speaker_verifier=lambda claimed, _pcm: SpeakerVerification(
            "verified" if claimed == PROFILE_ID else "mismatch",
            "speaker_verified" if claimed == PROFILE_ID else "speaker_mismatch",
        ),
        profile_claims={"dad": PROFILE_ID},
        identity=identity,
        outbox=outbox,
        client=server,
        device_id=DEVICE_ID,
        lease_id=LEASE_ID,
        model_version="synthetic-v1",
        request_id_factory=(
            f"33333333-3333-4333-8333-{index:012d}" for index in range(1, 32)
        ).__next__,
    )
    synth = RecordingSynthesizer()
    monotonic = (value for index in range(64) for value in (index * 100_000_000, index * 100_000_000 + 20_000_000))
    worker = VoiceWorker(
        decoder=SyntheticDecoder(),
        vad=SyntheticVad(),
        collector=SyntheticCollector(len(texts)),
        processor=processor,
        synthesizer=synth,
        status_writer=VoiceStatusWriter(tmp_path / "voice-status.json", clock=lambda: NOW),
        clock=lambda: NOW,
        monotonic_ns=monotonic.__next__,
    )
    return worker, synth, server, outbox, identity


def test_synthetic_audio_closes_bottle_direct_cancel_and_identity_paths(tmp_path: Path) -> None:
    contract = verify_vendored_voice_care_contract()
    assert contract.source_commit == "bb1337226c1948695159d14199c9bb73cdaf115a"
    texts = [
        "小小，我是爸爸，开始喂配方奶",
        "小小，我是爸爸，喝了90毫升配方奶",
        "小小，我是爸爸，喂完了喝了90毫升配方奶",
        "小小，我是爸爸，确认保存",
        "小小，我是爸爸，开始亲喂",
        "小小，我是爸爸，喂完了亲喂18分钟",
        "小小，我是爸爸，确认保存",
        "小小，我是爸爸，开始喂奶",
        "小小，我是爸爸，取消记录",
        "小小，我是妈妈，开始喂奶",
    ]
    worker, synth, server, outbox, _identity = make_pipeline(tmp_path, texts)

    for _text in texts:
        worker.step(threading.Event())

    assert synth.codes == [
        "accepted_pending",
        "accepted_pending",
        "needs_confirmation",
        "saved",
        "accepted_pending",
        "needs_confirmation",
        "saved",
        "accepted_pending",
        "accepted_pending",
        "identity_mismatch",
    ]
    assert len(server.care_events) == 2
    assert [item["intentType"] for item in server.intents] == [
        "feeding_start",
        "feeding_update",
        "feeding_end",
        "care_confirm",
        "feeding_start",
        "feeding_end",
        "care_confirm",
        "feeding_start",
        "care_cancel",
        "feeding_start",
    ]
    assert server.intents[0]["speakerState"] == "verified"
    assert server.intents[-1]["speakerState"] == "mismatch"
    for intent in server.intents:
        assert "transcript" not in intent
        assert "profileId" not in intent
    assert outbox.pending_count() == 0
    status = (tmp_path / "voice-status.json").read_text(encoding="ascii")
    assert "identity_mismatch" in status
    for forbidden in ("小小", "爸爸", "妈妈", "transcript", PROFILE_ID):
        assert forbidden not in status


def test_signed_outbox_retries_exact_bytes_after_outage_without_plaintext(tmp_path: Path) -> None:
    worker, _synth, server, outbox, identity = make_pipeline(tmp_path, [])
    del worker
    unsigned = {
        "schemaVersion": 1,
        "requestId": "33333333-3333-4333-8333-000000000099",
        "deviceId": DEVICE_ID,
        "leaseId": LEASE_ID,
        "issuedAt": NOW.isoformat(),
        "occurredAt": NOW.isoformat(),
        "deliveryMode": "live",
        "speakerState": "verified",
        "source": "voice",
        "modelVersion": "synthetic-v1",
        "intentType": "feeding_start",
        "careSessionId": None,
        "payload": {"mode": "bottle", "startedAt": NOW.isoformat()},
    }
    signed = identity.sign_intent(unsigned)
    assert outbox.enqueue(signed) == outbox.enqueue(signed)
    client = OutageThenServer(server)

    first = outbox.deliver(client)
    second = outbox.deliver(client)

    assert first[0].state == "pending"
    assert second[0].semantic_code == "accepted_pending"
    assert client.raw == [signed, signed]
    assert len(server.intents) == 1
    assert outbox.pending_count() == 0
    database = tmp_path / "private" / "voice-outbox.sqlite3"
    raw = database.read_bytes().lower()
    for forbidden in (b"feeding_start", b"transcript", b"audio", b"pcm"):
        assert forbidden not in raw
    with sqlite3.connect(database) as connection:
        assert connection.execute(
            "select state, nonce, ciphertext from voice_intent_outbox"
        ).fetchone() == ("awaiting_confirmation", None, None)
