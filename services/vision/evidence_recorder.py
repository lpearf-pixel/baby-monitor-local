from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta
import json
import sys
from typing import Literal, Protocol, TextIO

from packages.contracts.vision import RiskTransition
from services.storage.visual_risk import (
    StoredVisualRiskEvent,
    VisualRiskEventStore,
)
from services.vision.evidence_files import GuardianEvidenceFiles
from services.vision.frame_policy import PreparedAnalysisFrame


PRE_EVENT_SECONDS = 10
POST_EVENT_SECONDS = 30
MAX_EVIDENCE_FRAMES = 21


class EvidenceFilesLike(Protocol):
    def write_snapshot(
        self,
        event_id: str,
        frame: PreparedAnalysisFrame,
    ) -> str: ...

    def write_clip(
        self,
        event_id: str,
        frames: tuple[PreparedAnalysisFrame, ...],
    ) -> str: ...


@dataclass
class _ActiveCapture:
    event_id: str
    started_at: datetime
    deadline: datetime
    frames: list[PreparedAnalysisFrame]


class _EvidenceLog:
    def __init__(self, stream: TextIO) -> None:
        self._stream = stream

    def emit(
        self,
        code: str,
        *,
        observed_at: datetime,
        event_id: str | None = None,
        state: str,
        result: str,
        frame_count: int,
    ) -> None:
        payload: dict[str, object] = {
            "schema_version": 1,
            "component": "baby_guardian",
            "code": code,
            "observed_at": observed_at.isoformat(),
            "state": state,
            "result": result,
            "frame_count": frame_count,
        }
        if event_id is not None:
            payload["event_id"] = event_id
        try:
            self._stream.write(
                json.dumps(
                    payload,
                    ensure_ascii=True,
                    sort_keys=True,
                    separators=(",", ":"),
                )
                + "\n"
            )
            self._stream.flush()
        except Exception:
            return


class GuardianEvidenceRecorder:
    def __init__(
        self,
        *,
        store: VisualRiskEventStore,
        files: EvidenceFilesLike | GuardianEvidenceFiles,
        frame_window: Callable[..., tuple[PreparedAnalysisFrame, ...]],
        stream: TextIO = sys.stderr,
    ) -> None:
        self._store = store
        self._files = files
        self._frame_window = frame_window
        self._log = _EvidenceLog(stream)
        self._active: dict[str, _ActiveCapture] = {}

    def start(
        self,
        event: StoredVisualRiskEvent,
        transition: RiskTransition,
    ) -> None:
        try:
            if self._store.get_evidence(event.event_id) is not None:
                return
        except Exception:
            self._emit_persistence_failure(event.event_id, transition.observed_at)
            return

        try:
            frames = self._frame_window(
                start_at=transition.observed_at
                - timedelta(seconds=PRE_EVENT_SECONDS),
                end_at=transition.observed_at,
            )
        except Exception:
            frames = ()
        frames = frames[-MAX_EVIDENCE_FRAMES:]
        deadline = transition.observed_at + timedelta(seconds=POST_EVENT_SECONDS)
        if not frames:
            self._fail_start(
                event_id=event.event_id,
                observed_at=transition.observed_at,
                deadline=deadline,
                failure_code="snapshot_unavailable",
            )
            return

        try:
            snapshot_key = self._files.write_snapshot(event.event_id, frames[-1])
        except Exception:
            self._fail_start(
                event_id=event.event_id,
                observed_at=transition.observed_at,
                deadline=deadline,
                failure_code="media_write_failed",
            )
            return

        try:
            evidence = self._store.begin_evidence(
                event_id=event.event_id,
                started_at=transition.observed_at,
                capture_deadline=deadline,
                snapshot_key=snapshot_key,
                frame_count=len(frames),
            )
        except Exception:
            self._emit_persistence_failure(event.event_id, transition.observed_at)
            return
        if evidence.state != "collecting":
            return
        self._active[event.event_id] = _ActiveCapture(
            event_id=event.event_id,
            started_at=transition.observed_at,
            deadline=deadline,
            frames=list(frames),
        )
        self._log.emit(
            "guardian.evidence_started",
            observed_at=transition.observed_at,
            event_id=event.event_id,
            state="collecting",
            result="started",
            frame_count=len(frames),
        )

    def observe(self, frame: PreparedAnalysisFrame) -> None:
        for event_id, capture in tuple(self._active.items()):
            if frame.captured_at < capture.started_at:
                continue
            if capture.frames and frame.captured_at <= capture.frames[-1].captured_at:
                continue
            if len(capture.frames) < MAX_EVIDENCE_FRAMES:
                capture.frames.append(frame)
            else:
                capture.frames[-1] = frame
            if frame.captured_at >= capture.deadline:
                self._complete(capture, completed_at=frame.captured_at)
                self._active.pop(event_id, None)

    def recover_interrupted(self, interrupted_at: datetime) -> None:
        self._interrupt(interrupted_at, failure_code="worker_restarted")

    def close(self, interrupted_at: datetime) -> None:
        self._interrupt(interrupted_at, failure_code="worker_stopped")
        self._active.clear()

    def _complete(
        self,
        capture: _ActiveCapture,
        *,
        completed_at: datetime,
    ) -> None:
        frames = tuple(capture.frames)
        try:
            clip_key = self._files.write_clip(capture.event_id, frames)
        except Exception:
            self._record_failure(
                event_id=capture.event_id,
                failed_at=completed_at,
                failure_code="media_write_failed",
                frame_count=len(frames),
            )
            return
        try:
            ready = self._store.complete_evidence(
                event_id=capture.event_id,
                completed_at=completed_at,
                clip_key=clip_key,
                frame_count=len(frames),
            )
        except Exception:
            self._emit_persistence_failure(capture.event_id, completed_at)
            return
        self._log.emit(
            "guardian.evidence_ready",
            observed_at=completed_at,
            event_id=ready.event_id,
            state=ready.state,
            result="completed",
            frame_count=ready.frame_count,
        )

    def _fail_start(
        self,
        *,
        event_id: str,
        observed_at: datetime,
        deadline: datetime,
        failure_code: Literal["snapshot_unavailable", "media_write_failed"],
    ) -> None:
        try:
            self._store.begin_evidence(
                event_id=event_id,
                started_at=observed_at,
                capture_deadline=deadline,
                snapshot_key=None,
                frame_count=0,
            )
        except Exception:
            self._emit_persistence_failure(event_id, observed_at)
            return
        self._record_failure(
            event_id=event_id,
            failed_at=observed_at,
            failure_code=failure_code,
            frame_count=0,
        )

    def _record_failure(
        self,
        *,
        event_id: str,
        failed_at: datetime,
        failure_code: Literal["snapshot_unavailable", "media_write_failed"],
        frame_count: int,
    ) -> None:
        try:
            failed = self._store.fail_evidence(
                event_id=event_id,
                failed_at=failed_at,
                failure_code=failure_code,
                frame_count=frame_count,
            )
        except Exception:
            self._emit_persistence_failure(event_id, failed_at)
            return
        self._log.emit(
            "guardian.evidence_failed",
            observed_at=failed_at,
            event_id=event_id,
            state=failed.state,
            result=failure_code,
            frame_count=failed.frame_count,
        )

    def _interrupt(
        self,
        interrupted_at: datetime,
        *,
        failure_code: Literal["worker_restarted", "worker_stopped"],
    ) -> None:
        try:
            interrupted = self._store.interrupt_collecting_evidence(
                interrupted_at=interrupted_at,
                failure_code=failure_code,
            )
        except Exception:
            self._emit_persistence_failure(None, interrupted_at)
            return
        for evidence in interrupted:
            self._log.emit(
                "guardian.evidence_interrupted",
                observed_at=interrupted_at,
                event_id=evidence.event_id,
                state=evidence.state,
                result=failure_code,
                frame_count=evidence.frame_count,
            )

    def _emit_persistence_failure(
        self,
        event_id: str | None,
        observed_at: datetime,
    ) -> None:
        self._log.emit(
            "guardian.evidence_failed",
            observed_at=observed_at,
            event_id=event_id,
            state="failed",
            result="persistence_unavailable",
            frame_count=0,
        )
