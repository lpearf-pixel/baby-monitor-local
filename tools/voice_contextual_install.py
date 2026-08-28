from __future__ import annotations

import argparse
import hashlib
import os
import subprocess
import tempfile
import urllib.request
from collections.abc import Callable
from pathlib import Path

from services.voice.contextual_artifacts import (
    CONTEXTUAL_ARTIFACT,
    CONTEXTUAL_BUNDLE_DIGEST,
    CONTEXTUAL_MANIFEST_NAME,
    ContextualFile,
    build_contextual_manifest,
    contextual_bundle_relative_path,
    validate_contextual_bundle,
    validate_contextual_bundle_candidate,
)
from tools.voice_contextual_environment import (
    validate_contextual_environment,
    validate_contextual_environment_candidate,
    validate_contextual_environment_path,
)


INSTALL_FAILED = "VOICE_CONTEXTUAL_INSTALL_FAILED"
_BASE_URL = (
    "https://www.modelscope.cn/models/iic/"
    "speech_paraformer-large-contextual_asr_nat-zh-cn-16k-common-vocab8404-onnx/"
    f"resolve/{CONTEXTUAL_ARTIFACT.upstream_revision}"
)
MODEL_URLS = {item.path: f"{_BASE_URL}/{item.path}" for item in CONTEXTUAL_ARTIFACT.files}
Runner = Callable[..., subprocess.CompletedProcess[str]]
Downloader = Callable[[str, Path, ContextualFile], None]
Validator = Callable[[Path, Path], Path]


def install_contextual_candidate(
    project_root: Path,
    *,
    base_python: Path,
    runner: Runner = subprocess.run,
    downloader: Downloader | None = None,
    environment_candidate_validator: Validator = validate_contextual_environment_candidate,
    environment_validator: Validator = validate_contextual_environment,
    bundle_candidate_validator: Validator = validate_contextual_bundle_candidate,
    bundle_validator: Validator | None = None,
) -> tuple[Path, Path]:
    """Install one immutable evaluation-only environment and model bundle."""

    try:
        root = Path(project_root)
        environment = validate_contextual_environment_path(root)
        root = root.resolve(strict=True)
        requirements = root / "config/voice-contextual-requirements.txt"
        base = Path(base_python).resolve(strict=True)
        if (
            requirements.is_symlink()
            or not requirements.is_file()
            or not base.is_file()
            or not os.access(base, os.X_OK)
        ):
            raise ValueError(INSTALL_FAILED)
        runtime = root / "runtime"
        runtime.mkdir(mode=0o700, parents=True, exist_ok=True)
        if environment.exists():
            environment_validator(root, environment)
        else:
            staging_environment = Path(
                tempfile.mkdtemp(prefix=".voice-contextual-venv.staging-", dir=runtime)
            )
            first = runner(
                (str(base), "-m", "venv", str(staging_environment)),
                check=False,
                capture_output=True,
                text=True,
                timeout=300,
            )
            python = staging_environment / "bin/python"
            if first.returncode != 0 or not python.is_file():
                raise ValueError(INSTALL_FAILED)
            second = runner(
                (
                    str(python),
                    "-m",
                    "pip",
                    "install",
                    "--disable-pip-version-check",
                    "--index-url",
                    "https://pypi.org/simple",
                    "--require-hashes",
                    "--no-deps",
                    "--no-build-isolation",
                    "--requirement",
                    str(requirements),
                ),
                check=False,
                capture_output=True,
                text=True,
                timeout=900,
            )
            if second.returncode != 0:
                raise ValueError(INSTALL_FAILED)
            environment_candidate_validator(root, staging_environment)
            staging_environment.rename(environment)
            environment_validator(root, environment)

        bundle = root / contextual_bundle_relative_path(CONTEXTUAL_BUNDLE_DIGEST)
        final_validator = bundle_validator or (
            lambda checked_root, _candidate: validate_contextual_bundle(checked_root)
        )
        if bundle.exists():
            final_validator(root, bundle)
        else:
            parent = bundle.parent
            parent.mkdir(mode=0o700, parents=True, exist_ok=True)
            parent.chmod(0o700)
            staging_bundle = Path(tempfile.mkdtemp(prefix=".staging-", dir=parent))
            staging_bundle.chmod(0o700)
            fetch = downloader or _download_file
            for expected in CONTEXTUAL_ARTIFACT.files:
                fetch(MODEL_URLS[expected.path], staging_bundle / expected.path, expected)
            manifest_path = staging_bundle / CONTEXTUAL_MANIFEST_NAME
            _write_private_file(manifest_path, build_contextual_manifest())
            bundle_candidate_validator(root, staging_bundle)
            staging_bundle.rename(bundle)
            final_validator(root, bundle)
        return environment, bundle
    except (OSError, subprocess.SubprocessError, ValueError):
        raise ValueError(INSTALL_FAILED) from None


def _download_file(url: str, destination: Path, expected: ContextualFile) -> None:
    digest = hashlib.sha256()
    size = 0
    descriptor = os.open(destination, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        with opener.open(url, timeout=30) as response:
            while True:
                chunk = response.read(1024 * 1024)
                if not chunk:
                    break
                size += len(chunk)
                if size > expected.size:
                    raise ValueError(INSTALL_FAILED)
                digest.update(chunk)
                _write_all(descriptor, chunk)
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
    if size != expected.size or digest.hexdigest() != expected.sha256:
        raise ValueError(INSTALL_FAILED)


def _write_private_file(path: Path, payload: bytes) -> None:
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    try:
        _write_all(descriptor, payload)
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _write_all(descriptor: int, payload: bytes) -> None:
    written = 0
    while written < len(payload):
        count = os.write(descriptor, payload[written:])
        if count <= 0:
            raise OSError(INSTALL_FAILED)
        written += count


def main() -> int:
    parser = argparse.ArgumentParser(description="Install fixed contextual ASR candidate")
    parser.add_argument("operation", choices=("install", "check"))
    parser.add_argument("--project-root", type=Path, default=Path.cwd())
    parser.add_argument("--base-python", type=Path, default=Path("/usr/local/bin/python3.11"))
    arguments = parser.parse_args()
    try:
        if arguments.operation == "install":
            install_contextual_candidate(
                arguments.project_root,
                base_python=arguments.base_python,
            )
        else:
            root = arguments.project_root.resolve(strict=True)
            environment = validate_contextual_environment_path(root)
            validate_contextual_environment(root, environment)
            validate_contextual_bundle(root)
    except (OSError, ValueError):
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
