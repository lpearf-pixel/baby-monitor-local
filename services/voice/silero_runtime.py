"""Manifest-validated Silero VAD runtime for bounded Voice Care utterances."""

from __future__ import annotations

import math
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

import numpy as np

from services.voice.artifacts import VoiceArtifactSpec, validate_voice_artifact


SILERO_UNAVAILABLE = "voice_model_unavailable"
SILERO_PCM_INVALID = "voice_pcm_invalid"
SAMPLE_RATE_HZ = 16_000
_SAMPLE_WIDTH_BYTES = 2
_CHUNK_SAMPLES = 512
_CONTEXT_SAMPLES = 64
_SPEECH_THRESHOLD = 0.50
_SILENCE_THRESHOLD = 0.35
_MIN_SPEECH_SAMPLES = 4_000
_TERMINAL_SILENCE_SAMPLES = 12_800
_SPEECH_PAD_SAMPLES = 8_000
_MAX_UTTERANCE_SAMPLES = 128_000
_MAX_CAPTURE_SAMPLES = 480_000
_STATE_SHAPE = (2, 1, 128)


@dataclass(frozen=True)
class SpeechSpan:
    start_sample: int
    end_sample: int
    peak_probability: float


@dataclass(frozen=True)
class SileroAnalysis:
    spans: tuple[SpeechSpan, ...]
    peak_probability: float


@dataclass(frozen=True)
class _SessionPolicy:
    intra_op_num_threads: int = 1
    inter_op_num_threads: int = 1


class _Session(Protocol):
    def get_inputs(self) -> list[Any]: ...

    def get_outputs(self) -> list[Any]: ...

    def run(
        self, output_names: tuple[str, str], inputs: dict[str, np.ndarray]
    ) -> tuple[object, object]: ...


SessionFactory = Callable[[Path, object, tuple[str, ...]], _Session]
ArtifactValidator = Callable[[VoiceArtifactSpec, Path], Path]


class SileroOnnxSegmenter:
    """Segment one bounded 16 kHz mono stream with the pinned Silero model."""

    def __init__(
        self,
        artifact: VoiceArtifactSpec,
        *,
        project_root: Path,
        artifact_validator: ArtifactValidator = validate_voice_artifact,
        session_factory: SessionFactory | None = None,
    ) -> None:
        try:
            if (
                artifact.artifact_id != "silero-vad-v6.2"
                or artifact.required_files != ("silero_vad.onnx",)
            ):
                raise ValueError
            bundle = artifact_validator(artifact, project_root)
            model = bundle / "silero_vad.onnx"
            if not bundle.is_absolute() or model.is_symlink() or not model.is_file():
                raise ValueError
            factory = session_factory or _onnx_session
            self._session = factory(
                model,
                _SessionPolicy(),
                ("CPUExecutionProvider",),
            )
            if [item.name for item in self._session.get_inputs()] != [
                "input",
                "state",
                "sr",
            ] or [item.name for item in self._session.get_outputs()] != [
                "output",
                "stateN",
            ]:
                raise ValueError
        except Exception:
            raise ValueError(SILERO_UNAVAILABLE) from None

    def segment(self, pcm: bytes) -> tuple[SpeechSpan, ...]:
        return self.analyze(pcm).spans

    def analyze(self, pcm: bytes) -> SileroAnalysis:
        if (
            type(pcm) is not bytes
            or not pcm
            or len(pcm) % _SAMPLE_WIDTH_BYTES
            or len(pcm) > _MAX_CAPTURE_SAMPLES * _SAMPLE_WIDTH_BYTES
        ):
            raise ValueError(SILERO_PCM_INVALID)
        samples = np.frombuffer(pcm, dtype="<i2").astype(np.float32)
        samples /= 32_768.0
        try:
            probabilities = self._probabilities(samples)
            return SileroAnalysis(
                _speech_spans(probabilities, samples.size),
                max(probabilities),
            )
        except Exception:
            raise ValueError(SILERO_UNAVAILABLE) from None

    def _probabilities(self, samples: np.ndarray) -> tuple[float, ...]:
        state = np.zeros(_STATE_SHAPE, dtype=np.float32)
        context = np.zeros((1, _CONTEXT_SAMPLES), dtype=np.float32)
        probabilities: list[float] = []
        for offset in range(0, samples.size, _CHUNK_SAMPLES):
            chunk = samples[offset : offset + _CHUNK_SAMPLES]
            if chunk.size < _CHUNK_SAMPLES:
                chunk = np.pad(chunk, (0, _CHUNK_SAMPLES - chunk.size))
            chunk = chunk.reshape(1, _CHUNK_SAMPLES).astype(np.float32, copy=False)
            model_input = np.concatenate((context, chunk), axis=1)
            raw_probability, raw_state = self._session.run(
                ("output", "stateN"),
                {
                    "input": model_input,
                    "state": state,
                    "sr": np.asarray(SAMPLE_RATE_HZ, dtype=np.int64),
                },
            )
            probability_values = np.asarray(raw_probability, dtype=np.float32)
            next_state = np.asarray(raw_state, dtype=np.float32)
            if (
                probability_values.size != 1
                or next_state.shape != _STATE_SHAPE
                or not np.isfinite(next_state).all()
            ):
                raise ValueError
            probability = float(probability_values.reshape(-1)[0])
            if not math.isfinite(probability) or not 0.0 <= probability <= 1.0:
                raise ValueError
            probabilities.append(probability)
            state = next_state
            context = chunk[:, -_CONTEXT_SAMPLES:].copy()
        return tuple(probabilities)


def _speech_spans(
    probabilities: tuple[float, ...], total_samples: int
) -> tuple[SpeechSpan, ...]:
    spans: list[SpeechSpan] = []
    speech_start: int | None = None
    last_speech_end: int | None = None
    silence_start: int | None = None
    peak = 0.0
    for index, probability in enumerate(probabilities):
        chunk_start = index * _CHUNK_SAMPLES
        chunk_end = min(total_samples, chunk_start + _CHUNK_SAMPLES)
        if speech_start is None:
            if probability >= _SPEECH_THRESHOLD:
                speech_start = chunk_start
                last_speech_end = chunk_end
                silence_start = None
                peak = probability
            continue
        peak = max(peak, probability)
        if probability >= _SPEECH_THRESHOLD:
            last_speech_end = chunk_end
            silence_start = None
        elif probability < _SILENCE_THRESHOLD:
            if silence_start is None:
                silence_start = chunk_start
            if chunk_end - silence_start >= _TERMINAL_SILENCE_SAMPLES:
                _append_span(spans, speech_start, last_speech_end, peak, total_samples)
                speech_start = None
                last_speech_end = None
                silence_start = None
                peak = 0.0
                continue
        if chunk_end - speech_start >= _MAX_UTTERANCE_SAMPLES:
            _append_span(spans, speech_start, last_speech_end, peak, total_samples)
            speech_start = None
            break
    if speech_start is not None:
        _append_span(spans, speech_start, last_speech_end, peak, total_samples)
    return tuple(spans)


def _append_span(
    spans: list[SpeechSpan],
    speech_start: int,
    last_speech_end: int | None,
    peak: float,
    total_samples: int,
) -> None:
    if last_speech_end is None or last_speech_end - speech_start < _MIN_SPEECH_SAMPLES:
        return
    padded_start = max(0, speech_start - _SPEECH_PAD_SAMPLES)
    padded_end = min(total_samples, last_speech_end + _SPEECH_PAD_SAMPLES)
    padded_end = min(padded_end, padded_start + _MAX_UTTERANCE_SAMPLES)
    spans.append(SpeechSpan(padded_start, padded_end, peak))


def _onnx_session(
    model: Path, policy: object, providers: tuple[str, ...]
) -> _Session:
    import onnxruntime

    if not isinstance(policy, _SessionPolicy):
        raise ValueError(SILERO_UNAVAILABLE)
    options = onnxruntime.SessionOptions()
    options.intra_op_num_threads = policy.intra_op_num_threads
    options.inter_op_num_threads = policy.inter_op_num_threads
    return onnxruntime.InferenceSession(
        str(model),
        sess_options=options,
        providers=list(providers),
    )


__all__ = [
    "SILERO_PCM_INVALID",
    "SILERO_UNAVAILABLE",
    "SileroAnalysis",
    "SpeechSpan",
    "SileroOnnxSegmenter",
]
