from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
import subprocess

import pytest

from services.vision.realtime_status import (
    RealtimeVisualStatusStaleError,
    RealtimeVisualStatusUnavailableError,
)


ROOT = Path(__file__).resolve().parents[2]


def snapshot(
    fps: int,
    *,
    p50: float = 100.0,
    p95: float = 170.0,
    maximum: float = 190.0,
    model_state: str = "available",
) -> dict[str, object]:
    return {
        "schema_version": 1,
        "written_at_unix": 100.0,
        "realtime_fps": fps,
        "sample_count": 7,
        "processing_p50_ms": p50,
        "processing_p95_ms": p95,
        "processing_max_ms": maximum,
        "realtime_model_state": model_state,
    }


def sequence_reader(
    values: list[dict[str, object] | BaseException],
) -> Callable[[], dict[str, object]]:
    remaining = iter(values)

    def read() -> dict[str, object]:
        value = next(remaining)
        if isinstance(value, BaseException):
            raise value
        return value

    return read


def run_sampler(
    values: list[dict[str, object] | BaseException],
    capsys: pytest.CaptureFixture[str],
    *,
    interval_seconds: float = 10.0,
) -> tuple[int, list[str], str]:
    from tools import realtime_visual_performance

    exit_code = realtime_visual_performance.main(
        duration_seconds=len(values) * interval_seconds,
        interval_seconds=interval_seconds,
        reader=sequence_reader(values),
        sleeper=lambda _seconds: None,
    )
    captured = capsys.readouterr()
    return exit_code, captured.out.splitlines(), captured.err


def test_all_five_fps_samples_within_budget_pass_and_report_aggregates(
    capsys: pytest.CaptureFixture[str],
) -> None:
    values = [
        snapshot(5, p50=90.0, p95=150.0, maximum=180.0),
        snapshot(5, p50=110.0, p95=180.0, maximum=220.0),
        snapshot(5, p50=100.0, p95=160.0, maximum=200.0),
    ]

    exit_code, stdout, stderr = run_sampler(values, capsys)

    assert exit_code == 0
    assert stdout == [
        "samples=3",
        "fps_5_count=3",
        "fps_3_count=0",
        "fps_1_count=0",
        "processing_p50_ms=100",
        "processing_p95_ms=180",
        "processing_max_ms=220",
        "model_state=available",
        "performance=PASS mode=5fps",
    ]
    assert stderr == ""


def test_five_fps_worst_rolling_p95_over_budget_fails(
    capsys: pytest.CaptureFixture[str],
) -> None:
    values = [snapshot(5), snapshot(5, p95=180.001, maximum=200.0)]

    exit_code, stdout, stderr = run_sampler(values, capsys)

    assert exit_code != 0
    assert stdout[-1] == "performance=FAIL reason=five_fps_budget_exceeded"
    assert stderr == ""


def test_five_to_three_fps_with_stable_sixty_second_tail_passes(
    capsys: pytest.CaptureFixture[str],
) -> None:
    values = [
        snapshot(5),
        snapshot(5),
        *[
            snapshot(3, p50=190.0, p95=300.0, maximum=330.0)
            for _ in range(6)
        ],
    ]

    exit_code, stdout, stderr = run_sampler(values, capsys)

    assert exit_code == 0
    assert stdout[0:4] == [
        "samples=8",
        "fps_5_count=2",
        "fps_3_count=6",
        "fps_1_count=0",
    ]
    assert stdout[-1] == "performance=PASS mode=3fps"
    assert stderr == ""


def test_three_fps_tail_shorter_than_sixty_seconds_fails(
    capsys: pytest.CaptureFixture[str],
) -> None:
    values = [snapshot(5), snapshot(5), *[snapshot(3) for _ in range(5)]]

    exit_code, stdout, _stderr = run_sampler(values, capsys)

    assert exit_code != 0
    assert stdout[-1] == "performance=FAIL reason=three_fps_unstable"


def test_three_fps_worst_rolling_p95_over_budget_fails(
    capsys: pytest.CaptureFixture[str],
) -> None:
    values = [snapshot(3) for _ in range(5)] + [
        snapshot(3, p50=200.0, p95=300.001, maximum=340.0)
    ]

    exit_code, stdout, _stderr = run_sampler(values, capsys)

    assert exit_code != 0
    assert stdout[-1] == "performance=FAIL reason=three_fps_budget_exceeded"


@pytest.mark.parametrize(
    ("values", "reason"),
    [
        ([snapshot(5), snapshot(1)], "one_fps_observed"),
        (
            [snapshot(5), snapshot(5, model_state="degraded")],
            "model_degraded",
        ),
    ],
)
def test_unsafe_runtime_state_fails_closed(
    capsys: pytest.CaptureFixture[str],
    values: list[dict[str, object]],
    reason: str,
) -> None:
    exit_code, stdout, _stderr = run_sampler(values, capsys)

    assert exit_code != 0
    assert stdout[-1] == f"performance=FAIL reason={reason}"


@pytest.mark.parametrize(
    ("failure", "reason"),
    [
        (RealtimeVisualStatusUnavailableError(), "metrics_unavailable"),
        (RealtimeVisualStatusStaleError(), "metrics_stale"),
        (ValueError("private payload"), "metrics_invalid"),
        (
            RuntimeError("/private/family/realtime-visual.json secret"),
            "metrics_read_failed",
        ),
    ],
)
def test_read_failures_only_report_stable_redacted_reason(
    capsys: pytest.CaptureFixture[str],
    failure: BaseException,
    reason: str,
) -> None:
    exit_code, stdout, stderr = run_sampler([failure], capsys)

    assert exit_code != 0
    assert stdout == [f"performance=FAIL reason={reason}"]
    assert stderr == ""
    assert "private" not in "\n".join(stdout)
    assert "secret" not in "\n".join(stdout)


def test_terminal_interrupt_is_not_converted_to_a_partial_result(
    capsys: pytest.CaptureFixture[str],
) -> None:
    with pytest.raises(KeyboardInterrupt):
        run_sampler([KeyboardInterrupt()], capsys)


def test_make_target_uses_fixed_production_defaults() -> None:
    completed = subprocess.run(
        ["make", "-n", "alpha-visual-performance"],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )

    assert completed.returncode == 0
    assert completed.stderr == ""
    assert completed.stdout.strip() == (
        "./.venv-alpha/bin/python tools/realtime_visual_performance.py"
    )
