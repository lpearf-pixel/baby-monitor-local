from __future__ import annotations

import json
from io import StringIO
from pathlib import Path
import sqlite3
import threading
from types import SimpleNamespace

import pytest

from services.vision.realtime_status import (
    RealtimeVisualMetricsSnapshot,
    RealtimeVisualStatusPublisher,
)
from services.vision.realtime_analyzer import RealtimeStageTiming
from packages.contracts.vision import VisualRiskKind
from services.storage.visual_risk import VisualRiskEventStore


def test_slow_analysis_line_is_fixed_redacted_ascii() -> None:
    from tools.run_visual_worker import _print_slow_analysis

    stream = StringIO()
    _print_slow_analysis(
        RealtimeStageTiming(10.0, 20.0, 190.0, 220.0),
        stream=stream,
    )

    assert stream.getvalue() == (
        "realtime_slow_analysis decode_ms=10.000 features_ms=20.000 "
        "semantic_ms=190.000 total_ms=220.000\n"
    )


class RecordingRing:
    def snapshot_window(self, **_kwargs: object) -> tuple[object, ...]:
        return ()


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
        self.ring = RecordingRing()
        self.closed = False
        self.fail_close = fail_close

    def close(self) -> None:
        self.closed = True
        if self.fail_close:
            raise RuntimeError("/private/household/scheduler-state")


def enabled_settings(data_dir: Path = Path("runtime-data")) -> SimpleNamespace:
    return SimpleNamespace(
        visual=SimpleNamespace(enabled=True),
        app=SimpleNamespace(data_dir=data_dir),
        retention=SimpleNamespace(event_retention_days=30, event_quota_gb=30),
    )


@pytest.fixture(autouse=True)
def disable_guardian_delivery(monkeypatch) -> None:
    from tools import run_visual_worker

    monkeypatch.setattr(
        run_visual_worker,
        "build_guardian_notifier",
        lambda _settings, _environ: None,
    )


def test_main_wires_real_status_writer_into_visual_runtime(
    tmp_path: Path,
    monkeypatch,
) -> None:
    from tools import run_visual_worker

    resources = RecordingResources()
    captured: dict[str, object] = {}
    settings = enabled_settings()

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
    monkeypatch.setattr(
        run_visual_worker,
        "build_visual_health_notifier",
        lambda _settings, _environ: None,
    )

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
    database = tmp_path / "runtime-data/visual-health.sqlite3"
    with sqlite3.connect(database) as connection:
        table = connection.execute(
            """
            SELECT name FROM sqlite_master
            WHERE type = 'table' AND name = 'visual_health_incidents'
            """
        ).fetchone()
    assert table == ("visual_health_incidents",)
    assert callable(captured["on_frame_health"])
    assert captured["initial_frame_health_code"] is None
    assert callable(captured["on_risk_transition"])
    assert callable(captured["on_safe_frame"])
    assert captured["initial_risk_snapshot"].open_risks == frozenset()
    guardian_database = tmp_path / "runtime-data/events.sqlite3"
    with sqlite3.connect(guardian_database) as connection:
        table = connection.execute(
            """
            SELECT name FROM sqlite_master
            WHERE type = 'table' AND name = 'visual_risk_events'
            """
        ).fetchone()
    assert table == ("visual_risk_events",)
    with sqlite3.connect(guardian_database) as connection:
        evidence_table = connection.execute(
            """
            SELECT name FROM sqlite_master
            WHERE type = 'table' AND name = 'visual_risk_evidence'
            """
        ).fetchone()
    assert evidence_table == ("visual_risk_evidence",)


def test_main_restores_open_guardian_event_into_visual_runtime(
    tmp_path: Path,
    monkeypatch,
) -> None:
    from datetime import UTC, datetime
    from tools import run_visual_worker

    data_dir = tmp_path / "runtime-data"
    store = VisualRiskEventStore(data_dir / "events.sqlite3")
    store.migrate()
    store.open_event(
        event_id="event-face",
        risk_kind=VisualRiskKind.FACE_NOT_VISIBLE,
        opened_at=datetime(2026, 8, 11, 12, 0, tzinfo=UTC),
        confidence=0.82,
        rule_version="visual-risk-v1",
    )
    store.begin_evidence(
        event_id="event-face",
        started_at=datetime(2026, 8, 11, 12, 0, tzinfo=UTC),
        capture_deadline=datetime(2026, 8, 11, 12, 0, 30, tzinfo=UTC),
        snapshot_key=None,
        frame_count=0,
    )
    resources = RecordingResources()
    captured: dict[str, object] = {}
    settings = enabled_settings()
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
    monkeypatch.setattr(
        run_visual_worker,
        "build_visual_health_notifier",
        lambda _settings, _environ: None,
    )

    assert run_visual_worker.main(["--settings", str(tmp_path / "settings.yaml")]) == 0
    assert captured["initial_risk_snapshot"].open_risks == frozenset(
        {VisualRiskKind.FACE_NOT_VISIBLE}
    )
    evidence = store.get_evidence("event-face")
    assert evidence is not None
    assert evidence.state == "interrupted"
    assert evidence.failure_code == "worker_restarted"


def test_main_flushes_final_status_when_resource_cleanup_fails(
    tmp_path: Path,
    monkeypatch,
    capsys,
) -> None:
    from tools import run_visual_worker

    resources = RecordingResources(fail_close=True)
    settings = enabled_settings()
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
    monkeypatch.setattr(
        run_visual_worker,
        "build_visual_health_notifier",
        lambda _settings, _environ: None,
    )

    exit_code = run_visual_worker.main(
        ["--settings", str(tmp_path / "settings.yaml")]
    )
    captured = capsys.readouterr()

    assert exit_code == 2
    assert captured.out == ""
    stderr_lines = captured.err.splitlines()
    assert stderr_lines[-1] == "visual_worker_runtime_failed"
    retention_log = json.loads(stderr_lines[0])
    assert retention_log["code"] == "guardian.evidence_retention_completed"
    assert retention_log["result"] == "within_quota"
    assert resources.closed is True
    status_path = tmp_path / "runtime/status/realtime-visual.json"
    payload = json.loads(status_path.read_text(encoding="utf-8"))
    assert payload["sample_count"] == 7


def test_main_starts_and_stops_guardian_dispatcher_thread(
    tmp_path: Path,
    monkeypatch,
) -> None:
    from tools import run_visual_worker

    started = threading.Event()
    stopped = threading.Event()

    class RecordingDispatcher:
        def run(self, stop_event: object) -> None:
            started.set()
            stop_event.wait(1)
            stopped.set()

    class WaitingWorker(RecordingWorker):
        def run(self, _stop_event: object) -> None:
            assert started.wait(1)
            super().run(_stop_event)

    resources = RecordingResources()
    resources.worker = WaitingWorker()
    settings = enabled_settings()
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
    monkeypatch.setattr(
        run_visual_worker,
        "build_visual_health_notifier",
        lambda _settings, _environ: None,
    )
    monkeypatch.setattr(
        run_visual_worker,
        "build_guardian_notifier",
        lambda _settings, _environ: object(),
    )
    monkeypatch.setattr(
        run_visual_worker,
        "GuardianNotificationDispatcher",
        lambda **_kwargs: RecordingDispatcher(),
    )

    assert run_visual_worker.main(["--settings", str(tmp_path / "settings.yaml")]) == 0
    assert started.is_set()
    assert stopped.is_set()


def test_invalid_guardian_notification_config_disables_only_dispatcher(
    tmp_path: Path,
    monkeypatch,
    capsys,
) -> None:
    from tools import run_visual_worker

    resources = RecordingResources()
    settings = enabled_settings()
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
    monkeypatch.setattr(
        run_visual_worker,
        "build_visual_health_notifier",
        lambda _settings, _environ: None,
    )
    monkeypatch.setattr(
        run_visual_worker,
        "build_guardian_notifier",
        lambda _settings, _environ: (_ for _ in ()).throw(ValueError("secret")),
    )

    assert run_visual_worker.main(["--settings", str(tmp_path / "settings.yaml")]) == 0
    captured = capsys.readouterr()
    assert captured.out == ""
    stderr_lines = captured.err.splitlines()
    assert stderr_lines[0] == "guardian_notification_disabled"
    retention_log = json.loads(stderr_lines[1])
    assert retention_log["code"] == "guardian.evidence_retention_completed"
    assert retention_log["result"] == "within_quota"
    assert resources.worker.ran is True


def test_main_wires_central_retention_settings_and_stops_worker_thread(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from tools import run_visual_worker

    started = threading.Event()
    stopped = threading.Event()
    captured: dict[str, object] = {}
    files_sentinel = SimpleNamespace()

    class RecordingRetention:
        def __init__(self, **kwargs: object) -> None:
            captured.update(kwargs)

        def cleanup(self, _now: object) -> None:
            return None

    class RecordingRetentionWorker:
        def __init__(self, *, cleanup: object, stream: object) -> None:
            captured["cleanup"] = cleanup
            captured["stream"] = stream

        def run(self, stop_event: object) -> None:
            started.set()
            stop_event.wait(1)
            stopped.set()

    class WaitingWorker(RecordingWorker):
        def run(self, stop_event: object) -> None:
            assert started.wait(1)
            super().run(stop_event)

    resources = RecordingResources()
    resources.worker = WaitingWorker()
    settings = enabled_settings()
    settings.retention.event_retention_days = 17
    settings.retention.event_quota_gb = 3
    monkeypatch.setattr(run_visual_worker, "ROOT", tmp_path)
    monkeypatch.setattr(run_visual_worker.AppSettings, "load", lambda _path: settings)

    def build_evidence_files(root: Path) -> object:
        captured["evidence_root"] = root
        return files_sentinel

    monkeypatch.setattr(
        run_visual_worker,
        "GuardianEvidenceFiles",
        build_evidence_files,
    )
    monkeypatch.setattr(
        run_visual_worker,
        "GuardianEvidenceRetention",
        RecordingRetention,
        raising=False,
    )
    monkeypatch.setattr(
        run_visual_worker,
        "GuardianEvidenceRetentionWorker",
        RecordingRetentionWorker,
        raising=False,
    )

    def build(_settings: object, **kwargs: object) -> RecordingResources:
        resources.worker.status_callback = kwargs["on_realtime_status"]
        return resources

    monkeypatch.setattr(run_visual_worker, "build_visual_runtime", build)
    monkeypatch.setattr(
        run_visual_worker,
        "build_visual_health_notifier",
        lambda _settings, _environ: None,
    )

    assert run_visual_worker.main(["--settings", str(tmp_path / "settings.yaml")]) == 0
    assert started.is_set()
    assert stopped.is_set()
    assert captured["evidence_root"] == (
        tmp_path / "runtime-data" / "guardian-evidence"
    )
    assert captured["store"].integrity_check() == "ok"
    assert captured["files"] is files_sentinel
    assert captured["retention_days"] == 17
    assert captured["quota_bytes"] == 3 * 1024**3
    assert callable(captured["cleanup"])


def test_unexpected_retention_thread_failure_is_redacted_and_isolated(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    from tools import run_visual_worker

    started = threading.Event()

    class FailingRetentionWorker:
        def __init__(self, **kwargs: object) -> None:
            self.stream = kwargs["stream"]

        def run(self, _stop_event: object) -> None:
            started.set()
            raise RuntimeError("token at /private/guardian-evidence")

        def report_unavailable(self) -> None:
            self.stream.write(
                json.dumps(
                    {
                        "code": "guardian.evidence_retention_failed",
                        "component": "baby_guardian",
                        "observed_at": "2026-08-13T12:00:00+00:00",
                        "result": "retention_unavailable",
                        "schema_version": 1,
                    },
                    sort_keys=True,
                    separators=(",", ":"),
                )
                + "\n"
            )

    class WaitingWorker(RecordingWorker):
        def run(self, stop_event: object) -> None:
            assert started.wait(1)
            super().run(stop_event)

    resources = RecordingResources()
    resources.worker = WaitingWorker()
    settings = enabled_settings()
    monkeypatch.setattr(run_visual_worker, "ROOT", tmp_path)
    monkeypatch.setattr(run_visual_worker.AppSettings, "load", lambda _path: settings)
    monkeypatch.setattr(
        run_visual_worker,
        "GuardianEvidenceRetention",
        lambda **_kwargs: SimpleNamespace(cleanup=lambda _now: None),
        raising=False,
    )
    monkeypatch.setattr(
        run_visual_worker,
        "GuardianEvidenceRetentionWorker",
        FailingRetentionWorker,
        raising=False,
    )

    def build(_settings: object, **kwargs: object) -> RecordingResources:
        resources.worker.status_callback = kwargs["on_realtime_status"]
        return resources

    monkeypatch.setattr(run_visual_worker, "build_visual_runtime", build)
    monkeypatch.setattr(
        run_visual_worker,
        "build_visual_health_notifier",
        lambda _settings, _environ: None,
    )

    assert run_visual_worker.main(["--settings", str(tmp_path / "settings.yaml")]) == 0
    output = capsys.readouterr()
    assert output.out == ""
    retention_log = json.loads(output.err)
    assert retention_log["code"] == "guardian.evidence_retention_failed"
    assert retention_log["result"] == "retention_unavailable"
    assert resources.worker.ran is True
    assert "token" not in output.err
    assert "private" not in output.err
