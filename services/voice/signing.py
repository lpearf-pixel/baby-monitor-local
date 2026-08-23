"""Closed Ed25519 signing boundary for Baby Care Voice Care intents."""

from __future__ import annotations

import base64
import json
import re
from collections.abc import Mapping
from uuid import UUID

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from packages.contracts.voice_care import parse_voice_care_intent
from services.voice.keychain import KeychainSecretStore


VOICE_SIGNING_INVALID = "voice_signing_invalid"
DEVICE_SIGNING_KEY_ACCOUNT = "device-signing-key.v1"
_MAX_SAFE_INTEGER = 9_007_199_254_740_991
_PLACEHOLDER_SIGNATURE = "A" * 86
_BASE64URL_32 = re.compile(r"^[A-Za-z0-9_-]{42}[AEIMQUYcgkosw048]$")


def _base64url(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")


def _validate_json_value(value: object) -> None:
    if value is None or type(value) in (str, bool):
        return
    if type(value) is int:
        if abs(value) > _MAX_SAFE_INTEGER:
            raise ValueError(VOICE_SIGNING_INVALID)
        return
    if type(value) is list:
        for item in value:
            _validate_json_value(item)
        return
    if type(value) is dict:
        for key, item in value.items():
            if type(key) is not str:
                raise ValueError(VOICE_SIGNING_INVALID)
            _validate_json_value(item)
        return
    raise ValueError(VOICE_SIGNING_INVALID)


def canonical_json_bytes(value: object) -> bytes:
    """Return the shared JSON canonical form used by Baby Care signatures."""

    try:
        _validate_json_value(value)
        return json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError, UnicodeError):
        raise ValueError(VOICE_SIGNING_INVALID) from None


class DeviceIdentity:
    """Persist only a raw Ed25519 seed in the macOS Keychain boundary."""

    def __init__(self, keychain: KeychainSecretStore) -> None:
        self._keychain = keychain

    def _private_key(self) -> Ed25519PrivateKey:
        try:
            seed = self._keychain.get_or_create(DEVICE_SIGNING_KEY_ACCOUNT, size=32)
            return Ed25519PrivateKey.from_private_bytes(seed)
        except Exception:
            raise ValueError(VOICE_SIGNING_INVALID) from None

    def public_key_bytes(self) -> bytes:
        try:
            return self._private_key().public_key().public_bytes(
                encoding=serialization.Encoding.Raw,
                format=serialization.PublicFormat.Raw,
            )
        except Exception:
            raise ValueError(VOICE_SIGNING_INVALID) from None

    def public_key_base64url(self) -> str:
        return _base64url(self.public_key_bytes())

    def sign_intent(self, unsigned_intent: Mapping[str, object]) -> bytes:
        """Validate the closed envelope, sign it, and return canonical JSON bytes."""

        try:
            if type(unsigned_intent) is not dict or "signature" in unsigned_intent:
                raise ValueError(VOICE_SIGNING_INVALID)
            signing_value = dict(unsigned_intent)
            candidate = dict(signing_value)
            candidate["signature"] = _PLACEHOLDER_SIGNATURE
            parse_voice_care_intent(canonical_json_bytes(candidate))
            signature = _base64url(
                self._private_key().sign(canonical_json_bytes(signing_value))
            )
            signed_value = dict(signing_value)
            signed_value["signature"] = signature
            signed = canonical_json_bytes(signed_value)
            parse_voice_care_intent(signed)
            return signed
        except Exception:
            raise ValueError(VOICE_SIGNING_INVALID) from None

    def sign_pairing_challenge(
        self,
        *,
        challenge_id: str,
        challenge: str,
        device_id: str,
    ) -> dict[str, str]:
        """Bind the server challenge, device ID and this device's public key."""

        try:
            if (
                type(challenge_id) is not str
                or str(UUID(challenge_id)) != challenge_id
                or type(device_id) is not str
                or str(UUID(device_id)) != device_id
                or type(challenge) is not str
                or _BASE64URL_32.fullmatch(challenge) is None
                or _base64url(base64.urlsafe_b64decode(challenge + "=")) != challenge
            ):
                raise ValueError
            public_key = self.public_key_base64url()
            signing_value = {
                "challengeId": challenge_id,
                "challenge": challenge,
                "deviceId": device_id,
                "publicKey": public_key,
                "purpose": "baby-care-voice-pair-v1",
            }
            signature = _base64url(
                self._private_key().sign(canonical_json_bytes(signing_value))
            )
            return {
                "challengeId": challenge_id,
                "challenge": challenge,
                "deviceId": device_id,
                "publicKey": public_key,
                "signature": signature,
            }
        except Exception:
            raise ValueError(VOICE_SIGNING_INVALID) from None


__all__ = [
    "DEVICE_SIGNING_KEY_ACCOUNT",
    "VOICE_SIGNING_INVALID",
    "DeviceIdentity",
    "canonical_json_bytes",
]
