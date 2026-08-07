from __future__ import annotations

import json
import stat
import threading
import time
from dataclasses import replace
from pathlib import Path

import pytest

from services.vision.realtime_status import RealtimeVisualMetricsSnapshot


def snapshot() -> RealtimeVisualMetricsSnapshot:
    return RealtimeVisualMetricsSnapshot(
        realtime_fps=3,
        sample_count=7,
        processing_p50_ms=101.1254,
        processing_p95_ms=202.2505,
        processing_max_ms=303.3756,
        realtime_model_state="available",
    )


def writer_for(path: Path, *, wall_clock: float = 1_754_560_000.125):
    from services.vision import realtime_status

    return realtime_status.RealtimeVisualStatusWriter(
        path,
        wall_clock=lambda: wall_clock,
    )


def test_writer_publishes_exact_schema_with_mode_six_hundred(tmp_path: Path) -> None:
    target = tmp_path / "status" / "realtime-visual.json"

    writer_for(target)(snapshot())

    assert json.loads(target.read_text(encoding="utf-8")) == {
        "schema_version": 1,
        "written_at_unix": 1_754_560_000.125,
        "realtime_fps": 3,
        "sample_count": 7,
        "processing_p50_ms": 101.125,
        "processing_p95_ms": 202.251,
        "processing_max_ms": 303.376,
        "realtime_model_state": "available",
    }
    assert stat.S_IMODE(target.stat().st_mode) == 0o600
    assert list(target.parent.iterdir()) == [target]


def test_writer_atomically_replaces_existing_target_and_permissions(
    tmp_path: Path,
) -> None:
    target = tmp_path / "realtime-visual.json"
    target.write_text("old-private-content", encoding="utf-8")
    target.chmod(0o644)
    updated = replace(
        snapshot(),
        realtime_fps=1,
        sample_count=1,
        processing_p50_ms=9.0,
        processing_p95_ms=9.0,
        processing_max_ms=9.0,
        realtime_model_state="degraded",
    )

    writer_for(target, wall_clock=42.0)(updated)

    payload = json.loads(target.read_text(encoding="utf-8"))
    assert payload["written_at_unix"] == 42.0
    assert payload["realtime_fps"] == 1
    assert payload["realtime_model_state"] == "degraded"
    assert stat.S_IMODE(target.stat().st_mode) == 0o600
    assert list(tmp_path.iterdir()) == [target]


def test_writer_rounds_large_finite_processing_values(tmp_path: Path) -> None:
    target = tmp_path / "realtime-visual.json"
    large = replace(
        snapshot(),
        processing_p50_ms=1e30,
        processing_p95_ms=1e30,
        processing_max_ms=1e30,
    )

    writer_for(target)(large)

    payload = json.loads(target.read_text(encoding="utf-8"))
    assert payload["processing_p50_ms"] == 1e30
    assert payload["processing_p95_ms"] == 1e30
    assert payload["processing_max_ms"] == 1e30


def test_publisher_coalesces_slow_writes_without_blocking_callers() -> None:
    from services.vision import realtime_status

    started = threading.Event()
    release = threading.Event()
    written: list[RealtimeVisualMetricsSnapshot] = []

    def slow_writer(item: RealtimeVisualMetricsSnapshot) -> None:
        written.append(item)
        if len(written) == 1:
            started.set()
            assert release.wait(timeout=2.0)

    publisher = realtime_status.RealtimeVisualStatusPublisher(slow_writer)
    try:
        publisher(replace(snapshot(), sample_count=1))
        assert started.wait(timeout=1.0)

        before = time.monotonic()
        for sample_count in range(2, 21):
            publisher(replace(snapshot(), sample_count=sample_count))
        elapsed = time.monotonic() - before

        assert elapsed < 0.1
        release.set()
        publisher.close()
    finally:
        release.set()
        publisher.close()

    assert [item.sample_count for item in written] == [1, 20]


def test_publisher_reports_only_stable_code_when_sole_write_fails() -> None:
    from services.vision import realtime_status

    failures: list[str] = []

    def fail_writer(_item: RealtimeVisualMetricsSnapshot) -> None:
        raise RuntimeError("/private/household/realtime-visual.json")

    publisher = realtime_status.RealtimeVisualStatusPublisher(
        fail_writer,
        on_failure=failures.append,
    )

    publisher(snapshot())
    publisher.close()

    assert failures == ["realtime_status_write_failed"]
    assert "/private" not in repr(failures)


def test_publisher_reports_failure_from_final_coalesced_write() -> None:
    from services.vision import realtime_status

    started = threading.Event()
    release = threading.Event()
    written: list[int] = []
    failures: list[str] = []

    def writer(item: RealtimeVisualMetricsSnapshot) -> None:
        written.append(item.sample_count)
        if len(written) == 1:
            started.set()
            assert release.wait(timeout=2.0)
            return
        raise RuntimeError("secret final write detail")

    publisher = realtime_status.RealtimeVisualStatusPublisher(
        writer,
        on_failure=failures.append,
    )
    try:
        publisher(replace(snapshot(), sample_count=1))
        assert started.wait(timeout=1.0)
        for sample_count in range(2, 21):
            publisher(replace(snapshot(), sample_count=sample_count))
        release.set()
        publisher.close()
    finally:
        release.set()
        publisher.close()

    assert written == [1, 20]
    assert failures == ["realtime_status_write_failed"]
    assert "secret" not in repr(failures)


@pytest.mark.parametrize(
    "invalid",
    [
        replace(snapshot(), realtime_fps=2),
        replace(snapshot(), realtime_fps=True),
        replace(snapshot(), sample_count=0),
        replace(snapshot(), sample_count=52),
        replace(snapshot(), sample_count=True),
        replace(snapshot(), processing_p50_ms=float("nan")),
        replace(snapshot(), processing_p95_ms=float("inf")),
        replace(snapshot(), processing_max_ms=-1.0),
        replace(
            snapshot(),
            processing_p50_ms=203.0,
            processing_p95_ms=202.0,
        ),
        replace(
            snapshot(),
            processing_p95_ms=304.0,
            processing_max_ms=303.0,
        ),
        replace(snapshot(), realtime_model_state="disabled"),
    ],
)
def test_writer_rejects_invalid_snapshot_before_filesystem_mutation(
    tmp_path: Path,
    invalid: RealtimeVisualMetricsSnapshot,
) -> None:
    target = tmp_path / "status" / "realtime-visual.json"

    with pytest.raises(ValueError, match="invalid realtime metrics snapshot"):
        writer_for(target)(invalid)

    assert not target.parent.exists()


@pytest.mark.parametrize("wall_clock", [-1.0, float("nan"), float("inf")])
def test_writer_rejects_invalid_wall_clock_before_filesystem_mutation(
    tmp_path: Path,
    wall_clock: float,
) -> None:
    target = tmp_path / "status" / "realtime-visual.json"

    with pytest.raises(ValueError, match="invalid realtime metrics snapshot"):
        writer_for(target, wall_clock=wall_clock)(snapshot())

    assert not target.parent.exists()
