from __future__ import annotations

import plistlib
import tempfile
from pathlib import Path

import pytest

from tools.voice_keychain_helper_build import (
    HELPER_BUNDLE_ID,
    HELPER_DESIGNATED_REQUIREMENT,
    VoiceKeychainHelperBuildError,
    build_voice_keychain_helper,
)
from tools import voice_keychain_helper_build


def test_build_creates_fixed_signed_helper_app_without_external_writes(
    tmp_path: Path,
) -> None:
    source = tmp_path / "tools/native/voice_keychain_helper.c"
    source.parent.mkdir(parents=True)
    source.write_text("int main(void) { return 0; }\n", encoding="ascii")
    commands: list[list[str]] = []

    def run(argv: list[str]) -> str:
        commands.append(argv)
        if argv[0] == "/usr/bin/clang":
            output = Path(argv[argv.index("-o") + 1])
            output.write_bytes(b"mach-o")
            output.chmod(0o755)
        return ""

    executable = build_voice_keychain_helper(
        tmp_path,
        runner=run,
        system=lambda: "Darwin",
        machine=lambda: "x86_64",
    )

    app = tmp_path / ".local/VoiceKeychainHelper.app"
    assert executable == app / "Contents/MacOS/voice-keychain-helper"
    assert executable.read_bytes() == b"mach-o"
    assert executable.stat().st_mode & 0o777 == 0o755
    with (app / "Contents/Info.plist").open("rb") as handle:
        info = plistlib.load(handle)
    assert info["CFBundleIdentifier"] == HELPER_BUNDLE_ID
    assert info["CFBundleExecutable"] == "voice-keychain-helper"
    assert info["LSUIElement"] is True
    assert commands[0][0] == "/usr/bin/clang"
    assert commands[0][-4:] == [
        "-framework",
        "Security",
        "-framework",
        "CoreFoundation",
    ]
    assert commands[-2] == [
        "/usr/bin/codesign",
        "--force",
        "--deep",
        "--sign",
        "-",
        "--requirements",
        HELPER_DESIGNATED_REQUIREMENT,
        str(app),
    ]
    assert commands[-1] == [
        "/usr/bin/codesign",
        "--verify",
        "--deep",
        "--strict",
        "--requirements",
        HELPER_DESIGNATED_REQUIREMENT,
        str(app),
    ]


def test_build_rejects_wrong_platform_and_symlinked_local_parent(
    tmp_path: Path,
) -> None:
    calls: list[list[str]] = []
    with pytest.raises(VoiceKeychainHelperBuildError):
        build_voice_keychain_helper(
            tmp_path,
            runner=lambda argv: calls.append(argv) or "",
            system=lambda: "Linux",
            machine=lambda: "x86_64",
        )
    assert calls == []

    source = tmp_path / "tools/native/voice_keychain_helper.c"
    source.parent.mkdir(parents=True)
    source.write_text("int main(void) { return 0; }\n", encoding="ascii")
    external = tmp_path / "external"
    external.mkdir()
    (tmp_path / ".local").symlink_to(external, target_is_directory=True)
    with pytest.raises(VoiceKeychainHelperBuildError):
        build_voice_keychain_helper(
            tmp_path,
            runner=lambda argv: calls.append(argv) or "",
            system=lambda: "Darwin",
            machine=lambda: "x86_64",
        )
    assert list(external.iterdir()) == []
    assert calls == []


def test_real_command_runner_keeps_only_fixed_path_and_resolved_tempdir(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    observed: dict[str, object] = {}

    def run(argv: list[str], **options: object) -> object:
        observed.update({"argv": argv, **options})
        return type("Completed", (), {"returncode": 0, "stdout": ""})()

    monkeypatch.setattr(voice_keychain_helper_build.subprocess, "run", run)

    voice_keychain_helper_build._run(["/usr/bin/true"])

    assert observed["env"] == {
        "PATH": "/usr/bin:/bin",
        "TMPDIR": str(Path(tempfile.gettempdir()).resolve(strict=True)),
    }
