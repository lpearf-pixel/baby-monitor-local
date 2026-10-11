from __future__ import annotations

import json
from datetime import datetime, timezone

from services.voice.m7_gateway import (
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
