from __future__ import annotations

import json
import os
import subprocess
import sys
import textwrap
import time
from pathlib import Path

import pytest

from packages.contracts.settings import VoiceCareSettings
from services.voice.artifacts import voice_artifact_spec
from services.voice.asr import AsrResult
from services.voice.paraformer import ParaformerProcess, RecoveringParaformerProcess


PCM = b"\x01\x00" * (16_000 * 2)


class _RecoveringChild:
    def __init__(self, outcomes: list[AsrResult | ValueError]) -> None:
        self._outcomes = outcomes
        self.closed = False

    def transcribe(self, _pcm: bytes) -> AsrResult:
        outcome = self._outcomes.pop(0)
        if isinstance(outcome, ValueError):
            raise outcome
        return outcome

    def close(self) -> None:
        self.closed = True


def test_recovering_paraformer_rebuilds_once_after_child_becomes_unavailable() -> None:
    failed = _RecoveringChild([ValueError("voice_model_unavailable")])
    recovered = _RecoveringChild(
        [AsrResult(text="小小开始喂奶", language="zh", duration_ms=12)]
    )
    children = iter((failed, recovered))
    process = RecoveringParaformerProcess(lambda: next(children))

    result = process.transcribe(PCM)

    assert result.text == "小小开始喂奶"
    assert failed.closed is True
    assert recovered.closed is False


def _spec():
    return voice_artifact_spec(
        VoiceCareSettings(
            enabled=False,
            paraformer_zh_manifest_sha256="5" * 64,
        ),
        "sherpa-onnx-paraformer-zh-2023-09-14",
    )


def _helper(
    tmp_path: Path,
    response: object,
    *,
    delay: float = 0.0,
    drain_stdin: bool = True,
) -> Path:
    path = tmp_path / "protocol_helper.py"
    encoded = json.dumps(
        response, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    )
    path.write_text(
        textwrap.dedent(
            f"""
            import struct
            import sys
            import time

            sys.stdout.write('{{"schemaVersion":1,"state":"ready"}}\\n')
            sys.stdout.flush()
            if not {drain_stdin!r}:
                time.sleep(30)
                raise SystemExit(0)
            while True:
                header = sys.stdin.buffer.read(4)
                if not header:
                    break
                size = struct.unpack(">I", header)[0]
                pcm = sys.stdin.buffer.read(size)
                if len(pcm) != size:
                    break
                time.sleep({delay!r})
                sys.stdout.buffer.write(({encoded!r} + "\\n").encode("utf-8"))
                sys.stdout.buffer.flush()
            """
        ),
        encoding="utf-8",
    )
    return path


def _process(
    tmp_path: Path,
    response: object,
    *,
    delay: float = 0.0,
    request_timeout: float = 3.0,
    drain_stdin: bool = True,
) -> tuple[ParaformerProcess, list[tuple[str, ...]], list[dict[str, object]]]:
    environment = tmp_path / "runtime/voice-asr-venv"
    bundle = tmp_path / "bundle"
    runner = tmp_path / "tools/voice_paraformer_runner.py"
    environment.mkdir(parents=True)
    bundle.mkdir()
    runner.parent.mkdir()
    runner.write_text("# fixed runner fixture\n", encoding="ascii")
    helper = _helper(tmp_path, response, delay=delay, drain_stdin=drain_stdin)
    commands: list[tuple[str, ...]] = []
    options: list[dict[str, object]] = []

    def popen(command: tuple[str, ...], **kwargs: object):
        commands.append(command)
        options.append(kwargs)
        child = subprocess.Popen((sys.executable, str(helper)), **kwargs)
        options[-1]["spawned_process"] = child
        return child

    process = ParaformerProcess(
        _spec(),
        project_root=tmp_path,
        environment_validator=lambda _root, _prefix: environment,
        artifact_validator=lambda _spec, _root: bundle,
        popen_factory=popen,
        request_timeout_seconds=request_timeout,
    )
    return process, commands, options


def test_paraformer_process_reuses_one_offline_child_and_keeps_pcm_out_of_argv(
    tmp_path: Path,
) -> None:
    response = {"language": "zh", "latencyMs": 12, "schemaVersion": 1, "text": "小小我是爸爸"}
    process, commands, options = _process(tmp_path, response)
    try:
        first = process.transcribe(PCM)
        second = process.transcribe(PCM)
    finally:
        process.close()

    assert first.text == "小小我是爸爸"
    assert first.language == "zh"
    assert first.duration_ms == 12
    assert second == first
    assert len(commands) == 1
    assert commands[0][:3] == (
        str(tmp_path / "runtime/voice-asr-venv/bin/python"),
        "-I",
        str(tmp_path / "tools/voice_paraformer_runner.py"),
    )
    assert not any(PCM.hex() in argument for argument in commands[0])
    child_environment = options[0]["env"]
    assert isinstance(child_environment, dict)
    assert child_environment == {
        "HF_HUB_OFFLINE": "1",
        "NO_PROXY": "*",
        "PYTHONUNBUFFERED": "1",
        **({"PATH": os.environ["PATH"]} if "PATH" in os.environ else {}),
    }


@pytest.mark.parametrize(
    "response",
    (
        {"language": "en", "latencyMs": 1, "schemaVersion": 1, "text": "x"},
        {"language": "zh", "latencyMs": 3_001, "schemaVersion": 1, "text": "x"},
        {"language": "zh", "latencyMs": 1, "schemaVersion": 2, "text": "x"},
        {"language": "zh", "latencyMs": 1, "schemaVersion": 1, "text": ""},
        {"extra": "x", "language": "zh", "latencyMs": 1, "schemaVersion": 1, "text": "x"},
    ),
)
def test_paraformer_process_rejects_noncanonical_or_invalid_response(
    tmp_path: Path, response: object
) -> None:
    process, _commands, _options = _process(tmp_path, response)
    with pytest.raises(ValueError, match="^voice_model_unavailable$"):
        process.transcribe(PCM)
    assert process.closed is True


@pytest.mark.parametrize("pcm", (b"", b"\x00", b"\x00\x00" * (16_000 * 8 + 1)))
def test_paraformer_process_rejects_invalid_pcm_before_child_write(
    tmp_path: Path, pcm: bytes
) -> None:
    response = {"language": "zh", "latencyMs": 1, "schemaVersion": 1, "text": "x"}
    process, _commands, _options = _process(tmp_path, response)
    try:
        with pytest.raises(ValueError, match="^voice_pcm_invalid$"):
            process.transcribe(pcm)
    finally:
        process.close()


def test_paraformer_process_timeout_destroys_and_settles_child(tmp_path: Path) -> None:
    response = {"language": "zh", "latencyMs": 1, "schemaVersion": 1, "text": "x"}
    process, _commands, options = _process(
        tmp_path, response, delay=1.0, request_timeout=0.05
    )
    with pytest.raises(ValueError, match="^voice_model_unavailable$"):
        process.transcribe(PCM)
    assert process.closed is True
    child = options[0]["spawned_process"]
    assert isinstance(child, subprocess.Popen)
    assert child.poll() is not None


def test_paraformer_request_deadline_covers_a_child_that_never_drains_stdin(
    tmp_path: Path,
) -> None:
    response = {"language": "zh", "latencyMs": 1, "schemaVersion": 1, "text": "x"}
    process, _commands, options = _process(
        tmp_path,
        response,
        request_timeout=0.05,
        drain_stdin=False,
    )

    started = time.monotonic()
    with pytest.raises(ValueError, match="^voice_model_unavailable$"):
        process.transcribe(b"\x00\x00" * (16_000 * 8))

    assert time.monotonic() - started < 1.0
    child = options[0]["spawned_process"]
    assert isinstance(child, subprocess.Popen)
    assert child.poll() is not None


def test_paraformer_real_isolated_command_does_not_import_project_shadow_modules(
    tmp_path: Path,
) -> None:
    environment = tmp_path / "runtime/voice-asr-venv"
    environment.mkdir(parents=True)
    (environment / "bin").mkdir()
    (environment / "bin/python").symlink_to(Path(sys.executable).resolve())
    bundle = tmp_path / "bundle"
    bundle.mkdir()
    marker = tmp_path / "shadow-imported"
    (tmp_path / "json.py").write_text(
        f"from pathlib import Path\nPath({str(marker)!r}).write_text('bad')\n",
        encoding="ascii",
    )
    runner = tmp_path / "tools/voice_paraformer_runner.py"
    runner.parent.mkdir()
    runner.write_text(
        textwrap.dedent(
            """
            import json
            import struct
            import sys

            print('{"schemaVersion":1,"state":"ready"}', flush=True)
            size = struct.unpack(">I", sys.stdin.buffer.read(4))[0]
            sys.stdin.buffer.read(size)
            print(json.dumps({"language":"zh","latencyMs":1,"schemaVersion":1,"text":"x"}, sort_keys=True, separators=(",", ":")), flush=True)
            """
        ),
        encoding="ascii",
    )

    process = ParaformerProcess(
        _spec(),
        project_root=tmp_path,
        environment_validator=lambda _root, _prefix: environment,
        artifact_validator=lambda _spec, _root: bundle,
    )
    try:
        assert process.transcribe(b"\x00\x00").text == "x"
    finally:
        process.close()
    assert not marker.exists()
