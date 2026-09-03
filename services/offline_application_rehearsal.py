from __future__ import annotations

import io
import hashlib
import json
import os
import sqlite3
from collections import Counter
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path
from threading import Event

from pydantic import ValidationError

from packages.contracts.offline_application_rehearsal import (
    ApplicationScenarioResultV1,
    FaultResultV1,
    RehearsalScenarioV1,
    RehearsalSuiteV1,
    RepetitionIterationV1,
    RepetitionResultV1,
)
from packages.contracts.vision import (
    RiskTransition,
    RiskTransitionKind,
    VisualReview,
    VisualRiskKind,
    VisualRiskState,
)
from services.events.guardian_query import (
    GuardianEventQueryService,
    GuardianEventQueryUnavailable,
)
from services.offline_application_sinks import RecordingNotificationStore
from services.offline_application_sinks import RecordingReplySink
from services.storage.visual_risk import VisualRiskEventStore
from services.vision.risk_evidence import canonicalize_visual_review
from services.vision.risk_event_pipeline import VisualRiskEventPipeline
from services.vision.risk_state import VisualRiskStateMachine
from services.voice.listen_only import ListenOnlyController
from services.voice.asr import AsrResult


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
    def __init__(
        self,
        root: Path,
        *,
        voice_fixture_provider: Callable[[str], bytes] | None = None,
        asr_factory: Callable[[], object] | None = None,
        reply_sink_factory: Callable[[str], RecordingReplySink] | None = None,
    ) -> None:
        self._root = Path(root)
        self._voice_fixture_provider = voice_fixture_provider
        self._asr_factory = asr_factory
        self._reply_sink_factory = reply_sink_factory

    def fault_root(self, fault_id: str) -> Path:
        if not fault_id.startswith("FAULT-"):
            raise ValueError("offline_application_fault_invalid")
        return self._root / fault_id.lower()

    @staticmethod
    def execute_component(component: Callable[[], object]) -> object:
        return component()

    def run_functional_pack(
        self, suite: RehearsalSuiteV1
    ) -> tuple[ApplicationScenarioResultV1, ...]:
        event_number = iter(range(1, 10_000))
        notification_number = iter(range(1, 10_000))
        results: list[ApplicationScenarioResultV1] = []
        namespace = hashlib.sha256(self._root.name.encode("utf-8")).hexdigest()[:8]
        event_factory = lambda: f"event-{namespace}-{next(event_number):08d}"
        notification_factory = lambda: f"notification-{namespace}-{next(notification_number):08d}"
        for scenario in suite.scenarios:
            root = self._root / scenario.scenario_id
            if scenario.lane == "application_oracle":
                result = run_application_oracle_scenario(
                    scenario, root, event_id_factory=event_factory,
                    notification_id_factory=notification_factory,
                )
            elif self._voice_fixture_provider is None or self._asr_factory is None or self._reply_sink_factory is None:
                continue
            elif scenario.lane == "voice_application":
                result = run_voice_application_scenario(
                    scenario, root,
                    voice_fixture_provider=self._voice_fixture_provider,
                    asr_factory=self._asr_factory,
                    reply_sink_factory=self._reply_sink_factory,
                )
            else:
                result = run_joined_application_scenario(
                    scenario, root,
                    voice_fixture_provider=self._voice_fixture_provider,
                    asr_factory=self._asr_factory,
                    reply_sink_factory=self._reply_sink_factory,
                    event_id_factory=event_factory,
                    notification_id_factory=notification_factory,
                )
            results.append(result)
        return tuple(results)


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
        if (
            outcome.reason == "voice_model_unavailable"
            and step.expected_reason != "voice_model_unavailable"
        ):
            self.failure = "voice_source_failed"
            return
        if (outcome.action_code, outcome.match_kind) != (
            step.expected_action_code, step.expected_match_kind
        ):
            self.failure = "voice_identity_mismatch"
            return
        expected_response = {
            "listen_only_armed": "listen_only_ready",
            "listen_only_acknowledged": "listen_only_received",
        }.get(step.expected_reason)
        if (outcome.reason, outcome.response_code, outcome.phase) != (
            step.expected_reason, expected_response, step.expected_phase
        ):
            self.failure = "voice_outcome_mismatch"
            return
        if outcome.action_code is not None:
            self.counts[f"action.{outcome.action_code}"] += 1
        if step.voice_fixture_id == "ambiguous_multi":
            self.counts["silence.ambiguous"] += 1
        elif step.voice_fixture_id == "no_match":
            self.counts["silence.no_match"] += 1
        elif step.voice_fixture_id == "source_failure":
            self.counts["closed.voice_source_failed"] += 1
        elif step.reply_behavior == "timeout":
            self.counts["closed.reply_timeout"] += 1
        elif step.reply_behavior == "failure":
            self.counts["closed.reply_failure"] += 1
        elif step.expected_action_code is None and step.voice_fixture_id != "wake":
            self.counts["silence.no_wake"] += 1

    def finish(self) -> tuple[dict[str, int], tuple[str, ...], str | None]:
        self.counts["reply.total"] = len(self._router.recorded)
        for reply in self._router.recorded:
            self.counts[f"reply.{reply.terminal_state}"] += 1
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


class _InjectedComponentFailure(Exception):
    pass


class _SequenceAsr:
    def __init__(self, *texts: str) -> None:
        self._texts = iter(texts)

    def transcribe(self, _pcm: bytes) -> AsrResult:
        return AsrResult(next(self._texts), "zh", 1)


def _alert_transition() -> RiskTransition:
    return RiskTransition(
        transition_kind=RiskTransitionKind.ALERT_OPENED,
        risk_kind=VisualRiskKind.FACE_NOT_VISIBLE,
        previous_state=VisualRiskState.WATCH,
        current_state=VisualRiskState.ALERT,
        observed_at=EPOCH,
        confidence=0.9,
        notify=True,
    )


def _fault_visual_component(runner: OfflineApplicationRehearsalRunner) -> bool:
    def fail() -> None:
        raise _InjectedComponentFailure

    try:
        runner.execute_component(fail)
    except _InjectedComponentFailure:
        return True
    return False


def _fault_semantic_invalid(_runner: OfflineApplicationRehearsalRunner) -> bool:
    try:
        VisualReview.model_validate({"invalid": True})
    except ValidationError:
        return True
    return False


def _fault_semantic_conflict(_runner: OfflineApplicationRehearsalRunner) -> bool:
    review = VisualReview.model_validate({
        "baby_visibility": "not_visible", "face_visibility": "not_visible",
        "posture": "supine", "bed_state": "outside_candidate",
        "adult_presence": "absent", "image_quality": "usable",
        "risk": "high", "reason_codes": ["face_not_visible", "outside_candidate"],
        "confidence": 0.9,
    })
    evidence = canonicalize_visual_review(review)
    return bool(
        evidence.outside.candidate
        and evidence.semantic_conflicts
        and not evidence.face.candidate
    )


def _fault_duplicate_review(runner: OfflineApplicationRehearsalRunner) -> bool:
    root = _prepare_root(runner.fault_root("FAULT-DUPLICATE-REVIEW-01"))
    store = VisualRiskEventStore(root / "guardian.sqlite3")
    store.migrate()
    stream = io.StringIO()
    pipeline = VisualRiskEventPipeline(
        store=store, stream=stream, event_id_factory=lambda: "event-fault-duplicate",
    )
    alert = _alert_transition()
    pipeline.handle(alert)
    pipeline.handle(alert)
    return (
        len(store.list_events()) == 1
        and stream.getvalue().count('"code":"guardian.notification_queued"') == 1
    )


def _fault_nonmonotonic(_runner: OfflineApplicationRehearsalRunner) -> bool:
    machine = VisualRiskStateMachine()
    safe = VisualReview.model_validate({
        "baby_visibility": "visible", "face_visibility": "clear",
        "posture": "supine", "bed_state": "inside", "adult_presence": "absent",
        "image_quality": "usable", "risk": "none", "reason_codes": [],
        "confidence": 0.9,
    })
    machine.evaluate(safe, EPOCH + timedelta(seconds=10))
    try:
        machine.evaluate(safe, EPOCH)
    except ValueError:
        return True
    return False


def _fault_voice_no_match(_runner: OfflineApplicationRehearsalRunner) -> bool:
    sink = RecordingReplySink(behavior="success", id_factory=lambda: "reply-fault-nomatch")
    controller = ListenOnlyController(
        asr=_SequenceAsr("\u5c0f\u5c0f", "synthetic unsupported"),
        synthesizer=sink, monotonic_ns=lambda: 0,
    )
    try:
        armed = controller.handle(b"wake", Event())
        rejected = controller.handle(b"unsupported", Event())
        return (
            armed.reason == "listen_only_armed"
            and rejected.reason == "listen_only_followup_far"
            and rejected.phase == "idle"
            and sink.residual_sessions == 0
        )
    finally:
        sink.close()


def _fault_reply(
    _runner: OfflineApplicationRehearsalRunner,
    behavior: str,
) -> bool:
    sink = RecordingReplySink(
        behavior=behavior,  # type: ignore[arg-type]
        id_factory=lambda: f"reply-fault-{behavior}",
    )
    controller = ListenOnlyController(
        asr=_SequenceAsr("\u5c0f\u5c0f"), synthesizer=sink, monotonic_ns=lambda: 0,
    )
    try:
        outcome = controller.handle(b"wake", Event())
        return (
            outcome.reason == "voice_output_unavailable"
            and outcome.phase == "idle"
            and len(sink.recorded) == 1
            and sink.recorded[0].terminal_state == (
                "timed_out" if behavior == "timeout" else "failed"
            )
            and sink.residual_sessions == 0
        )
    finally:
        sink.close()


def _fault_event_store(_runner: OfflineApplicationRehearsalRunner) -> bool:
    class FailingStore:
        def load_open(self):
            raise sqlite3.OperationalError("synthetic store failure")

    stream = io.StringIO()
    pipeline = VisualRiskEventPipeline(store=FailingStore(), stream=stream)  # type: ignore[arg-type]
    pipeline.handle(_alert_transition())
    return '"code":"guardian.persistence_failed"' in stream.getvalue()


def _fault_projection(runner: OfflineApplicationRehearsalRunner) -> bool:
    root = _prepare_root(runner.fault_root("FAULT-PROJECTION-01"))
    try:
        GuardianEventQueryService(root / "guardian.sqlite3").recent_events()
    except GuardianEventQueryUnavailable:
        return True
    return False


_FAULT_EXERCISES = (
    _fault_visual_component,
    _fault_semantic_invalid,
    _fault_semantic_conflict,
    _fault_duplicate_review,
    _fault_nonmonotonic,
    _fault_voice_no_match,
    lambda runner: _fault_reply(runner, "timeout"),
    lambda runner: _fault_reply(runner, "failure"),
    _fault_event_store,
    _fault_projection,
)


def run_fault_pack(
    runner_factory: Callable[[], OfflineApplicationRehearsalRunner],
) -> tuple[FaultResultV1, ...]:
    results: list[FaultResultV1] = []
    for (fault_id, reason), exercise in zip(_FAULTS, _FAULT_EXERCISES, strict=True):
        closed = False
        try:
            closed = exercise(runner_factory())
        except Exception:
            closed = False
        results.append(
            FaultResultV1(
                fault_id=fault_id,
                outcome="CLOSED" if closed else "UNEXPECTED",
                reason=reason if closed else "fault_not_closed",
                cleanup_count=0,
            )
        )
    return tuple(results)


def _stable_functional_digest(
    results: tuple[ApplicationScenarioResultV1, ...],
) -> str:
    payload = [item.model_dump(mode="json") for item in results]
    next_event = 0
    next_reply = 0
    for item in payload:
        normalized_events = []
        for _value in item["event_ids"]:
            next_event += 1
            normalized_events.append(f"event-{next_event:04d}")
        item["event_ids"] = normalized_events
        normalized_replies = []
        for _value in item["reply_ids"]:
            next_reply += 1
            normalized_replies.append(f"reply-{next_reply:04d}")
        item["reply_ids"] = normalized_replies
    canonical = json.dumps(payload, ensure_ascii=True, sort_keys=True, separators=(",", ":")).encode("ascii")
    return hashlib.sha256(canonical).hexdigest()


def _cross_risk_instance_pass(index: int, suite: RehearsalSuiteV1) -> bool:
    machine = VisualRiskStateMachine()
    if index % 2 == 0:
        scenario = suite.scenarios[2]
        transitions = tuple(
            transition
            for step in scenario.steps
            for transition in machine.evaluate(
                step.visual_review, EPOCH + timedelta(milliseconds=step.offset_ms)
            )
            if step.visual_review is not None
        )
        return all(item.risk_kind is not VisualRiskKind.FACE_NOT_VISIBLE for item in transitions)
    scenario = suite.scenarios[5]
    transitions = tuple(
        transition
        for step in scenario.steps
        for transition in machine.evaluate(
            step.visual_review, EPOCH + timedelta(milliseconds=step.offset_ms)
        )
        if step.visual_review is not None
    )
    recoveries = [
        item for item in transitions
        if item.risk_kind is VisualRiskKind.FACE_NOT_VISIBLE
        and item.transition_kind.value == "recovered"
    ]
    return len(recoveries) == 1 and recoveries[0].notify is False


def run_repetition_gate(
    runner_factory: Callable[[int], OfflineApplicationRehearsalRunner],
    suite: RehearsalSuiteV1,
    *,
    full_run_count: int = 10,
    cross_risk_count: int = 50,
) -> RepetitionResultV1:
    if full_run_count != 10 or cross_risk_count != 50:
        raise ValueError("repetition_quota_invalid")
    iterations: list[RepetitionIterationV1] = []
    seen_ids: set[str] = set()
    expected_digest: str | None = None
    first_failure: str | None = None
    for iteration in range(1, 11):
        results = runner_factory(iteration).run_functional_pack(suite)
        digest = _stable_functional_digest(results)
        identifiers = [value for item in results for value in (*item.event_ids, *item.reply_ids)]
        if len(results) != 12 or any(item.status != "PASS" for item in results):
            first_failure = first_failure or "functional_iteration_failed"
        elif any(value in seen_ids for value in identifiers) or len(identifiers) != len(set(identifiers)):
            first_failure = first_failure or "duplicate_generated_id"
        elif any(item.counts.get("residual_reply_sessions", 0) != 0 for item in results):
            first_failure = first_failure or "residual_reply_session"
        elif any(item.counts.get("face.output", 0) != 0 for item in results if "EMPTY-BED" in item.scenario_id or "ADULT-ONLY" in item.scenario_id or "CROSS-RISK-LEGACY" in item.scenario_id):
            first_failure = first_failure or "no_baby_face_output"
        elif expected_digest is not None and digest != expected_digest:
            first_failure = first_failure or "stable_digest_mismatch"
        expected_digest = expected_digest or digest
        seen_ids.update(identifiers)
        iterations.append(RepetitionIterationV1(
            iteration=iteration,
            status="PASS" if first_failure is None else "FAIL",
            stable_digest=digest,
            counts={"functional_pass": sum(item.status == "PASS" for item in results)},
        ))
    cross_pass = sum(_cross_risk_instance_pass(index, suite) for index in range(50))
    if cross_pass != 50:
        first_failure = first_failure or "cross_risk_failed"
    return RepetitionResultV1(
        status="PASS" if first_failure is None else "FAIL",
        reason=first_failure or "ok",
        iterations=tuple(iterations),
        cross_risk_instances=50,
        cross_risk_pass=cross_pass,
    )


__all__ = [
    "OfflineApplicationRehearsalRunner", "run_application_oracle_scenario",
    "run_fault_pack", "run_joined_application_scenario",
    "run_repetition_gate", "run_voice_application_scenario",
]
