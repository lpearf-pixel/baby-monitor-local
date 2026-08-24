from __future__ import annotations

from types import SimpleNamespace

import pytest

from packages.contracts.audio import AudioFailureReason
from packages.contracts.settings import AudioSettings
from services.audio.source import DecoderRead
from services.voice.asr import AsrResult
from services.voice.asr_calibration import (
    ASR_CALIBRATION_FAILED,
    AsrCalibrationCapture,
    AsrCalibrationFailure,
    AsrCalibrationEvaluator,
    BoundedCalibrationPcmCapture,
    FixedWindowAsrCalibrationCapture,
)
from services.voice.asr_corpus import PRIVATE_ASR_PROMPTS
from services.voice.silero_runtime import SpeechSpan


class Corpus:
    def __init__(self, clips=()) -> None:
        self.clips = list(clips)
        self.batches: list[tuple[tuple[str, bytes], ...]] = []

    def append(self, prompt_id: str, pcm: bytes) -> None:
        self.clips.append((prompt_id, pcm))

    def append_many(self, values: tuple[tuple[str, bytes], ...]) -> None:
        self.batches.append(values)
        self.clips.extend(values)

    def read_all(self):
        return tuple(self.clips)


class Segmenter:
    def __init__(self, spans: tuple[SpeechSpan, ...]) -> None:
        self.spans = spans

    def segment(self, _pcm: bytes) -> tuple[SpeechSpan, ...]:
        return self.spans


def test_capture_persists_only_the_unique_bounded_speech_span() -> None:
    window = b"a" * 2_000 + b"b" * 16_000 + b"c" * 2_000
    corpus = Corpus()
    capture = AsrCalibrationCapture(
        capture_window=lambda: window,
        segmenter=Segmenter((SpeechSpan(1_000, 9_000, 0.91),)),
        corpus=corpus,
    )

    report = capture.capture("feeding_start_dad")

    assert corpus.clips == [("feeding_start_dad", window[2_000:18_000])]
    assert report.prompt_id == "feeding_start_dad"
    assert report.duration_ms == 500
    assert report.vad_peak_milli == 910
    assert report.encrypted_clip_persisted is True
    assert "小小" not in repr(report)


@pytest.mark.parametrize("spans", [(), (SpeechSpan(0, 4_000, 0.9), SpeechSpan(5_000, 9_000, 0.8))])
def test_capture_rejects_missing_or_ambiguous_speech(spans) -> None:
    corpus = Corpus()
    capture = AsrCalibrationCapture(
        capture_window=lambda: b"\0\0" * 16_000,
        segmenter=Segmenter(spans),
        corpus=corpus,
    )

    with pytest.raises(ValueError, match=f"^{ASR_CALIBRATION_FAILED}$"):
        capture.capture("feeding_start_dad")

    assert corpus.clips == []


def test_fixed_window_capture_persists_one_exact_supervised_eight_second_clip() -> None:
    pcm = b"f" * 256_000
    corpus = Corpus()
    capture = FixedWindowAsrCalibrationCapture(
        capture_window=lambda: pcm,
        corpus=corpus,
    )

    report = capture.capture("feeding_start_dad")

    assert corpus.clips == [("feeding_start_dad", pcm)]
    assert report.prompt_id == "feeding_start_dad"
    assert report.duration_ms == 8_000
    assert report.encrypted_clip_persisted is True


def test_fixed_window_capture_rejects_non_eight_second_or_free_form_input() -> None:
    corpus = Corpus()
    capture = FixedWindowAsrCalibrationCapture(
        capture_window=lambda: b"f" * 255_998,
        corpus=corpus,
    )

    with pytest.raises(ValueError, match=f"^{ASR_CALIBRATION_FAILED}$"):
        capture.capture("feeding_start_dad")
    with pytest.raises(ValueError, match=f"^{ASR_CALIBRATION_FAILED}$"):
        capture.capture("free_form")
    assert corpus.clips == []


def test_batch_capture_maps_six_spans_to_fixed_prompts_in_one_publication() -> None:
    window = bytes(range(256)) * 1_000
    prompt_ids = tuple(PRIVATE_ASR_PROMPTS)
    spans = tuple(
        SpeechSpan(index * 1_000, index * 1_000 + 800, 0.80 + index / 100)
        for index in range(6)
    )
    corpus = Corpus()
    capture = AsrCalibrationCapture(
        capture_window=lambda: window,
        segmenter=Segmenter(spans),
        corpus=corpus,
    )

    reports = capture.capture_all(prompt_ids)

    expected = tuple(
        (prompt_id, window[span.start_sample * 2 : span.end_sample * 2])
        for prompt_id, span in zip(prompt_ids, spans, strict=True)
    )
    assert corpus.batches == [expected]
    assert tuple(report.prompt_id for report in reports) == prompt_ids
    assert all(report.encrypted_clip_persisted for report in reports)


def test_batch_capture_rejects_wrong_segment_count_without_publication() -> None:
    corpus = Corpus()
    capture = AsrCalibrationCapture(
        capture_window=lambda: b"\0\0" * 16_000,
        segmenter=Segmenter((SpeechSpan(0, 4_000, 0.9),)),
        corpus=corpus,
    )

    with pytest.raises(AsrCalibrationFailure, match=f"^{ASR_CALIBRATION_FAILED}$") as error:
        capture.capture_all(tuple(PRIVATE_ASR_PROMPTS))

    assert error.value.stage == "vad"
    assert error.value.detected_segment_count == 1
    assert corpus.batches == []


class Engine:
    def __init__(self, texts: dict[bytes, str], duration_ms: int) -> None:
        self.texts = texts
        self.duration_ms = duration_ms

    def transcribe(self, pcm: bytes) -> AsrResult:
        return AsrResult(self.texts[pcm], "zh", self.duration_ms)


def test_evaluator_compares_identical_encrypted_clips_without_transcript_output() -> None:
    clips = {
        "feeding_start_dad": b"d" * 8_000,
        "feeding_start_mom": b"m" * 8_000,
        "feeding_amount": b"a" * 8_000,
        "feeding_finish": b"f" * 8_000,
        "care_cancel": b"c" * 8_000,
        "negative_weather": b"n" * 8_000,
    }
    expected = {
        "feeding_start_dad": "小小，我是爸爸，现在开始喂奶。",
        "feeding_start_mom": "小小，我是妈妈，现在开始喂奶。",
        "feeding_amount": "小小，宝宝喝了九十毫升配方奶。",
        "feeding_finish": "小小，喂奶结束。",
        "care_cancel": "小小，取消这次记录。",
        "negative_weather": "今天天气不错。",
    }
    corpus = Corpus(tuple(clips.items()))
    evaluator = AsrCalibrationEvaluator(
        corpus=corpus,
        engines={
            "base": Engine({clips[key]: value for key, value in expected.items()}, 900),
            "small": Engine(
                {
                    clips[key]: (
                        "今天的天气不错。" if key == "negative_weather" else value
                    )
                    for key, value in expected.items()
                },
                1_800,
            ),
        },
    )

    report = evaluator.evaluate()

    assert report.selected_model == "base"
    assert report.gate_passed is True
    assert report.models[0].samples_evaluated == 6
    assert report.models[0].exact_matches == 6
    assert report.models[0].wake_matches == 6
    assert report.models[0].latency_p95_ms == 900
    assert report.models[0].passed is True
    assert report.models[1].exact_matches == 5
    assert report.models[1].passed is False
    assert "爸爸" not in repr(report)
    assert "天气" not in repr(report)


def test_evaluator_rejects_incomplete_fixed_prompt_corpus() -> None:
    pcm = b"d" * 8_000
    evaluator = AsrCalibrationEvaluator(
        corpus=Corpus((("feeding_start_dad", pcm),)),
        engines={
            "base": Engine({pcm: "小小，我是爸爸，现在开始喂奶"}, 900),
            "small": Engine({pcm: "小小，我是爸爸，现在开始喂奶"}, 900),
        },
    )

    with pytest.raises(ValueError, match=f"^{ASR_CALIBRATION_FAILED}$"):
        evaluator.evaluate()


class Decoder:
    def __init__(self, reads: list[DecoderRead]) -> None:
        self.reads = reads
        self.closed = False

    def read(self, maximum: int, *, timeout_seconds: float | None = None) -> DecoderRead:
        assert maximum > 0
        assert timeout_seconds is not None and 0 < timeout_seconds <= 10
        return self.reads.pop(0)

    def close(self) -> None:
        self.closed = True


def test_bounded_window_capture_closes_decoder_on_success_and_failure() -> None:
    success = Decoder([DecoderRead(b"a" * 192_000), DecoderRead(b"b" * 192_000)])
    capture = BoundedCalibrationPcmCapture(
        AudioSettings(), decoder_factory=lambda _settings: success, clock=lambda: 0.0
    )
    assert capture.capture() == b"a" * 192_000 + b"b" * 192_000
    assert success.closed is True

    failure = Decoder([DecoderRead(b"", AudioFailureReason.AUDIO_SOURCE_UNAVAILABLE)])
    with pytest.raises(ValueError, match=f"^{ASR_CALIBRATION_FAILED}$"):
        BoundedCalibrationPcmCapture(
            AudioSettings(), decoder_factory=lambda _settings: failure, clock=lambda: 0.0
        ).capture()
    assert failure.closed is True


def test_bounded_batch_window_is_exactly_thirty_seconds() -> None:
    decoder = Decoder([DecoderRead(b"x" * 960_000)])

    pcm = BoundedCalibrationPcmCapture(
        AudioSettings(),
        capture_seconds=30,
        decoder_factory=lambda _settings: decoder,
        clock=lambda: 0.0,
    ).capture()

    assert len(pcm) == 960_000
    assert decoder.closed is True


def test_bounded_fixed_clip_is_exactly_eight_seconds() -> None:
    decoder = Decoder([DecoderRead(b"e" * 256_000)])

    pcm = BoundedCalibrationPcmCapture(
        AudioSettings(),
        capture_seconds=8,
        decoder_factory=lambda _settings: decoder,
        clock=lambda: 0.0,
    ).capture()

    assert len(pcm) == 256_000
    assert decoder.closed is True


def test_bounded_capture_retries_one_empty_initial_decoder_failure() -> None:
    failed = Decoder([DecoderRead(b"", AudioFailureReason.AUDIO_SOURCE_UNAVAILABLE)])
    recovered = Decoder([DecoderRead(b"r" * 384_000)])
    decoders = iter((failed, recovered))

    pcm = BoundedCalibrationPcmCapture(
        AudioSettings(),
        decoder_factory=lambda _settings: next(decoders),
        clock=lambda: 0.0,
    ).capture()

    assert pcm == b"r" * 384_000
    assert failed.closed is True
    assert recovered.closed is True


def test_bounded_capture_does_not_join_streams_after_partial_audio() -> None:
    failed = Decoder(
        [
            DecoderRead(b"p" * 16_000),
            DecoderRead(b"", AudioFailureReason.AUDIO_SOURCE_UNAVAILABLE),
        ]
    )
    created = 0

    def factory(_settings: AudioSettings) -> Decoder:
        nonlocal created
        created += 1
        return failed

    with pytest.raises(AsrCalibrationFailure, match=f"^{ASR_CALIBRATION_FAILED}$") as error:
        BoundedCalibrationPcmCapture(
            AudioSettings(), decoder_factory=factory, clock=lambda: 0.0
        ).capture()

    assert error.value.stage == "capture"
    assert error.value.captured_ms == 500
    assert created == 1
    assert failed.closed is True
