from __future__ import annotations

import stat
import struct
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

from services.voice.helper_keychain import (
    HELPER_KEYCHAIN_UNAVAILABLE,
    HelperKeychainBackend,
)
from services.voice.keychain import VOICE_KEYCHAIN_SERVICE


REQUEST = struct.Struct(">4sBHH")
RESPONSE = struct.Struct(">4sBH")


def _helper(tmp_path: Path) -> Path:
    path = (
        tmp_path
        / ".local/VoiceKeychainHelper.app/Contents/MacOS/voice-keychain-helper"
    )
    path.parent.mkdir(parents=True)
    path.write_bytes(b"helper")
    path.chmod(0o755)
    return path


class Runner:
    def __init__(self, response: bytes) -> None:
        self.response = response
        self.calls: list[tuple[list[str], dict[str, object]]] = []

    def __call__(self, argv: list[str], **kwargs: object) -> object:
        self.calls.append((argv, kwargs))
        return SimpleNamespace(returncode=0, stdout=self.response, stderr=b"")


def _response(status_code: int, secret: bytes = b"") -> bytes:
    return RESPONSE.pack(b"VKR1", status_code, len(secret)) + secret


def test_backend_transports_secret_only_in_bounded_stdin_pipe(tmp_path: Path) -> None:
    helper = _helper(tmp_path)
    runner = Runner(_response(0))
    backend = HelperKeychainBackend(helper, boundary=tmp_path, runner=runner)

    backend.write(
        VOICE_KEYCHAIN_SERVICE,
        "voice-asr-calibration-key.v2",
        b"k" * 32,
    )

    assert len(runner.calls) == 1
    argv, options = runner.calls[0]
    assert argv == [str(helper)]
    assert options["capture_output"] is True
    assert options["check"] is False
    assert options["env"] == {}
    assert options["timeout"] == 5.0
    request = options["input"]
    assert isinstance(request, bytes)
    magic, operation, account_size, secret_size = REQUEST.unpack(
        request[: REQUEST.size]
    )
    assert (magic, operation, account_size, secret_size) == (
        b"VKH1",
        2,
        len(b"voice-asr-calibration-key.v2"),
        32,
    )
    assert request.endswith(b"voice-asr-calibration-key.v2" + b"k" * 32)
    assert "k" * 32 not in repr(argv)
    assert "k" * 32 not in repr({key: value for key, value in options.items() if key != "input"})


def test_backend_maps_exact_read_not_found_and_delete_protocol(tmp_path: Path) -> None:
    helper = _helper(tmp_path)
    runner = Runner(_response(0, b"s" * 32))
    backend = HelperKeychainBackend(helper, boundary=tmp_path, runner=runner)

    assert backend.read(VOICE_KEYCHAIN_SERVICE, "device-signing-key.v1") == b"s" * 32
    runner.response = _response(1)
    assert backend.read(VOICE_KEYCHAIN_SERVICE, "voice-outbox-key.v1") is None
    runner.response = _response(0)
    backend.delete(
        VOICE_KEYCHAIN_SERVICE,
        "voice-profile-key.v1.123e4567-e89b-12d3-a456-426614174000",
    )

    operations = [REQUEST.unpack(call[1]["input"][: REQUEST.size])[1] for call in runner.calls]
    assert operations == [1, 1, 3]


@pytest.mark.parametrize(
    ("service", "account", "secret"),
    [
        ("other", "voice-asr-calibration-key.v2", None),
        (VOICE_KEYCHAIN_SERVICE, "../escape", None),
        (VOICE_KEYCHAIN_SERVICE, "voice-profile-key.v1.not-a-uuid", None),
        (VOICE_KEYCHAIN_SERVICE, "voice-asr-calibration-key.v2", b"short"),
    ],
)
def test_backend_rejects_unapproved_input_before_spawning(
    tmp_path: Path, service: str, account: str, secret: bytes | None
) -> None:
    runner = Runner(_response(0))
    backend = HelperKeychainBackend(_helper(tmp_path), boundary=tmp_path, runner=runner)

    with pytest.raises(ValueError, match=f"^{HELPER_KEYCHAIN_UNAVAILABLE}$"):
        if secret is None:
            backend.read(service, account)
        else:
            backend.write(service, account, secret)

    assert runner.calls == []


@pytest.mark.parametrize(
    "response",
    [
        b"",
        _response(0, b"short"),
        _response(0, b"x" * 33),
        RESPONSE.pack(b"BAD!", 0, 0),
        RESPONSE.pack(b"VKR1", 9, 0),
        _response(2),
    ],
)
def test_backend_fails_closed_for_malformed_or_unavailable_helper_output(
    tmp_path: Path, response: bytes
) -> None:
    backend = HelperKeychainBackend(
        _helper(tmp_path), boundary=tmp_path, runner=Runner(response)
    )

    with pytest.raises(ValueError, match=f"^{HELPER_KEYCHAIN_UNAVAILABLE}$"):
        backend.read(VOICE_KEYCHAIN_SERVICE, "voice-asr-calibration-key.v2")


def test_backend_fails_closed_for_timeout_and_symlinked_helper_path(
    tmp_path: Path,
) -> None:
    helper = _helper(tmp_path)

    def timeout(*_args: object, **_kwargs: object) -> object:
        raise subprocess.TimeoutExpired([str(helper)], 5.0, output=b"private")

    backend = HelperKeychainBackend(helper, boundary=tmp_path, runner=timeout)
    with pytest.raises(ValueError, match=f"^{HELPER_KEYCHAIN_UNAVAILABLE}$"):
        backend.read(VOICE_KEYCHAIN_SERVICE, "voice-asr-calibration-key.v2")

    symlink_root = tmp_path / "symlink-case"
    helper = (
        symlink_root
        / ".local/VoiceKeychainHelper.app/Contents/MacOS/voice-keychain-helper"
    )
    helper.parent.mkdir(parents=True)
    external = tmp_path / "external"
    external.write_bytes(b"helper")
    external.chmod(stat.S_IRUSR | stat.S_IWUSR | stat.S_IXUSR)
    helper.symlink_to(external)
    with pytest.raises(ValueError, match=f"^{HELPER_KEYCHAIN_UNAVAILABLE}$"):
        HelperKeychainBackend(
            helper, boundary=symlink_root, runner=Runner(_response(0))
        )
