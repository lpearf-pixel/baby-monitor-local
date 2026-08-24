from __future__ import annotations

import json
import os
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

from packages.contracts.settings import VoiceCareSettings
from services.voice.artifacts import voice_artifact_spec
from services.voice.ecapa import EcapaProcess


PCM = b"\x01\x00" * (16_000 * 2)
EMBEDDING = [1.0] + [0.0] * 191


def _spec():
    return voice_artifact_spec(
        VoiceCareSettings(
            enabled=False,
            speechbrain_ecapa_manifest_sha256="4" * 64,
        ),
        "speechbrain-ecapa-voxceleb",
    )


def _helper(tmp_path: Path, response: object, *, delay: float = 0.0) -> Path:
    path = tmp_path / "protocol_helper.py"
    encoded = json.dumps(response, sort_keys=True, separators=(",", ":"))
    path.write_text(
        textwrap.dedent(
            f"""
            import struct
            import sys
            import time

            sys.stdout.write('{{"schemaVersion":1,"state":"ready"}}\\n')
            sys.stdout.flush()
            while True:
                header = sys.stdin.buffer.read(4)
                if not header:
                    break
                size = struct.unpack(">I", header)[0]
                pcm = sys.stdin.buffer.read(size)
                if len(pcm) != size:
                    break
                time.sleep({delay!r})
                sys.stdout.write({encoded!r} + "\\n")
                sys.stdout.flush()
            """
        ),
        encoding="ascii",
    )
    return path


def _process(
    tmp_path: Path,
    response: object,
    *,
    delay: float = 0.0,
    request_timeout: float = 5.0,
) -> tuple[EcapaProcess, list[tuple[str, ...]]]:
    environment = tmp_path / "runtime/voice-speaker-venv"
    bundle = tmp_path / "bundle"
    runner = tmp_path / "tools/voice_ecapa_runner.py"
    environment.mkdir(parents=True)
    bundle.mkdir()
    runner.parent.mkdir()
    runner.write_text("# fixed runner fixture\n", encoding="ascii")
    helper = _helper(tmp_path, response, delay=delay)
    commands: list[tuple[str, ...]] = []

    def popen(command: tuple[str, ...], **kwargs: object):
        commands.append(command)
        assert kwargs["cwd"] == str(tmp_path)
        return subprocess.Popen((sys.executable, str(helper)), **kwargs)

    process = EcapaProcess(
        _spec(),
        project_root=tmp_path,
        environment_validator=lambda _root, _prefix: environment,
        artifact_validator=lambda _spec, _root: bundle,
        popen_factory=popen,
        request_timeout_seconds=request_timeout,
    )
    return process, commands


def test_ecapa_process_reuses_one_child_and_sends_audio_only_over_stdin(
    tmp_path: Path,
) -> None:
    response = {"embedding": EMBEDDING, "latencyMs": 12, "schemaVersion": 1}
    process, commands = _process(tmp_path, response)
    try:
        first = process.embed(PCM)
        second = process.embed(PCM)
    finally:
        process.close()

    assert first.embedding == tuple(EMBEDDING)
    assert first.latency_ms == 12
    assert second == first
    assert len(commands) == 1
    command = commands[0]
    assert not any(PCM.hex() in argument for argument in command)
    assert command[:3] == (
        str(tmp_path / "runtime/voice-speaker-venv/bin/python"),
        "-m",
        "tools.voice_ecapa_runner",
    )


@pytest.mark.parametrize(
    "response",
    (
        {"embedding": EMBEDDING[:-1], "latencyMs": 1, "schemaVersion": 1},
        {"embedding": [2.0] + [0.0] * 191, "latencyMs": 1, "schemaVersion": 1},
        {"embedding": EMBEDDING, "latencyMs": 1, "schemaVersion": 2},
        {"embedding": EMBEDDING, "latencyMs": "1", "schemaVersion": 1},
        {"embedding": EMBEDDING, "latencyMs": 1, "schemaVersion": 1, "path": "x"},
    ),
)
def test_ecapa_process_rejects_noncanonical_or_invalid_responses(
    tmp_path: Path, response: object
) -> None:
    process, _commands = _process(tmp_path, response)
    try:
        with pytest.raises(ValueError, match="^voice_model_unavailable$"):
            process.embed(PCM)
    finally:
        process.close()


@pytest.mark.parametrize("seconds", (0.1, 8.1))
def test_ecapa_process_rejects_pcm_outside_the_bounded_window(
    tmp_path: Path, seconds: float
) -> None:
    response = {"embedding": EMBEDDING, "latencyMs": 1, "schemaVersion": 1}
    process, _commands = _process(tmp_path, response)
    try:
        pcm = b"\x00\x00" * int(16_000 * seconds)
        with pytest.raises(ValueError, match="^voice_pcm_invalid$"):
            process.embed(pcm)
    finally:
        process.close()


def test_ecapa_process_times_out_and_settles_the_child(tmp_path: Path) -> None:
    response = {"embedding": EMBEDDING, "latencyMs": 1, "schemaVersion": 1}
    process, _commands = _process(
        tmp_path, response, delay=1.0, request_timeout=0.05
    )

    with pytest.raises(ValueError, match="^voice_model_unavailable$"):
        process.embed(PCM)

    process.close()
    assert process.closed is True


def test_ecapa_process_uses_an_offline_sanitized_child_environment(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    response = {"embedding": EMBEDDING, "latencyMs": 1, "schemaVersion": 1}
    monkeypatch.setenv("HF_TOKEN", "must-not-cross-boundary")
    observed: dict[str, object] = {}
    helper = _helper(tmp_path, response)
    environment = tmp_path / "runtime/voice-speaker-venv"
    bundle = tmp_path / "bundle"
    runner = tmp_path / "tools/voice_ecapa_runner.py"
    environment.mkdir(parents=True)
    bundle.mkdir()
    runner.parent.mkdir()
    runner.write_text("# fixed runner fixture\n", encoding="ascii")

    def popen(_command: tuple[str, ...], **kwargs: object):
        observed.update(kwargs)
        return subprocess.Popen((sys.executable, str(helper)), **kwargs)

    process = EcapaProcess(
        _spec(),
        project_root=tmp_path,
        environment_validator=lambda _root, _prefix: environment,
        artifact_validator=lambda _spec, _root: bundle,
        popen_factory=popen,
    )
    process.close()

    child_environment = observed["env"]
    assert isinstance(child_environment, dict)
    assert child_environment["HF_HUB_OFFLINE"] == "1"
    assert child_environment["TRANSFORMERS_OFFLINE"] == "1"
    assert child_environment["NO_PROXY"] == "*"
    assert "HF_TOKEN" not in child_environment
