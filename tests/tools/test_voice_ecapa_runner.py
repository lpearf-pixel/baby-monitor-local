from __future__ import annotations

import io
import json
import struct

import pytest

from tools.voice_ecapa_runner import run_protocol


PCM = b"\x01\x00" * (16_000 * 2)
EMBEDDING = tuple([1.0] + [0.0] * 191)


def _frame(pcm: bytes) -> bytes:
    return struct.pack(">I", len(pcm)) + pcm


def test_runner_processes_two_framed_requests_without_persisting_pcm() -> None:
    input_stream = io.BytesIO(_frame(PCM) + _frame(PCM))
    output_stream = io.BytesIO()
    calls: list[bytes] = []

    def encoder(pcm: bytes) -> tuple[float, ...]:
        calls.append(pcm)
        return EMBEDDING

    assert run_protocol(input_stream, output_stream, encoder=encoder) == 0

    lines = output_stream.getvalue().splitlines()
    assert json.loads(lines[0]) == {"schemaVersion": 1, "state": "ready"}
    assert len(lines) == 3
    for line in lines[1:]:
        result = json.loads(line)
        assert set(result) == {"embedding", "latencyMs", "schemaVersion"}
        assert result["schemaVersion"] == 1
        assert result["embedding"] == list(EMBEDDING)
        assert isinstance(result["latencyMs"], int)
    assert calls == [PCM, PCM]


@pytest.mark.parametrize(
    "payload",
    (
        struct.pack(">I", 100),
        _frame(b"\x00\x00" * 100),
        _frame(b"\x00\x00" * (16_000 * 9)),
        _frame(b"\x00" * (16_000 * 2 + 1)),
    ),
)
def test_runner_fails_closed_on_malformed_or_out_of_bounds_pcm(payload: bytes) -> None:
    output_stream = io.BytesIO()

    assert run_protocol(
        io.BytesIO(payload), output_stream, encoder=lambda _pcm: EMBEDDING
    ) == 1
    assert output_stream.getvalue().splitlines() == [
        b'{"schemaVersion":1,"state":"ready"}'
    ]


@pytest.mark.parametrize(
    "embedding",
    (
        tuple([1.0] + [0.0] * 190),
        tuple([2.0] + [0.0] * 191),
        tuple([float("nan")] + [0.0] * 191),
    ),
)
def test_runner_fails_closed_on_invalid_encoder_output(
    embedding: tuple[float, ...],
) -> None:
    output_stream = io.BytesIO()

    assert run_protocol(
        io.BytesIO(_frame(PCM)),
        output_stream,
        encoder=lambda _pcm: embedding,
    ) == 1
    assert len(output_stream.getvalue().splitlines()) == 1
