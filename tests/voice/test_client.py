from __future__ import annotations

import json

import pytest

from services.voice.client import (
    VOICE_CARE_MEDIA_TYPE,
    VoiceCareClient,
    VoiceSemanticResponse,
)


class RecordingTransport:
    def __init__(self, *, status_code: int = 200, body: bytes = b"") -> None:
        self.status_code = status_code
        self.body = body
        self.calls: list[tuple[str, dict[str, str], bytes, float]] = []

    def post(
        self,
        path: str,
        headers: dict[str, str],
        body: bytes,
        timeout_seconds: float,
    ) -> tuple[int, bytes]:
        self.calls.append((path, headers, body, timeout_seconds))
        return self.status_code, self.body


def semantic_body(code: str = "saved") -> bytes:
    return json.dumps(
        {
            "schemaVersion": 1,
            "code": code,
            "careSessionId": "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa"
            if code in {"saved", "accepted_pending"}
            else None,
            "careEventId": "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb"
            if code == "saved"
            else None,
            "sessionVersion": 1 if code in {"saved", "accepted_pending"} else None,
            "proposalDigest": "a" * 64 if code == "saved" else None,
            "warningDigest": None,
            "warningCodes": [],
            "readback": None,
        },
        separators=(",", ":"),
        sort_keys=True,
    ).encode()


def test_client_posts_exact_signed_bytes_to_the_fixed_intent_route() -> None:
    transport = RecordingTransport(body=semantic_body())
    client = VoiceCareClient(transport, timeout_seconds=3.0)

    result = client.send(b'{"signed":"intent"}')

    assert result.code == "saved"
    assert transport.calls == [
        (
            "/api/voice-care/intents",
            {"content-type": VOICE_CARE_MEDIA_TYPE},
            b'{"signed":"intent"}',
            3.0,
        )
    ]


@pytest.mark.parametrize("status_code", [400, 401, 409, 429, 500, 503])
def test_client_never_fabricates_saved_for_non_success_http(status_code: int) -> None:
    result = VoiceCareClient(
        RecordingTransport(status_code=status_code, body=b'{"code":"saved"}')
    ).send(b"{}")

    assert result == VoiceSemanticResponse.temporarily_unavailable()


def test_client_fails_closed_for_transport_failure_or_malformed_response() -> None:
    class BrokenTransport(RecordingTransport):
        def post(self, path, headers, body, timeout_seconds):
            raise RuntimeError("token at /private/family")

    for transport in (
        BrokenTransport(),
        RecordingTransport(body=b"not-json"),
        RecordingTransport(body=b'{"schemaVersion":1,"code":"saved"}'),
        RecordingTransport(
            body=semantic_body().replace(
                b'"schemaVersion":1', b'"schemaVersion":1,"schemaVersion":1'
            )
        ),
    ):
        assert VoiceCareClient(transport).send(b"{}") == (
            VoiceSemanticResponse.temporarily_unavailable()
        )


def test_client_accepts_only_closed_semantic_codes_and_consistent_fields() -> None:
    pending = VoiceCareClient(
        RecordingTransport(body=semantic_body("accepted_pending"))
    ).send(b"{}")
    assert pending.code == "accepted_pending"
    assert pending.care_event_id is None

    invalid = json.loads(semantic_body("saved"))
    invalid["warningCodes"] = ["unknown_warning"]
    response = VoiceCareClient(
        RecordingTransport(body=json.dumps(invalid).encode())
    ).send(b"{}")
    assert response == VoiceSemanticResponse.temporarily_unavailable()


def test_client_accepts_actual_needs_confirmation_and_state_conflict_shapes() -> None:
    needs_confirmation = json.loads(semantic_body("accepted_pending"))
    needs_confirmation.update(
        {
            "code": "needs_confirmation",
            "proposalDigest": "b" * 64,
            "warningDigest": "c" * 64,
            "warningCodes": ["unusual_value"],
            "readback": {
                "templateId": "feeding_bottle_readback",
                "liquidType": "formula",
                "amountMl": 90,
                "bottleCapacityMl": None,
            },
        }
    )
    parsed = VoiceCareClient(
        RecordingTransport(body=json.dumps(needs_confirmation).encode())
    ).send(b"{}")
    assert parsed.code == "needs_confirmation"
    assert parsed.readback == needs_confirmation["readback"]

    conflict = json.loads(semantic_body("accepted_pending"))
    conflict["code"] = "state_conflict"
    parsed_conflict = VoiceCareClient(
        RecordingTransport(body=json.dumps(conflict).encode())
    ).send(b"{}")
    assert parsed_conflict.code == "state_conflict"
    assert parsed_conflict.care_session_id == conflict["careSessionId"]
