"""Versioned Baby Care v2 intent construction and transport boundary."""

from __future__ import annotations

import json
from datetime import datetime
from typing import Protocol

from services.voice.client import VoiceSemanticResponse
from services.voice.signing import DeviceIdentity


class IntentSigner(Protocol):
    def sign_intent(self, value: dict[str, object]) -> bytes: ...


class V2Transport(Protocol):
    def __call__(self, body: bytes) -> tuple[int, bytes]: ...


def build_feeding_update_v2(
    *,
    identity: IntentSigner,
    request_id: str,
    device_id: str,
    lease_id: str,
    session_id: str,
    expected_version: int,
    occurred_at: datetime,
    components: tuple[dict[str, object], ...],
) -> bytes:
    timestamp = occurred_at.isoformat()
    value = {
        "schemaVersion": 2,
        "requestId": request_id,
        "deviceId": device_id,
        "leaseId": lease_id,
        "issuedAt": timestamp,
        "occurredAt": timestamp,
        "deliveryMode": "live",
        "speakerState": "verified",
        "source": "voice",
        "modelVersion": "m7-llm",
        "intentType": "feeding_update",
        "careSessionId": session_id,
        "payload": {
            "expectedVersion": expected_version,
            "components": [dict(component) for component in components],
        },
    }
    return identity.sign_intent(value)


class V2VoiceCareGateway:
    def __init__(self, transport: V2Transport) -> None:
        self._transport = transport
        self.last_schema_version: int | None = None

    def send(self, body: bytes) -> VoiceSemanticResponse:
        try:
            status, raw = self._transport(body)
            if status != 200 or len(raw) > 16_384:
                raise ValueError
            payload = json.loads(raw.decode("utf-8"))
            if not isinstance(payload, dict) or payload.get("schemaVersion") != 2:
                raise ValueError("v2_required")
            code = payload.get("code")
            if code not in {
                "accepted_pending",
                "saved",
                "needs_identity",
                "needs_confirmation",
                "identity_mismatch",
                "state_conflict",
                "temporarily_unavailable",
                "rejected",
            }:
                raise ValueError("invalid_code")
            self.last_schema_version = 2
            return VoiceSemanticResponse(
                2,
                code,
                payload.get("careSessionId"),
                payload.get("careEventId"),
                payload.get("sessionVersion"),
                payload.get("proposalDigest"),
                payload.get("warningDigest"),
                tuple(payload.get("warningCodes", [])),
                payload.get("readback"),
            )
        except Exception:
            self.last_schema_version = None
            return VoiceSemanticResponse.temporarily_unavailable()


__all__ = ["V2VoiceCareGateway", "build_feeding_update_v2"]
