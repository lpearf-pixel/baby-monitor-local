from __future__ import annotations

import argparse
import os
import signal
import sys
import threading
from datetime import datetime
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from packages.contracts.settings import AppSettings
from packages.contracts.vision import RiskTransition
from services.environment.local_env import load_local_env_file
from services.notifications.guardian_dispatcher import GuardianNotificationDispatcher
from services.storage.visual_health import VisualHealthStore
from services.storage.visual_risk import StoredVisualRiskEvent, VisualRiskEventStore
from services.vision.bootstrap import build_visual_runtime
from services.vision.evidence_files import GuardianEvidenceFiles
from services.vision.evidence_recorder import GuardianEvidenceRecorder
from services.vision.evidence_retention import (
    GuardianEvidenceRetention,
    GuardianEvidenceRetentionWorker,
)
from services.vision.frame_health import FrameHealthTransition
from services.vision.frame_health_pipeline import VisualFrameHealthPipeline
from services.vision.frame_policy import PreparedAnalysisFrame
from services.vision.notification_config import (
    build_guardian_notifier,
    build_visual_health_notifier,
)
from services.vision.risk_event_pipeline import VisualRiskEventPipeline
from services.vision.realtime_status import (
    RealtimeVisualStatusPublisher,
    RealtimeVisualStatusWriter,
)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run the independent local Qwen visual-review worker."
    )
    parser.add_argument(
        "--settings",
        type=Path,
        required=True,
        help="Path to the strict local YAML settings file.",
    )
    parser.add_argument(
        "--env-file",
        type=Path,
        help="Optional mode-600 local environment file; values are never logged.",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    status_publisher: RealtimeVisualStatusPublisher | None = None
    evidence_recorder: GuardianEvidenceRecorder | None = None
    guardian_dispatcher: GuardianNotificationDispatcher | None = None
    evidence_retention_worker: GuardianEvidenceRetentionWorker | None = None
    try:
        if args.env_file is not None:
            load_local_env_file(args.env_file)
        settings = AppSettings.load(args.settings)
        if not settings.visual.enabled:
            return 0
        data_dir = settings.app.data_dir
        if not data_dir.is_absolute():
            data_dir = ROOT / data_dir
        visual_health_store = VisualHealthStore(
            data_dir / "visual-health.sqlite3"
        )
        visual_health_store.migrate()
        try:
            visual_health_notifier = build_visual_health_notifier(
                settings,
                os.environ,
            )
        except ValueError:
            visual_health_notifier = None
            print("visual_health_notification_disabled", file=sys.stderr)
        visual_health_pipeline = VisualFrameHealthPipeline.restore(
            store=visual_health_store,
            notifier=visual_health_notifier,
        )
        visual_risk_store = VisualRiskEventStore(data_dir / "events.sqlite3")
        visual_risk_store.migrate()
        try:
            guardian_notifier = build_guardian_notifier(settings, os.environ)
        except ValueError:
            guardian_notifier = None
            print("guardian_notification_disabled", file=sys.stderr)
        if guardian_notifier is not None:
            guardian_dispatcher = GuardianNotificationDispatcher(
                store=visual_risk_store,
                notifier=guardian_notifier,
                stream=sys.stderr,
            )

        def handle_event_opened(
            event: StoredVisualRiskEvent,
            transition: RiskTransition,
        ) -> None:
            if evidence_recorder is not None:
                evidence_recorder.start(event, transition)

        visual_risk_pipeline = VisualRiskEventPipeline(
            store=visual_risk_store,
            stream=sys.stderr,
            on_event_opened=handle_event_opened,
        )
        initial_risk_snapshot = visual_risk_pipeline.restore_snapshot(
            datetime.now().astimezone()
        )

        def handle_frame_health(transition: FrameHealthTransition) -> None:
            try:
                visual_health_pipeline.handle(transition)
            except Exception:
                print("visual_health_pipeline_failed", file=sys.stderr)
                raise

        status_publisher = RealtimeVisualStatusPublisher(
            RealtimeVisualStatusWriter(
                ROOT / "runtime/status/realtime-visual.json"
            ),
            on_failure=lambda _code: print(
                "realtime_status_write_failed",
                file=sys.stderr,
            ),
        )

        def handle_safe_frame(frame: PreparedAnalysisFrame) -> None:
            if evidence_recorder is not None:
                evidence_recorder.observe(frame)

        resources = build_visual_runtime(
            settings,
            initial_frame_health_code=visual_health_pipeline.open_code,
            initial_risk_snapshot=initial_risk_snapshot,
            on_frame_health=handle_frame_health,
            on_safe_frame=handle_safe_frame,
            on_risk_transition=visual_risk_pipeline.handle,
            on_realtime_status=status_publisher,
        )
        evidence_files = GuardianEvidenceFiles(data_dir / "guardian-evidence")
        evidence_recorder = GuardianEvidenceRecorder(
            store=visual_risk_store,
            files=evidence_files,
            frame_window=resources.ring.snapshot_window,
            stream=sys.stderr,
        )
        evidence_recorder.recover_interrupted(datetime.now().astimezone())
        evidence_retention = GuardianEvidenceRetention(
            store=visual_risk_store,
            files=evidence_files,
            retention_days=settings.retention.event_retention_days,
            quota_bytes=settings.retention.event_quota_gb * 1024**3,
        )
        evidence_retention_worker = GuardianEvidenceRetentionWorker(
            cleanup=evidence_retention.cleanup,
            stream=sys.stderr,
        )
    except Exception:
        if status_publisher is not None:
            status_publisher.close()
        print("visual_worker_startup_failed", file=sys.stderr)
        return 2

    stop_event = threading.Event()
    guardian_thread: threading.Thread | None = None
    retention_thread: threading.Thread | None = None

    def stop(_signum: int, _frame: object) -> None:
        stop_event.set()

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)
    if guardian_dispatcher is not None:
        def run_guardian_dispatcher() -> None:
            try:
                guardian_dispatcher.run(stop_event)
            except Exception:
                print("guardian_notification_dispatcher_failed", file=sys.stderr)

        try:
            guardian_thread = threading.Thread(
                target=run_guardian_dispatcher,
                name="guardian-notification-dispatcher",
                daemon=True,
            )
            guardian_thread.start()
        except Exception:
            guardian_thread = None
            print("guardian_notification_disabled", file=sys.stderr)
    if evidence_retention_worker is not None:
        def run_evidence_retention() -> None:
            try:
                evidence_retention_worker.run(stop_event)
            except Exception:
                evidence_retention_worker.report_unavailable()

        try:
            retention_thread = threading.Thread(
                target=run_evidence_retention,
                name="guardian-evidence-retention",
                daemon=True,
            )
            retention_thread.start()
        except Exception:
            retention_thread = None
            evidence_retention_worker.report_unavailable()
    runtime_failed = False
    try:
        resources.worker.run(stop_event)
    except Exception:
        runtime_failed = True
    finally:
        stop_event.set()
        if guardian_thread is not None:
            guardian_thread.join(timeout=20)
            if guardian_thread.is_alive():
                print("guardian_notification_stop_timeout", file=sys.stderr)
        if retention_thread is not None:
            retention_thread.join(timeout=20)
            if retention_thread.is_alive():
                assert evidence_retention_worker is not None
                evidence_retention_worker.report_unavailable()
        try:
            if evidence_recorder is not None:
                evidence_recorder.close(datetime.now().astimezone())
        except Exception:
            pass
        try:
            resources.close()
        except Exception:
            runtime_failed = True
        try:
            assert status_publisher is not None
            status_publisher.close()
        except Exception:
            runtime_failed = True
    if runtime_failed:
        print("visual_worker_runtime_failed", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
