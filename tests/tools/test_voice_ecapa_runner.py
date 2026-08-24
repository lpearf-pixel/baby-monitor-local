from __future__ import annotations

import io
import json
import struct
import sys
import types
from pathlib import Path

import pytest

from tools.voice_ecapa_runner import (
    _load_speechbrain_encoder,
    _normalize_model_embedding,
    run_protocol,
)


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


def test_speechbrain_loader_overrides_the_public_remote_pretrained_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[dict[str, object]] = []

    class EncoderClassifier:
        @classmethod
        def from_hparams(cls, **kwargs: object) -> object:
            calls.append(kwargs)
            return object()

    fake_torch = types.ModuleType("torch")
    fake_torch.set_num_threads = lambda _count: None  # type: ignore[attr-defined]
    fake_speechbrain = types.ModuleType("speechbrain")
    fake_inference = types.ModuleType("speechbrain.inference")
    fake_speaker = types.ModuleType("speechbrain.inference.speaker")
    fake_speaker.EncoderClassifier = EncoderClassifier  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "torch", fake_torch)
    monkeypatch.setitem(sys.modules, "speechbrain", fake_speechbrain)
    monkeypatch.setitem(sys.modules, "speechbrain.inference", fake_inference)
    monkeypatch.setitem(sys.modules, "speechbrain.inference.speaker", fake_speaker)
    bundle = tmp_path / "bundle"
    bundle.mkdir()

    _load_speechbrain_encoder(bundle)

    assert len(calls) == 1
    call = calls[0]
    assert call["source"] == str(bundle)
    assert call["run_opts"] == {"device": "cpu"}
    assert call["overrides"] == {"pretrained_path": str(bundle)}
    savedir = Path(str(call["savedir"]))
    assert savedir != bundle
    assert not savedir.exists()


def test_model_embedding_is_explicitly_l2_normalized() -> None:
    raw = tuple([3.0, 4.0] + [0.0] * 190)

    normalized = _normalize_model_embedding(raw)

    assert normalized == tuple([0.6, 0.8] + [0.0] * 190)
    with pytest.raises(ValueError, match="^VOICE_ECAPA_PROTOCOL_INVALID$"):
        _normalize_model_embedding(tuple([0.0] * 192))
