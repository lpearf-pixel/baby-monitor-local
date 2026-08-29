from __future__ import annotations

import math
import time
from collections import Counter
from collections.abc import Callable, Iterator, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from io import StringIO
from pathlib import Path
from typing import Literal, Protocol

from packages.contracts.private_visual_overlay import PrivateAssetMetadata
from packages.contracts.vision import (
    NormalizedPolygon,
    RealtimeCandidateTransition,
    RealtimeObservation,
    RiskTransition,
    VisualReview,
)
from packages.contracts.visual_corpus import (
    GuardianReplayAggregate,
    ReplayResult,
    VisualCorpusClip,
)
from services.events.guardian_query import GuardianEventQueryService
from services.storage.visual_risk import VisualRiskEventStore
from services.stream.file_frame_source import (
    FileFrameSourceUnavailable,
    FfmpegFileFrameSource,
)
from services.stream.frame_source import CapturedFrame
from services.vision.frame_health import VisualFrameHealthMonitor
from services.vision.frame_policy import VisionFramePolicy
from services.vision.frame_ring import AnalysisFrameRing
from services.vision.realtime_analyzer import RealtimeVisualAnalyzer
from services.vision.realtime_candidates import RealtimeCandidateStateMachine
from services.vision.realtime_load import RealtimeLoadController
from services.vision.realtime_models import RealtimeModelBackend
from services.vision.review_runtime import ReviewRuntimeCode, VisualReviewRuntime
from services.vision.review_scheduler import ReviewCompletion, ReviewCompletionCode
from services.vision.risk_event_pipeline import VisualRiskEventPipeline
from services.vision.risk_state import VisualRiskStateMachine
from services.vision.worker import VisualWorker


REPLAY_STARTED_AT = datetime(2000, 1, 1, tzinfo=UTC)
MAX_REPLAY_FRAMES = 600
MAX_AGGREGATE_KEYS = 128


class PrivateReplayProjectionError(ValueError):
    """Stable failure for a private replay identity projection."""


@dataclass(frozen=True)
class PrivateReplayProjection:
    clip_id: str
    groups: tuple[str, ...]


def private_replay_projections(
    assets: Sequence[PrivateAssetMetadata],
    *,
    mapping: Mapping[str, str],
) -> tuple[PrivateReplayProjection, ...]:
    asset_ids = [asset.private_asset_id for asset in assets]
    digests = [asset.sha256 for asset in assets]
    mapping_values = list(mapping.values())
    if (
        not 1 <= len(assets) <= 20
        or len(set(asset_ids)) != len(asset_ids)
        or len(set(digests)) != len(digests)
        or set(mapping) != set(asset_ids)
        or len(mapping_values) != len(set(mapping_values))
        or any(not isinstance(value, str) or not value for value in mapping_values)
    ):
        raise PrivateReplayProjectionError("private_overlay_duplicate_clip")

    return tuple(
        PrivateReplayProjection(
            clip_id=asset.private_asset_id,
            groups=tuple(
                sorted({f"scenario:{scenario.value}" for scenario in asset.scenario_ids})
            ),
        )
        for asset in sorted(assets, key=lambda item: item.private_asset_id)
    )


class ReplayFrameSource(Protocol):
    def iter_frames(
        self,
        *,
        started_at: datetime,
        pace: bool = False,
    ) -> Iterator[CapturedFrame]: ...


@dataclass(frozen=True)
class GuardianReplayReview:
    observed_at: datetime
    review: VisualReview

    def __post_init__(self) -> None:
        if self.observed_at.tzinfo is None or self.observed_at.utcoffset() is None:
            raise ValueError("guardian_review_time_invalid")


class GuardianSemanticProvider(Protocol):
    def collect(self) -> Sequence[GuardianReplayReview]: ...

    def close(self) -> None: ...


GuardianSemanticProfile = Literal[
    "realtime_only",
    "semantic_existing",
    "synthetic_test",
]


class GuardianReplayProjector:
    """Runs current Guardian rules against an isolated, new event store."""

    def __init__(
        self,
        *,
        database_path: Path,
        semantic_provider: GuardianSemanticProvider | None = None,
    ) -> None:
        self._database_path = Path(database_path)
        self._semantic_provider = semantic_provider

    def run(
        self,
        *,
        semantic_profile: GuardianSemanticProfile,
        reviews: Sequence[GuardianReplayReview] = (),
    ) -> GuardianReplayAggregate:
        if semantic_profile == "realtime_only":
            return _empty_guardian_result(
                semantic_profile=semantic_profile,
                status="PASS",
                reason="ok",
            )

        selected_reviews: Sequence[GuardianReplayReview]
        if semantic_profile == "semantic_existing":
            if self._semantic_provider is None:
                return _empty_guardian_result(
                    semantic_profile=semantic_profile,
                    status="SKIP",
                    reason="semantic_reviewer_unavailable",
                )
            try:
                selected_reviews = tuple(self._semantic_provider.collect())
            except Exception:
                return _empty_guardian_result(
                    semantic_profile=semantic_profile,
                    status="FAIL",
                    reason="semantic_review_failed",
                )
            finally:
                try:
                    self._semantic_provider.close()
                except Exception:
                    pass
            if not selected_reviews:
                return _empty_guardian_result(
                    semantic_profile=semantic_profile,
                    status="SKIP",
                    reason="semantic_reviewer_unavailable",
                )
        else:
            selected_reviews = tuple(reviews)

        if not _guardian_sequence_is_valid(selected_reviews):
            return _empty_guardian_result(
                semantic_profile=semantic_profile,
                status="FAIL",
                reason="guardian_review_sequence_invalid",
            )
        if self._database_path.exists() or self._database_path.is_symlink():
            return _empty_guardian_result(
                semantic_profile=semantic_profile,
                status="FAIL",
                reason="guardian_store_not_empty",
            )
        if _path_has_symlink(self._database_path.parent):
            return _empty_guardian_result(
                semantic_profile=semantic_profile,
                status="FAIL",
                reason="guardian_store_unsafe",
            )

        transition_counts: Counter[str] = Counter()
        log = StringIO()
        try:
            store = VisualRiskEventStore(self._database_path)
            store.migrate()
            event_sequence = iter(
                f"corpus-event-{index:04d}" for index in range(1, 33)
            )
            pipeline = VisualRiskEventPipeline(
                store=store,
                stream=log,
                event_id_factory=lambda: next(event_sequence),
            )
            current_time = [selected_reviews[0].observed_at]
            current_tick = [0.0]

            def handle_transition(transition: RiskTransition) -> None:
                risk = (
                    transition.risk_kind.value
                    if transition.risk_kind is not None
                    else "none"
                )
                key = f"{transition.transition_kind.value}.{risk}"
                if key not in transition_counts and len(transition_counts) >= 32:
                    raise ValueError("guardian_transition_overflow")
                transition_counts[key] += 1
                pipeline.handle(transition)

            runtime = VisualReviewRuntime(
                risk_machine=VisualRiskStateMachine(),
                now=lambda: current_time[0],
                monotonic=lambda: current_tick[0],
                on_risk_transition=handle_transition,
            )
            first_at = selected_reviews[0].observed_at
            for item in selected_reviews:
                current_time[0] = item.observed_at
                current_tick[0] = (item.observed_at - first_at).total_seconds()
                update = runtime.handle(
                    ReviewCompletion(
                        code=ReviewCompletionCode.OK,
                        review=item.review,
                    )
                )
                if update.code is not ReviewRuntimeCode.OK:
                    raise RuntimeError("guardian_runtime_failed")
            if "guardian.persistence_failed" in log.getvalue() or (
                "guardian.notification_queue_failed" in log.getvalue()
            ):
                raise RuntimeError("guardian_persistence_failed")
            if store.integrity_check() != "ok":
                raise RuntimeError("guardian_integrity_failed")
            events = store.list_events()
            dashboard = GuardianEventQueryService(self._database_path).recent_events()
        except Exception:
            return _empty_guardian_result(
                semantic_profile=semantic_profile,
                status="FAIL",
                reason="guardian_projection_failed",
            )

        event_counts = Counter(
            f"{event.risk_kind.value}.{event.state}" for event in events
        )
        return GuardianReplayAggregate(
            status="PASS",
            reason="ok",
            semantic_profile=semantic_profile,
            transition_counts=dict(sorted(transition_counts.items())),
            event_counts=dict(sorted(event_counts.items())),
            dashboard_event_count=len(dashboard.events),
            dashboard_open_event_count=sum(
                event.state == "open" for event in dashboard.events
            ),
            production_state_touched=False,
            notification_dispatch_attempted=False,
            evidence_persisted=False,
        )


@dataclass(frozen=True)
class ReplayProfile:
    profile_id: Literal["analysis_realtime", "analysis_slow"]
    fps: Literal[1, 5]
    model_backend: RealtimeModelBackend | None = field(default=None, repr=False)
    require_model: bool = True

    def __post_init__(self) -> None:
        expected_fps = 5 if self.profile_id == "analysis_realtime" else 1
        if self.fps != expected_fps:
            raise ValueError("visual_corpus_profile_invalid")


class RecordingRealtimeAnalyzer:
    """Delegates to the production analyzer and retains aggregates only."""

    def __init__(self, delegate: object) -> None:
        self._delegate = delegate
        self.observation_counts: Counter[str] = Counter()
        self.processing_ms: list[float] = []

    @property
    def model_state(self) -> str:
        return str(getattr(self._delegate, "model_state", "degraded"))

    def pop_health_transition(self) -> str | None:
        method = getattr(self._delegate, "pop_health_transition")
        result = method()
        return result if isinstance(result, str) else None

    def analyze(
        self,
        frame: object,
        *,
        monotonic_now: float,
    ) -> RealtimeObservation:
        method = getattr(self._delegate, "analyze")
        observation = method(frame, monotonic_now=monotonic_now)
        if not isinstance(observation, RealtimeObservation):
            raise ValueError("visual_corpus_observation_invalid")
        self._record(observation)
        return observation

    def _record(self, observation: RealtimeObservation) -> None:
        values = {
            f"scene_quality.{observation.scene_quality.value}",
            f"pose_count.{_count_bucket(observation.pose_count)}",
            f"face_count.{_count_bucket(observation.face_count)}",
            f"bed_subject_track.{observation.bed_subject_track.value}",
            f"adult_track.{observation.adult_track.value}",
            f"head_face_state.{observation.head_face_state.value}",
        }
        if len(self.observation_counts.keys() | values) > MAX_AGGREGATE_KEYS:
            raise ValueError("visual_corpus_aggregate_overflow")
        self.observation_counts.update(values)
        if len(self.processing_ms) >= MAX_REPLAY_FRAMES:
            raise ValueError("visual_corpus_result_overflow")
        self.processing_ms.append(observation.processing_ms)


class _NullReviewScheduler:
    def poll(self) -> None:
        return None

    def try_submit(self, *args: object, **kwargs: object) -> None:
        return None

    def close(self) -> None:
        return None


PreparedResolver = Callable[[VisualCorpusClip, ReplayProfile], Path]
SourceFactory = Callable[[Path, Literal[1, 5]], ReplayFrameSource]
AnalyzerFactory = Callable[[ReplayProfile], object]


class VisualCorpusReplay:
    def __init__(
        self,
        *,
        prepared_resolver: PreparedResolver,
        source_factory: SourceFactory | None = None,
        analyzer_factory: AnalyzerFactory | None = None,
        perf_counter: Callable[[], float] = time.perf_counter,
    ) -> None:
        self._prepared_resolver = prepared_resolver
        self._source_factory = source_factory or _default_source_factory
        self._analyzer_factory = analyzer_factory or _default_analyzer_factory
        self._perf_counter = perf_counter
        self.last_recording_analyzer: RecordingRealtimeAnalyzer | None = None

    def run_clip(
        self,
        clip: VisualCorpusClip,
        *,
        profile: ReplayProfile,
    ) -> ReplayResult:
        if profile.require_model and profile.model_backend is None:
            return _empty_result(
                clip.clip_id,
                status="SKIP",
                reason="visual_corpus_model_unavailable",
                model_state="unavailable",
                groups=_comparison_groups(clip),
            )
        try:
            prepared_path = self._prepared_resolver(clip, profile)
            if not isinstance(prepared_path, Path):
                raise ValueError
            source = self._source_factory(prepared_path, profile.fps)
        except Exception:
            return _empty_result(
                clip.clip_id,
                status="FAIL",
                reason="visual_corpus_input_invalid",
                model_state=_initial_model_state(profile),
                groups=_comparison_groups(clip),
            )

        try:
            delegate = self._analyzer_factory(profile)
            analyzer = RecordingRealtimeAnalyzer(delegate)
            self.last_recording_analyzer = analyzer
            candidates = RealtimeCandidateStateMachine()
            load = RealtimeLoadController()
            candidate_counts: Counter[str] = Counter()
            worker = VisualWorker(
                stream_factory=lambda: iter(()),
                frame_policy=VisionFramePolicy(
                    bed_zone=clip.analysis_region or _full_frame_polygon(),
                    privacy_masks=clip.privacy_masks,
                ),
                frame_ring=AnalysisFrameRing(),
                frame_health=VisualFrameHealthMonitor(),
                review_scheduler=_NullReviewScheduler(),
                realtime_analyzer=analyzer,
                candidate_machine=candidates,
                load_controller=load,
                on_realtime_candidate=lambda transition: _record_candidate(
                    candidate_counts,
                    transition,
                ),
            )
        except Exception:
            return _empty_result(
                clip.clip_id,
                status="FAIL",
                reason="visual_corpus_worker_unavailable",
                model_state=_initial_model_state(profile),
                groups=_comparison_groups(clip),
            )

        frames_total = 0
        frames_processed = 0
        frames_skipped = 0
        decode_errors = 0
        worker_errors = 0
        pipeline_ms: list[float] = []
        status: Literal["PASS", "FAIL", "SKIP"] = "PASS"
        reason = "ok"
        iterator: Iterator[CapturedFrame] | None = None
        try:
            iterator = source.iter_frames(started_at=REPLAY_STARTED_AT, pace=False)
            for frame in iterator:
                frames_total += 1
                if frames_total > MAX_REPLAY_FRAMES:
                    status = "FAIL"
                    reason = "visual_corpus_result_overflow"
                    frames_skipped += 1
                    worker_errors += 1
                    break
                monotonic_now = (
                    frame.captured_at - REPLAY_STARTED_AT
                ).total_seconds()
                started = self._perf_counter()
                try:
                    prepared = worker.run_frame(
                        frame,
                        monotonic_now=monotonic_now,
                    )
                except Exception:
                    pipeline_ms.append(
                        max(0.0, (self._perf_counter() - started) * 1000)
                    )
                    frames_skipped += 1
                    worker_errors += 1
                    status = "FAIL"
                    reason = "visual_corpus_worker_failed"
                    break
                pipeline_ms.append(
                    max(0.0, (self._perf_counter() - started) * 1000)
                )
                if prepared is None:
                    frames_skipped += 1
                else:
                    frames_processed += 1
                health = worker.health()
                if health.code == "frame_policy_failed":
                    worker_errors += 1
                    status = "FAIL"
                    reason = "visual_corpus_worker_failed"
                    break
                if health.code == "realtime_analysis_failed":
                    worker_errors += 1
                    status = "FAIL"
                    reason = "visual_corpus_analysis_failed"
                    break
                if profile.require_model and analyzer.model_state != "available":
                    worker_errors += 1
                    status = "FAIL"
                    reason = "visual_corpus_model_degraded"
                    break
        except FileFrameSourceUnavailable:
            decode_errors += 1
            status = "FAIL"
            reason = "visual_corpus_decode_failed"
        except Exception:
            worker_errors += 1
            status = "FAIL"
            reason = "visual_corpus_worker_failed"
        finally:
            close = getattr(iterator, "close", None)
            if callable(close):
                close()

        processed_distribution = _distribution(analyzer.processing_ms)
        pipeline_distribution = _distribution(pipeline_ms)
        expected_frames = round((clip.end_ms - clip.start_ms) * profile.fps / 1000)
        return ReplayResult(
            clip_id=clip.clip_id,
            status=status,
            reason=reason,
            frames_total=frames_total,
            frames_processed=frames_processed,
            frames_skipped=frames_skipped,
            decode_errors=decode_errors,
            worker_errors=worker_errors,
            model_state=_normalized_model_state(analyzer.model_state),
            observation_counts=dict(analyzer.observation_counts),
            candidate_counts=dict(candidate_counts),
            processing_p50_ms=processed_distribution[0],
            processing_p95_ms=processed_distribution[1],
            processing_max_ms=processed_distribution[2],
            pipeline_p50_ms=pipeline_distribution[0],
            pipeline_p95_ms=pipeline_distribution[1],
            pipeline_max_ms=pipeline_distribution[2],
            dropped_frames=max(0, expected_frames - frames_total),
            queue_backlog_max=0,
            frame_observations_persisted=False,
            groups=_comparison_groups(clip),
        )


def _default_source_factory(
    path: Path,
    fps: Literal[1, 5],
) -> ReplayFrameSource:
    return FfmpegFileFrameSource(path, fps=fps)


def _default_analyzer_factory(profile: ReplayProfile) -> object:
    return RealtimeVisualAnalyzer(model_backend=profile.model_backend)


def _full_frame_polygon() -> NormalizedPolygon:
    return NormalizedPolygon.model_validate(
        {
            "points": [
                {"x": 0.0, "y": 0.0},
                {"x": 1.0, "y": 0.0},
                {"x": 1.0, "y": 1.0},
                {"x": 0.0, "y": 1.0},
            ]
        }
    )


def _record_candidate(
    counts: Counter[str],
    transition: RealtimeCandidateTransition,
) -> None:
    key = (
        f"{transition.transition_kind.value}."
        f"{transition.candidate_kind.value}"
    )
    if key not in counts and len(counts) >= MAX_AGGREGATE_KEYS:
        raise ValueError("visual_corpus_aggregate_overflow")
    counts[key] += 1


def _count_bucket(value: int | None) -> str:
    if value is None:
        return "unknown"
    if value <= 1:
        return str(value)
    return "2plus"


def _distribution(values: list[float]) -> tuple[float, float, float]:
    if not values:
        return (0.0, 0.0, 0.0)
    if any(not math.isfinite(value) or value < 0 for value in values):
        raise ValueError("visual_corpus_metric_invalid")
    ordered = sorted(values)
    return (
        round(_nearest_rank(ordered, 0.50), 3),
        round(_nearest_rank(ordered, 0.95), 3),
        round(ordered[-1], 3),
    )


def _nearest_rank(values: list[float], quantile: float) -> float:
    index = max(0, math.ceil(quantile * len(values)) - 1)
    return values[index]


def _initial_model_state(
    profile: ReplayProfile,
) -> Literal["available", "degraded", "disabled", "unavailable"]:
    return "available" if profile.model_backend is not None else "unavailable"


def _normalized_model_state(
    value: str,
) -> Literal["available", "degraded", "disabled", "unavailable"]:
    if value in {"available", "degraded", "disabled", "unavailable"}:
        return value  # type: ignore[return-value]
    return "degraded"


def _empty_result(
    clip_id: str,
    *,
    status: Literal["PASS", "FAIL", "SKIP"],
    reason: str,
    model_state: Literal["available", "degraded", "disabled", "unavailable"],
    groups: tuple[str, ...] = (),
) -> ReplayResult:
    return ReplayResult(
        clip_id=clip_id,
        status=status,
        reason=reason,
        frames_total=0,
        frames_processed=0,
        frames_skipped=0,
        decode_errors=0,
        worker_errors=0,
        model_state=model_state,
        processing_p50_ms=0,
        processing_p95_ms=0,
        processing_max_ms=0,
        pipeline_p50_ms=0,
        pipeline_p95_ms=0,
        pipeline_max_ms=0,
        dropped_frames=0,
        queue_backlog_max=0,
        frame_observations_persisted=False,
        groups=groups,
    )


def _comparison_groups(clip: VisualCorpusClip) -> tuple[str, ...]:
    labels = clip.labels
    framing = f"framing:{labels.framing.value}"
    scale = f"scale:{labels.subject_scale.value}"
    lighting = f"lighting:{labels.lighting.value}"
    visibility = f"visibility:{labels.baby_visibility.value}"
    wide_role = f"wide_role:{labels.wide_content_role.value}"
    return (
        framing,
        scale,
        lighting,
        visibility,
        wide_role,
        f"{framing}+{lighting}",
        f"{scale}+{visibility}",
    )


def _guardian_sequence_is_valid(
    reviews: Sequence[GuardianReplayReview],
) -> bool:
    if not reviews or len(reviews) > MAX_REPLAY_FRAMES:
        return False
    previous: datetime | None = None
    for item in reviews:
        if not isinstance(item, GuardianReplayReview):
            return False
        if previous is not None and item.observed_at < previous:
            return False
        previous = item.observed_at
    return True


def _path_has_symlink(path: Path) -> bool:
    absolute = path.absolute()
    return any(candidate.is_symlink() for candidate in (absolute, *absolute.parents))


def _empty_guardian_result(
    *,
    semantic_profile: GuardianSemanticProfile,
    status: Literal["PASS", "FAIL", "SKIP"],
    reason: str,
) -> GuardianReplayAggregate:
    return GuardianReplayAggregate(
        status=status,
        reason=reason,
        semantic_profile=semantic_profile,
        transition_counts={},
        event_counts={},
        dashboard_event_count=0,
        dashboard_open_event_count=0,
        production_state_touched=False,
        notification_dispatch_attempted=False,
        evidence_persisted=False,
    )
