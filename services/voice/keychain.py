"""Narrow macOS Keychain boundary for Voice Care secrets."""

from __future__ import annotations

import ctypes
import re
import secrets
from collections.abc import Callable
from typing import Protocol


KEYCHAIN_UNAVAILABLE = "voice_keychain_unavailable"
VOICE_KEYCHAIN_SERVICE = "com.baby-monitor-local.voice-care"
_LABEL = re.compile(r"^[A-Za-z0-9._-]{1,64}$")
_ERR_SEC_SUCCESS = 0
_ERR_SEC_DUPLICATE_ITEM = -25299
_ERR_SEC_ITEM_NOT_FOUND = -25300
_CF_STRING_ENCODING_UTF8 = 0x08000100


class KeychainBackend(Protocol):
    def read(self, service: str, account: str) -> bytes | None: ...

    def write(self, service: str, account: str, secret: bytes) -> None:
        """Create the item if absent without replacing an existing secret."""
        ...

    def delete(self, service: str, account: str) -> None: ...


class KeychainSecretStore:
    """Validate fixed labels and map all backend details to one closed failure."""

    def __init__(
        self,
        backend: KeychainBackend,
        *,
        random_bytes: Callable[[int], bytes] = secrets.token_bytes,
    ) -> None:
        self._backend = backend
        self._random_bytes = random_bytes

    def read(self, account: str, *, size: int) -> bytes | None:
        try:
            _validate_account(account)
            _validate_size(size)
            value = self._backend.read(VOICE_KEYCHAIN_SERVICE, account)
            if value is None:
                return None
            if type(value) is not bytes or len(value) != size:
                raise ValueError(KEYCHAIN_UNAVAILABLE)
            return value
        except Exception:
            raise ValueError(KEYCHAIN_UNAVAILABLE) from None

    def get_or_create(self, account: str, *, size: int) -> bytes:
        existing = self.read(account, size=size)
        if existing is not None:
            return existing
        try:
            generated = self._random_bytes(size)
            if type(generated) is not bytes or len(generated) != size:
                raise ValueError(KEYCHAIN_UNAVAILABLE)
            self._backend.write(VOICE_KEYCHAIN_SERVICE, account, generated)
            stored = self._backend.read(VOICE_KEYCHAIN_SERVICE, account)
            if type(stored) is not bytes or len(stored) != size:
                raise ValueError(KEYCHAIN_UNAVAILABLE)
            return stored
        except Exception:
            raise ValueError(KEYCHAIN_UNAVAILABLE) from None

    def delete(self, account: str) -> None:
        try:
            _validate_account(account)
            self._backend.delete(VOICE_KEYCHAIN_SERVICE, account)
        except Exception:
            raise ValueError(KEYCHAIN_UNAVAILABLE) from None


class MacOSSecurityKeychain:
    """Generic-password storage using Security.framework, never a CLI argument."""

    def __init__(self, framework: _SecurityFramework | None = None) -> None:
        try:
            self._framework = framework or _SecurityFramework()
        except Exception:
            raise ValueError(KEYCHAIN_UNAVAILABLE) from None

    def read(self, service: str, account: str) -> bytes | None:
        try:
            return self._framework.read(service, account)
        except Exception:
            raise ValueError(KEYCHAIN_UNAVAILABLE) from None

    def write(self, service: str, account: str, secret: bytes) -> None:
        try:
            self._framework.write(service, account, secret)
        except Exception:
            raise ValueError(KEYCHAIN_UNAVAILABLE) from None

    def delete(self, service: str, account: str) -> None:
        try:
            self._framework.delete(service, account)
        except Exception:
            raise ValueError(KEYCHAIN_UNAVAILABLE) from None


class _CFDictionaryKeyCallBacks(ctypes.Structure):
    _fields_ = [
        ("version", ctypes.c_long),
        ("retain", ctypes.c_void_p),
        ("release", ctypes.c_void_p),
        ("copy_description", ctypes.c_void_p),
        ("equal", ctypes.c_void_p),
        ("hash", ctypes.c_void_p),
    ]


class _CFDictionaryValueCallBacks(ctypes.Structure):
    _fields_ = [
        ("version", ctypes.c_long),
        ("retain", ctypes.c_void_p),
        ("release", ctypes.c_void_p),
        ("copy_description", ctypes.c_void_p),
        ("equal", ctypes.c_void_p),
    ]


class _SecurityFramework:
    """Small ctypes wrapper around SecItem generic-password calls."""

    def __init__(self) -> None:
        self._security = ctypes.CDLL(
            "/System/Library/Frameworks/Security.framework/Security"
        )
        self._core = ctypes.CDLL(
            "/System/Library/Frameworks/CoreFoundation.framework/CoreFoundation"
        )
        self._configure()
        self._key_callbacks = _CFDictionaryKeyCallBacks.in_dll(
            self._core, "kCFTypeDictionaryKeyCallBacks"
        )
        self._value_callbacks = _CFDictionaryValueCallBacks.in_dll(
            self._core, "kCFTypeDictionaryValueCallBacks"
        )
        self._constants = {
            name: ctypes.c_void_p.in_dll(self._security, name).value
            for name in (
                "kSecClass",
                "kSecClassGenericPassword",
                "kSecAttrService",
                "kSecAttrAccount",
                "kSecValueData",
                "kSecReturnData",
                "kSecMatchLimit",
                "kSecMatchLimitOne",
                "kSecAttrAccessible",
                "kSecAttrAccessibleAfterFirstUnlockThisDeviceOnly",
            )
        }
        self._true = ctypes.c_void_p.in_dll(self._core, "kCFBooleanTrue").value

    def read(self, service: str, account: str) -> bytes | None:
        query, owned = self._dictionary(
            (
                ("kSecClass", self._constants["kSecClassGenericPassword"]),
                ("kSecAttrService", self._string(service, owned := [])),
                ("kSecAttrAccount", self._string(account, owned)),
                ("kSecReturnData", self._true),
                ("kSecMatchLimit", self._constants["kSecMatchLimitOne"]),
            ),
            owned,
        )
        result = ctypes.c_void_p()
        try:
            status = self._security.SecItemCopyMatching(query, ctypes.byref(result))
            if status == _ERR_SEC_ITEM_NOT_FOUND:
                return None
            _require_success(status)
            length = self._core.CFDataGetLength(result)
            pointer = self._core.CFDataGetBytePtr(result)
            if length < 0 or (length and not pointer):
                raise ValueError(KEYCHAIN_UNAVAILABLE)
            return bytes(pointer[:length])
        finally:
            if result.value:
                self._core.CFRelease(result)
            self._release(query, owned)

    def write(self, service: str, account: str, secret: bytes) -> None:
        owned: list[int] = []
        add, owned = self._dictionary(
            (
                ("kSecClass", self._constants["kSecClassGenericPassword"]),
                ("kSecAttrService", self._string(service, owned)),
                ("kSecAttrAccount", self._string(account, owned)),
                ("kSecValueData", self._data(secret, owned)),
                (
                    "kSecAttrAccessible",
                    self._constants[
                        "kSecAttrAccessibleAfterFirstUnlockThisDeviceOnly"
                    ],
                ),
            ),
            owned,
        )
        try:
            status = self._security.SecItemAdd(add, None)
            if status != _ERR_SEC_DUPLICATE_ITEM:
                _require_success(status)
        finally:
            self._release(add, owned)

    def delete(self, service: str, account: str) -> None:
        owned: list[int] = []
        query, owned = self._dictionary(
            (
                ("kSecClass", self._constants["kSecClassGenericPassword"]),
                ("kSecAttrService", self._string(service, owned)),
                ("kSecAttrAccount", self._string(account, owned)),
            ),
            owned,
        )
        try:
            status = self._security.SecItemDelete(query)
            if status != _ERR_SEC_ITEM_NOT_FOUND:
                _require_success(status)
        finally:
            self._release(query, owned)

    def _configure(self) -> None:
        self._core.CFStringCreateWithCString.argtypes = [
            ctypes.c_void_p,
            ctypes.c_char_p,
            ctypes.c_uint32,
        ]
        self._core.CFStringCreateWithCString.restype = ctypes.c_void_p
        self._core.CFDataCreate.argtypes = [
            ctypes.c_void_p,
            ctypes.POINTER(ctypes.c_ubyte),
            ctypes.c_long,
        ]
        self._core.CFDataCreate.restype = ctypes.c_void_p
        self._core.CFDictionaryCreate.argtypes = [
            ctypes.c_void_p,
            ctypes.POINTER(ctypes.c_void_p),
            ctypes.POINTER(ctypes.c_void_p),
            ctypes.c_long,
            ctypes.POINTER(_CFDictionaryKeyCallBacks),
            ctypes.POINTER(_CFDictionaryValueCallBacks),
        ]
        self._core.CFDictionaryCreate.restype = ctypes.c_void_p
        self._core.CFDataGetLength.argtypes = [ctypes.c_void_p]
        self._core.CFDataGetLength.restype = ctypes.c_long
        self._core.CFDataGetBytePtr.argtypes = [ctypes.c_void_p]
        self._core.CFDataGetBytePtr.restype = ctypes.POINTER(ctypes.c_ubyte)
        self._core.CFRelease.argtypes = [ctypes.c_void_p]
        self._security.SecItemCopyMatching.argtypes = [
            ctypes.c_void_p,
            ctypes.POINTER(ctypes.c_void_p),
        ]
        self._security.SecItemCopyMatching.restype = ctypes.c_int32
        self._security.SecItemAdd.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
        self._security.SecItemAdd.restype = ctypes.c_int32
        self._security.SecItemDelete.argtypes = [ctypes.c_void_p]
        self._security.SecItemDelete.restype = ctypes.c_int32

    def _string(self, value: str, owned: list[int]) -> int:
        created = self._core.CFStringCreateWithCString(
            None, value.encode("utf-8"), _CF_STRING_ENCODING_UTF8
        )
        if not created:
            raise ValueError(KEYCHAIN_UNAVAILABLE)
        owned.append(created)
        return created

    def _data(self, value: bytes, owned: list[int]) -> int:
        buffer = (ctypes.c_ubyte * len(value)).from_buffer_copy(value)
        created = self._core.CFDataCreate(None, buffer, len(value))
        if not created:
            raise ValueError(KEYCHAIN_UNAVAILABLE)
        owned.append(created)
        return created

    def _dictionary(
        self, pairs: tuple[tuple[str, int | None], ...], owned: list[int]
    ) -> tuple[int, list[int]]:
        keys = (ctypes.c_void_p * len(pairs))(
            *(self._constants[name] for name, _ in pairs)
        )
        values = (ctypes.c_void_p * len(pairs))(*(value for _, value in pairs))
        created = self._core.CFDictionaryCreate(
            None,
            keys,
            values,
            len(pairs),
            ctypes.byref(self._key_callbacks),
            ctypes.byref(self._value_callbacks),
        )
        if not created:
            raise ValueError(KEYCHAIN_UNAVAILABLE)
        return created, owned

    def _release(self, dictionary: int, owned: list[int]) -> None:
        self._core.CFRelease(dictionary)
        for item in owned:
            self._core.CFRelease(item)


def _validate_account(account: str) -> None:
    if type(account) is not str or _LABEL.fullmatch(account) is None:
        raise ValueError(KEYCHAIN_UNAVAILABLE)


def _validate_size(size: int) -> None:
    if type(size) is not int or not 16 <= size <= 4_096:
        raise ValueError(KEYCHAIN_UNAVAILABLE)


def _require_success(status: int) -> None:
    if status != _ERR_SEC_SUCCESS:
        raise ValueError(KEYCHAIN_UNAVAILABLE)


__all__ = [
    "KEYCHAIN_UNAVAILABLE",
    "KeychainBackend",
    "KeychainSecretStore",
    "MacOSSecurityKeychain",
    "VOICE_KEYCHAIN_SERVICE",
]
