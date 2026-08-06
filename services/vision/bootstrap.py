from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field

from packages.contracts.settings import AppSettings
from services.stream.frame_source import Go2RtcAnalysisFrameSource
from services.vision.frame_health import VisualFrameHealthMonitor
from services.vision.frame_policy import VisionFramePolicy
from services.vision.frame_ring import AnalysisFrameRing
from services.vision.ollama_client import OllamaVisualReviewer
from services.vision.review_runtime import VisualReviewRuntime
from services.vision.review_scheduler import VisualReviewScheduler
from services.vision.risk_state import VisualRiskStateMachine
from services.vision.worker import VisualWorker


@dataclass
class VisualRuntimeResources:
    worker: VisualWorker
    runtime: VisualReviewRuntime
    source: Go2RtcAnalysisFrameSource
    policy: VisionFramePolicy
    ring: AnalysisFrameRing
    frame_health: VisualFrameHealthMonitor
    reviewer: OllamaVisualReviewer
    scheduler: VisualReviewScheduler
    risk_machine: VisualRiskStateMachine
    executor: ThreadPoolExecutor
    _closed: bool = field(default=False, init=False, repr=False)

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        self.scheduler.close()
        self.executor.shutdown(wait=False, cancel_futures=True)


def build_visual_runtime(settings: AppSettings) -> VisualRuntimeResources:
    if not settings.visual.enabled:
        raise ValueError("visual_review_disabled")
    if settings.visual.bed_zone is None:
        raise ValueError("VISUAL_BED_ZONE_REQUIRED")

    source = Go2RtcAnalysisFrameSource(
        base_url=_go2rtc_base_url(
            settings.stream.go2rtc_api_host,
            settings.stream.go2rtc_api_port,
        )
    )
    policy = VisionFramePolicy(
        bed_zone=settings.visual.bed_zone,
        privacy_masks=settings.visual.privacy_masks,
    )
    ring = AnalysisFrameRing()
    frame_health = VisualFrameHealthMonitor()
    reviewer = OllamaVisualReviewer(base_url=settings.visual.ollama_base_url)
    executor = ThreadPoolExecutor(
        max_workers=1,
        thread_name_prefix="visual-review",
    )
    scheduler = VisualReviewScheduler(
        reviewer=reviewer.review,
        executor=executor,
    )
    risk_machine = VisualRiskStateMachine()
    runtime = VisualReviewRuntime(risk_machine=risk_machine)
    worker = VisualWorker(
        stream_factory=lambda: source.iter_frames(timeout_seconds=8),
        frame_policy=policy,
        frame_ring=ring,
        frame_health=frame_health,
        review_scheduler=scheduler,
        on_review_completion=runtime.handle,
    )
    return VisualRuntimeResources(
        worker=worker,
        runtime=runtime,
        source=source,
        policy=policy,
        ring=ring,
        frame_health=frame_health,
        reviewer=reviewer,
        scheduler=scheduler,
        risk_machine=risk_machine,
        executor=executor,
    )


def _go2rtc_base_url(host: str, port: int) -> str:
    formatted_host = f"[{host}]" if ":" in host else host
    return f"http://{formatted_host}:{port}"

