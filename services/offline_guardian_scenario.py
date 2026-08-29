from __future__ import annotations

import os
import stat
from pathlib import Path

from packages.contracts.offline_guardian_scenario import (
    OfflineGuardianScenarioV1,
    ScenarioLaneResult,
)
from packages.contracts.visual_corpus import VisualCorpusManifest
from services.vision.corpus_replay import (
    GuardianReplayProjector,
    GuardianReplayReview,
    PreparedResolver,
    ReplayProfile,
    VisualCorpusReplay,
)
from services.vision.realtime_models import RealtimeModelBackend


def run_visual_lane(
    scenario: OfflineGuardianScenarioV1,
    manifest: VisualCorpusManifest,
    prepared_resolver: PreparedResolver,
    model_backend: RealtimeModelBackend | None,
) -> ScenarioLaneResult:
    """Replay one admitted public clip and retain observational aggregates only."""

    visual = scenario.visual
    if visual is None or "visual_observation" not in scenario.required_lanes:
        return _visual_failure("offline_scenario_lane_unavailable")
    clips = tuple(clip for clip in manifest.clips if clip.clip_id == visual.clip_id)
    if len(clips) != 1:
        return _visual_failure("offline_scenario_clip_missing")

    profile = ReplayProfile(
        profile_id=visual.profile,
        fps=5 if visual.profile == "analysis_realtime" else 1,
        model_backend=model_backend,
        require_model=True,
    )
    aggregate = VisualCorpusReplay(
        prepared_resolver=prepared_resolver,
    ).run_clip(clips[0], profile=profile)
    counts = {
        "frames.total": aggregate.frames_total,
        "frames.processed": aggregate.frames_processed,
        "frames.skipped": aggregate.frames_skipped,
        "frames.dropped": aggregate.dropped_frames,
        "errors.decode": aggregate.decode_errors,
        "errors.worker": aggregate.worker_errors,
    }
    metrics = {
        "model.p50": aggregate.processing_p50_ms,
        "model.p95": aggregate.processing_p95_ms,
        "model.max": aggregate.processing_max_ms,
        "pipeline.p50": aggregate.pipeline_p50_ms,
        "pipeline.p95": aggregate.pipeline_p95_ms,
        "pipeline.max": aggregate.pipeline_max_ms,
    }
    status = aggregate.status
    reason = aggregate.reason
    if status == "PASS" and aggregate.frames_processed < visual.minimum_frames_processed:
        status = "FAIL"
        reason = "offline_scenario_visual_insufficient"
    elif status != "PASS":
        status = "FAIL"
    return ScenarioLaneResult(
        lane="visual_observation",
        status=status,
        reason=reason,
        counts=counts,
        metrics_ms=metrics,
    )


def run_guardian_lane(
    scenario: OfflineGuardianScenarioV1,
    runtime_root: Path,
) -> ScenarioLaneResult:
    """Project one fixed semantic timeline into a new isolated event store."""

    root = Path(runtime_root)
    if not _private_runtime_root(root):
        return _failure("offline_scenario_runtime_unsafe")
    if scenario.guardian is None or "guardian_deterministic" not in scenario.required_lanes:
        return _failure("offline_scenario_lane_unavailable")

    database = root / "guardian-events.sqlite3"
    if database.exists() or database.is_symlink():
        return _failure("guardian_store_not_empty")

    reviews = tuple(
        GuardianReplayReview(
            observed_at=entry.observed_at,
            review=entry.review,
        )
        for entry in scenario.guardian.timeline
    )
    aggregate = GuardianReplayProjector(database_path=database).run(
        semantic_profile="synthetic_test",
        reviews=reviews,
    )
    if aggregate.status != "PASS":
        return _failure(aggregate.reason)

    try:
        database.chmod(0o600)
    except OSError:
        return _failure("offline_scenario_runtime_unsafe")

    counts = {
        **{
            f"transition.{key}": count
            for key, count in aggregate.transition_counts.items()
        },
        **{f"event.{key}": count for key, count in aggregate.event_counts.items()},
        "dashboard.event": aggregate.dashboard_event_count,
        "dashboard.open": aggregate.dashboard_open_event_count,
    }
    expected = {
        **{
            f"transition.{key}": count
            for key, count in scenario.guardian.transition_counts.items()
        },
        **{
            f"event.{key}": count
            for key, count in scenario.guardian.event_counts.items()
        },
        "dashboard.event": scenario.guardian.dashboard_event_count,
        "dashboard.open": scenario.guardian.dashboard_open_event_count,
    }
    return ScenarioLaneResult(
        lane="guardian_deterministic",
        status="PASS" if counts == expected else "FAIL",
        reason="ok" if counts == expected else "scenario_guardian_mismatch",
        counts=counts,
    )


def _private_runtime_root(root: Path) -> bool:
    try:
        metadata = root.lstat()
    except OSError:
        return False
    return (
        stat.S_ISDIR(metadata.st_mode)
        and not root.is_symlink()
        and metadata.st_uid == os.getuid()
        and stat.S_IMODE(metadata.st_mode) == 0o700
    )


def _failure(reason: str) -> ScenarioLaneResult:
    return ScenarioLaneResult(
        lane="guardian_deterministic",
        status="FAIL",
        reason=reason,
    )


def _visual_failure(reason: str) -> ScenarioLaneResult:
    return ScenarioLaneResult(
        lane="visual_observation",
        status="FAIL",
        reason=reason,
    )


__all__ = ["run_guardian_lane", "run_visual_lane"]
