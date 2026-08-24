from __future__ import annotations

from pathlib import Path

from tools import voice_keychain_probe


class Store:
    def __init__(self, value: bytes | None = b"k" * 32) -> None:
        self.value = value
        self.calls: list[tuple[str, int]] = []

    def read(self, account: str, *, size: int) -> bytes | None:
        self.calls.append((account, size))
        return self.value


def test_probe_reports_only_aggregate_available_state(tmp_path: Path) -> None:
    output: list[str] = []
    store = Store()

    result = voice_keychain_probe.main(
        project_root=tmp_path,
        keychain_factory=lambda root: store if root == tmp_path else None,
        printer=output.append,
    )

    assert result == 0
    assert output == ["key_state=available", "key_bytes=32"]
    assert store.calls == [("voice-asr-calibration-key.v2", 32)]
    assert "kkkk" not in "\n".join(output)


def test_probe_fails_closed_without_creating_a_key(tmp_path: Path) -> None:
    output: list[str] = []
    store = Store(None)

    result = voice_keychain_probe.main(
        project_root=tmp_path,
        keychain_factory=lambda _root: store,
        printer=output.append,
    )

    assert result == 1
    assert output == ["key_state=unavailable"]
    assert store.calls == [("voice-asr-calibration-key.v2", 32)]
