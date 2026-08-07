from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

from services.vision.realtime_status import (
    RealtimeVisualMetricsSnapshot,
    RealtimeVisualStatusPublisher,
)


class RecordingWorker:
    def __init__(self) -> None:
        self.ran = False
        self.status_callback = None

    def run(self, _stop_event: object) -> None:
        self.ran = True
        assert self.status_callback is not None
        self.status_callback(
            RealtimeVisualMetricsSnapshot(
                realtime_fps=3,
                sample_count=7,
                processing_p50_ms=101.125,
                processing_p95_ms=202.25,
                processing_max_ms=303.375,
                realtime_model_state="available",
            )
        )


class RecordingResources:
    def __init__(self, *, fail_close: bool = False) -> None:
        self.worker = RecordingWorker()
        self.closed = False
        self.fail_close = fail_close

    def close(self) -> None:
        self.closed = True
        if self.fail_close:
            raise RuntimeError("/private/household/scheduler-state")


def test_main_wires_real_status_writer_into_visual_runtime(
    tmp_path: Path,
    monkeypatch,
) -> None:
    from tools import run_visual_worker

    resources = RecordingResources()
    captured: dict[str, object] = {}
    settings = SimpleNamespace(visual=SimpleNamespace(enabled=True))

    monkeypatch.setattr(run_visual_worker, "ROOT", tmp_path)
    monkeypatch.setattr(
        run_visual_worker.AppSettings,
        "load",
        lambda _path: settings,
    )

    def build(_settings: object, **kwargs: object) -> RecordingResources:
        captured.update(kwargs)
        resources.worker.status_callback = kwargs["on_realtime_status"]
        return resources

    monkeypatch.setattr(run_visual_worker, "build_visual_runtime", build)

    exit_code = run_visual_worker.main(
        ["--settings", str(tmp_path / "settings.yaml")]
    )

    assert exit_code == 0
    assert resources.worker.ran is True
    assert resources.closed is True
    callback = captured["on_realtime_status"]
    assert isinstance(callback, RealtimeVisualStatusPublisher)
    status_path = tmp_path / "runtime/status/realtime-visual.json"
    payload = json.loads(status_path.read_text(encoding="utf-8"))
    assert payload["realtime_fps"] == 3
    assert payload["sample_count"] == 7


def test_main_flushes_final_status_when_resource_cleanup_fails(
    tmp_path: Path,
    monkeypatch,
    capsys,
) -> None:
    from tools import run_visual_worker

    resources = RecordingResources(fail_close=True)
    settings = SimpleNamespace(visual=SimpleNamespace(enabled=True))
    monkeypatch.setattr(run_visual_worker, "ROOT", tmp_path)
    monkeypatch.setattr(
        run_visual_worker.AppSettings,
        "load",
        lambda _path: settings,
    )

    def build(_settings: object, **kwargs: object) -> RecordingResources:
        resources.worker.status_callback = kwargs["on_realtime_status"]
        return resources

    monkeypatch.setattr(run_visual_worker, "build_visual_runtime", build)

    exit_code = run_visual_worker.main(
        ["--settings", str(tmp_path / "settings.yaml")]
    )
    captured = capsys.readouterr()

    assert exit_code == 2
    assert captured.out == ""
    assert captured.err == "visual_worker_runtime_failed\n"
    assert resources.closed is True
    status_path = tmp_path / "runtime/status/realtime-visual.json"
    payload = json.loads(status_path.read_text(encoding="utf-8"))
    assert payload["sample_count"] == 7
