from __future__ import annotations

import argparse
import os
import platform
import plistlib
import shutil
import subprocess
import tempfile
from collections.abc import Callable
from pathlib import Path


HELPER_BUNDLE_ID = "com.babymonitor.voice-keychain-helper"
HELPER_DESIGNATED_REQUIREMENT = (
    '=designated => identifier "com.babymonitor.voice-keychain-helper"'
)
HELPER_RELATIVE = Path(
    ".local/VoiceKeychainHelper.app/Contents/MacOS/voice-keychain-helper"
)
SOURCE_RELATIVE = Path("tools/native/voice_keychain_helper.c")


class VoiceKeychainHelperBuildError(ValueError):
    pass


Runner = Callable[[list[str]], str]


def build_voice_keychain_helper(
    project_root: Path,
    *,
    runner: Runner | None = None,
    system: Callable[[], str] = platform.system,
    machine: Callable[[], str] = platform.machine,
) -> Path:
    run = runner or _run
    try:
        if system() != "Darwin" or machine() != "x86_64":
            raise ValueError
        root = Path(project_root)
        if root.is_symlink():
            raise ValueError
        root = root.resolve(strict=True)
        source = root / SOURCE_RELATIVE
        local = root / ".local"
        if source.is_symlink() or not source.is_file() or local.is_symlink():
            raise ValueError
        if local.exists() and not local.is_dir():
            raise ValueError
        local.mkdir(mode=0o755, exist_ok=True)
        app = root / ".local/VoiceKeychainHelper.app"
        executable = root / HELPER_RELATIVE
        contents = app / "Contents"
        macos = contents / "MacOS"
        if app.is_symlink() or contents.is_symlink() or macos.is_symlink():
            raise ValueError
        macos.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(
            prefix="voice-keychain-helper-", dir=local
        ) as temporary:
            candidate = Path(temporary) / "voice-keychain-helper"
            run(
                [
                    "/usr/bin/clang",
                    "-std=c11",
                    "-Wall",
                    "-Wextra",
                    "-Werror",
                    "-O2",
                    str(source),
                    "-o",
                    str(candidate),
                    "-framework",
                    "Security",
                    "-framework",
                    "CoreFoundation",
                ]
            )
            if candidate.is_symlink() or not candidate.is_file():
                raise ValueError
            candidate.chmod(0o755)
            shutil.copyfile(candidate, executable)
            executable.chmod(0o755)
        info = {
            "CFBundleDevelopmentRegion": "en",
            "CFBundleExecutable": "voice-keychain-helper",
            "CFBundleIdentifier": HELPER_BUNDLE_ID,
            "CFBundleInfoDictionaryVersion": "6.0",
            "CFBundleName": "Baby Monitor Voice Keychain Helper",
            "CFBundlePackageType": "APPL",
            "CFBundleShortVersionString": "1.0",
            "CFBundleVersion": "1",
            "LSUIElement": True,
        }
        info_path = contents / "Info.plist"
        with info_path.open("wb") as handle:
            plistlib.dump(info, handle, fmt=plistlib.FMT_BINARY, sort_keys=True)
        run(
            [
                "/usr/bin/codesign",
                "--force",
                "--deep",
                "--sign",
                "-",
                "--requirements",
                HELPER_DESIGNATED_REQUIREMENT,
                str(app),
            ]
        )
        run(
            [
                "/usr/bin/codesign",
                "--verify",
                "--deep",
                "--strict",
                "--requirements",
                HELPER_DESIGNATED_REQUIREMENT,
                str(app),
            ]
        )
        return executable
    except VoiceKeychainHelperBuildError:
        raise
    except Exception:
        raise VoiceKeychainHelperBuildError("voice_keychain_helper_build_failed") from None


def _run(argv: list[str]) -> str:
    temporary_root = Path(tempfile.gettempdir()).resolve(strict=True)
    completed = subprocess.run(
        argv,
        check=False,
        capture_output=True,
        text=True,
        timeout=60,
        env={"PATH": "/usr/bin:/bin", "TMPDIR": str(temporary_root)},
    )
    if completed.returncode != 0:
        raise VoiceKeychainHelperBuildError("voice_keychain_helper_build_failed")
    return completed.stdout


def main(argv: list[str] | None = None, *, project_root: Path | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build the fixed Voice Keychain helper")
    parser.add_argument("operation", choices=("ensure",))
    arguments = parser.parse_args(argv)
    try:
        build_voice_keychain_helper(project_root or Path(__file__).resolve().parents[1])
        print("voice_keychain_helper=available")
        return 0
    except Exception:
        print("voice_keychain_helper=unavailable")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = [
    "HELPER_BUNDLE_ID",
    "HELPER_DESIGNATED_REQUIREMENT",
    "VoiceKeychainHelperBuildError",
    "build_voice_keychain_helper",
]
