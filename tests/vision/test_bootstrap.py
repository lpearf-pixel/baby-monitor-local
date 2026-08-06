from __future__ import annotations

from packages.contracts.settings import (
    AppSettings,
    CameraSettings,
    NotificationSettings,
    SecuritySettings,
    VisualSettings,
)
from packages.contracts.vision import NormalizedPoint, NormalizedPolygon
from services.stream.frame_source import Go2RtcAnalysisFrameSource
from services.vision.frame_health import VisualFrameHealthMonitor
from services.vision.frame_policy import VisionFramePolicy
from services.vision.frame_ring import AnalysisFrameRing
from services.vision.ollama_client import OllamaVisualReviewer
from services.vision.review_runtime import VisualReviewRuntime
from services.vision.review_scheduler import VisualReviewScheduler
from services.vision.risk_state import VisualRiskStateMachine
from services.vision.worker import VisualWorker


def bed_zone() -> NormalizedPolygon:
    return NormalizedPolygon(
        points=(
            NormalizedPoint(x=0.2, y=0.2),
            NormalizedPoint(x=0.8, y=0.2),
            NormalizedPoint(x=0.8, y=0.8),
            NormalizedPoint(x=0.2, y=0.8),
        )
    )


def settings(*, enabled: bool = True) -> AppSettings:
    return AppSettings(
        camera=CameraSettings(
            identifier="nursery-main",
            model="MJSXJ17CM",
            account_secret_env="MI_ACCOUNT_SECRET_REF",
        ),
        visual=VisualSettings(
            enabled=enabled,
            bed_zone=bed_zone() if enabled else None,
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

