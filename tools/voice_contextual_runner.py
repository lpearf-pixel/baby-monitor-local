from __future__ import annotations

import argparse
import hashlib
import json
import os
import struct
import sys
import tempfile
import time
from collections.abc import Callable
from pathlib import Path
from typing import BinaryIO


SAMPLE_RATE_HZ = 16_000
SAMPLE_WIDTH_BYTES = 2
MAX_PCM_BYTES = 8 * SAMPLE_RATE_HZ * SAMPLE_WIDTH_BYTES
CONTEXTUAL_HOTWORDS = (
    "小小 开始喂奶 喂奶结束 开始换尿布 换好尿布了 开始拍嗝 拍嗝结束"
)
CONTEXTUAL_HOTWORDS_SHA256 = hashlib.sha256(
    CONTEXTUAL_HOTWORDS.encode("utf-8")
).hexdigest()
_ARTIFACT_ID = "funasr-contextual-paraformer-zh-int8"
_BUNDLE_DIGEST = "7a77621ef509ad4074cb357425f0c449fbb5bc60a4dd94baa1534cbbb8d5b9aa"
_FILES = {
    "am.mvn": (11_203, "29b3c740a2c0cfc6b308126d31d7f265fa2be74f3bb095cd2f143ea970896ae5"),
    "config.yaml": (2_532, "1d9057edeaba9e131cb98f26011606497cf3af187d8943525ddb5ee36c836b1b"),
    "model_eb.onnx": (25_618_359, "d31446a5af664291a2922cca253a4200a523f347d6fc3cb1bff356bf60a116b6"),
    "model_quant.onnx": (871_251_660, "f404e6eb532b54fd95761e2b4be4ed1998e8cff3cb3b930a9bee1f2d556e5035"),
    "seg_dict": (8_287_834, "59a2ef803a3f1648ad03a2e1480db1c1ee0c0d7dc4ef4dbd16cea33944329022"),
    "tokens.json": (93_676, "2b20c2b12572d682afff84ce1c8d560f67b8b32a4c1f21567411d141ed352127"),
}
Recognizer = Callable[[bytes], str]


def run_protocol(
    input_stream: BinaryIO, output_stream: BinaryIO, *, recognizer: Recognizer
) -> int:
    try:
        _write_json(output_stream, {"schemaVersion": 1, "state": "ready"})
        while True:
            header = _read_exact(input_stream, 4, allow_eof=True)
            if header is None:
                return 0
            size = struct.unpack(">I", header)[0]
            if not size or size > MAX_PCM_BYTES or size % SAMPLE_WIDTH_BYTES:
                return 1
            pcm = _read_exact(input_stream, size, allow_eof=False)
            if pcm is None:
                return 1
            started = time.monotonic_ns()
            text = recognizer(pcm)
            latency_ms = max(0, (time.monotonic_ns() - started) // 1_000_000)
            if (
                type(text) is not str
                or len(text) > 4_096
                or any(ord(character) < 32 for character in text)
            ):
                return 1
            _write_json(
                output_stream,
                {
                    "language": "zh",
                    "latencyMs": latency_ms,
                    "schemaVersion": 1,
                    "text": text,
                },
            )
    except Exception:
        return 1


def _load_contextual_recognizer(
    bundle: Path, *, model_class: object | None = None
) -> Recognizer:
    import numpy as np

    if model_class is None:
        from funasr_onnx import ContextualParaformer

        model_class = ContextualParaformer
    with tempfile.TemporaryDirectory(prefix="voice-contextual-alias-") as name:
        alias = Path(name)
        alias.chmod(0o700)
        aliases = {
            "am.mvn": "am.mvn",
            "config.yaml": "config.yaml",
            "model_eb_quant.onnx": "model_eb.onnx",
            "model_quant.onnx": "model_quant.onnx",
            "seg_dict": "seg_dict",
            "tokens.json": "tokens.json",
        }
        for target_name, source_name in aliases.items():
            (alias / target_name).symlink_to((bundle / source_name).resolve(strict=True))
        model = model_class(  # type: ignore[operator]
            str(alias),
            batch_size=1,
            device_id="-1",
            intra_op_num_threads=2,
            quantize=True,
        )

    def recognize(pcm: bytes) -> str:
        samples = np.frombuffer(pcm, dtype="<i2").astype(np.float32) / 32768.0
        result = model(samples, hotwords=CONTEXTUAL_HOTWORDS)
        if (
            not isinstance(result, list)
            or len(result) != 1
            or not isinstance(result[0], dict)
            or type(result[0].get("preds")) is not str
        ):
            raise ValueError("VOICE_CONTEXTUAL_PROTOCOL_INVALID")
        return result[0]["preds"]

    return recognize


def _validate_bundle(project_root: Path, artifact: Path, manifest_sha256: str) -> Path:
    root = project_root.resolve(strict=True)
    expected = (
        root
        / "runtime/models/voice-contextual"
        / _ARTIFACT_ID
        / _BUNDLE_DIGEST
    )
    checked = artifact.resolve(strict=True)
    if (
        manifest_sha256 != _BUNDLE_DIGEST
        or checked != expected
        or artifact.is_symlink()
        or set(item.name for item in checked.iterdir())
        != {*_FILES, "manifest.json"}
    ):
        raise ValueError("VOICE_CONTEXTUAL_ARTIFACT_INVALID")
    manifest = (checked / "manifest.json").read_bytes()
    if hashlib.sha256(manifest).hexdigest() != _BUNDLE_DIGEST:
        raise ValueError("VOICE_CONTEXTUAL_ARTIFACT_INVALID")
    for name, (expected_size, expected_digest) in _FILES.items():
        path = checked / name
        if path.is_symlink() or path.stat().st_size != expected_size:
            raise ValueError("VOICE_CONTEXTUAL_ARTIFACT_INVALID")
        digest = hashlib.sha256()
        with path.open("rb") as stream:
            for chunk in iter(lambda: stream.read(1024 * 1024), b""):
                digest.update(chunk)
        if digest.hexdigest() != expected_digest:
            raise ValueError("VOICE_CONTEXTUAL_ARTIFACT_INVALID")
    return checked


def _read_exact(stream: BinaryIO, size: int, *, allow_eof: bool) -> bytes | None:
    payload = bytearray()
    while len(payload) < size:
        chunk = stream.read(size - len(payload))
        if not chunk:
            if allow_eof and not payload:
                return None
            raise ValueError("VOICE_CONTEXTUAL_PROTOCOL_INVALID")
        payload.extend(chunk)
    return bytes(payload)


def _write_json(stream: BinaryIO, value: object) -> None:
    payload = (
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        + "\n"
    ).encode("utf-8")
    stream.write(payload)
    stream.flush()


def main() -> int:
    parser = argparse.ArgumentParser(description="Run fixed contextual ASR candidate")
    parser.add_argument("--project-root", type=Path, required=True)
    parser.add_argument("--artifact", type=Path, required=True)
    parser.add_argument("--manifest-sha256", required=True)
    parser.add_argument("--expected-prefix", type=Path, required=True)
    arguments = parser.parse_args()
    try:
        if Path(sys.prefix).resolve(strict=True) != arguments.expected_prefix.resolve(
            strict=True
        ):
            return 1
        os.environ["NO_PROXY"] = "*"
        bundle = _validate_bundle(
            arguments.project_root,
            arguments.artifact,
            arguments.manifest_sha256,
        )
        recognizer = _load_contextual_recognizer(bundle)
        return run_protocol(sys.stdin.buffer, sys.stdout.buffer, recognizer=recognizer)
    except Exception:
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
