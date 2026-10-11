"""Versioned Baby Care v2 intent construction and transport boundary."""

from __future__ import annotations

import json
from datetime import datetime
from collections.abc import Callable
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
                "cancelled",
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


class M7BabyCareGateway:
    """M6SessionGateway adapter backed by the signed Baby Care v2 device route."""

    def __init__(
        self,
        *,
        identity: IntentSigner,
        transport: V2Transport,
        device_id: str,
        lease_id: str,
        request_id_factory: Callable[[], str],
        clock: Callable[[], datetime],
    ) -> None:
        self._identity = identity
        self._sender = V2VoiceCareGateway(transport)
        self._device_id = device_id
        self._lease_id = lease_id
        self._request_id_factory = request_id_factory
        self._clock = clock
        self._session_id: str | None = None
        self._version: int | None = None
        self._started_at: datetime | None = None
        self._proposal_digest: str | None = None

    def start(self, *, occurred_at: datetime) -> str:
        value = _envelope(
            request_id=self._request_id_factory(), device_id=self._device_id,
            lease_id=self._lease_id, occurred_at=occurred_at, intent_type="feeding_start",
            session_id=None, payload={"mode": "unknown", "startedAt": occurred_at.isoformat()},
        )
        result = self._sender.send(self._identity.sign_intent(value))
        if result.code != "accepted_pending" or result.care_session_id is None or result.session_version is None:
            raise RuntimeError("voice_care_start_failed")
        self._session_id, self._version, self._started_at = result.care_session_id, result.session_version, occurred_at
        return result.care_session_id

    def update(self, *, session_id: str, components: tuple[dict[str, object], ...]) -> None:
        self._require_session(session_id)
        value = _envelope(
            request_id=self._request_id_factory(), device_id=self._device_id,
            lease_id=self._lease_id, occurred_at=self._clock(), intent_type="feeding_update",
            session_id=session_id, payload={"expectedVersion": self._require_version(), "components": list(components)},
        )
        result = self._sender.send(self._identity.sign_intent(value))
        if result.code != "accepted_pending" or result.session_version is None:
            raise RuntimeError("voice_care_update_failed")
        self._version = result.session_version

    def end(self, *, session_id: str, components: tuple[dict[str, object], ...]) -> str:
        self._require_session(session_id)
        now = self._clock()
        value = _envelope(
            request_id=self._request_id_factory(), device_id=self._device_id,
            lease_id=self._lease_id, occurred_at=now, intent_type="feeding_end",
            session_id=session_id, payload={
                "expectedVersion": self._require_version(),
                "finalProposal": {"schemaVersion": 2, "startedAt": (self._started_at or now).isoformat(), "endedAt": now.isoformat(), "components": list(components)},
            },
        )
        result = self._sender.send(self._identity.sign_intent(value))
        if result.code != "needs_confirmation" or result.proposal_digest is None or result.session_version is None:
            raise RuntimeError("voice_care_end_failed")
        self._version, self._proposal_digest = result.session_version, result.proposal_digest
        return result.proposal_digest

    def confirm(self, *, session_id: str, proposal_id: str) -> str:
        self._require_session(session_id)
        if proposal_id != self._proposal_digest:
            raise RuntimeError("voice_care_proposal_mismatch")
        value = _envelope(
            request_id=self._request_id_factory(), device_id=self._device_id,
            lease_id=self._lease_id, occurred_at=self._clock(), intent_type="care_confirm",
            session_id=session_id, payload={"proposalDigest": proposal_id, "expectedVersion": self._require_version(), "warningDigest": None, "confirmedWarningCodes": []},
        )
        result = self._sender.send(self._identity.sign_intent(value))
        if result.code != "saved":
            return result.code
        self._version = result.session_version
        return "saved"

    def cancel(self, *, session_id: str) -> str:
        self._require_session(session_id)
        value = _envelope(
            request_id=self._request_id_factory(), device_id=self._device_id,
            lease_id=self._lease_id, occurred_at=self._clock(), intent_type="care_cancel",
            session_id=session_id, payload={"expectedVersion": self._require_version(), "reason": "caregiver_cancelled"},
        )
        result = self._sender.send(self._identity.sign_intent(value))
        if result.code == "cancelled":
            self._session_id = None
        return result.code

    def query(self) -> tuple[dict[str, object], ...]:
        raise RuntimeError("voice_care_query_requires_authoritative_read_route")

    def _require_session(self, session_id: str) -> None:
        if session_id != self._session_id:
            raise RuntimeError("voice_care_session_mismatch")

    def _require_version(self) -> int:
        if self._version is None:
            raise RuntimeError("voice_care_version_unavailable")
        return self._version


def _envelope(*, request_id: str, device_id: str, lease_id: str, occurred_at: datetime,
              intent_type: str, session_id: str | None, payload: dict[str, object]) -> dict[str, object]:
    return {
        "schemaVersion": 2,
        "requestId": request_id,
        "deviceId": device_id,
        "leaseId": lease_id,
        "issuedAt": occurred_at.isoformat(),
        "occurredAt": occurred_at.isoformat(),
        "deliveryMode": "live",
        "speakerState": "verified",
        "source": "voice",
        "modelVersion": "m7-llm",
        "intentType": intent_type,
        "careSessionId": session_id,
        "payload": payload,
    }


__all__ = ["M7BabyCareGateway", "V2VoiceCareGateway", "build_feeding_update_v2"]
