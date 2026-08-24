from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest

from packages.contracts.settings import VoiceCareSettings
from services.voice.artifacts import voice_artifact_spec
from services.voice.silero_runtime import (
    SILERO_PCM_INVALID,
    SILERO_UNAVAILABLE,
    SileroOnnxSegmenter,
)


def _spec():
    return voice_artifact_spec(
        VoiceCareSettings(silero_vad_manifest_sha256="a" * 64),
        "silero-vad-v6.2",
    )


class FakeSession:
    def __init__(self, probabilities: list[object]) -> None:
        self.probabilities = iter(probabilities)
        self.calls: list[dict[str, np.ndarray]] = []

    def get_inputs(self):
        return [
            SimpleNamespace(name="input"),
            SimpleNamespace(name="state"),
            SimpleNamespace(name="sr"),
        ]

    def get_outputs(self):
        return [SimpleNamespace(name="output"), SimpleNamespace(name="stateN")]

    def run(self, output_names, inputs):
        assert output_names == ("output", "stateN")
        self.calls.append(inputs)
        probability = next(self.probabilities)
        next_state = np.asarray(inputs["state"], dtype=np.float32) + 1.0
        return np.asarray([[probability]], dtype=np.float32), next_state


def _segmenter(
    tmp_path: Path, session: FakeSession
) -> tuple[SileroOnnxSegmenter, list[tuple[Path, object, tuple[str, ...]]]]:
    bundle = tmp_path / "validated"
    bundle.mkdir()
    model = bundle / "silero_vad.onnx"
    model.write_bytes(b"synthetic")
    calls: list[tuple[Path, object, tuple[str, ...]]] = []

    def factory(path: Path, options: object, providers: tuple[str, ...]):
        calls.append((path, options, providers))
        return session

    segmenter = SileroOnnxSegmenter(
        _spec(),
        project_root=tmp_path,
        artifact_validator=lambda _artifact, _root: bundle,
        session_factory=factory,
    )
    return segmenter, calls


def test_segmenter_validates_registry_artifact_before_fixed_cpu_session(
    tmp_path: Path,
) -> None:
    session = FakeSession([0.0])
    segmenter, calls = _segmenter(tmp_path, session)

    assert segmenter.segment(b"\0\0" * 512) == ()
    assert len(calls) == 1
    path, options, providers = calls[0]
    assert path == tmp_path / "validated/silero_vad.onnx"
    assert providers == ("CPUExecutionProvider",)
    assert options.intra_op_num_threads == 1
    assert options.inter_op_num_threads == 1


def test_segmenter_returns_one_padded_bounded_span_and_carries_model_state(
    tmp_path: Path,
) -> None:
    probabilities = [0.0] * 20 + [0.9] * 10 + [0.0] * 25
    session = FakeSession(probabilities)
    segmenter, _calls = _segmenter(tmp_path, session)
    pcm = np.arange(55 * 512, dtype=np.int16).tobytes()

    spans = segmenter.segment(pcm)

    assert len(spans) == 1
    assert spans[0].start_sample == 2_240
    assert spans[0].end_sample == 23_360
    assert spans[0].peak_probability == pytest.approx(0.9)
    assert session.calls[0]["input"].shape == (1, 576)
    assert session.calls[0]["input"].dtype == np.float32
    assert session.calls[0]["state"].shape == (2, 1, 128)
    assert session.calls[0]["sr"].shape == ()
    assert int(session.calls[0]["sr"]) == 16_000
    assert np.all(session.calls[1]["state"] == 1.0)


@pytest.mark.parametrize(
    "malformed",
    [float("nan"), float("inf"), -0.1, 1.1, [0.1, 0.2]],
)
def test_segmenter_rejects_malformed_probability_fail_closed(
    tmp_path: Path, malformed: object
) -> None:
    segmenter, _calls = _segmenter(tmp_path, FakeSession([malformed]))

    with pytest.raises(ValueError, match=f"^{SILERO_UNAVAILABLE}$"):
        segmenter.segment(b"\0\0" * 512)


def test_segmenter_rejects_malformed_state_and_invalid_pcm_fail_closed(
    tmp_path: Path,
) -> None:
    class InvalidStateSession(FakeSession):
        def run(self, output_names, inputs):
            probability, _state = super().run(output_names, inputs)
            return probability, np.zeros((1, 1, 128), dtype=np.float32)

    segmenter, _calls = _segmenter(tmp_path, InvalidStateSession([0.9]))
    with pytest.raises(ValueError, match=f"^{SILERO_UNAVAILABLE}$"):
        segmenter.segment(b"\0\0" * 512)
    with pytest.raises(ValueError, match=f"^{SILERO_PCM_INVALID}$"):
        segmenter.segment(b"x")


def test_segmenter_caps_padded_utterance_at_eight_seconds(tmp_path: Path) -> None:
    frame_count = 300
    segmenter, _calls = _segmenter(tmp_path, FakeSession([0.9] * frame_count))

    spans = segmenter.segment(b"\0\0" * (512 * frame_count))

    assert len(spans) == 1
    assert spans[0].end_sample - spans[0].start_sample == 128_000
