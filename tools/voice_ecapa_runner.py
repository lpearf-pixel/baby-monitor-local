from __future__ import annotations

import argparse
import json
import math
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
MIN_PCM_BYTES = int(0.8 * SAMPLE_RATE_HZ * SAMPLE_WIDTH_BYTES)
MAX_PCM_BYTES = 8 * SAMPLE_RATE_HZ * SAMPLE_WIDTH_BYTES
EMBEDDING_DIMENSIONS = 192
Encoder = Callable[[bytes], tuple[float, ...]]


def run_protocol(
    input_stream: BinaryIO, output_stream: BinaryIO, *, encoder: Encoder
) -> int:
    """Serve the fixed framed-PCM protocol without writing audio to disk."""

    try:
        _write_json(output_stream, {"schemaVersion": 1, "state": "ready"})
        while True:
            header = _read_exact(input_stream, 4, allow_eof=True)
            if header is None:
                return 0
            length = struct.unpack(">I", header)[0]
            if (
                length < MIN_PCM_BYTES
                or length > MAX_PCM_BYTES
                or length % SAMPLE_WIDTH_BYTES
            ):
                return 1
            pcm = _read_exact(input_stream, length, allow_eof=False)
            if pcm is None:
                return 1
            started = time.monotonic_ns()
            embedding = _validated_embedding(encoder(pcm))
            latency_ms = max(0, (time.monotonic_ns() - started) // 1_000_000)
            _write_json(
                output_stream,
                {
                    "embedding": list(embedding),
                    "latencyMs": latency_ms,
                    "schemaVersion": 1,
                },
            )
    except Exception:
        return 1


def _read_exact(
    stream: BinaryIO, size: int, *, allow_eof: bool
) -> bytes | None:
    chunks = bytearray()
    while len(chunks) < size:
        chunk = stream.read(size - len(chunks))
        if not chunk:
            if allow_eof and not chunks:
                return None
            raise ValueError("VOICE_ECAPA_PROTOCOL_INVALID")
        chunks.extend(chunk)
    return bytes(chunks)


def _validated_embedding(raw: object) -> tuple[float, ...]:
    if type(raw) is not tuple or len(raw) != EMBEDDING_DIMENSIONS:
        raise ValueError("VOICE_ECAPA_PROTOCOL_INVALID")
    if any(type(value) not in {int, float} or not math.isfinite(value) for value in raw):
        raise ValueError("VOICE_ECAPA_PROTOCOL_INVALID")
    values = tuple(float(value) for value in raw)
    norm = math.sqrt(sum(value * value for value in values))
    if not math.isfinite(norm) or not 0.999 <= norm <= 1.001:
        raise ValueError("VOICE_ECAPA_PROTOCOL_INVALID")
    return values


def _write_json(stream: BinaryIO, value: object) -> None:
    payload = (json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n").encode(
        "ascii"
    )
    stream.write(payload)
    stream.flush()


def _load_speechbrain_encoder(bundle: Path) -> Encoder:
    import numpy as np
    import torch
    from speechbrain.inference.speaker import EncoderClassifier

    torch.set_num_threads(max(1, min(4, os.cpu_count() or 1)))
    with tempfile.TemporaryDirectory(prefix="voice-ecapa-runtime-") as temporary:
        classifier = EncoderClassifier.from_hparams(
            source=str(bundle),
            savedir=temporary,
            run_opts={"device": "cpu"},
            overrides={"pretrained_path": str(bundle)},
        )

    def encode(pcm: bytes) -> tuple[float, ...]:
        samples = np.frombuffer(pcm, dtype="<i2").astype(np.float32) / 32768.0
        waveform = torch.from_numpy(samples).unsqueeze(0)
        with torch.inference_mode():
            encoded = classifier.encode_batch(waveform, normalize=True)
        flattened = encoded.detach().cpu().reshape(-1).tolist()
        return _normalize_model_embedding(tuple(float(value) for value in flattened))

    return encode


def _normalize_model_embedding(raw: tuple[float, ...]) -> tuple[float, ...]:
    if len(raw) != EMBEDDING_DIMENSIONS or any(
        not math.isfinite(value) for value in raw
    ):
        raise ValueError("VOICE_ECAPA_PROTOCOL_INVALID")
    norm = math.sqrt(sum(value * value for value in raw))
    if not math.isfinite(norm) or norm <= 0.0:
        raise ValueError("VOICE_ECAPA_PROTOCOL_INVALID")
    return tuple(value / norm for value in raw)


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the offline local ECAPA adapter")
    parser.add_argument("--artifact", type=Path, required=True)
    parser.add_argument("--manifest-sha256", required=True)
    parser.add_argument("--expected-prefix", type=Path, required=True)
    arguments = parser.parse_args()
    try:
        if (
            Path(sys.prefix).resolve(strict=True)
            != arguments.expected_prefix.resolve(strict=True)
        ):
            return 1
        os.environ["HF_HUB_OFFLINE"] = "1"
        os.environ["TRANSFORMERS_OFFLINE"] = "1"
        os.environ["NO_PROXY"] = "*"
        from packages.contracts.settings import VoiceCareSettings
        from services.voice.artifacts import (
            validate_voice_artifact_bundle,
            voice_artifact_spec,
        )

        spec = voice_artifact_spec(
            VoiceCareSettings(
                enabled=False,
                speechbrain_ecapa_manifest_sha256=arguments.manifest_sha256,
            ),
            "speechbrain-ecapa-voxceleb",
        )
        bundle = validate_voice_artifact_bundle(spec, arguments.artifact)
        encoder = _load_speechbrain_encoder(bundle)
        return run_protocol(sys.stdin.buffer, sys.stdout.buffer, encoder=encoder)
    except Exception:
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
