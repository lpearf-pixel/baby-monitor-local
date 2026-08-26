from __future__ import annotations

import io
import json
import struct
import types
from pathlib import Path

import numpy as np
import pytest

from tools.voice_paraformer_runner import (
    _load_paraformer_recognizer,
    _validate_paraformer_bundle,
    _verified_bundle_snapshot,
    run_protocol,
)


PCM = b"\x01\x00" * (16_000 * 2)


def _frame(pcm: bytes) -> bytes:
    return struct.pack(">I", len(pcm)) + pcm


def test_runner_processes_two_in_memory_requests_with_canonical_utf8() -> None:
    input_stream = io.BytesIO(_frame(PCM) + _frame(PCM))
    output_stream = io.BytesIO()
    calls: list[bytes] = []

    def recognizer(pcm: bytes) -> str:
        calls.append(pcm)
        return "小小我是爸爸"

    assert run_protocol(input_stream, output_stream, recognizer=recognizer) == 0
    lines = output_stream.getvalue().splitlines()
    assert json.loads(lines[0]) == {"schemaVersion": 1, "state": "ready"}
    assert len(lines) == 3
    for line in lines[1:]:
        result = json.loads(line)
        assert result["language"] == "zh"
        assert result["text"] == "小小我是爸爸"
        assert set(result) == {"language", "latencyMs", "schemaVersion", "text"}
        assert b"\\u5c0f" not in line
    assert calls == [PCM, PCM]


def test_runner_keeps_serving_after_a_bounded_empty_no_match() -> None:
    input_stream = io.BytesIO(_frame(PCM) + _frame(PCM))
    output_stream = io.BytesIO()
    results = iter(("", "小小"))

    assert run_protocol(
        input_stream, output_stream, recognizer=lambda _pcm: next(results)
    ) == 0

    lines = [json.loads(line) for line in output_stream.getvalue().splitlines()]
    assert lines[1]["text"] == ""
    assert lines[2]["text"] == "小小"


def test_runner_fails_closed_on_malformed_pcm_or_invalid_text() -> None:
    for payload, value in (
        (struct.pack(">I", 1), "x"),
        (_frame(b""), "x"),
        (_frame(b"\x00\x00" * (16_000 * 8 + 1)), "x"),
    ):
        output_stream = io.BytesIO()
        assert run_protocol(
            io.BytesIO(payload), output_stream, recognizer=lambda _pcm, value=value: value
        ) == 1
        assert output_stream.getvalue().splitlines() == [
            b'{"schemaVersion":1,"state":"ready"}'
        ]


def test_loader_uses_only_fixed_greedy_paraformer_configuration(tmp_path: Path) -> None:
    bundle = tmp_path / "bundle"
    bundle.mkdir()
    (bundle / "model.int8.onnx").write_bytes(b"model")
    (bundle / "tokens.txt").write_text("<blank> 0\n", encoding="utf-8")
    created: list[dict[str, object]] = []
    streams: list[object] = []

    class Stream:
        def __init__(self) -> None:
            self.result = types.SimpleNamespace(text="小小我是爸爸")
            self.accepted: tuple[int, np.ndarray] | None = None

        def accept_waveform(self, sample_rate: int, samples: np.ndarray) -> None:
            self.accepted = (sample_rate, samples)

    class OfflineRecognizer:
        @classmethod
        def from_paraformer(cls, **kwargs: object):
            created.append(kwargs)
            return cls()

        def create_stream(self) -> Stream:
            stream = Stream()
            streams.append(stream)
            return stream

        def decode_stream(self, _stream: Stream) -> None:
            return None

    runtime = types.SimpleNamespace(OfflineRecognizer=OfflineRecognizer)
    recognize = _load_paraformer_recognizer(bundle, runtime_module=runtime)

    assert recognize(PCM) == "小小我是爸爸"
    assert created == [
        {
            "debug": False,
            "decoding_method": "greedy_search",
            "feature_dim": 80,
            "num_threads": 2,
            "paraformer": str(bundle / "model.int8.onnx"),
            "sample_rate": 16_000,
            "tokens": str(bundle / "tokens.txt"),
        }
    ]
    assert len(streams) == 1
    stream = streams[0]
    assert isinstance(stream, Stream)
    assert stream.accepted is not None
    sample_rate, samples = stream.accepted
    assert sample_rate == 16_000
    assert samples.dtype == np.float32
    assert samples.shape == (32_000,)


def test_runner_validates_bundle_without_project_runtime_dependencies(
    tmp_path: Path,
) -> None:
    import hashlib

    bundle = tmp_path / "bundle"
    bundle.mkdir()
    files = {"model.int8.onnx": b"model", "tokens.txt": b"tokens"}
    for name, payload in files.items():
        (bundle / name).write_bytes(payload)
    manifest = {
        "artifact_id": "sherpa-onnx-paraformer-zh-2023-09-14",
        "files": {
            name: hashlib.sha256(payload).hexdigest()
            for name, payload in files.items()
        },
        "source_manifest_sha256": "a" * 64,
        "source_revision": "def027084691107096b5ebba69785756d63de6c5",
        "spdx_license": "Apache-2.0",
    }
    encoded = (json.dumps(manifest, sort_keys=True, separators=(",", ":")) + "\n").encode(
        "ascii"
    )
    (bundle / "manifest.json").write_bytes(encoded)

    assert _validate_paraformer_bundle(
        bundle, hashlib.sha256(encoded).hexdigest()
    ) == bundle.resolve()

    (bundle / "tokens.txt").write_bytes(b"changed")
    try:
        _validate_paraformer_bundle(bundle, hashlib.sha256(encoded).hexdigest())
    except ValueError as error:
        assert str(error) == "VOICE_PARAFORMER_BUNDLE_INVALID"
    else:
        raise AssertionError("modified bundle must fail closed")


def test_runner_snapshot_rejects_model_replacement_between_manifest_and_open(
    tmp_path: Path, monkeypatch
) -> None:
    import hashlib
    import os

    bundle = tmp_path / "bundle"
    bundle.mkdir()
    files = {"model.int8.onnx": b"model", "tokens.txt": b"tokens"}
    for name, payload in files.items():
        (bundle / name).write_bytes(payload)
    manifest = {
        "artifact_id": "sherpa-onnx-paraformer-zh-2023-09-14",
        "files": {
            name: hashlib.sha256(payload).hexdigest()
            for name, payload in files.items()
        },
        "source_manifest_sha256": "a" * 64,
        "source_revision": "def027084691107096b5ebba69785756d63de6c5",
        "spdx_license": "Apache-2.0",
    }
    encoded = (json.dumps(manifest, sort_keys=True, separators=(",", ":")) + "\n").encode(
        "ascii"
    )
    (bundle / "manifest.json").write_bytes(encoded)
    actual_open = os.open
    replaced = False

    def racing_open(path, flags, mode=0o777, *, dir_fd=None):
        nonlocal replaced
        if path == "model.int8.onnx" and dir_fd is not None and not replaced:
            replaced = True
            (bundle / "model.int8.onnx").rename(bundle / "old-model")
            (bundle / "model.int8.onnx").write_bytes(b"replacement")
        return actual_open(path, flags, mode, dir_fd=dir_fd)

    monkeypatch.setattr("tools.voice_paraformer_runner.os.open", racing_open)

    with pytest.raises(ValueError, match="^VOICE_PARAFORMER_BUNDLE_INVALID$"):
        with _verified_bundle_snapshot(
            bundle, hashlib.sha256(encoded).hexdigest()
        ):
            pass
