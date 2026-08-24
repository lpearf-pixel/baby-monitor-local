"""Aggregate-only Silero control and private signal diagnostics."""

from __future__ import annotations

import math
from collections.abc import Callable
from dataclasses import dataclass
from typing import Protocol

import numpy as np

from services.voice.asr_corpus import PRIVATE_ASR_PROMPTS
from services.voice.silero_runtime import SAMPLE_RATE_HZ, SileroAnalysis, SpeechSpan


VAD_DIAGNOSTIC_FAILED = "voice_vad_diagnostic_failed"
VAD_CANDIDATE_UNAVAILABLE = "vad_candidate_unavailable"
VAD_CONTROL_UNAVAILABLE = "vad_control_unavailable"
_MAX_GAIN_DB = 12.0


class _Corpus(Protocol):
    def read_all(self) -> tuple[tuple[str, bytes], ...]: ...


class _Segmenter(Protocol):
    def analyze(self, pcm: bytes) -> SileroAnalysis: ...


@dataclass(frozen=True)
class VadGainResult:
    pcm: bytes
    applied_gain_db: float


@dataclass(frozen=True)
class PrivateVadMetrics:
    prompt_id: str
    rms_dbfs_milli: int
    raw_peak_milli: int
    raw_span_count: int
    applied_gain_db_milli: int
    final_span_count: int


@dataclass(frozen=True)
class VadDiagnosticReport:
    gate_passed: bool
    reason: str
    control_rms_dbfs_milli: int
    control_peak_milli: int
    control_span_count: int
    private: tuple[PrivateVadMetrics, ...]


class VadGainPreprocessor:
    """Apply bounded gain to one in-memory VAD copy, never to corpus or ASR bytes."""

    def apply(self, pcm: bytes, *, requested_gain_db: float) -> VadGainResult:
        try:
            if (
                type(pcm) is not bytes
                or not pcm
                or len(pcm) % 2
                or type(requested_gain_db) not in {int, float}
                or not math.isfinite(float(requested_gain_db))
                or not 0.0 <= float(requested_gain_db) <= _MAX_GAIN_DB
            ):
                raise ValueError
            values = np.frombuffer(pcm, dtype="<i2").astype(np.float64)
            peak = float(np.max(np.abs(values)))
            requested_factor = 10.0 ** (float(requested_gain_db) / 20.0)
            safe_factor = requested_factor if peak == 0.0 else min(
                requested_factor, 32_767.0 / peak
            )
            gained = np.clip(np.rint(values * safe_factor), -32_768, 32_767)
            applied = 0.0 if safe_factor <= 1.0 else 20.0 * math.log10(safe_factor)
            return VadGainResult(gained.astype("<i2").tobytes(), applied)
        except Exception:
            raise ValueError(VAD_DIAGNOSTIC_FAILED) from None


class VadDiagnostic:
    def __init__(
        self,
        *,
        segmenter: _Segmenter,
        corpus: _Corpus,
        control_pcm: Callable[[], bytes],
        preprocessor: VadGainPreprocessor | None = None,
    ) -> None:
        self._segmenter = segmenter
        self._corpus = corpus
        self._control_pcm = control_pcm
        self._preprocessor = preprocessor or VadGainPreprocessor()

    def run(self) -> VadDiagnosticReport:
        try:
            control = self._control_pcm()
            _validate_pcm(control)
            control_analysis = self._segmenter.analyze(control)
            _validate_analysis(control_analysis, len(control) // 2)
            control_rms = _rms_dbfs_milli(control)
            clips = self._corpus.read_all()
            if tuple(prompt_id for prompt_id, _pcm in clips) != tuple(
                PRIVATE_ASR_PROMPTS
            ):
                raise ValueError
            raw: list[tuple[str, bytes, int, SileroAnalysis]] = []
            for prompt_id, pcm in clips:
                _validate_pcm(pcm)
                analysis = self._segmenter.analyze(pcm)
                _validate_analysis(analysis, len(pcm) // 2)
                raw.append((prompt_id, pcm, _rms_dbfs_milli(pcm), analysis))
            should_gain = (
                len(control_analysis.spans) == 1
                and all(len(item[3].spans) == 0 for item in raw)
                and all(control_rms - item[2] >= 12_000 for item in raw)
            )
            metrics: list[PrivateVadMetrics] = []
            for prompt_id, pcm, rms, analysis in raw:
                final = analysis
                gain_milli = 0
                if should_gain:
                    gained = self._preprocessor.apply(pcm, requested_gain_db=12.0)
                    gain_milli = round(gained.applied_gain_db * 1_000)
                    final = self._segmenter.analyze(gained.pcm)
                    _validate_analysis(final, len(gained.pcm) // 2)
                metrics.append(
                    PrivateVadMetrics(
                        prompt_id,
                        rms,
                        round(analysis.peak_probability * 1_000),
                        len(analysis.spans),
                        gain_milli,
                        len(final.spans),
                    )
                )
            gate_passed = len(control_analysis.spans) == 1 and all(
                item.final_span_count == 1 for item in metrics
            )
            reason = (
                "none"
                if gate_passed
                else VAD_CONTROL_UNAVAILABLE
                if len(control_analysis.spans) != 1
                else VAD_CANDIDATE_UNAVAILABLE
            )
            return VadDiagnosticReport(
                gate_passed,
                reason,
                control_rms,
                round(control_analysis.peak_probability * 1_000),
                len(control_analysis.spans),
                tuple(metrics),
            )
        except Exception:
            raise ValueError(VAD_DIAGNOSTIC_FAILED) from None


def _validate_pcm(pcm: bytes) -> None:
    if type(pcm) is not bytes or not pcm or len(pcm) % 2:
        raise ValueError


def _validate_analysis(analysis: SileroAnalysis, sample_count: int) -> None:
    if (
        not isinstance(analysis, SileroAnalysis)
        or not math.isfinite(analysis.peak_probability)
        or not 0.0 <= analysis.peak_probability <= 1.0
    ):
        raise ValueError
    for span in analysis.spans:
        if (
            not isinstance(span, SpeechSpan)
            or span.start_sample < 0
            or span.end_sample <= span.start_sample
            or span.end_sample > sample_count
            or span.end_sample - span.start_sample > SAMPLE_RATE_HZ * 8
        ):
            raise ValueError


def _rms_dbfs_milli(pcm: bytes) -> int:
    values = np.frombuffer(pcm, dtype="<i2").astype(np.float64)
    rms = float(np.sqrt(np.mean(np.square(values)))) / 32_768.0
    return round(max(-120.0, 20.0 * math.log10(max(rms, 1e-6))) * 1_000)


__all__ = [
    "PrivateVadMetrics",
    "VAD_CANDIDATE_UNAVAILABLE",
    "VAD_CONTROL_UNAVAILABLE",
    "VAD_DIAGNOSTIC_FAILED",
    "VadDiagnostic",
    "VadDiagnosticReport",
    "VadGainPreprocessor",
    "VadGainResult",
]
