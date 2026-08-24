"""Stable signed-helper boundary for non-interactive Voice Care Keychain access."""

from __future__ import annotations

import os
import re
import struct
import subprocess
from collections.abc import Callable
from pathlib import Path

from services.voice.keychain import KeychainSecretStore, VOICE_KEYCHAIN_SERVICE


HELPER_KEYCHAIN_UNAVAILABLE = "voice_keychain_unavailable"
_HELPER_RELATIVE = Path(
    ".local/VoiceKeychainHelper.app/Contents/MacOS/voice-keychain-helper"
)
_REQUEST = struct.Struct(">4sBHH")
_RESPONSE = struct.Struct(">4sBH")
_REQUEST_MAGIC = b"VKH1"
_RESPONSE_MAGIC = b"VKR1"
_READ = 1
_WRITE = 2
_DELETE = 3
_SUCCESS = 0
_NOT_FOUND = 1
_FIXED_ACCOUNTS = frozenset(
    {
        "voice-asr-calibration-key.v2",
        "device-signing-key.v1",
        "voice-outbox-key.v1",
    }
)
_PROFILE_ACCOUNT = re.compile(
    r"^voice-profile-key\.v1\."
    r"[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-"
    r"[89ab][0-9a-f]{3}-[0-9a-f]{12}$"
)
_SECRET_BYTES = 32
_TIMEOUT_SECONDS = 5.0


Runner = Callable[..., object]


class HelperKeychainBackend:
    """Invoke only the fixed signed native helper over anonymous subprocess pipes."""

    def __init__(
        self,
        helper: Path,
        *,
        boundary: Path,
        runner: Runner = subprocess.run,
    ) -> None:
        try:
            boundary_path = Path(boundary)
            if boundary_path.is_symlink():
                raise ValueError
            checked_boundary = boundary_path.resolve(strict=True)
            helper_path = Path(helper)
            if helper_path != checked_boundary / _HELPER_RELATIVE:
                raise ValueError
            current = checked_boundary
            for part in _HELPER_RELATIVE.parts:
                current = current / part
                if current.is_symlink():
                    raise ValueError
            if not helper_path.is_file() or not os.access(helper_path, os.X_OK):
                raise ValueError
        except Exception:
            raise ValueError(HELPER_KEYCHAIN_UNAVAILABLE) from None
        self._helper = helper_path
        self._runner = runner

    def read(self, service: str, account: str) -> bytes | None:
        return self._invoke(_READ, service, account, b"")

    def write(self, service: str, account: str, secret: bytes) -> None:
        result = self._invoke(_WRITE, service, account, secret)
        if result is not None:
            raise ValueError(HELPER_KEYCHAIN_UNAVAILABLE)

    def delete(self, service: str, account: str) -> None:
        result = self._invoke(_DELETE, service, account, b"")
        if result is not None:
            raise ValueError(HELPER_KEYCHAIN_UNAVAILABLE)

    def _invoke(
        self, operation: int, service: str, account: str, secret: bytes
    ) -> bytes | None:
        try:
            if service != VOICE_KEYCHAIN_SERVICE or not _allowed_account(account):
                raise ValueError
            if type(secret) is not bytes or (
                operation == _WRITE and len(secret) != _SECRET_BYTES
            ) or (operation != _WRITE and secret):
                raise ValueError
            account_bytes = account.encode("ascii")
            request = (
                _REQUEST.pack(
                    _REQUEST_MAGIC,
                    operation,
                    len(account_bytes),
                    len(secret),
                )
                + account_bytes
                + secret
            )
            completed = self._runner(
                [str(self._helper)],
                input=request,
                capture_output=True,
                check=False,
                env={},
                timeout=_TIMEOUT_SECONDS,
            )
            if getattr(completed, "returncode", None) != 0:
                raise ValueError
            output = getattr(completed, "stdout", None)
            if type(output) is not bytes or len(output) < _RESPONSE.size:
                raise ValueError
            magic, status, size = _RESPONSE.unpack(output[: _RESPONSE.size])
            payload = output[_RESPONSE.size :]
            if magic != _RESPONSE_MAGIC or len(payload) != size:
                raise ValueError
            if status == _NOT_FOUND and operation == _READ and size == 0:
                return None
            if status != _SUCCESS:
                raise ValueError
            if operation == _READ:
                if size != _SECRET_BYTES:
                    raise ValueError
                return bytes(payload)
            if size != 0:
                raise ValueError
            return None
        except Exception:
            raise ValueError(HELPER_KEYCHAIN_UNAVAILABLE) from None


def _allowed_account(account: str) -> bool:
    return type(account) is str and (
        account in _FIXED_ACCOUNTS or _PROFILE_ACCOUNT.fullmatch(account) is not None
    )


def keychain_helper_path(project_root: Path) -> Path:
    return Path(project_root).resolve(strict=True) / _HELPER_RELATIVE


def keychain_for_runtime(project_root: Path) -> KeychainSecretStore:
    root = Path(project_root).resolve(strict=True)
    return KeychainSecretStore(
        HelperKeychainBackend(keychain_helper_path(root), boundary=root)
    )


__all__ = [
    "HELPER_KEYCHAIN_UNAVAILABLE",
    "HelperKeychainBackend",
    "keychain_for_runtime",
    "keychain_helper_path",
]
