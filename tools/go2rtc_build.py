from __future__ import annotations

import argparse
import functools
import os
import platform
import re
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

if __package__ in {None, ""}:
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from packages.monitoring.go2rtc_build import (
    GO2RTC_COMMIT,
    GO2RTC_DESIGNATED_REQUIREMENT,
    BuildMetadata,
    Go2RTCBuildError,
    install_candidate,
    install_macos_app_bundle,
    metadata_matches,
    read_metadata,
    rollback_latest,
    run_upstream_protocol_diagnostic_gate,
    run_upstream_protocol_gate,
    sha256_file,
    verify_and_apply_patch,
)


UPSTREAM_URL = "https://github.com/AlexxIT/go2rtc.git"
PLATFORM = "darwin/amd64"
MINIMUM_GO = (1, 24)
PATCH_RELATIVE = Path("patches/go2rtc-macos-hybrid-hd.patch")
METADATA_KEYS = (
    "upstream_commit",
    "go_version",
    "patch_sha256",
    "binary_sha256",
    "build_time",
    "platform",
)


def _run(
    args: list[str],
    *,
    cwd: Path | None = None,
    env: dict[str, str] | None = None,
) -> str:
    try:
        result = subprocess.run(
            args,
            cwd=cwd,
            env=env,
            check=True,
            capture_output=True,
            text=True,
        )
    except (OSError, subprocess.CalledProcessError) as exc:
        raise Go2RTCBuildError("BUILD_COMMAND_FAILED") from exc
    return result.stdout.strip()


def _paths(root: Path) -> tuple[Path, Path, Path, Path]:
    root = root.resolve()
    return (
        root / ".local/bin/go2rtc",
        root / "runtime/build/go2rtc.json",
        root / "runtime/backups/go2rtc",
        root / PATCH_RELATIVE,
    )


def _platform_guard() -> None:
    if platform.system() != "Darwin" or platform.machine() != "x86_64":
        raise Go2RTCBuildError("UNSUPPORTED_PLATFORM")


def _go_toolchain() -> tuple[str, str, dict[str, str]]:
    go = shutil.which("go")
    if not go:
        raise Go2RTCBuildError("GO_NOT_FOUND")
    env = dict(os.environ)
    configured_root = env.pop("GOROOT", None)
    version_output = _run([go, "version"], env=env)
    match = re.search(r"\bgo(\d+)\.(\d+)(?:\.\d+)?\b", version_output)
    if match is None or tuple(map(int, match.groups())) < MINIMUM_GO:
        raise Go2RTCBuildError("GO_VERSION_UNSUPPORTED")
    resolved_root = _run([go, "env", "GOROOT"], env=env)
    if not resolved_root or not Path(resolved_root).is_dir():
        raise Go2RTCBuildError("GO_ROOT_INVALID")
    if configured_root and Path(configured_root).resolve() != Path(resolved_root).resolve():
        raise Go2RTCBuildError("GO_ROOT_MISMATCH")
    return go, match.group(0), env


def _installed_build_is_current(
    binary: Path,
    metadata_path: Path,
    *,
    patch_sha256: str,
) -> bool:
    metadata = read_metadata(metadata_path)
    return bool(
        binary.is_file()
        and os.access(binary, os.X_OK)
        and metadata is not None
        and metadata_matches(
            metadata_path,
            upstream_commit=GO2RTC_COMMIT,
            patch_sha256=patch_sha256,
            platform=PLATFORM,
        )
        and sha256_file(binary) == metadata.binary_sha256
    )


def _install_app_bundle(root: Path, binary: Path) -> Path:
    app_bundle = root.resolve() / ".local/Go2RTC.app"
    executable = install_macos_app_bundle(
        binary,
        app_bundle,
        signer=lambda path: _run(
            [
                "codesign",
                "--force",
                "--deep",
                "--sign",
                "-",
                "--requirements",
                GO2RTC_DESIGNATED_REQUIREMENT,
                str(path),
            ]
        ),
    )
    _run(
        [
            "codesign",
            "--verify",
            "--deep",
            "--strict",
            "--requirements",
            GO2RTC_DESIGNATED_REQUIREMENT,
            str(app_bundle),
        ]
    )
    return executable


def _build(root: Path, *, force: bool) -> None:
    _platform_guard()
    binary, metadata_path, backups, patch = _paths(root)
    if not patch.is_file():
        raise Go2RTCBuildError("PATCH_NOT_FOUND")
    patch_sha256 = sha256_file(patch)
    if not force and _installed_build_is_current(
        binary, metadata_path, patch_sha256=patch_sha256
    ):
        _install_app_bundle(root, binary)
        print("go2rtc_build=UNCHANGED")
        return

    go, go_version, build_env = _go_toolchain()
    build_env.update({"CGO_ENABLED": "0", "GOOS": "darwin", "GOARCH": "amd64"})
    with tempfile.TemporaryDirectory(prefix="baby-monitor-go2rtc-") as temporary:
        temporary_path = Path(temporary)
        source = temporary_path / "source"
        candidate = temporary_path / "go2rtc"
        _run(
            ["git", "clone", "--filter=blob:none", "--no-checkout", UPSTREAM_URL, str(source)]
        )
        _run(["git", "checkout", "--detach", GO2RTC_COMMIT], cwd=source)
        verify_and_apply_patch(source, patch)
        run_upstream_protocol_gate(
            source,
            go,
            runner=functools.partial(subprocess.run, env=build_env),
        )
        _run(
            [go, "build", "-trimpath", "-ldflags", "-s -w", "-o", str(candidate), "."],
            cwd=source,
            env=build_env,
        )
        if not candidate.is_file():
            raise Go2RTCBuildError("BUILD_OUTPUT_MISSING")
        candidate.chmod(0o755)
        file_output = _run(["file", str(candidate)])
        if "Mach-O 64-bit executable x86_64" not in file_output:
            raise Go2RTCBuildError("BUILD_ARCH_INVALID")
        _run([str(candidate), "-version"])
        _run(["codesign", "--force", "--sign", "-", str(candidate)])
        metadata = BuildMetadata(
            upstream_commit=GO2RTC_COMMIT,
            go_version=go_version,
            patch_sha256=patch_sha256,
            binary_sha256=sha256_file(candidate),
            build_time=datetime.now(timezone.utc).isoformat(timespec="seconds"),
            platform=PLATFORM,
        )
        install_candidate(
            candidate,
            binary,
            backups,
            metadata_path,
            metadata,
            datetime.now(timezone.utc),
        )
    _install_app_bundle(root, binary)
    print("go2rtc_build=UPDATED")


def _info(root: Path) -> None:
    binary, metadata_path, _backups, _patch = _paths(root)
    metadata = read_metadata(metadata_path)
    if (
        metadata is None
        or not binary.is_file()
        or not os.access(binary, os.X_OK)
        or sha256_file(binary) != metadata.binary_sha256
    ):
        raise Go2RTCBuildError("GO2RTC_BUILD_NOT_FOUND")
    values = metadata.as_dict()
    for key in METADATA_KEYS:
        print(f"{key}={values[key]}")


def _rollback(root: Path) -> None:
    _platform_guard()
    binary, metadata_path, backups, _patch = _paths(root)
    rollback_latest(binary, backups, metadata_path, datetime.now(timezone.utc))
    _install_app_bundle(root, binary)
    print("go2rtc_build=ROLLED_BACK")


def _protocol_test(root: Path) -> None:
    _platform_guard()
    _binary, _metadata_path, _backups, patch = _paths(root)
    if not patch.is_file():
        raise Go2RTCBuildError("PATCH_NOT_FOUND")
    go, _go_version, build_env = _go_toolchain()
    with tempfile.TemporaryDirectory(prefix="baby-monitor-go2rtc-protocol-") as temporary:
        source = Path(temporary) / "source"
        _run(
            [
                "git",
                "clone",
                "--filter=blob:none",
                "--no-checkout",
                UPSTREAM_URL,
                str(source),
            ]
        )
        _run(["git", "checkout", "--detach", GO2RTC_COMMIT], cwd=source)
        verify_and_apply_patch(source, patch)
        run_upstream_protocol_diagnostic_gate(
            source,
            go,
            runner=functools.partial(subprocess.run, env=build_env),
        )
    print("go2rtc_protocol_test=D2_BOUNDARY_HARDENED_CAUSE_UNPROVEN")


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description="Manage the pinned Intel macOS go2rtc build")
    result.add_argument(
        "--root",
        type=Path,
        default=Path(__file__).resolve().parents[1],
        help=argparse.SUPPRESS,
    )
    result.add_argument(
        "command", choices=("ensure", "rebuild", "info", "rollback", "protocol-test")
    )
    return result


def main(argv: list[str] | None = None) -> int:
    options = parser().parse_args(argv)
    try:
        if options.command == "ensure":
            _build(options.root, force=False)
        elif options.command == "rebuild":
            _build(options.root, force=True)
        elif options.command == "info":
            _info(options.root)
        elif options.command == "protocol-test":
            _protocol_test(options.root)
        else:
            _rollback(options.root)
    except Go2RTCBuildError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
