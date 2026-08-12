from __future__ import annotations

from pathlib import Path

import pytest


STAGE_NAMES = (
    "frame_policy_excluded_from_metric",
    "jpeg_decode",
    "yunet_face",
    "pose_preprocess",
    "pose_inference",
    "pose_decode",
    "semantic_backend_total",
    "production_analyzer_total",
)


def test_render_report_uses_literal_nearest_rank_stage_statistics() -> None:
    from tools.realtime_visual_diagnostic import render_report

    samples = {
        name: (1.0, 2.0, 3.0, 4.0, 100.0)
        for name in STAGE_NAMES
    }

    report = render_report(samples)

    expected_line = "p50=3.000ms p95=100.000ms max=100.000ms"
    assert report.splitlines() == [
        f"{name}: {expected_line}" for name in STAGE_NAMES
    ] + ["diagnostic=PASS"]


def test_main_redacts_unexpected_live_diagnostic_failure(
    capsys: pytest.CaptureFixture[str],
) -> None:
    from tools.realtime_visual_diagnostic import main

    def fail(_settings: Path) -> dict[str, tuple[float, ...]]:
        raise RuntimeError(
            "/Users/private/nursery.jpg at 192.168.2.6 contains a secret"
        )

    exit_code = main(
        ["--settings", "runtime/settings.yaml"],
        run=fail,
    )

    captured = capsys.readouterr()
    assert exit_code == 2
    assert captured.out == "diagnostic=FAIL reason=diagnostic_failed\n"
    assert captured.err == ""
    assert "private" not in captured.out
    assert "192.168" not in captured.out


def test_main_reports_stable_stage_failure_without_exception_details(
    capsys: pytest.CaptureFixture[str],
) -> None:
    from tools.realtime_visual_diagnostic import DiagnosticStageError, main

    def fail(_settings: Path) -> dict[str, tuple[float, ...]]:
        raise DiagnosticStageError(
            "pose_inference_failed",
            RuntimeError("/Users/private/nursery.jpg at 192.168.2.6"),
        )

    exit_code = main(
        ["--settings", "runtime/settings.yaml"],
        run=fail,
    )

    captured = capsys.readouterr()
    assert exit_code == 2
    assert captured.out == "diagnostic=FAIL reason=pose_inference_failed\n"
    assert captured.err == ""
    assert "private" not in captured.out
    assert "192.168" not in captured.out


def test_run_stage_converts_dependency_failure_to_stable_reason() -> None:
    from tools.realtime_visual_diagnostic import (
        DiagnosticStageError,
        _run_stage,
    )

    def fail() -> None:
        raise RuntimeError("private dependency detail")

    with pytest.raises(DiagnosticStageError) as captured:
        _run_stage("frame_capture_failed", fail)

    assert captured.value.reason == "frame_capture_failed"
    assert str(captured.value) == "frame_capture_failed"


def test_run_stage_preserves_existing_stage_failure() -> None:
    from tools.realtime_visual_diagnostic import (
        DiagnosticStageError,
        _run_stage,
    )

    existing = DiagnosticStageError(
        "model_backend_unavailable",
        RuntimeError("private dependency detail"),
    )

    with pytest.raises(DiagnosticStageError) as captured:
        _run_stage(
            "semantic_backend_failed",
            lambda: (_ for _ in ()).throw(existing),
        )

    assert captured.value is existing


def test_main_prints_complete_report_from_injected_live_runner(
    capsys: pytest.CaptureFixture[str],
) -> None:
    from tools.realtime_visual_diagnostic import main

    def succeed(_settings: Path) -> dict[str, tuple[float, ...]]:
        return {name: (10.0, 20.0) for name in STAGE_NAMES}

    exit_code = main(
        ["--settings", "runtime/settings.yaml"],
        run=succeed,
    )

    captured = capsys.readouterr()
    assert exit_code == 0
    assert captured.out.endswith("diagnostic=PASS\n")
    assert captured.out.count("p50=15.000ms p95=20.000ms max=20.000ms") == 8
    assert captured.err == ""
