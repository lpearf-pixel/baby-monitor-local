from __future__ import annotations

import os
import signal
import stat
import threading
from collections import Counter
from collections.abc import Callable
from contextlib import contextmanager
from pathlib import Path

from packages.contracts.offline_guardian_scenario import (
    OfflineGuardianScenarioV1,
    OfflineScenarioResultV1,
    OfflineScenarioRunV1,
    OfflineScenarioSuiteV1,
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
from services.voice.listen_only import Asr, ListenOnlyController, Synthesizer
from services.voice.vad import VoiceActivityDetector


VOICE_FRAME_BYTES = 3_200
MAX_GENERATED_PCM_BYTES = 1_024 * 1_024
DEFAULT_RUN_TIMEOUT_SECONDS = 180.0


class OfflineScenarioTimeout(BaseException):
    """Whole-run deadline that lane-level Exception handlers cannot swallow."""


class OfflineGuardianScenarioRunner:
    def __init__(
        self,
        *,
        runtime_root: Path,
        runtime_boundary: Path,
        visual_manifest: VisualCorpusManifest,
        prepared_resolver: PreparedResolver,
        prepared_root: Path,
        model_backend: RealtimeModelBackend | None,
        voice_fixture_provider: Callable[[str], bytes],
        voice_vad_factory: Callable[[], VoiceActivityDetector],
        voice_asr_factory: Callable[[], Asr],
        voice_synthesizer_factory: Callable[[], Synthesizer],
        timeout_seconds: float = DEFAULT_RUN_TIMEOUT_SECONDS,
    ) -> None:
        self._runtime_root = Path(runtime_root)
        self._runtime_boundary = Path(runtime_boundary)
        self._visual_manifest = visual_manifest
        self._prepared_resolver = prepared_resolver
        self._prepared_root = Path(prepared_root)
        self._model_backend = model_backend
        self._voice_fixture_provider = voice_fixture_provider
        self._voice_vad_factory = voice_vad_factory
        self._voice_asr_factory = voice_asr_factory
        self._voice_synthesizer_factory = voice_synthesizer_factory
        if not 0 < timeout_seconds <= DEFAULT_RUN_TIMEOUT_SECONDS:
            raise ValueError("offline_scenario_timeout_invalid")
        self._timeout_seconds = float(timeout_seconds)

    def run(self, suite: OfflineScenarioSuiteV1) -> OfflineScenarioRunV1:
        with _run_deadline(self._timeout_seconds):
            return self._run(suite)

    def _run(self, suite: OfflineScenarioSuiteV1) -> OfflineScenarioRunV1:
        self._create_runtime_root()
        results: list[OfflineScenarioResultV1] = []
        first_reason: str | None = None
        any_skip = False
        for scenario in suite.scenarios:
            scenario_root = self._runtime_root / scenario.scenario_id
            scenario_root.mkdir(mode=0o700)
            scenario_root.chmod(0o700)
            lanes: list[ScenarioLaneResult] = []
            for lane in scenario.required_lanes:
                if lane == "visual_observation":
                    result = run_visual_lane(
                        scenario,
                        self._visual_manifest,
                        self._prepared_resolver,
                        self._prepared_root,
                        self._model_backend,
                    )
                elif lane == "guardian_deterministic":
                    result = run_guardian_lane(scenario, scenario_root)
                else:
                    components: list[object] = []
                    try:
                        vad = self._voice_vad_factory()
                        components.append(vad)
                        asr = self._voice_asr_factory()
                        components.append(asr)
                        synthesizer = self._voice_synthesizer_factory()
                        components.append(synthesizer)
                        result = run_voice_lane(
                            scenario,
                            self._voice_fixture_provider,
                            vad,
                            asr,
                            synthesizer,
                        )
                    finally:
                        for component in reversed(components):
                            _close_best_effort(component)
                lanes.append(result)
                if result.status != "PASS" and first_reason is None:
                    first_reason = result.reason
                any_skip = any_skip or result.status == "SKIP"
            scenario_status = _aggregate_status(lanes)
            scenario_reason = next(
                (lane.reason for lane in lanes if lane.status != "PASS"),
                "ok",
            )
            results.append(
                OfflineScenarioResultV1(
                    scenario_id=scenario.scenario_id,
                    status=scenario_status,
                    reason=scenario_reason,
                    lanes=tuple(lanes),
                )
            )

        overall_status = _aggregate_status(
            tuple(lane for result in results for lane in result.lanes)
        )
        return OfflineScenarioRunV1(
            suite_id=suite.suite_id,
            status=overall_status,
            reason=first_reason or ("offline_scenario_skipped" if any_skip else "ok"),
            results=tuple(results),
        )

    def _create_runtime_root(self) -> None:
        root = self._runtime_root
        parent = self._runtime_boundary
        if (
            root.parent != parent
            or root.exists()
            or root.is_symlink()
            or not _private_runtime_root(parent)
        ):
            raise ValueError("offline_scenario_runtime_unsafe")
        try:
            root.mkdir(mode=0o700)
            root.chmod(0o700)
        except OSError:
            raise ValueError("offline_scenario_runtime_unsafe") from None
        if not _private_runtime_root(root):
            raise ValueError("offline_scenario_runtime_unsafe")


def _aggregate_status(
    lanes: tuple[ScenarioLaneResult, ...] | list[ScenarioLaneResult],
) -> str:
    if any(lane.status == "FAIL" for lane in lanes):
        return "FAIL"
    if any(lane.status == "SKIP" for lane in lanes):
        return "SKIP"
    return "PASS"


def run_voice_lane(
    scenario: OfflineGuardianScenarioV1,
    fixture_provider: Callable[[str], bytes],
    vad: VoiceActivityDetector,
    asr: Asr,
    synthesizer: Synthesizer,
) -> ScenarioLaneResult:
    """Exercise generated PCM through VAD and the current listen-only controller."""

    voice = scenario.voice
    if voice is None or "voice_generated" not in scenario.required_lanes:
        return _voice_failure("offline_scenario_lane_unavailable")

    controller = ListenOnlyController(asr=asr, synthesizer=synthesizer)
    outcome_counts: Counter[str] = Counter()
    response_count = 0
    speech_count = 0
    cancelled = threading.Event()
    for step in voice.steps:
        try:
            pcm = fixture_provider(step.step_id)
        except Exception:
            return _voice_failure("offline_scenario_voice_fixture_invalid")
        if (
            not isinstance(pcm, bytes)
            or not pcm
            or len(pcm) > MAX_GENERATED_PCM_BYTES
            or len(pcm) % VOICE_FRAME_BYTES
        ):
            return _voice_failure("offline_scenario_voice_fixture_invalid")

        speech = False
        for offset in range(0, len(pcm), VOICE_FRAME_BYTES):
            observation = vad.observe(pcm[offset : offset + VOICE_FRAME_BYTES])
            if observation.reason is not None:
                return _voice_failure(observation.reason)
            speech = speech or observation.speech
        if speech != step.speech_expected:
            return _voice_failure("scenario_voice_mismatch")
        if not speech:
            continue
        speech_count += 1
        outcome = controller.handle(
            pcm,
            cancelled,
            from_replay=step.from_replay,
        )
        pcm = b""
        if outcome.reason in {"voice_model_unavailable", "voice_output_unavailable"}:
            return _voice_failure(outcome.reason)
        if (
            outcome.reason != step.expected_reason
            or outcome.response_code != step.expected_response_code
        ):
            return _voice_failure("scenario_voice_mismatch")
        outcome_counts[f"outcome.{outcome.reason}"] += 1
        response_count += int(outcome.response_code is not None)

    counts = {
        "steps.total": len(voice.steps),
        "vad.speech": speech_count,
        "responses.total": response_count,
        **dict(sorted(outcome_counts.items())),
    }
    return ScenarioLaneResult(
        lane="voice_generated",
        status="PASS" if response_count == voice.expected_response_count else "FAIL",
        reason=(
            "ok"
            if response_count == voice.expected_response_count
            else "scenario_voice_mismatch"
        ),
        counts=counts,
    )


def run_visual_lane(
    scenario: OfflineGuardianScenarioV1,
    manifest: VisualCorpusManifest,
    prepared_resolver: PreparedResolver,
    prepared_root: Path,
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
    root = Path(prepared_root)
    if not _private_runtime_root(root):
        return _visual_failure("visual_corpus_input_invalid")

    def resolve_prepared(clip, selected_profile):
        path = prepared_resolver(clip, selected_profile)
        if not _private_prepared_file(path, root):
            raise ValueError
        return path

    aggregate = VisualCorpusReplay(
        prepared_resolver=resolve_prepared,
    ).run_clip(clips[0], profile=profile)
    counts = {
        "frames.total": aggregate.frames_total,
        "frames.processed": aggregate.frames_processed,
        "frames.skipped": aggregate.frames_skipped,
        "frames.dropped": aggregate.dropped_frames,
        "errors.decode": aggregate.decode_errors,
        "errors.worker": aggregate.worker_errors,
        **{
            f"observation.{key}": count
            for key, count in aggregate.observation_counts.items()
        },
        **{
            f"candidate.{key}": count
            for key, count in aggregate.candidate_counts.items()
        },
    }
    if len(counts) > 64:
        return _visual_failure("offline_scenario_visual_aggregate_overflow")
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
        and not _path_has_symlink(root)
        and metadata.st_uid == os.getuid()
        and stat.S_IMODE(metadata.st_mode) == 0o700
    )


def _path_has_symlink(path: Path) -> bool:
    absolute = path.absolute()
    return any(candidate.is_symlink() for candidate in (absolute, *absolute.parents))


def _private_prepared_file(path: Path, root: Path) -> bool:
    candidate = Path(path)
    try:
        metadata = candidate.lstat()
    except OSError:
        return False
    return (
        candidate.parent == root
        and not _path_has_symlink(candidate)
        and stat.S_ISREG(metadata.st_mode)
        and metadata.st_uid == os.getuid()
        and stat.S_IMODE(metadata.st_mode) == 0o600
        and metadata.st_nlink == 1
    )


def _close_best_effort(component: object) -> None:
    close = getattr(component, "close", None)
    if callable(close):
        try:
            close()
        except Exception:
            pass


@contextmanager
def _run_deadline(timeout_seconds: float):
    if threading.current_thread() is not threading.main_thread():
        raise ValueError("offline_scenario_runtime_unsafe")
    previous_handler = signal.getsignal(signal.SIGALRM)

    def expire(_signum: int, _frame: object) -> None:
        raise OfflineScenarioTimeout("offline_scenario_timeout")

    signal.signal(signal.SIGALRM, expire)
    previous_timer = signal.setitimer(signal.ITIMER_REAL, timeout_seconds)
    try:
        yield
    finally:
        signal.setitimer(signal.ITIMER_REAL, *previous_timer)
        signal.signal(signal.SIGALRM, previous_handler)


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


def _voice_failure(reason: str) -> ScenarioLaneResult:
    return ScenarioLaneResult(
        lane="voice_generated",
        status="FAIL",
        reason=reason,
    )


__all__ = [
    "OfflineGuardianScenarioRunner",
    "OfflineScenarioTimeout",
    "run_guardian_lane",
    "run_visual_lane",
    "run_voice_lane",
]
