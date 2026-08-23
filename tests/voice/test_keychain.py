from __future__ import annotations

import inspect

import pytest

from services.voice.keychain import (
    KEYCHAIN_UNAVAILABLE,
    KeychainSecretStore,
    MacOSSecurityKeychain,
)


class FakeKeychain:
    def __init__(self) -> None:
        self.values: dict[tuple[str, str], bytes] = {}

    def read(self, service: str, account: str) -> bytes | None:
        return self.values.get((service, account))

    def write(self, service: str, account: str, secret: bytes) -> None:
        self.values[(service, account)] = bytes(secret)

    def delete(self, service: str, account: str) -> None:
        self.values.pop((service, account), None)


def test_secret_store_creates_once_without_putting_secret_in_an_argument() -> None:
    backend = FakeKeychain()
    generated = bytearray(b"k" * 32)
    store = KeychainSecretStore(backend, random_bytes=lambda size: bytes(generated[:size]))

    first = store.get_or_create("voice-profile-key.v1", size=32)
    generated[:] = b"x" * 32
    second = store.get_or_create("voice-profile-key.v1", size=32)

    assert first == second == b"k" * 32
    assert backend.values == {
        ("com.baby-monitor-local.voice-care", "voice-profile-key.v1"): b"k" * 32
    }
    source = inspect.getsource(MacOSSecurityKeychain)
    assert "subprocess" not in source
    assert "/usr/bin/security" not in source


def test_secret_store_deletes_only_the_requested_account() -> None:
    backend = FakeKeychain()
    store = KeychainSecretStore(backend, random_bytes=lambda size: b"a" * size)
    store.get_or_create("voice-profile-key.v1", size=32)
    store.get_or_create("device-signing-key.v1", size=32)

    store.delete("voice-profile-key.v1")

    assert store.read("voice-profile-key.v1", size=32) is None
    assert store.read("device-signing-key.v1", size=32) == b"a" * 32


def test_secret_store_fails_closed_for_invalid_labels_or_backend_details() -> None:
    class BrokenKeychain(FakeKeychain):
        def read(self, service: str, account: str) -> bytes | None:
            raise RuntimeError("private keychain detail")

    with pytest.raises(ValueError, match=f"^{KEYCHAIN_UNAVAILABLE}$"):
        KeychainSecretStore(BrokenKeychain()).read("voice-profile-key.v1", size=32)
    with pytest.raises(ValueError, match=f"^{KEYCHAIN_UNAVAILABLE}$"):
        KeychainSecretStore(FakeKeychain()).read("../escape", size=32)
