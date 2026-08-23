from __future__ import annotations

import json
import os
import sqlite3
from datetime import UTC, datetime, timedelta

import pytest

from services.voice.client import VoiceSemanticResponse
from services.voice.keychain import KeychainSecretStore
from services.voice.outbox import (
    OUTBOX_INVALID,
    VoiceIntentOutbox,
)
from services.voice.signing import DeviceIdentity
from tests.voice.test_signing import FakeKeychain, unsigned_feeding_start


class RecordingClient:
    def __init__(self, responses: list[VoiceSemanticResponse]) -> None:
        self.responses = responses
        self.sent: list[bytes] = []

    def send(self, intent: bytes) -> VoiceSemanticResponse:
        self.sent.append(intent)
        return self.responses.pop(0)


def make_signed(backend: FakeKeychain, *, occurred_at: datetime) -> bytes:
    value = unsigned_feeding_start()
    stamp = occurred_at.isoformat()
    value["issuedAt"] = stamp
    value["occurredAt"] = stamp
    value["payload"] = {"mode": "bottle", "startedAt": stamp}
    identity = DeviceIdentity(
        KeychainSecretStore(backend, random_bytes=lambda size: b"s" * size)
    )
    return identity.sign_intent(value)


def make_outbox(tmp_path, backend, clock) -> VoiceIntentOutbox:
    return VoiceIntentOutbox(
        tmp_path / "private" / "voice-outbox.sqlite3",
        KeychainSecretStore(backend, random_bytes=lambda size: b"o" * size),
        now=lambda: clock[0],
        random_bytes=os.urandom,
        retention_seconds=60,
        max_items=4,
    )


def saved_response() -> VoiceSemanticResponse:
    return VoiceSemanticResponse(
        schema_version=1,
        code="saved",
        care_session_id="aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
        care_event_id="bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb",
        session_version=1,
        proposal_digest="a" * 64,
        warning_digest=None,
        warning_codes=(),
        readback=None,
    )


def accepted_pending_response() -> VoiceSemanticResponse:
    return VoiceSemanticResponse(
        schema_version=1,
        code="accepted_pending",
        care_session_id="aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
        care_event_id=None,
        session_version=1,
        proposal_digest=None,
        warning_digest=None,
        warning_codes=(),
        readback=None,
    )


def test_outbox_retries_exact_signed_bytes_and_survives_restart(tmp_path) -> None:
    backend = FakeKeychain()
    clock = [datetime(2026, 8, 19, 4, tzinfo=UTC)]
    signed = make_signed(backend, occurred_at=clock[0])
    first = make_outbox(tmp_path, backend, clock)
    assert first.enqueue(signed).state == "pending"
    unavailable = RecordingClient([VoiceSemanticResponse.temporarily_unavailable()])
    assert first.deliver(unavailable)[0].state == "pending"

    restarted = make_outbox(tmp_path, backend, clock)
    saved = RecordingClient([saved_response()])
    result = restarted.deliver(saved)

    assert unavailable.sent == [signed]
    assert saved.sent == [signed]
    assert result[0].state == "delivered"
    assert result[0].response == saved_response()
    assert restarted.pending_count() == 0


def test_outbox_duplicate_request_is_idempotent_but_conflict_fails_closed(tmp_path) -> None:
    backend = FakeKeychain()
    clock = [datetime(2026, 8, 19, 4, tzinfo=UTC)]
    outbox = make_outbox(tmp_path, backend, clock)
    signed = make_signed(backend, occurred_at=clock[0])

    first = outbox.enqueue(signed)
    second = outbox.enqueue(signed)
    changed = json.loads(signed)
    changed["signature"] = "A" * 86

    assert first == second
    assert outbox.pending_count() == 1
    with pytest.raises(ValueError, match=f"^{OUTBOX_INVALID}$"):
        outbox.enqueue(json.dumps(changed, sort_keys=True, separators=(",", ":")).encode())


def test_outbox_marks_expired_or_ambiguous_intent_for_reconciliation(tmp_path) -> None:
    backend = FakeKeychain()
    clock = [datetime(2026, 8, 19, 4, tzinfo=UTC)]
    outbox = make_outbox(tmp_path, backend, clock)
    signed = make_signed(backend, occurred_at=clock[0])
    outbox.enqueue(signed)
    unavailable = RecordingClient([VoiceSemanticResponse.temporarily_unavailable()])
    assert outbox.deliver(unavailable)[0].state == "pending"
    clock[0] += timedelta(seconds=61)
    client = RecordingClient([saved_response()])

    results = outbox.deliver(client)

    assert client.sent == []
    assert results[0].state == "reconcile_required"
    assert results[0].response is None
    assert outbox.pending_count() == 0


def test_outbox_does_not_send_at_the_exact_expiration_boundary(tmp_path) -> None:
    backend = FakeKeychain()
    clock = [datetime(2026, 8, 19, 4, tzinfo=UTC)]
    outbox = make_outbox(tmp_path, backend, clock)
    outbox.enqueue(make_signed(backend, occurred_at=clock[0]))
    clock[0] += timedelta(seconds=60)
    client = RecordingClient([saved_response()])

    result = outbox.deliver(client)

    assert client.sent == []
    assert result[0].state == "reconcile_required"


def test_outbox_stops_replay_after_server_accepts_pending_confirmation(tmp_path) -> None:
    backend = FakeKeychain()
    clock = [datetime(2026, 8, 19, 4, tzinfo=UTC)]
    outbox = make_outbox(tmp_path, backend, clock)
    signed = make_signed(backend, occurred_at=clock[0])
    outbox.enqueue(signed)
    client = RecordingClient([accepted_pending_response()])

    result = outbox.deliver(client)

    assert result[0].state == "awaiting_confirmation"
    assert result[0].response == accepted_pending_response()
    assert outbox.pending_count() == 0


def test_outbox_tamper_fails_closed_without_sending(tmp_path) -> None:
    backend = FakeKeychain()
    clock = [datetime(2026, 8, 19, 4, tzinfo=UTC)]
    outbox = make_outbox(tmp_path, backend, clock)
    outbox.enqueue(make_signed(backend, occurred_at=clock[0]))
    database = tmp_path / "private" / "voice-outbox.sqlite3"
    with sqlite3.connect(database) as connection:
        row = connection.execute(
            "SELECT request_id, ciphertext FROM voice_intent_outbox"
        ).fetchone()
        ciphertext = bytearray(row[1])
        ciphertext[-1] ^= 1
        connection.execute(
            "UPDATE voice_intent_outbox SET ciphertext = ? WHERE request_id = ?",
            (bytes(ciphertext), row[0]),
        )
    client = RecordingClient([saved_response()])

    with pytest.raises(ValueError, match=f"^{OUTBOX_INVALID}$"):
        outbox.deliver(client)
    assert client.sent == []


def test_outbox_database_contains_no_plaintext_voice_or_endpoint_material(tmp_path) -> None:
    backend = FakeKeychain()
    clock = [datetime(2026, 8, 19, 4, tzinfo=UTC)]
    outbox = make_outbox(tmp_path, backend, clock)
    signed = make_signed(backend, occurred_at=clock[0])
    outbox.enqueue(signed)
    database = tmp_path / "private" / "voice-outbox.sqlite3"

    raw = database.read_bytes()
    schema = " ".join(
        row[0]
        for row in sqlite3.connect(database).execute(
            "SELECT sql FROM sqlite_master WHERE sql IS NOT NULL"
        )
    ).lower()

    for forbidden in (
        b"feeding_start",
        b"transcript",
        b"embedding",
        b"endpoint",
        b"credential",
        b"audio",
        b"pcm",
    ):
        assert forbidden not in raw.lower()
        assert forbidden.decode() not in schema
    assert os.stat(database).st_mode & 0o777 == 0o600
    assert os.stat(database.parent).st_mode & 0o777 == 0o700


def test_outbox_is_bounded_and_rejects_symlink_database(tmp_path) -> None:
    backend = FakeKeychain()
    clock = [datetime(2026, 8, 19, 4, tzinfo=UTC)]
    outbox = make_outbox(tmp_path, backend, clock)
    for index in range(4):
        signed = json.loads(make_signed(backend, occurred_at=clock[0]))
        signed["requestId"] = f"33333333-3333-4333-8333-{index:012d}"
        signed["signature"] = "A" * 86
        outbox.enqueue(json.dumps(signed, sort_keys=True, separators=(",", ":")).encode())
    with pytest.raises(ValueError, match=f"^{OUTBOX_INVALID}$"):
        outbox.enqueue(make_signed(backend, occurred_at=clock[0]))

    target = tmp_path / "target.sqlite3"
    target.touch()
    link = tmp_path / "outbox-link.sqlite3"
    link.symlink_to(target)
    with pytest.raises(ValueError, match=f"^{OUTBOX_INVALID}$"):
        VoiceIntentOutbox(link, KeychainSecretStore(backend))
