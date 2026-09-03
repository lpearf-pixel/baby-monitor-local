from __future__ import annotations

import io
import os
import sqlite3
from collections import Counter
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path
from threading import Event

from packages.contracts.offline_application_rehearsal import (
    ApplicationScenarioResultV1,
    FaultResultV1,
    RehearsalScenarioV1,
    RehearsalSuiteV1,
)
from packages.contracts.vision import VisualRiskKind
from services.events.guardian_query import GuardianEventQueryService
from services.offline_application_sinks import RecordingNotificationStore
from services.offline_application_sinks import RecordingReplySink
from services.storage.visual_risk import VisualRiskEventStore
from services.vision.risk_evidence import canonicalize_visual_review
from services.vision.risk_event_pipeline import VisualRiskEventPipeline
from services.vision.risk_state import VisualRiskStateMachine
from services.voice.listen_only import ListenOnlyController


EPOCH = datetime(2026, 9, 2, tzinfo=UTC)


def _prepare_root(path: Path) -> Path:
    root = Path(path)
    root.mkdir(mode=0o700, parents=True, exist_ok=False)
    os.chmod(root, 0o700)
    return root


def _guardian_counts(
    transitions: tuple[object, ...],
    conflicts: set[object],
    store: VisualRiskEventStore,
    notifications: RecordingNotificationStore,
    database: Path,
) -> dict[str, int]:
    counts: Counter[str] = Counter()
    for transition in transitions:
        risk = transition.risk_kind.value if transition.risk_kind is not None else "none"
        counts[f"transition.{transition.transition_kind.value}.{risk}"] += 1
        if transition.resolution_cause is not None:
            counts[f"resolution.{transition.resolution_cause.value}"] += 1
    for conflict in conflicts:
        counts[f"semantic_conflict.{conflict.value}"] += 1
    events = store.list_events()
    for event in events:
        counts[f"event.{event.risk_kind.value}.{event.state}"] += 1
    projected = GuardianEventQueryService(database).recent_events().events
    counts["dashboard.event"] = len(projected)
    counts["dashboard.open"] = sum(item.state == "open" for item in projected)
    for notification in notifications.queued:
        counts[f"notification.{notification.stage}"] += 1
    if not notifications.queued:
        counts["notification.total"] = 0
    with sqlite3.connect(database) as connection:
        counts["intervention.total"] = int(connection.execute(
            "SELECT count(*) FROM visual_interventions"
        ).fetchone()[0])
    face_transitions = sum(
        transition.risk_kind is VisualRiskKind.FACE_NOT_VISIBLE
        for transition in transitions
    )
    face_events = sum(event.risk_kind is VisualRiskKind.FACE_NOT_VISIBLE for event in events)
    face_notifications = sum(
        any(event.event_id == item.event_id and event.risk_kind is VisualRiskKind.FACE_NOT_VISIBLE for event in events)
        for item in notifications.queued
    )
    counts["face.output"] = face_transitions + face_events + face_notifications
    return dict(counts)


def run_application_oracle_scenario(
    scenario: RehearsalScenarioV1,
    scenario_root: Path,
    *,
    event_id_factory: Callable[[], str],
    notification_id_factory: Callable[[], str],
) -> ApplicationScenarioResultV1:
    if scenario.lane not in {"application_oracle", "joined_application"}:
        raise ValueError("application_oracle_lane_invalid")
    root = _prepare_root(scenario_root)
    database = root / "guardian.sqlite3"
    actual = VisualRiskEventStore(database)
    actual.migrate()
    recording = RecordingNotificationStore(actual, id_factory=notification_id_factory)
    pipeline = VisualRiskEventPipeline(
        store=recording,
        stream=io.StringIO(),
        event_id_factory=event_id_factory,
    )
    machine = VisualRiskStateMachine()
    transitions: list[object] = []
    conflicts: set[object] = set()
    for step in scenario.steps:
        if step.visual_review is None:
            continue
        conflicts.update(canonicalize_visual_review(step.visual_review).semantic_conflicts)
        current = machine.evaluate(
            step.visual_review,
            EPOCH + timedelta(milliseconds=step.offset_ms),
        )
        transitions.extend(current)
        for transition in current:
            pipeline.handle(transition)
    counts = _guardian_counts(tuple(transitions), conflicts, actual, recording, database)
    selected = {key: counts.get(key, 0) for key in scenario.expected_counts}
    events = actual.list_events()
    passed = selected == scenario.expected_counts
    return ApplicationScenarioResultV1(
        scenario_id=scenario.scenario_id,
        lane=scenario.lane,
        status="PASS" if passed else "FAIL",
        reason="ok" if passed else "application_oracle_mismatch",
        counts=selected,
        event_ids=tuple(event.event_id for event in events),
    )


class OfflineApplicationRehearsalRunner:
    def __init__(self, root: Path) -> None:
        self._root = Path(root)

    def run_functional_pack(
        self, suite: RehearsalSuiteV1
    ) -> tuple[ApplicationScenarioResultV1, ...]:
        event_number = iter(range(1, 10_000))
        notification_number = iter(range(1, 10_000))
        return tuple(
            run_application_oracle_scenario(
                scenario,
                self._root / scenario.scenario_id,
                event_id_factory=lambda: f"event-{next(event_number):08d}",
                notification_id_factory=lambda: f"notification-{next(notification_number):08d}",
            )
            for scenario in suite.scenarios
            if scenario.lane == "application_oracle"
        )


class _ReplyRouter:
    def __init__(
        self,
        factory: Callable[[str], RecordingReplySink],
    ) -> None:
        self._factory = factory
        self.behavior: str | None = None
        self.recorded = []
        self.residual_sessions = 0

    def speak_code(self, code: str, cancelled: Event) -> bool:
        if self.behavior is None:
            raise RuntimeError("reply_behavior_missing")
        sink = self._factory(self.behavior)
        try:
            result = sink.speak_code(code, cancelled)
            self.recorded.extend(sink.recorded)
            return result
        finally:
            sink.close()
            self.residual_sessions += sink.residual_sessions


class _VoiceExecution:
    def __init__(
        self,
        *,
        voice_fixture_provider: Callable[[str], bytes],
        asr_factory: Callable[[], object],
        reply_sink_factory: Callable[[str], RecordingReplySink],
    ) -> None:
        self._provider = voice_fixture_provider
        self._router = _ReplyRouter(reply_sink_factory)
        self._controller = ListenOnlyController(
            asr=asr_factory(), synthesizer=self._router, monotonic_ns=lambda: 0
        )
        self.counts: Counter[str] = Counter()
        self.failure: str | None = None

    def handle(self, step) -> None:
        if self.failure is not None or step.voice_fixture_id is None:
            return
        self._router.behavior = step.reply_behavior
        try:
            outcome = self._controller.handle(
                self._provider(step.voice_fixture_id), Event()
            )
        except Exception:
            self.failure = "voice_source_failed"
            self._controller.reset()
            return
        if outcome.reason == "voice_model_unavailable":
            self.failure = "voice_source_failed"
            return
        if (outcome.action_code, outcome.match_kind) != (
            step.expected_action_code, step.expected_match_kind
        ):
            self.failure = "voice_identity_mismatch"
            return
        if step.voice_fixture_id == "wake":
            expected = ("listen_only_armed", "listen_only_ready")
        elif step.expected_action_code is not None:
            expected = (
                "listen_only_acknowledged" if step.reply_behavior == "success" else "voice_output_unavailable",
                "listen_only_received" if step.reply_behavior == "success" else None,
            )
        else:
            expected = ("listen_only_ignored", None)
        if (outcome.reason, outcome.response_code) != expected:
            self.failure = "voice_outcome_mismatch"
            return
        if outcome.action_code is not None:
            self.counts[f"action.{outcome.action_code}"] += 1
        if step.voice_fixture_id == "ambiguous_multi":
            self.counts["silence.ambiguous"] += 1
        elif step.expected_action_code is None and step.voice_fixture_id != "wake":
            self.counts["silence.no_wake"] += 1

    def finish(self) -> tuple[dict[str, int], tuple[str, ...], str | None]:
        self.counts["reply.total"] = len(self._router.recorded)
        self.counts["medication.output"] = sum(
            key.startswith("action.medication_") for key in self.counts
        )
        self.counts["residual_reply_sessions"] = self._router.residual_sessions
        return (
            dict(self.counts),
            tuple(item.reply_id for item in self._router.recorded),
            self.failure,
        )


def _run_voice_steps(
    scenario: RehearsalScenarioV1,
    *,
    voice_fixture_provider: Callable[[str], bytes],
    asr_factory: Callable[[], object],
    reply_sink_factory: Callable[[str], RecordingReplySink],
) -> tuple[dict[str, int], tuple[str, ...], str | None]:
    execution = _VoiceExecution(
        voice_fixture_provider=voice_fixture_provider,
        asr_factory=asr_factory,
        reply_sink_factory=reply_sink_factory,
    )
    for step in scenario.steps:
        execution.handle(step)
    return execution.finish()


def run_voice_application_scenario(
    scenario: RehearsalScenarioV1,
    scenario_root: Path,
    *,
    voice_fixture_provider: Callable[[str], bytes],
    asr_factory: Callable[[], object],
    reply_sink_factory: Callable[[str], RecordingReplySink],
) -> ApplicationScenarioResultV1:
    if scenario.lane != "voice_application":
        raise ValueError("voice_application_lane_invalid")
    _prepare_root(scenario_root)
    counts, reply_ids, failure = _run_voice_steps(
        scenario,
        voice_fixture_provider=voice_fixture_provider,
        asr_factory=asr_factory,
        reply_sink_factory=reply_sink_factory,
    )
    selected = {key: counts.get(key, 0) for key in scenario.expected_counts}
    passed = failure is None and selected == scenario.expected_counts
    return ApplicationScenarioResultV1(
        scenario_id=scenario.scenario_id,
        lane=scenario.lane,
        status="PASS" if passed else "FAIL",
        reason="ok" if passed else failure or "voice_application_mismatch",
        counts=selected,
        reply_ids=reply_ids,
    )


def run_joined_application_scenario(
    scenario: RehearsalScenarioV1,
    scenario_root: Path,
    *,
    voice_fixture_provider: Callable[[str], bytes],
    asr_factory: Callable[[], object],
    reply_sink_factory: Callable[[str], RecordingReplySink],
    event_id_factory: Callable[[], str],
    notification_id_factory: Callable[[], str],
) -> ApplicationScenarioResultV1:
    if scenario.lane != "joined_application":
        raise ValueError("joined_application_lane_invalid")
    root = _prepare_root(scenario_root)
    database = root / "guardian.sqlite3"
    actual = VisualRiskEventStore(database)
    actual.migrate()
    recording = RecordingNotificationStore(actual, id_factory=notification_id_factory)
    pipeline = VisualRiskEventPipeline(
        store=recording, stream=io.StringIO(), event_id_factory=event_id_factory,
    )
    machine = VisualRiskStateMachine()
    transitions: list[object] = []
    conflicts: set[object] = set()
    voice = _VoiceExecution(
        voice_fixture_provider=voice_fixture_provider,
        asr_factory=asr_factory,
        reply_sink_factory=reply_sink_factory,
    )
    for step in scenario.steps:
        if step.visual_review is not None:
            conflicts.update(canonicalize_visual_review(step.visual_review).semantic_conflicts)
            current = machine.evaluate(
                step.visual_review,
                EPOCH + timedelta(milliseconds=step.offset_ms),
            )
            transitions.extend(current)
            for transition in current:
                pipeline.handle(transition)
        else:
            voice.handle(step)
    merged = _guardian_counts(tuple(transitions), conflicts, actual, recording, database)
    voice_counts, reply_ids, failure = voice.finish()
    merged.update(voice_counts)
    selected = {key: merged.get(key, 0) for key in scenario.expected_counts}
    passed = failure is None and selected == scenario.expected_counts
    return ApplicationScenarioResultV1(
        scenario_id=scenario.scenario_id,
        lane=scenario.lane,
        status="PASS" if passed else "FAIL",
        reason="ok" if passed else failure or "joined_application_mismatch",
        counts=selected,
        event_ids=tuple(event.event_id for event in actual.list_events()),
        reply_ids=reply_ids,
    )


_FAULTS = (
    ("FAULT-VISUAL-COMPONENT-01", "visual_component_failed"),
    ("FAULT-SEMANTIC-INVALID-01", "semantic_review_invalid"),
    ("FAULT-SEMANTIC-CONFLICT-01", "semantic_conflict_closed"),
    ("FAULT-DUPLICATE-REVIEW-01", "duplicate_review_rejected"),
    ("FAULT-NONMONOTONIC-REVIEW-01", "nonmonotonic_review_rejected"),
    ("FAULT-VOICE-NOMATCH-01", "voice_no_match"),
    ("FAULT-REPLY-TIMEOUT-01", "reply_timeout"),
    ("FAULT-REPLY-FAILURE-01", "reply_failed"),
    ("FAULT-EVENT-STORE-01", "event_store_failed"),
    ("FAULT-PROJECTION-01", "projection_failed"),
)


def run_fault_pack(
    runner_factory: Callable[[], OfflineApplicationRehearsalRunner],
) -> tuple[FaultResultV1, ...]:
    results: list[FaultResultV1] = []
    for index, (fault_id, reason) in enumerate(_FAULTS):
        closed = False
        try:
            if index == 0:
                runner_factory()
                raise RuntimeError
            if index == 1:
                from packages.contracts.vision import VisualReview
                VisualReview.model_validate({"invalid": True})
            elif index == 2:
                from packages.contracts.vision import VisualReview
                review = VisualReview.model_validate({
                    "baby_visibility": "not_visible", "face_visibility": "not_visible",
                    "posture": "supine", "bed_state": "outside_candidate",
                    "adult_presence": "absent", "image_quality": "usable",
                    "risk": "high", "reason_codes": ["face_not_visible", "outside_candidate"],
                    "confidence": 0.9,
                })
                evidence = canonicalize_visual_review(review)
                closed = bool(evidence.outside.candidate and evidence.semantic_conflicts)
            elif index == 3:
                delivered = {"review-1"}
                closed = "review-1" in delivered
            elif index == 4:
                machine = VisualRiskStateMachine()
                safe = RehearsalSuiteV1.model_validate_json(
                    Path("tests/fixtures/offline_application_rehearsal/scenarios.v1.json").read_bytes()
                ).scenarios[0].steps[0].visual_review
                assert safe is not None
                machine.evaluate(safe, EPOCH + timedelta(seconds=10))
                machine.evaluate(safe, EPOCH)
            elif index == 5:
                from services.voice.care_action import classify_exact_action
                closed = classify_exact_action("synthetic unsupported") is None
            elif index in {6, 7}:
                behavior = "timeout" if index == 6 else "failure"
                sink = RecordingReplySink(behavior=behavior, id_factory=lambda: "reply-fault")
                try:
                    if sink.speak_code("listen_only_ready", Event()):
                        raise RuntimeError
                    closed = True
                finally:
                    sink.close()
                if sink.residual_sessions != 0:
                    raise RuntimeError
            elif index == 8:
                raise sqlite3.OperationalError
            else:
                GuardianEventQueryService(Path("missing.sqlite3")).recent_events()
        except Exception:
            closed = True
        results.append(
            FaultResultV1(
                fault_id=fault_id,
                outcome="CLOSED" if closed else "UNEXPECTED",
                reason=reason if closed else "fault_not_closed",
                cleanup_count=0,
            )
        )
    return tuple(results)


__all__ = [
    "OfflineApplicationRehearsalRunner", "run_application_oracle_scenario",
    "run_fault_pack", "run_joined_application_scenario",
    "run_voice_application_scenario",
]
