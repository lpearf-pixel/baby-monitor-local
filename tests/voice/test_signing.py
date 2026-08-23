from __future__ import annotations

import base64
import json

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

from services.voice.keychain import KeychainSecretStore
from services.voice.signing import (
    VOICE_SIGNING_INVALID,
    DeviceIdentity,
    canonical_json_bytes,
)


_SEED = bytes.fromhex(
    "9d61b19deffd5a60ba844af492ec2cc44449c5697b326919703bac031cae7f60"
)
_PUBLIC_KEY = bytes.fromhex(
    "d75a980182b10ab7d54bfed3c964073a0ee172f3daa62325af021a68f707511a"
)
_EXPECTED_SIGNATURE = (
    "Mwlnf3FH_210bcOCBztwEIeItNMscBJw7pb1ZWCYbZI6JmAnW-u4jCaBVFE1rUIx"
    "pRFxCypOZpilL7fmIEJ7Cw"
)


class FakeKeychain:
    def __init__(self) -> None:
        self.values: dict[tuple[str, str], bytes] = {}

    def read(self, service: str, account: str) -> bytes | None:
        return self.values.get((service, account))

    def write(self, service: str, account: str, secret: bytes) -> None:
        self.values.setdefault((service, account), bytes(secret))

    def delete(self, service: str, account: str) -> None:
        self.values.pop((service, account), None)


def unsigned_feeding_start() -> dict[str, object]:
    return {
        "schemaVersion": 1,
        "requestId": "33333333-3333-4333-8333-333333333333",
        "deviceId": "11111111-1111-4111-8111-111111111111",
        "leaseId": "22222222-2222-4222-8222-222222222222",
        "issuedAt": "2026-08-19T04:00:00+00:00",
        "occurredAt": "2026-08-19T04:00:00+00:00",
        "deliveryMode": "live",
        "speakerState": "verified",
        "source": "voice",
        "modelVersion": "voice-v1",
        "intentType": "feeding_start",
        "careSessionId": None,
        "payload": {
            "mode": "bottle",
            "startedAt": "2026-08-19T04:00:00+00:00",
        },
    }


def test_device_identity_matches_the_cross_repository_golden_vector() -> None:
    backend = FakeKeychain()
    identity = DeviceIdentity(
        KeychainSecretStore(backend, random_bytes=lambda size: _SEED[:size])
    )

    signed = identity.sign_intent(unsigned_feeding_start())
    payload = json.loads(signed)

    assert identity.public_key_bytes() == _PUBLIC_KEY
    assert payload["signature"] == _EXPECTED_SIGNATURE
    signing_value = dict(payload)
    signature = signing_value.pop("signature")
    Ed25519PublicKey.from_public_bytes(_PUBLIC_KEY).verify(
        base64.urlsafe_b64decode(signature + "=="),
        canonical_json_bytes(signing_value),
    )


def test_device_identity_reuses_the_keychain_seed_after_restart() -> None:
    backend = FakeKeychain()
    first = DeviceIdentity(
        KeychainSecretStore(backend, random_bytes=lambda size: _SEED[:size])
    )
    first_signature = json.loads(first.sign_intent(unsigned_feeding_start()))["signature"]
    second = DeviceIdentity(
        KeychainSecretStore(backend, random_bytes=lambda size: b"x" * size)
    )

    assert json.loads(second.sign_intent(unsigned_feeding_start()))["signature"] == first_signature
    assert list(backend.values) == [
        ("com.baby-monitor-local.voice-care", "device-signing-key.v1")
    ]


def test_device_identity_signs_the_closed_pairing_challenge() -> None:
    identity = DeviceIdentity(
        KeychainSecretStore(FakeKeychain(), random_bytes=lambda size: _SEED[:size])
    )

    payload = identity.sign_pairing_challenge(
        challenge_id="44444444-4444-4444-8444-444444444444",
        challenge="A" * 43,
        device_id="11111111-1111-4111-8111-111111111111",
    )

    assert payload == {
        "challengeId": "44444444-4444-4444-8444-444444444444",
        "challenge": "A" * 43,
        "deviceId": "11111111-1111-4111-8111-111111111111",
        "publicKey": "11qYAYKxCrfVS_7TyWQHOg7hcvPapiMlrwIaaPcHURo",
        "signature": (
            "gqYRAtOYPeoYEl3JL3nxQtkVMmrVTRK_GCF3kjJelzII6QgkRXWX9Lq-DEQEbOcR"
            "1lRp-cWlddaw-kMj9EMPDQ"
        ),
    }


def test_device_identity_rejects_invalid_pairing_fields() -> None:
    identity = DeviceIdentity(
        KeychainSecretStore(FakeKeychain(), random_bytes=lambda size: _SEED[:size])
    )
    with pytest.raises(ValueError, match=f"^{VOICE_SIGNING_INVALID}$"):
        identity.sign_pairing_challenge(
            challenge_id="not-a-uuid",
            challenge="A" * 43,
            device_id="11111111-1111-4111-8111-111111111111",
        )


@pytest.mark.parametrize(
    "mutation",
    [
        lambda value: value.update({"endpointToken": "must-not-sign"}),
        lambda value: value.update({"signature": "A" * 86}),
        lambda value: value.update({"schemaVersion": 2}),
        lambda value: value["payload"].update({"amountMl": 12.5}),
    ],
)
def test_device_identity_rejects_non_contract_or_pre_signed_input(mutation) -> None:
    value = unsigned_feeding_start()
    mutation(value)
    identity = DeviceIdentity(
        KeychainSecretStore(FakeKeychain(), random_bytes=lambda size: _SEED[:size])
    )

    with pytest.raises(ValueError, match=f"^{VOICE_SIGNING_INVALID}$"):
        identity.sign_intent(value)


def test_canonical_json_rejects_non_integer_numbers_and_non_string_keys() -> None:
    for value in ({"value": 1.5}, {1: "value"}, {"value": 2**53}):
        with pytest.raises(ValueError, match=f"^{VOICE_SIGNING_INVALID}$"):
            canonical_json_bytes(value)
