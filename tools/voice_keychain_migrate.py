from __future__ import annotations

import hmac
from collections.abc import Callable
from pathlib import Path

from services.voice.asr_corpus import (
    ASR_CORPUS_KEY_ACCOUNT,
    LEGACY_ASR_CORPUS_KEY_ACCOUNT,
)
from services.voice.helper_keychain import HelperKeychainBackend, keychain_helper_path
from services.voice.keychain import (
    KeychainBackend,
    KeychainSecretStore,
    MacOSSecurityKeychain,
    VOICE_KEYCHAIN_SERVICE,
)


Printer = Callable[[str], None]
_KEY_BYTES = 32


def run_migration(
    *,
    legacy_store: KeychainSecretStore,
    helper_backend: KeychainBackend,
    printer: Printer = print,
) -> int:
    mutable_key: bytearray | None = None
    try:
        legacy_key = legacy_store.read(LEGACY_ASR_CORPUS_KEY_ACCOUNT, size=_KEY_BYTES)
        if legacy_key is None:
            raise ValueError
        mutable_key = bytearray(legacy_key)
        existing = helper_backend.read(VOICE_KEYCHAIN_SERVICE, ASR_CORPUS_KEY_ACCOUNT)
        if existing is None:
            helper_backend.write(
                VOICE_KEYCHAIN_SERVICE,
                ASR_CORPUS_KEY_ACCOUNT,
                bytes(mutable_key),
            )
            existing = helper_backend.read(
                VOICE_KEYCHAIN_SERVICE, ASR_CORPUS_KEY_ACCOUNT
            )
        if (
            type(existing) is not bytes
            or len(existing) != _KEY_BYTES
            or not hmac.compare_digest(existing, mutable_key)
        ):
            raise ValueError
        printer("migration=PASS")
        printer("key_state=available")
        printer("key_bytes=32")
        return 0
    except Exception:
        printer("migration=FAIL")
        return 1
    finally:
        if mutable_key is not None:
            mutable_key[:] = b"\x00" * len(mutable_key)


def main(*, project_root: Path | None = None, printer: Printer = print) -> int:
    try:
        root = (project_root or Path.cwd()).resolve(strict=True)
        legacy_store = KeychainSecretStore(MacOSSecurityKeychain())
        helper_backend = HelperKeychainBackend(
            keychain_helper_path(root),
            boundary=root,
        )
    except Exception:
        printer("migration=FAIL")
        return 1
    return run_migration(
        legacy_store=legacy_store,
        helper_backend=helper_backend,
        printer=printer,
    )


if __name__ == "__main__":
    raise SystemExit(main())
