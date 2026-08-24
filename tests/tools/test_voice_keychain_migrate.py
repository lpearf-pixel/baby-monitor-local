from __future__ import annotations

from services.voice.keychain import KeychainSecretStore, VOICE_KEYCHAIN_SERVICE
from tools import voice_keychain_migrate


class Backend:
    def __init__(self, values: dict[tuple[str, str], bytes] | None = None) -> None:
        self.values = dict(values or {})
        self.writes: list[tuple[str, str, bytes]] = []

    def read(self, service: str, account: str) -> bytes | None:
        return self.values.get((service, account))

    def write(self, service: str, account: str, secret: bytes) -> None:
        self.writes.append((service, account, bytes(secret)))
        self.values.setdefault((service, account), bytes(secret))

    def delete(self, service: str, account: str) -> None:
        raise AssertionError("migration must not delete")


def test_migration_copies_existing_v1_key_to_helper_owned_v2_without_deletion() -> None:
    legacy_backend = Backend(
        {(VOICE_KEYCHAIN_SERVICE, "voice-asr-calibration-key.v1"): b"k" * 32}
    )
    helper_backend = Backend()
    output: list[str] = []

    result = voice_keychain_migrate.run_migration(
        legacy_store=KeychainSecretStore(legacy_backend),
        helper_backend=helper_backend,
        printer=output.append,
    )

    assert result == 0
    assert output == ["migration=PASS", "key_state=available", "key_bytes=32"]
    assert helper_backend.writes == [
        (VOICE_KEYCHAIN_SERVICE, "voice-asr-calibration-key.v2", b"k" * 32)
    ]
    assert legacy_backend.values == {
        (VOICE_KEYCHAIN_SERVICE, "voice-asr-calibration-key.v1"): b"k" * 32
    }
    assert "kkkk" not in "\n".join(output)


def test_migration_is_idempotent_only_for_the_identical_v2_key() -> None:
    legacy = Backend(
        {(VOICE_KEYCHAIN_SERVICE, "voice-asr-calibration-key.v1"): b"k" * 32}
    )
    helper = Backend(
        {(VOICE_KEYCHAIN_SERVICE, "voice-asr-calibration-key.v2"): b"k" * 32}
    )

    result = voice_keychain_migrate.run_migration(
        legacy_store=KeychainSecretStore(legacy),
        helper_backend=helper,
        printer=lambda _line: None,
    )

    assert result == 0
    assert helper.writes == []


def test_migration_fails_closed_for_missing_legacy_or_different_v2_key() -> None:
    outputs: list[list[str]] = []
    for legacy, helper in (
        (Backend(), Backend()),
        (
            Backend(
                {
                    (
                        VOICE_KEYCHAIN_SERVICE,
                        "voice-asr-calibration-key.v1",
                    ): b"k" * 32
                }
            ),
            Backend(
                {
                    (
                        VOICE_KEYCHAIN_SERVICE,
                        "voice-asr-calibration-key.v2",
                    ): b"x" * 32
                }
            ),
        ),
    ):
        output: list[str] = []
        result = voice_keychain_migrate.run_migration(
            legacy_store=KeychainSecretStore(legacy),
            helper_backend=helper,
            printer=output.append,
        )
        assert result == 1
        assert helper.writes == []
        outputs.append(output)

    assert outputs == [["migration=FAIL"], ["migration=FAIL"]]
