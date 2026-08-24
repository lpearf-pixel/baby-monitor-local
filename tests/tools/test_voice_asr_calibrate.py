from __future__ import annotations

from pathlib import Path

from services.voice.asr_corpus import PRIVATE_ASR_PROMPTS
from services.voice.keychain import KeychainSecretStore
from services.voice.asr_calibration import (
    ASR_CALIBRATION_FAILED,
    AsrCalibrationFailure,
    CalibrationCaptureReport,
    CalibrationGateReport,
    CalibrationModelMetrics,
)
from tools import voice_asr_calibrate


class MemoryKeychain:
    def __init__(self) -> None:
        self.values: dict[tuple[str, str], bytes] = {}

    def read(self, service: str, account: str) -> bytes | None:
        return self.values.get((service, account))

    def write(self, service: str, account: str, secret: bytes) -> None:
        self.values[(service, account)] = bytes(secret)

    def delete(self, service: str, account: str) -> None:
        self.values.pop((service, account), None)


class Capture:
    def capture(self, prompt_id: str) -> CalibrationCaptureReport:
        return CalibrationCaptureReport(prompt_id, 1_250, 913)

    def capture_all(self, prompt_ids: tuple[str, ...]):
        return tuple(
            CalibrationCaptureReport(prompt_id, 1_000 + index, 900 + index)
            for index, prompt_id in enumerate(prompt_ids)
        )


class Evaluator:
    def __init__(self, report: CalibrationGateReport) -> None:
        self.report = report

    def evaluate(self) -> CalibrationGateReport:
        return self.report


def test_capture_displays_fixed_prompt_before_confirmation_and_reports_aggregate_only(
    tmp_path: Path,
) -> None:
    output: list[str] = []
    events: list[str] = []

    result = voice_asr_calibrate.main(
        ["capture", "--prompt-id", "feeding_start_dad"],
        project_root=tmp_path,
        capture_builder=lambda root: events.append(f"build:{root}") or Capture(),
        input_fn=lambda prompt: events.append(prompt) or "",
        printer=output.append,
    )

    assert result == 0
    assert output == [
        "prompt_id=feeding_start_dad",
        "prompt=小小，我是爸爸，现在开始喂奶",
        "result=PASS",
        "operation=capture",
        "duration_ms=1250",
        "vad_peak_milli=913",
        "encrypted_clip_persisted=true",
    ]
    assert events == ["press_enter_then_speak=", f"build:{tmp_path}"]
    assert "transcript" not in "\n".join(output)


def test_capture_fixed_uses_supervised_eight_second_storage_without_vad(
    tmp_path: Path,
) -> None:
    output: list[str] = []

    result = voice_asr_calibrate.main(
        ["capture-fixed", "--prompt-id", "feeding_start_dad"],
        project_root=tmp_path,
        fixed_capture_builder=lambda _root: Capture(),
        input_fn=lambda _prompt: "",
        printer=output.append,
    )

    assert result == 0
    assert output == [
        "prompt_id=feeding_start_dad",
        "prompt=小小，我是爸爸，现在开始喂奶",
        "result=PASS",
        "operation=capture-fixed",
        "duration_ms=1250",
        "encrypted_clip_persisted=true",
    ]


def test_evaluate_prints_only_candidate_counts_and_latency(tmp_path: Path) -> None:
    report = CalibrationGateReport(
        models=(
            CalibrationModelMetrics(
                "base", True, 6, 6, 6, 800, 900, True, (), 0
            ),
            CalibrationModelMetrics(
                "small",
                True,
                6,
                5,
                6,
                1_600,
                1_900,
                False,
                ("negative_weather",),
                1,
            ),
        ),
        selected_model="base",
        gate_passed=True,
    )
    output: list[str] = []

    result = voice_asr_calibrate.main(
        ["evaluate"],
        project_root=tmp_path,
        evaluator_builder=lambda root: Evaluator(report),
        printer=output.append,
    )

    assert result == 0
    assert output == [
        "result=PASS",
        "operation=evaluate",
        "gate_passed=true",
        "selected_model=base",
        "base_available=true",
        "base_samples_evaluated=6",
        "base_exact_matches=6",
        "base_wake_matches=6",
        "base_latency_p50_ms=800",
        "base_latency_p95_ms=900",
        "base_mismatch_prompt_ids=none",
        "base_edit_distance_total=0",
        "base_passed=true",
        "small_available=true",
        "small_samples_evaluated=6",
        "small_exact_matches=5",
        "small_wake_matches=6",
        "small_latency_p50_ms=1600",
        "small_latency_p95_ms=1900",
        "small_mismatch_prompt_ids=negative_weather",
        "small_edit_distance_total=1",
        "small_passed=false",
    ]
    assert "爸爸" not in "\n".join(output)
    assert "transcript" not in "\n".join(output)


def test_capture_all_is_one_confirmed_fixed_order_session(tmp_path: Path) -> None:
    output: list[str] = []

    result = voice_asr_calibrate.main(
        ["capture-all"],
        project_root=tmp_path,
        capture_builder=lambda _root: Capture(),
        input_fn=lambda prompt: "" if prompt == "press_enter_then_read_all=" else "x",
        printer=output.append,
    )

    assert result == 0
    assert output[:7] == [
        "prompt_1=小小，我是爸爸，现在开始喂奶",
        "prompt_2=小小，我是妈妈，现在开始喂奶",
        "prompt_3=小小，宝宝喝了九十毫升配方奶",
        "prompt_4=小小，喂奶结束",
        "prompt_5=小小，取消这次记录",
        "prompt_6=今天天气不错",
        "instruction=pause_two_seconds_between_phrases",
    ]
    assert output[7:] == [
        "result=PASS",
        "operation=capture-all",
        "clip_count=6",
        "duration_total_ms=6015",
        "vad_peak_min_milli=900",
        "encrypted_clip_persisted=true",
    ]


def test_operator_redacts_builder_failure(tmp_path: Path) -> None:
    output: list[str] = []

    result = voice_asr_calibrate.main(
        ["evaluate"],
        project_root=tmp_path,
        evaluator_builder=lambda _root: (_ for _ in ()).throw(
            RuntimeError("private transcript and path")
        ),
        printer=output.append,
    )

    assert result == 1
    assert output == [
        "result=FAIL",
        "operation=evaluate",
        f"reason={ASR_CALIBRATION_FAILED}",
    ]
    assert "private" not in "\n".join(output)


def test_operator_reports_only_allowlisted_vad_failure_count(tmp_path: Path) -> None:
    output: list[str] = []

    result = voice_asr_calibrate.main(
        ["capture-all"],
        project_root=tmp_path,
        capture_builder=lambda _root: (_ for _ in ()).throw(
            AsrCalibrationFailure("vad", detected_segment_count=4)
        ),
        input_fn=lambda _prompt: "",
        printer=output.append,
    )

    assert result == 1
    assert output[-5:] == [
        "result=FAIL",
        "operation=capture-all",
        f"reason={ASR_CALIBRATION_FAILED}",
        "failure_stage=vad",
        "detected_segment_count=4",
    ]


def test_operator_reports_only_bounded_capture_progress(tmp_path: Path) -> None:
    output: list[str] = []

    result = voice_asr_calibrate.main(
        ["capture-all"],
        project_root=tmp_path,
        capture_builder=lambda _root: (_ for _ in ()).throw(
            AsrCalibrationFailure("capture", captured_ms=12_345)
        ),
        input_fn=lambda _prompt: "",
        printer=output.append,
    )

    assert result == 1
    assert output[-5:] == [
        "result=FAIL",
        "operation=capture-all",
        f"reason={ASR_CALIBRATION_FAILED}",
        "failure_stage=capture",
        "captured_ms=12345",
    ]


def test_private_corpus_uses_the_stable_runtime_keychain_factory(
    tmp_path: Path,
) -> None:
    backend = MemoryKeychain()
    store = KeychainSecretStore(backend, random_bytes=lambda size: b"k" * size)
    roots: list[Path] = []

    corpus = voice_asr_calibrate._private_corpus(
        tmp_path,
        keychain_factory=lambda root: roots.append(root) or store,
    )
    corpus.append(next(iter(PRIVATE_ASR_PROMPTS)), b"p" * 8_000)

    assert roots == [tmp_path]
    assert len(backend.values) == 1
