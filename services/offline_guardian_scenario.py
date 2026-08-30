from __future__ import annotations

import os
import signal
import stat
import threading
import time
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
from packages.contracts.visual_corpus import (
    ReviewState,
    SourceType,
    VisualCorpusClip,
    VisualCorpusManifest,
)
from packages.contracts.vision import (
    RealtimeCandidateKind,
    RealtimeCandidateTransitionKind,
)
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
SETTLEMENT_TIMEOUT_SECONDS = 1.0
SCENARIO_ACTION_CODES = (
    "feeding_command",
    "diaper_change_start",
    "diaper_change_complete",
    "burping_start",
    "burping_complete",
)
_COUNTED_EXACT_ACTIONS = frozenset(SCENARIO_ACTION_CODES)
_SCENARIO_CANDIDATE_KEYS = tuple(
    f"{transition.value}.{candidate.value}"
    for transition in RealtimeCandidateTransitionKind
    for candidate in RealtimeCandidateKind
)
_SCENARIO_CANDIDATE_KEY_SET = frozenset(_SCENARIO_CANDIDATE_KEYS)


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
        validate_visual_scenario_bindings(suite, self._visual_manifest)
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
                    except BaseException:
                        _close_voice_components(components)
                        raise
                    if not _close_voice_components(components) and result.status == "PASS":
                        result = _voice_failure(
                            "offline_scenario_voice_cleanup_failed",
                            counts=dict(result.counts),
                        )
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
                    visual_oracle_relationship=scenario.visual_oracle_relationship,
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


def validate_visual_scenario_bindings(
    suite: OfflineScenarioSuiteV1,
    manifest: VisualCorpusManifest,
) -> tuple[VisualCorpusClip, ...]:
    """Bind suite visuals to reviewed public roots without performing I/O."""

    identifiers = tuple(clip.clip_id for clip in manifest.clips)
    if len(set(identifiers)) != len(identifiers):
        raise ValueError("offline_scenario_visual_provenance_invalid")
    by_id = {clip.clip_id: clip for clip in manifest.clips}
    selected: list[VisualCorpusClip] = []
    selected_identifiers: set[str] = set()
    for scenario in suite.scenarios:
        visual = scenario.visual
        if visual is None:
            continue
        clip = by_id.get(visual.clip_id)
        if clip is None or clip.clip_id in selected_identifiers:
            raise ValueError("offline_scenario_visual_provenance_invalid")
        if clip.source_type is SourceType.PUBLIC_DATASET:
            valid = visual.provenance == "PUBLIC_VIDEO" and clip.parent_clip_id is None
        elif clip.source_type is SourceType.SYNTHETIC:
            parent = by_id.get(clip.parent_clip_id or "")
            valid = (
                visual.provenance == "GENERATED_VISUAL"
                and parent is not None
                and parent.review_state is ReviewState.REVIEWED
                and parent.source_type is SourceType.PUBLIC_DATASET
                and parent.parent_clip_id is None
                and parent.source_id == clip.source_id
            )
        else:
            valid = False
        if not valid:
            raise ValueError("offline_scenario_visual_provenance_invalid")
        selected.append(clip)
        selected_identifiers.add(clip.clip_id)
    return tuple(selected)


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
    outcome_counts: Counter[str] = Counter(
        {f"action.{action_code}": 0 for action_code in SCENARIO_ACTION_CODES}
    )
    response_count = 0
    speech_count = 0
    cancelled = threading.Event()

    def failure(reason: str) -> ScenarioLaneResult:
        return _voice_failure(
            reason,
            counts=_voice_counts(
                step_count=len(voice.steps),
                speech_count=speech_count,
                response_count=response_count,
                outcome_counts=outcome_counts,
            ),
        )

    for step in voice.steps:
        try:
            pcm = fixture_provider(step.step_id)
        except Exception:
            return failure("offline_scenario_voice_fixture_invalid")
        if (
            not isinstance(pcm, bytes)
            or not pcm
            or len(pcm) > MAX_GENERATED_PCM_BYTES
            or len(pcm) % VOICE_FRAME_BYTES
        ):
            return failure("offline_scenario_voice_fixture_invalid")

        speech = False
        for offset in range(0, len(pcm), VOICE_FRAME_BYTES):
            observation = vad.observe(pcm[offset : offset + VOICE_FRAME_BYTES])
            if observation.reason is not None:
                return failure(observation.reason)
            speech = speech or observation.speech
        if speech != step.speech_expected:
            return failure("scenario_voice_mismatch")
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
            return failure(outcome.reason)
        if (
            outcome.reason != step.expected_reason
            or outcome.response_code != step.expected_response_code
            or outcome.action_code != step.expected_action_code
            or outcome.match_kind != step.expected_match_kind
        ):
            return failure("scenario_voice_mismatch")
        outcome_counts[f"outcome.{outcome.reason}"] += 1
        if (
            outcome.match_kind == "exact"
            and outcome.action_code in _COUNTED_EXACT_ACTIONS
        ):
            outcome_counts[f"action.{outcome.action_code}"] += 1
        response_count += int(outcome.response_code is not None)

    counts = _voice_counts(
        step_count=len(voice.steps),
        speech_count=speech_count,
        response_count=response_count,
        outcome_counts=outcome_counts,
    )
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
    clip = clips[0]
    expected_provenance = (
        "PUBLIC_VIDEO"
        if clip.source_type is SourceType.PUBLIC_DATASET
        else "GENERATED_VISUAL"
        if clip.source_type is SourceType.SYNTHETIC
        else None
    )
    if visual.provenance != expected_provenance:
        return _visual_failure("offline_scenario_visual_provenance_mismatch")

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
    ).run_clip(clip, profile=profile)
    if not set(aggregate.candidate_counts).issubset(_SCENARIO_CANDIDATE_KEY_SET):
        return _visual_failure("offline_scenario_visual_aggregate_invalid")
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
            f"candidate.{key}": aggregate.candidate_counts.get(key, 0)
            for key in _SCENARIO_CANDIDATE_KEYS
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
    accounting_ok = (
        aggregate.frames_total == visual.expected_frames_processed
        and aggregate.frames_processed == visual.expected_frames_processed
        and aggregate.frames_skipped == 0
        and aggregate.dropped_frames == 0
        and aggregate.decode_errors == 0
        and aggregate.worker_errors == 0
    )
    if status == "PASS" and not accounting_ok:
        status = "FAIL"
        reason = "offline_scenario_visual_frame_mismatch"
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
    if (
        scenario.visual is not None
        and scenario.visual_oracle_relationship != "INDEPENDENT"
    ):
        return _failure("offline_scenario_lane_relationship_invalid")

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


def _close_voice_components(components: list[object]) -> bool:
    settled = True
    for component in reversed(components):
        close = getattr(component, "close", None)
        if not callable(close):
            continue
        try:
            close()
        except OfflineScenarioTimeout:
            settled = False
        except Exception:
            settled = False
    return settled


@contextmanager
def _run_deadline(timeout_seconds: float):
    if threading.current_thread() is not threading.main_thread():
        raise ValueError("offline_scenario_runtime_unsafe")
    previous_handler = signal.getsignal(signal.SIGALRM)
    previous_timer = signal.getitimer(signal.ITIMER_REAL)
    if previous_timer[0] > 0 and not getattr(
        previous_handler,
        "_offline_scenario_deadline",
        False,
    ):
        raise ValueError("offline_scenario_runtime_unsafe")
    started = time.monotonic()
    previous_remaining = previous_timer[0]
    effective_timeout = (
        min(timeout_seconds, previous_remaining)
        if previous_remaining > 0
        else timeout_seconds
    )

    def expire(_signum: int, _frame: object) -> None:
        signal.setitimer(signal.ITIMER_REAL, SETTLEMENT_TIMEOUT_SECONDS)
        raise OfflineScenarioTimeout("offline_scenario_timeout")

    expire._offline_scenario_deadline = True  # type: ignore[attr-defined]

    signal.signal(signal.SIGALRM, expire)
    signal.setitimer(signal.ITIMER_REAL, effective_timeout)
    try:
        yield
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
        signal.signal(signal.SIGALRM, previous_handler)
        elapsed = time.monotonic() - started
        restored_remaining = max(0.0, previous_remaining - elapsed)
        signal.setitimer(
            signal.ITIMER_REAL,
            restored_remaining,
            previous_timer[1],
        )


offline_scenario_deadline = _run_deadline


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


def _voice_counts(
    *,
    step_count: int,
    speech_count: int,
    response_count: int,
    outcome_counts: Counter[str],
) -> dict[str, int]:
    return {
        "steps.total": step_count,
        "vad.speech": speech_count,
        "responses.total": response_count,
        **dict(sorted(outcome_counts.items())),
    }


def _voice_failure(
    reason: str,
    *,
    counts: dict[str, int] | None = None,
) -> ScenarioLaneResult:
    return ScenarioLaneResult(
        lane="voice_generated",
        status="FAIL",
        reason=reason,
        counts=(
            counts
            if counts is not None
            else {
                f"action.{action_code}": 0
                for action_code in SCENARIO_ACTION_CODES
            }
        ),
    )


__all__ = [
    "OfflineGuardianScenarioRunner",
    "OfflineScenarioTimeout",
    "offline_scenario_deadline",
    "run_guardian_lane",
    "run_visual_lane",
    "run_voice_lane",
    "validate_visual_scenario_bindings",
]
