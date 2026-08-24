"""Private fixed-phrase ASR calibration capture and aggregate evaluation."""

from __future__ import annotations

import math
import time
import unicodedata
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Literal, Protocol

from packages.contracts.settings import AudioSettings
from services.audio.source import DecoderRead, FixedAudioDecoder
from services.voice.asr import AsrResult
from services.voice.asr_corpus import PRIVATE_ASR_PROMPTS
from services.voice.silero_runtime import SAMPLE_RATE_HZ, SpeechSpan
from services.voice.wake import validate_wake_prefix


ASR_CALIBRATION_FAILED = "voice_asr_calibration_failed"
CAPTURE_SECONDS = 12
MAX_LATENCY_MS = 3_000
_FAILURE_STAGES = frozenset({"preflight", "capture", "vad", "storage"})


class AsrCalibrationFailure(ValueError):
    def __init__(
        self,
        stage: str,
        *,
        detected_segment_count: int | None = None,
        captured_ms: int | None = None,
    ) -> None:
        self.stage = stage if stage in _FAILURE_STAGES else "preflight"
        self.detected_segment_count = (
            detected_segment_count
            if self.stage == "vad"
            and type(detected_segment_count) is int
            and 0 <= detected_segment_count <= 64
            else None
        )
        self.captured_ms = (
            captured_ms
            if self.stage == "capture"
            and type(captured_ms) is int
            and 0 <= captured_ms <= 30_000
            else None
        )
        super().__init__(ASR_CALIBRATION_FAILED)


class _Corpus(Protocol):
    def append(self, prompt_id: str, pcm: bytes) -> None: ...

    def append_many(self, values: tuple[tuple[str, bytes], ...]) -> None: ...

    def read_all(self) -> tuple[tuple[str, bytes], ...]: ...


class _Segmenter(Protocol):
    def segment(self, pcm: bytes) -> tuple[SpeechSpan, ...]: ...


class _Engine(Protocol):
    def transcribe(self, pcm: bytes) -> AsrResult: ...


class _Decoder(Protocol):
    def read(
        self, maximum: int, *, timeout_seconds: float | None = None
    ) -> DecoderRead: ...

    def close(self) -> None: ...


@dataclass(frozen=True)
class CalibrationCaptureReport:
    prompt_id: str
    duration_ms: int
    vad_peak_milli: int
    encrypted_clip_persisted: Literal[True] = True


@dataclass(frozen=True)
class FixedWindowCaptureReport:
    prompt_id: str
    duration_ms: Literal[8_000] = 8_000
    encrypted_clip_persisted: Literal[True] = True


@dataclass(frozen=True)
class CalibrationModelMetrics:
    model: str
    available: bool
    samples_evaluated: int
    exact_matches: int
    wake_matches: int
    latency_p50_ms: int | None
    latency_p95_ms: int | None
    passed: bool


@dataclass(frozen=True)
class CalibrationGateReport:
    models: tuple[CalibrationModelMetrics, ...]
    selected_model: str | None
    gate_passed: bool


class AsrCalibrationCapture:
    """Store only one unique Silero-selected fixed-prompt utterance."""

    def __init__(
        self,
        *,
        capture_window: Callable[[], bytes],
        segmenter: _Segmenter,
        corpus: _Corpus,
    ) -> None:
        self._capture_window = capture_window
        self._segmenter = segmenter
        self._corpus = corpus

    def capture(self, prompt_id: str) -> CalibrationCaptureReport:
        try:
            if prompt_id not in PRIVATE_ASR_PROMPTS:
                raise ValueError
            window = self._capture_window()
            if type(window) is not bytes or not window or len(window) % 2:
                raise ValueError
            spans = self._segmenter.segment(window)
            if len(spans) != 1:
                raise ValueError
            span = spans[0]
            if (
                not isinstance(span, SpeechSpan)
                or span.start_sample < 0
                or span.end_sample <= span.start_sample
                or span.end_sample * 2 > len(window)
                or span.end_sample - span.start_sample > SAMPLE_RATE_HZ * 8
            ):
                raise ValueError
            pcm = window[span.start_sample * 2 : span.end_sample * 2]
            self._corpus.append(prompt_id, pcm)
            return CalibrationCaptureReport(
                prompt_id=prompt_id,
                duration_ms=(span.end_sample - span.start_sample) * 1_000 // SAMPLE_RATE_HZ,
                vad_peak_milli=round(span.peak_probability * 1_000),
            )
        except Exception:
            raise ValueError(ASR_CALIBRATION_FAILED) from None

    def capture_all(
        self, prompt_ids: tuple[str, ...]
    ) -> tuple[CalibrationCaptureReport, ...]:
        stage = "preflight"
        try:
            if (
                type(prompt_ids) is not tuple
                or prompt_ids != tuple(PRIVATE_ASR_PROMPTS)
            ):
                raise ValueError
            stage = "capture"
            window = self._capture_window()
            if type(window) is not bytes or not window or len(window) % 2:
                raise ValueError
            stage = "vad"
            spans = self._segmenter.segment(window)
            if len(spans) != len(prompt_ids):
                raise AsrCalibrationFailure(
                    "vad", detected_segment_count=len(spans)
                )
            clips: list[tuple[str, bytes]] = []
            reports: list[CalibrationCaptureReport] = []
            for prompt_id, span in zip(prompt_ids, spans, strict=True):
                if (
                    not isinstance(span, SpeechSpan)
                    or span.start_sample < 0
                    or span.end_sample <= span.start_sample
                    or span.end_sample * 2 > len(window)
                    or span.end_sample - span.start_sample > SAMPLE_RATE_HZ * 8
                ):
                    raise ValueError
                clips.append(
                    (prompt_id, window[span.start_sample * 2 : span.end_sample * 2])
                )
                reports.append(
                    CalibrationCaptureReport(
                        prompt_id=prompt_id,
                        duration_ms=(span.end_sample - span.start_sample)
                        * 1_000
                        // SAMPLE_RATE_HZ,
                        vad_peak_milli=round(span.peak_probability * 1_000),
                    )
                )
            stage = "storage"
            self._corpus.append_many(tuple(clips))
            return tuple(reports)
        except AsrCalibrationFailure:
            raise
        except Exception:
            raise AsrCalibrationFailure(stage) from None


class AsrCalibrationEvaluator:
    """Compare fixed ASR candidates on identical decrypted clips in memory."""

    def __init__(self, *, corpus: _Corpus, engines: Mapping[str, _Engine]) -> None:
        if set(engines) != {"base", "small"}:
            raise ValueError(ASR_CALIBRATION_FAILED)
        self._corpus = corpus
        self._engines = engines

    def evaluate(self) -> CalibrationGateReport:
        try:
            clips = self._corpus.read_all()
            if (
                not clips
                or {prompt_id for prompt_id, _pcm in clips}
                != set(PRIVATE_ASR_PROMPTS)
            ):
                raise ValueError
            metrics = tuple(
                self._evaluate_model(model, clips) for model in ("base", "small")
            )
            selected = next((item.model for item in metrics if item.passed), None)
            return CalibrationGateReport(metrics, selected, selected is not None)
        except Exception:
            raise ValueError(ASR_CALIBRATION_FAILED) from None

    def _evaluate_model(
        self, model: str, clips: tuple[tuple[str, bytes], ...]
    ) -> CalibrationModelMetrics:
        exact_matches = 0
        wake_matches = 0
        latencies: list[int] = []
        try:
            engine = self._engines[model]
            for prompt_id, pcm in clips:
                expected = PRIVATE_ASR_PROMPTS[prompt_id]
                result = engine.transcribe(pcm)
                if (
                    not isinstance(result, AsrResult)
                    or result.language != "zh"
                    or type(result.duration_ms) is not int
                    or result.duration_ms < 0
                ):
                    raise ValueError
                exact_matches += int(
                    _normalize_exact(result.text) == _normalize_exact(expected)
                )
                expected_wake = prompt_id != "negative_weather"
                wake_matches += int(
                    validate_wake_prefix(result.text).accepted == expected_wake
                )
                latencies.append(result.duration_ms)
        except Exception:
            return CalibrationModelMetrics(model, False, 0, 0, 0, None, None, False)
        p50 = _nearest_rank(latencies, 0.50)
        p95 = _nearest_rank(latencies, 0.95)
        passed = (
            exact_matches == len(clips)
            and wake_matches == len(clips)
            and p95 <= MAX_LATENCY_MS
        )
        return CalibrationModelMetrics(
            model,
            True,
            len(clips),
            exact_matches,
            wake_matches,
            p50,
            p95,
            passed,
        )


class FixedWindowAsrCalibrationCapture:
    """Persist one explicit fixed prompt from one exact eight-second window."""

    def __init__(self, *, capture_window: Callable[[], bytes], corpus: _Corpus) -> None:
        self._capture_window = capture_window
        self._corpus = corpus

    def capture(self, prompt_id: str) -> FixedWindowCaptureReport:
        try:
            if prompt_id not in PRIVATE_ASR_PROMPTS:
                raise ValueError
            pcm = self._capture_window()
            if type(pcm) is not bytes or len(pcm) != SAMPLE_RATE_HZ * 2 * 8:
                raise ValueError
            self._corpus.append(prompt_id, pcm)
            return FixedWindowCaptureReport(prompt_id)
        except Exception:
            raise ValueError(ASR_CALIBRATION_FAILED) from None


class BoundedCalibrationPcmCapture:
    """Read one fixed 8-, 12- or 30-second Xiaomi window into bounded memory."""

    def __init__(
        self,
        settings: AudioSettings,
        *,
        capture_seconds: int = CAPTURE_SECONDS,
        decoder_factory: Callable[[AudioSettings], _Decoder] = FixedAudioDecoder,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        if type(capture_seconds) is not int or capture_seconds not in {8, 12, 30}:
            raise ValueError(ASR_CALIBRATION_FAILED)
        self._settings = settings
        self._capture_seconds = capture_seconds
        self._decoder_factory = decoder_factory
        self._clock = clock

    def capture(self) -> bytes:
        buffer = bytearray()
        decoder: _Decoder | None = None
        try:
            target = (
                self._settings.sample_rate_hz
                * self._settings.channels
                * self._settings.sample_width_bytes
                * self._capture_seconds
            )
            if target != 32_000 * self._capture_seconds:
                raise ValueError
            decoder = self._decoder_factory(self._settings)
            started = float(self._clock())
            retried_empty_source = False
            while len(buffer) < target:
                elapsed = float(self._clock()) - started
                remaining_seconds = self._capture_seconds + 6.0 - elapsed
                if remaining_seconds <= 0:
                    raise ValueError
                remaining = target - len(buffer)
                result = decoder.read(
                    remaining, timeout_seconds=min(10.0, remaining_seconds)
                )
                if (
                    isinstance(result, DecoderRead)
                    and result.failure_reason is not None
                    and not buffer
                    and not retried_empty_source
                ):
                    decoder.close()
                    decoder = self._decoder_factory(self._settings)
                    started = float(self._clock())
                    retried_empty_source = True
                    continue
                if (
                    not isinstance(result, DecoderRead)
                    or result.failure_reason is not None
                    or type(result.pcm) is not bytes
                    or not result.pcm
                    or len(result.pcm) > remaining
                    or len(result.pcm) % self._settings.sample_width_bytes
                ):
                    raise ValueError
                buffer.extend(result.pcm)
            return bytes(buffer)
        except AsrCalibrationFailure:
            raise
        except Exception:
            captured_ms = (
                len(buffer)
                * 1_000
                // (
                    self._settings.sample_rate_hz
                    * self._settings.channels
                    * self._settings.sample_width_bytes
                )
            )
            raise AsrCalibrationFailure(
                "capture", captured_ms=captured_ms
            ) from None
        finally:
            for index in range(len(buffer)):
                buffer[index] = 0
            buffer.clear()
            if decoder is not None:
                decoder.close()


def _normalize_exact(value: str) -> str:
    if not isinstance(value, str):
        raise ValueError(ASR_CALIBRATION_FAILED)
    normalized = unicodedata.normalize("NFKC", value)
    return "".join(
        character
        for character in normalized
        if not character.isspace()
        and not unicodedata.category(character).startswith("P")
    )


def _nearest_rank(values: list[int], quantile: float) -> int:
    ordered = sorted(values)
    return ordered[math.ceil(quantile * len(ordered)) - 1]


__all__ = [
    "ASR_CALIBRATION_FAILED",
    "AsrCalibrationFailure",
    "AsrCalibrationCapture",
    "AsrCalibrationEvaluator",
    "BoundedCalibrationPcmCapture",
    "CalibrationCaptureReport",
    "CalibrationGateReport",
    "CalibrationModelMetrics",
    "FixedWindowAsrCalibrationCapture",
    "FixedWindowCaptureReport",
]
