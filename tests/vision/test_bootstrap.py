from __future__ import annotations

from packages.contracts.settings import (
    AppSettings,
    CameraSettings,
    NotificationSettings,
    SecuritySettings,
    RealtimeVisualSettings,
    VisualSettings,
)
from datetime import UTC, datetime

from packages.contracts.vision import (
    NormalizedPoint,
    NormalizedPolygon,
    RiskSnapshot,
    VisualRiskKind,
    VisualRiskState,
)
from services.stream.frame_source import Go2RtcAnalysisFrameSource
from services.vision.frame_health import VisualFrameHealthMonitor
from services.vision.frame_policy import VisionFramePolicy
from services.vision.frame_ring import AnalysisFrameRing
from services.vision.ollama_client import OllamaVisualReviewer
from services.vision.review_runtime import VisualReviewRuntime
from services.vision.review_scheduler import VisualReviewScheduler
from services.vision.risk_state import VisualRiskStateMachine
from services.vision.worker import VisualWorker
from services.vision.realtime_analyzer import RealtimeVisualAnalyzer
from services.vision.realtime_candidates import RealtimeCandidateStateMachine
from services.vision.realtime_load import RealtimeLoadController


def bed_zone() -> NormalizedPolygon:
    return NormalizedPolygon(
        points=(
            NormalizedPoint(x=0.2, y=0.2),
            NormalizedPoint(x=0.8, y=0.2),
            NormalizedPoint(x=0.8, y=0.8),
            NormalizedPoint(x=0.2, y=0.8),
        )
    )


def settings(*, enabled: bool = True, realtime_enabled: bool = False) -> AppSettings:
    return AppSettings(
        camera=CameraSettings(
            identifier="nursery-main",
            model="MJSXJ17CM",
            account_secret_env="MI_ACCOUNT_SECRET_REF",
        ),
        visual=VisualSettings(
            enabled=enabled,
            bed_zone=bed_zone() if enabled else None,
            realtime=RealtimeVisualSettings(enabled=realtime_enabled),
        ),
        notifications=NotificationSettings(
            ntfy_topic="replace-with-private-topic",
            ntfy_token_env="NTFY_TOKEN",
            enable_wecom=False,
        ),
        security=SecuritySettings(session_secret_env="SESSION_SECRET_REF"),
    )


def test_bootstrap_composes_one_owned_visual_runtime() -> None:
    from services.vision.bootstrap import build_visual_runtime

    resources = build_visual_runtime(settings())
    try:
        assert isinstance(resources.worker, VisualWorker)
        assert isinstance(resources.runtime, VisualReviewRuntime)
        assert isinstance(resources.source, Go2RtcAnalysisFrameSource)
        assert isinstance(resources.policy, VisionFramePolicy)
        assert isinstance(resources.ring, AnalysisFrameRing)
        assert isinstance(resources.frame_health, VisualFrameHealthMonitor)
        assert isinstance(resources.reviewer, OllamaVisualReviewer)
        assert isinstance(resources.scheduler, VisualReviewScheduler)
        assert isinstance(resources.risk_machine, VisualRiskStateMachine)
        assert resources.executor._max_workers == 1
    finally:
        resources.close()


def test_bootstrap_rejects_disabled_visual_runtime_before_composition() -> None:
    from services.vision.bootstrap import build_visual_runtime

    try:
        build_visual_runtime(settings(enabled=False))
    except ValueError as failure:
        assert str(failure) == "visual_review_disabled"
    else:
        raise AssertionError("disabled visual runtime was composed")


def test_resource_close_is_idempotent() -> None:
    from services.vision.bootstrap import build_visual_runtime

    resources = build_visual_runtime(settings())

    resources.close()
    resources.close()


def test_bootstrap_composes_opt_in_realtime_path_without_models() -> None:
    from services.vision.bootstrap import build_visual_runtime

    resources = build_visual_runtime(settings(realtime_enabled=True))
    try:
        assert resources.source._stream_name == "analysis_realtime"
        assert isinstance(resources.realtime_analyzer, RealtimeVisualAnalyzer)
        assert isinstance(
            resources.candidate_machine,
            RealtimeCandidateStateMachine,
        )
        assert isinstance(resources.load_controller, RealtimeLoadController)
    finally:
        resources.close()


def test_bootstrap_delivers_realtime_status_callback_to_worker() -> None:
    from services.vision.bootstrap import build_visual_runtime

    received: list[object] = []
    resources = build_visual_runtime(
        settings(realtime_enabled=True),
        on_realtime_status=received.append,
    )
    marker = object()
    try:
        resources.worker._on_realtime_status(marker)
        assert received == [marker]
    finally:
        resources.close()


def test_bootstrap_delivers_frame_health_callback_to_worker() -> None:
    from services.vision.bootstrap import build_visual_runtime

    received: list[object] = []
    resources = build_visual_runtime(
        settings(),
        on_frame_health=received.append,
    )
    marker = object()
    try:
        resources.worker._on_frame_health(marker)
        assert received == [marker]
    finally:
        resources.close()


def test_bootstrap_delivers_safe_frame_callback_to_worker() -> None:
    from services.vision.bootstrap import build_visual_runtime

    received: list[object] = []
    resources = build_visual_runtime(
        settings(),
        on_safe_frame=received.append,
    )
    marker = object()
    try:
        resources.worker._on_safe_frame(marker)
        assert received == [marker]
    finally:
        resources.close()


def test_bootstrap_restores_open_frame_health_code() -> None:
    from services.vision.bootstrap import build_visual_runtime
    from services.vision.frame_health import FrameHealthCode

    resources = build_visual_runtime(
        settings(),
        initial_frame_health_code=FrameHealthCode.SOURCE_OFFLINE,
    )
    try:
        assert resources.frame_health.open_code is FrameHealthCode.SOURCE_OFFLINE
    finally:
        resources.close()


def test_bootstrap_restores_open_guardian_risks_and_injects_callback() -> None:
    from services.vision.bootstrap import build_visual_runtime

    received: list[object] = []
    snapshot = RiskSnapshot(
        snapshot_at=datetime(2026, 8, 11, 12, 0, tzinfo=UTC),
        open_risks=frozenset({VisualRiskKind.FACE_NOT_VISIBLE}),
    )

    resources = build_visual_runtime(
        settings(),
        initial_risk_snapshot=snapshot,
        on_risk_transition=received.append,
    )
    marker = object()
    try:
        assert (
            resources.risk_machine.state_for(VisualRiskKind.FACE_NOT_VISIBLE)
            is VisualRiskState.ALERT
        )
        resources.runtime._on_risk_transition(marker)
        assert received == [marker]
    finally:
        resources.close()
