from __future__ import annotations

import importlib
import sys
import threading
import time
from collections.abc import Callable, Iterable, MutableMapping
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

import numpy as np

from services.voice.artifacts import VoiceArtifactSpec, validate_voice_artifact


SAMPLE_RATE_HZ = 16_000
SAMPLE_WIDTH_BYTES = 2
MAX_UTTERANCE_SECONDS = 8
UNAVAILABLE_REASON = "voice_model_unavailable"
INVALID_PCM_REASON = "voice_pcm_invalid"
_WHISPER_ARTIFACT_IDS = frozenset(
    {"openai-whisper-base", "openai-whisper-small"}
)
_VOICE_HOTWORDS = "喂奶 开始 喂完 继续 结束 爸爸 妈妈"
_WHISPER_IMPORT_LOCK = threading.Lock()


@dataclass(frozen=True)
class AsrResult:
    text: str
    language: str
    duration_ms: int


class _Segment(Protocol):
    text: str


class _Info(Protocol):
    language: str


class _Runner(Protocol):
    def transcribe(
        self, samples: np.ndarray, **options: object
    ) -> tuple[Iterable[_Segment], _Info]: ...


RunnerFactory = Callable[..., _Runner]


class AsrEngine:
    """Closed adapter for one manifest-validated local Whisper bundle."""

    def __init__(
        self,
        artifact: VoiceArtifactSpec,
        *,
        project_root: Path,
        runner_factory: RunnerFactory | None = None,
        monotonic_ns: Callable[[], int] = time.monotonic_ns,
    ) -> None:
        try:
            if artifact.artifact_id not in _WHISPER_ARTIFACT_IDS:
                raise ValueError(UNAVAILABLE_REASON)
            bundle = validate_voice_artifact(artifact, project_root)
            if not bundle.is_absolute():
                raise ValueError(UNAVAILABLE_REASON)
            factory = runner_factory or _faster_whisper_runner
            self._runner = factory(
                model_path=bundle,
                device="cpu",
                compute_type="int8",
                local_files_only=True,
            )
        except Exception:
            raise ValueError(UNAVAILABLE_REASON) from None
        self._monotonic_ns = monotonic_ns

    def transcribe(self, pcm: bytes) -> AsrResult:
        if (
            type(pcm) is not bytes
            or not pcm
            or len(pcm) % SAMPLE_WIDTH_BYTES != 0
            or len(pcm)
            > SAMPLE_RATE_HZ
            * SAMPLE_WIDTH_BYTES
            * MAX_UTTERANCE_SECONDS
        ):
            raise ValueError(INVALID_PCM_REASON)
        samples = np.frombuffer(pcm, dtype="<i2").astype(np.float32)
        samples /= 32768.0
        started_ns = self._monotonic_ns()
        try:
            segments, info = self._runner.transcribe(
                samples,
                language="zh",
                task="transcribe",
                beam_size=5,
                temperature=0.0,
                condition_on_previous_text=False,
                vad_filter=False,
                without_timestamps=True,
                hotwords=_VOICE_HOTWORDS,
            )
            parts: list[str] = []
            for segment in segments:
                if not isinstance(segment.text, str):
                    raise ValueError(UNAVAILABLE_REASON)
                parts.append(segment.text)
            if info.language != "zh":
                raise ValueError(UNAVAILABLE_REASON)
            finished_ns = self._monotonic_ns()
            duration_ms = max(0, (finished_ns - started_ns) // 1_000_000)
        except Exception:
            raise ValueError(UNAVAILABLE_REASON) from None
        return AsrResult(text="".join(parts), language="zh", duration_ms=duration_ms)


def _faster_whisper_runner(
    *, model_path: Path, device: str, compute_type: str, local_files_only: bool
) -> _Runner:
    WhisperModel = _load_whisper_model_class()

    return WhisperModel(
        str(model_path),
        device=device,
        compute_type=compute_type,
        local_files_only=local_files_only,
    )


def _load_whisper_model_class(
    *,
    importer: Callable[[str], object] = importlib.import_module,
    modules: MutableMapping[str, object] = sys.modules,
    active_count: Callable[[], int] = threading.active_count,
) -> RunnerFactory:
    """Import runtime ASR without loading optional training/conversion Torch."""

    with _WHISPER_IMPORT_LOCK:
        if active_count() != 1 or "torch" in modules:
            raise ValueError(UNAVAILABLE_REASON)
        modules["torch"] = None
        try:
            module = importer("faster_whisper")
            model_class = getattr(module, "WhisperModel")
            if not callable(model_class):
                raise ValueError(UNAVAILABLE_REASON)
        except Exception:
            raise ValueError(UNAVAILABLE_REASON) from None
        finally:
            modules.pop("torch", None)
    return model_class
