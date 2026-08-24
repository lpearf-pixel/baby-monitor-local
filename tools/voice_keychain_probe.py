from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Protocol

from services.voice.asr_corpus import ASR_CORPUS_KEY_ACCOUNT
from services.voice.helper_keychain import keychain_for_runtime


class _Store(Protocol):
    def read(self, account: str, *, size: int) -> bytes | None: ...


KeychainFactory = Callable[[Path], _Store]
Printer = Callable[[str], None]


def main(
    *,
    project_root: Path | None = None,
    keychain_factory: KeychainFactory = keychain_for_runtime,
    printer: Printer = print,
) -> int:
    try:
        root = (project_root or Path.cwd()).resolve(strict=True)
        value = keychain_factory(root).read(ASR_CORPUS_KEY_ACCOUNT, size=32)
        if type(value) is not bytes or len(value) != 32:
            raise ValueError
        printer("key_state=available")
        printer("key_bytes=32")
        return 0
    except Exception:
        printer("key_state=unavailable")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
