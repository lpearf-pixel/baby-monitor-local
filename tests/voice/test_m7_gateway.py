from __future__ import annotations

import json
from datetime import datetime, timezone

from services.voice.m7_gateway import (
    M7BabyCareGateway,
    V2VoiceCareGateway,
    build_feeding_update_v2,
)


class Identity:
    def sign_intent(self, value: dict[str, object]) -> bytes:
        return json.dumps({**value, "signature": "A" * 86}, sort_keys=True, separators=(",", ":")).encode()


def test_v2_update_preserves_multiple_components_and_direct_duration() -> None:
    signed = build_feeding_update_v2(
        identity=Identity(),
        request_id="11111111-1111-4111-8111-111111111111",
        device_id="22222222-2222-4222-8222-222222222222",
        lease_id="33333333-3333-4333-8333-333333333333",
        session_id="44444444-4444-4444-8444-444444444444",
        expected_version=2,
        occurred_at=datetime(2026, 10, 11, 1, tzinfo=timezone.utc),
        components=(
            {"kind": "bottle", "liquidType": "expressed_breast_milk", "amountMl": 60},
            {"kind": "bottle", "liquidType": "formula", "amountMl": 30},
            {"kind": "direct_breastfeeding", "durationMinutes": 12},
        ),
    )

    payload = json.loads(signed)
    assert payload["schemaVersion"] == 2
    assert payload["intentType"] == "feeding_update"
    assert payload["payload"]["components"][0]["amountMl"] == 60
    assert payload["payload"]["components"][2] == {
        "kind": "direct_breastfeeding",
        "durationMinutes": 12,
    }


def test_v2_gateway_does_not_downgrade_components_to_v1() -> None:
    gateway = V2VoiceCareGateway(
        transport=lambda body: (200, b'{"schemaVersion":2,"code":"accepted_pending"}')
    )

    result = gateway.send(b'{"schemaVersion":2,"intentType":"feeding_update"}')

    assert result.code == "accepted_pending"
    assert gateway.last_schema_version == 2


def test_m7_baby_care_gateway_maps_m6_lifecycle_to_v2_and_uses_authoritative_codes() -> None:
    responses = iter(
        [
            {"schemaVersion": 2, "code": "accepted_pending", "careSessionId": "44444444-4444-4444-8444-444444444444", "sessionVersion": 1},
            {"schemaVersion": 2, "code": "accepted_pending", "careSessionId": "44444444-4444-4444-8444-444444444444", "sessionVersion": 2},
            {"schemaVersion": 2, "code": "needs_confirmation", "careSessionId": "44444444-4444-4444-8444-444444444444", "sessionVersion": 3, "proposalDigest": "a" * 64},
            {"schemaVersion": 2, "code": "saved", "careSessionId": "44444444-4444-4444-8444-444444444444", "careEventId": "55555555-5555-4555-8555-555555555555", "sessionVersion": 4, "proposalDigest": "a" * 64},
        ]
    )
    bodies: list[dict[str, object]] = []

    def transport(body: bytes) -> tuple[int, bytes]:
        payload = json.loads(body)
        bodies.append(payload)
        return 200, json.dumps(next(responses)).encode()

    gateway = M7BabyCareGateway(
        identity=Identity(),
        transport=transport,
        device_id="22222222-2222-4222-8222-222222222222",
        lease_id="33333333-3333-4333-8333-333333333333",
        request_id_factory=iter(
            [
                "11111111-1111-4111-8111-111111111111",
                "11111111-1111-4111-8111-111111111112",
                "11111111-1111-4111-8111-111111111113",
                "11111111-1111-4111-8111-111111111114",
            ]
        ).__next__,
        clock=lambda: datetime(2026, 10, 11, 1, tzinfo=timezone.utc),
    )

    session = gateway.start(occurred_at=datetime(2026, 10, 11, 1, tzinfo=timezone.utc))
    gateway.update(session_id=session, components=({"kind": "bottle", "liquidType": "formula", "amountMl": 30},))
    proposal = gateway.end(session_id=session, components=({"kind": "bottle", "liquidType": "formula", "amountMl": 30},))
    assert gateway.confirm(session_id=session, proposal_id=proposal) == "saved"
    assert [body["schemaVersion"] for body in bodies] == [2, 2, 2, 2]
    assert bodies[1]["payload"]["components"][0]["amountMl"] == 30
