from __future__ import annotations

import json
import os
import subprocess
import sys
import textwrap
from pathlib import Path

import numpy as np
import pytest

from services.voice.asr import AsrResult
from services.voice.contextual_paraformer import (
    CONTEXTUAL_HOTWORDS,
    CONTEXTUAL_HOTWORDS_SHA256,
    ContextualParaformerProcess,
)
from tools.voice_contextual_runner import _load_contextual_recognizer, run_protocol


PCM = b"\x00\x00" * 320


def _helper(tmp_path: Path, response: object, *, delay: float = 0.0) -> Path:
    helper = tmp_path / "child.py"
    helper.write_text(
        textwrap.dedent(
            f"""
            import json
            import struct
            import sys
            import time

            print('{{"schemaVersion":1,"state":"ready"}}', flush=True)
            while True:
                header = sys.stdin.buffer.read(4)
                if not header:
                    break
                size = struct.unpack(">I", header)[0]
                if len(sys.stdin.buffer.read(size)) != size:
                    break
                time.sleep({delay!r})
                print(json.dumps({response!r}, ensure_ascii=False, sort_keys=True, separators=(",", ":")), flush=True)
            """
        ),
        encoding="utf-8",
    )
    return helper


def _process(
    tmp_path: Path, response: object, *, timeout: float = 3.0, delay: float = 0.0
):
    environment = tmp_path / "runtime/voice-contextual-venv"
    (environment / "bin").mkdir(parents=True)
    bundle = tmp_path / "bundle"
    bundle.mkdir()
    runner_path = tmp_path / "tools/voice_contextual_runner.py"
    runner_path.parent.mkdir()
    runner_path.write_text("fixture", encoding="ascii")
    helper = _helper(tmp_path, response, delay=delay)
    commands: list[tuple[str, ...]] = []
    options: list[dict[str, object]] = []

    def popen(command: tuple[str, ...], **kwargs: object):
        commands.append(command)
        options.append(kwargs)
        child = subprocess.Popen((sys.executable, str(helper)), **kwargs)
        options[-1]["child"] = child
        return child

    process = ContextualParaformerProcess(
        project_root=tmp_path,
        environment_validator=lambda _root, _prefix: environment,
        artifact_validator=lambda _root: bundle,
        popen_factory=popen,
        request_timeout_seconds=timeout,
    )
    return process, commands, options


def test_hotwords_are_fixed_low_risk_and_digest_bound() -> None:
    assert CONTEXTUAL_HOTWORDS == (
        "小小 开始喂奶 喂奶结束 开始换尿布 换好尿布了 开始拍嗝 拍嗝结束"
    )
    assert len(CONTEXTUAL_HOTWORDS_SHA256) == 64
    assert "喂药" not in CONTEXTUAL_HOTWORDS


def test_process_reuses_one_isolated_child_and_returns_asr_result(tmp_path: Path) -> None:
    response = {
        "language": "zh",
        "latencyMs": 12,
        "schemaVersion": 1,
        "text": "开始拍嗝",
    }
    process, commands, options = _process(tmp_path, response)
    try:
        assert process.transcribe(PCM) == AsrResult("开始拍嗝", "zh", 12)
        assert process.transcribe(PCM) == AsrResult("开始拍嗝", "zh", 12)
    finally:
        process.close()

    assert len(commands) == 1
    assert commands[0][:3] == (
        str(tmp_path / "runtime/voice-contextual-venv/bin/python"),
        "-I",
        str(tmp_path / "tools/voice_contextual_runner.py"),
    )
    assert options[0]["stderr"] is subprocess.DEVNULL
    child_environment = options[0]["env"]
    assert isinstance(child_environment, dict)
    assert child_environment["NO_PROXY"] == "*"
    assert child_environment["OMP_NUM_THREADS"] == "2"
    assert not any(PCM.hex() in item for item in commands[0])


@pytest.mark.parametrize(
    "response",
    (
        {"language": "en", "latencyMs": 1, "schemaVersion": 1, "text": "x"},
        {"language": "zh", "latencyMs": 3001, "schemaVersion": 1, "text": "x"},
        {"extra": 1, "language": "zh", "latencyMs": 1, "schemaVersion": 1, "text": "x"},
    ),
)
def test_process_fails_closed_on_invalid_child_response(
    tmp_path: Path, response: object
) -> None:
    process, _commands, options = _process(tmp_path, response)
    with pytest.raises(ValueError, match="^voice_contextual_unavailable$"):
        process.transcribe(PCM)
    child = options[0]["child"]
    assert isinstance(child, subprocess.Popen)
    assert child.poll() is not None


def test_process_timeout_terminates_the_candidate_child(tmp_path: Path) -> None:
    response = {
        "language": "zh",
        "latencyMs": 1,
        "schemaVersion": 1,
        "text": "x",
    }
    process, _commands, options = _process(
        tmp_path, response, timeout=0.05, delay=1.0
    )
    with pytest.raises(ValueError, match="^voice_contextual_unavailable$"):
        process.transcribe(PCM)
    child = options[0]["child"]
    assert isinstance(child, subprocess.Popen)
    assert child.poll() is not None


def test_runner_uses_private_quantized_embedding_alias_and_fixed_hotwords(
    tmp_path: Path,
) -> None:
    bundle = tmp_path / "bundle"
    bundle.mkdir()
    for name in (
        "am.mvn",
        "config.yaml",
        "model_eb.onnx",
        "model_quant.onnx",
        "seg_dict",
        "tokens.json",
    ):
        (bundle / name).write_bytes(b"fixture")
    observed: dict[str, object] = {}

    class FakeModel:
        def __init__(self, model_dir: str, **options: object) -> None:
            root = Path(model_dir)
            observed["options"] = options
            observed["model_target"] = (root / "model_quant.onnx").resolve()
            observed["embedding_target"] = (root / "model_eb_quant.onnx").resolve()

        def __call__(self, samples: np.ndarray, *, hotwords: str):
            observed["samples"] = samples.copy()
            observed["hotwords"] = hotwords
            return [{"preds": "拍嗝结束"}]

    recognize = _load_contextual_recognizer(bundle, model_class=FakeModel)
    assert recognize(PCM) == "拍嗝结束"
    assert observed["options"] == {
        "batch_size": 1,
        "device_id": "-1",
        "intra_op_num_threads": 2,
        "quantize": True,
    }
    assert observed["model_target"] == bundle / "model_quant.onnx"
    assert observed["embedding_target"] == bundle / "model_eb.onnx"
    assert observed["hotwords"] == CONTEXTUAL_HOTWORDS


def test_runner_protocol_is_canonical_and_does_not_persist_pcm(tmp_path: Path) -> None:
    input_path = tmp_path / "input.bin"
    output_path = tmp_path / "output.bin"
    input_path.write_bytes(len(PCM).to_bytes(4, "big") + PCM)
    before = set(tmp_path.iterdir())
    with input_path.open("rb") as input_stream, output_path.open("wb") as output_stream:
        assert (
            run_protocol(
                input_stream,
                output_stream,
                recognizer=lambda _pcm: "小小",
            )
            == 0
        )
    lines = output_path.read_text("utf-8").splitlines()
    assert json.loads(lines[0]) == {"schemaVersion": 1, "state": "ready"}
    assert json.loads(lines[1])["text"] == "小小"
    assert set(tmp_path.iterdir()) == before | {output_path}
