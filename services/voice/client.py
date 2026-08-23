"""Bounded, fail-closed Baby Care Voice Care HTTP client."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Protocol
from uuid import UUID


VOICE_CARE_MEDIA_TYPE = "application/vnd.baby-care.voice-intent+json"
VOICE_CARE_INTENT_PATH = "/api/voice-care/intents"
_DIGEST = re.compile(r"^[a-f0-9]{64}$")
_CODES = {
    "accepted_pending",
    "saved",
    "needs_identity",
    "needs_confirmation",
    "identity_mismatch",
    "state_conflict",
    "temporarily_unavailable",
    "rejected",
}
_WARNINGS = {"possible_duplicate", "unusual_value", "sleep_overlap", "old_backfill"}


class VoiceCareTransport(Protocol):
    def post(
        self,
        path: str,
        headers: dict[str, str],
        body: bytes,
        timeout_seconds: float,
    ) -> tuple[int, bytes]: ...


@dataclass(frozen=True, slots=True)
class VoiceSemanticResponse:
    schema_version: int
    code: str
    care_session_id: str | None
    care_event_id: str | None
    session_version: int | None
    proposal_digest: str | None
    warning_digest: str | None
    warning_codes: tuple[str, ...]
    readback: dict[str, object] | None

    @classmethod
    def temporarily_unavailable(cls) -> "VoiceSemanticResponse":
        return cls(1, "temporarily_unavailable", None, None, None, None, None, (), None)


class VoiceCareClient:
    def __init__(
        self,
        transport: VoiceCareTransport,
        *,
        timeout_seconds: float = 5.0,
    ) -> None:
        if type(timeout_seconds) not in (int, float) or not 0.1 <= timeout_seconds <= 30:
            raise ValueError("voice_client_invalid")
        self._transport = transport
        self._timeout_seconds = float(timeout_seconds)

    def send(self, intent: bytes) -> VoiceSemanticResponse:
        if type(intent) is not bytes or not 0 < len(intent) <= 16_384:
            return VoiceSemanticResponse.temporarily_unavailable()
        try:
            status, body = self._transport.post(
                VOICE_CARE_INTENT_PATH,
                {"content-type": VOICE_CARE_MEDIA_TYPE},
                intent,
                self._timeout_seconds,
            )
            if status != 200 or type(body) is not bytes or len(body) > 16_384:
                raise ValueError
            return _parse_response(body)
        except Exception:
            return VoiceSemanticResponse.temporarily_unavailable()


def _uuid_or_none(value: object) -> str | None:
    if value is None:
        return None
    if type(value) is not str or str(UUID(value)) != value:
        raise ValueError
    return value


def _digest_or_none(value: object) -> str | None:
    if value is None:
        return None
    if type(value) is not str or _DIGEST.fullmatch(value) is None:
        raise ValueError
    return value


def _parse_readback(value: object) -> dict[str, object] | None:
    if value is None:
        return None
    if type(value) is not dict:
        raise ValueError
    template_id = value.get("templateId")
    if template_id == "feeding_bottle_readback":
        if set(value) != {"templateId", "liquidType", "amountMl", "bottleCapacityMl"}:
            raise ValueError
        if value["liquidType"] not in {"expressed_breast_milk", "formula"}:
            raise ValueError
        for field in ("amountMl", "bottleCapacityMl"):
            if value[field] is not None and (
                type(value[field]) is not int or not 0 < value[field] <= 9_007_199_254_740_991
            ):
                raise ValueError
    elif template_id == "feeding_direct_readback":
        if set(value) != {"templateId", "durationMinutes"}:
            raise ValueError
        duration = value["durationMinutes"]
        if type(duration) is not int or not 0 < duration <= 9_007_199_254_740_991:
            raise ValueError
    else:
        raise ValueError
    return dict(value)


def _parse_response(raw: bytes) -> VoiceSemanticResponse:
    payload = json.loads(raw.decode("utf-8"), object_pairs_hook=_reject_duplicate_keys)
    expected = {
        "schemaVersion",
        "code",
        "careSessionId",
        "careEventId",
        "sessionVersion",
        "proposalDigest",
        "warningDigest",
        "warningCodes",
        "readback",
    }
    if type(payload) is not dict or set(payload) != expected:
        raise ValueError
    code = payload["code"]
    if payload["schemaVersion"] != 1 or type(code) is not str or code not in _CODES:
        raise ValueError
    care_session_id = _uuid_or_none(payload["careSessionId"])
    care_event_id = _uuid_or_none(payload["careEventId"])
    session_version = payload["sessionVersion"]
    if session_version is not None and (
        type(session_version) is not int or not 0 < session_version <= 9_007_199_254_740_991
    ):
        raise ValueError
    proposal_digest = _digest_or_none(payload["proposalDigest"])
    warning_digest = _digest_or_none(payload["warningDigest"])
    warnings = payload["warningCodes"]
    if (
        type(warnings) is not list
        or len(warnings) > 4
        or len(set(warnings)) != len(warnings)
        or any(type(item) is not str or item not in _WARNINGS for item in warnings)
        or (bool(warnings) != (warning_digest is not None))
    ):
        raise ValueError
    readback = _parse_readback(payload["readback"])
    if code == "saved":
        if None in (care_session_id, care_event_id, session_version, proposal_digest):
            raise ValueError
    elif code == "accepted_pending":
        if care_session_id is None or session_version is None or care_event_id is not None:
            raise ValueError
    return VoiceSemanticResponse(
        schema_version=1,
        code=code,
        care_session_id=care_session_id,
        care_event_id=care_event_id,
        session_version=session_version,
        proposal_digest=proposal_digest,
        warning_digest=warning_digest,
        warning_codes=tuple(warnings),
        readback=readback,
    )


def _reject_duplicate_keys(pairs: list[tuple[str, object]]) -> dict[str, object]:
    value: dict[str, object] = {}
    for key, item in pairs:
        if key in value:
            raise ValueError
        value[key] = item
    return value


__all__ = [
    "VOICE_CARE_INTENT_PATH",
    "VOICE_CARE_MEDIA_TYPE",
    "VoiceCareClient",
    "VoiceCareTransport",
    "VoiceSemanticResponse",
]
