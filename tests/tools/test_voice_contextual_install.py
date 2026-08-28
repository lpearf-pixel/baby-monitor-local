from __future__ import annotations

import hashlib
import json
import subprocess
from pathlib import Path

import pytest

from services.voice.contextual_artifacts import (
    CONTEXTUAL_ARTIFACT,
    CONTEXTUAL_MANIFEST_NAME,
    build_contextual_manifest,
)
from tools.voice_contextual_environment import (
    PINNED_CONTEXTUAL_PACKAGES,
    validate_contextual_environment,
    validate_contextual_environment_path,
)
from tools.voice_contextual_install import (
    MODEL_URLS,
    install_contextual_candidate,
)


def test_environment_path_and_versions_are_isolated_and_exact(tmp_path: Path) -> None:
    expected = tmp_path / "runtime/voice-contextual-venv"
    assert validate_contextual_environment_path(tmp_path) == expected
    assert PINNED_CONTEXTUAL_PACKAGES["funasr-onnx"] == "0.4.2"
    assert PINNED_CONTEXTUAL_PACKAGES["numpy"] == "1.26.4"
    assert PINNED_CONTEXTUAL_PACKAGES["onnxruntime"] == "1.23.2"
    outside = tmp_path / "outside"
    outside.mkdir()
    (tmp_path / "runtime").symlink_to(outside, target_is_directory=True)
    with pytest.raises(ValueError, match="^VOICE_CONTEXTUAL_ENVIRONMENT_INVALID$"):
        validate_contextual_environment_path(tmp_path)


def test_environment_validator_requires_fixed_importable_distribution_set(
    tmp_path: Path,
) -> None:
    environment = tmp_path / "runtime/voice-contextual-venv"
    (environment / "bin").mkdir(parents=True)
    environment.chmod(0o700)
    python = environment / "bin/python"
    python.write_text("fixture", encoding="ascii")
    python.chmod(0o700)
    (environment / "pyvenv.cfg").write_text(
        "include-system-site-packages = false\n", encoding="ascii"
    )

    def runner(command: tuple[str, ...], **_kwargs: object):
        return subprocess.CompletedProcess(
            command,
            0,
            json.dumps(
                PINNED_CONTEXTUAL_PACKAGES,
                separators=(",", ":"),
                sort_keys=True,
            ),
            "",
        )

    assert (
        validate_contextual_environment(tmp_path, environment, runner=runner)
        == environment
    )

    drifted = dict(PINNED_CONTEXTUAL_PACKAGES)
    drifted["numpy"] = "9.9.9"

    def drift_runner(command: tuple[str, ...], **_kwargs: object):
        return subprocess.CompletedProcess(
            command,
            0,
            json.dumps(drifted, separators=(",", ":"), sort_keys=True),
            "private error",
        )

    with pytest.raises(ValueError, match="^VOICE_CONTEXTUAL_ENVIRONMENT_INVALID$"):
        validate_contextual_environment(tmp_path, environment, runner=drift_runner)


def test_model_urls_are_revision_pinned_and_closed() -> None:
    assert set(MODEL_URLS) == {item.path for item in CONTEXTUAL_ARTIFACT.files}
    assert all(
        CONTEXTUAL_ARTIFACT.upstream_revision in url
        and "master" not in url
        and "latest" not in url
        for url in MODEL_URLS.values()
    )


def test_installer_builds_private_staging_then_publishes_without_production_changes(
    tmp_path: Path,
) -> None:
    requirements = tmp_path / "config/voice-contextual-requirements.txt"
    requirements.parent.mkdir()
    requirements.write_text(
        "package==1 --hash=sha256:" + "a" * 64 + "\n",
        encoding="ascii",
    )
    base_python = tmp_path / "python3.11"
    base_python.write_text("fixture", encoding="ascii")
    base_python.chmod(0o700)
    commands: list[tuple[str, ...]] = []
    downloads: list[tuple[str, str]] = []
    validations: list[Path] = []

    def runner(command: tuple[str, ...], **_kwargs: object):
        commands.append(command)
        if command[1:3] == ("-m", "venv"):
            environment = Path(command[-1])
            (environment / "bin").mkdir(parents=True, exist_ok=True)
            (environment / "bin/python").write_text("fixture", encoding="ascii")
            (environment / "bin/python").chmod(0o700)
        return subprocess.CompletedProcess(command, 0, "", "")

    def downloader(url: str, destination: Path, expected) -> None:
        downloads.append((url, expected.path))
        destination.write_bytes(expected.path.encode("ascii"))
        destination.chmod(0o600)

    def environment_validator(_root: Path, candidate: Path) -> Path:
        validations.append(candidate)
        return candidate

    def bundle_validator(_root: Path, candidate: Path) -> Path:
        validations.append(candidate)
        assert (candidate / CONTEXTUAL_MANIFEST_NAME).read_bytes() == (
            build_contextual_manifest()
        )
        return candidate

    environment, bundle = install_contextual_candidate(
        tmp_path,
        base_python=base_python,
        runner=runner,
        downloader=downloader,
        environment_candidate_validator=environment_validator,
        environment_validator=environment_validator,
        bundle_candidate_validator=bundle_validator,
        bundle_validator=bundle_validator,
    )

    assert environment == tmp_path / "runtime/voice-contextual-venv"
    assert bundle.parent.name == CONTEXTUAL_ARTIFACT.artifact_id
    assert len(downloads) == len(CONTEXTUAL_ARTIFACT.files)
    assert len(commands) == 2
    assert commands[1][1:4] == ("-m", "pip", "install")
    assert "--require-hashes" in commands[1]
    assert "--no-deps" in commands[1]
    assert "--no-build-isolation" in commands[1]
    assert all("voice-asr-venv" not in str(path) for path in validations)
    assert not (tmp_path / "runtime/config/voice-care-models.json").exists()


def test_installer_rejects_unsafe_runtime_before_runner_or_download(tmp_path: Path) -> None:
    outside = tmp_path / "outside"
    outside.mkdir()
    (tmp_path / "runtime").symlink_to(outside, target_is_directory=True)
    called = False

    def runner(*_args: object, **_kwargs: object):
        nonlocal called
        called = True
        raise AssertionError

    with pytest.raises(ValueError, match="^VOICE_CONTEXTUAL_INSTALL_FAILED$"):
        install_contextual_candidate(
            tmp_path,
            base_python=tmp_path / "python",
            runner=runner,
        )
    assert called is False
