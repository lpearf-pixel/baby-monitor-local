from __future__ import annotations

from collections.abc import Callable, Sequence
from datetime import UTC, datetime, timedelta
import json
import os
from pathlib import Path
import tempfile
from typing import Any, Literal
from uuid import uuid4

from packages.contracts.vision import VisualReview
from services.vision.frame_policy import PreparedAnalysisFrame
from services.vision.review_scheduler import ReviewCompletionCode


RECENT_OBSERVATION_SCHEMA_VERSION = 1
RECENT_OBSERVATION_STALE_AFTER = timedelta(seconds=30)
_STATES = {"available", "stale", "no_result", "failed", "worker_restarted"}
_VISIBILITY = {"visible", "partial", "not_visible", "uncertain"}
_FRESHNESS = {"fresh", "stale", "unknown"}
_REASONS = {
    "none",
    "no_review_yet",
    "review_expired",
    "review_failed",
    "review_timeout",
    "worker_restarted",
}
_INTERNAL_KEYS = (
    "baby_visibility",
    "freshness",
    "input_frame_captured_at",
    "reason_code",
    "result_completed_at",
    "schema_version",
    "state",
    "worker_generation",
    "written_at",
)
_PUBLIC_KEYS = tuple(key for key in _INTERNAL_KEYS if key != "worker_generation")


def _aware_timestamp(value: object, *, field: str) -> datetime:
    if not isinstance(value, str):
        raise ValueError(f"{field} must be timezone-aware")
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError as exc:
        raise ValueError(f"{field} must be timezone-aware") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ValueError(f"{field} must be timezone-aware")
    return parsed


def _validate_payload(payload: object) -> dict[str, Any]:
    if not isinstance(payload, dict) or tuple(sorted(payload)) != tuple(sorted(_INTERNAL_KEYS)):
        raise ValueError("closed recent observation state required")
    if payload["schema_version"] != RECENT_OBSERVATION_SCHEMA_VERSION:
        raise ValueError("closed recent observation state required")
    state = payload["state"]
    visibility = payload["baby_visibility"]
    freshness = payload["freshness"]
    reason = payload["reason_code"]
    generation = payload["worker_generation"]
    if state not in _STATES or visibility not in _VISIBILITY | {None}:
        raise ValueError("closed recent observation state required")
    if freshness not in _FRESHNESS or reason not in _REASONS:
        raise ValueError("closed recent observation state required")
    if not isinstance(generation, str) or not generation or len(generation) > 64:
        raise ValueError("closed recent observation state required")
    _aware_timestamp(payload["written_at"], field="written_at")
    captured = payload["input_frame_captured_at"]
    completed = payload["result_completed_at"]
    if captured is not None:
        _aware_timestamp(captured, field="input_frame_captured_at")
    if completed is not None:
        _aware_timestamp(completed, field="result_completed_at")

    if state == "available":
        valid = visibility is not None and captured is not None and completed is not None
        valid = valid and freshness == "fresh" and reason == "none"
    elif state == "stale":
        valid = visibility is not None and captured is not None and completed is not None
        valid = valid and freshness == "stale" and reason == "review_expired"
    elif state == "no_result":
        valid = visibility is None and captured is None and completed is None
        valid = valid and freshness == "unknown" and reason == "no_review_yet"
    elif state == "failed":
        valid = visibility is None and captured is None and completed is None
        valid = valid and freshness == "unknown" and reason in {"review_failed", "review_timeout"}
    else:
        valid = visibility is None and captured is None and completed is None
        valid = valid and freshness == "unknown" and reason == "worker_restarted"
    if not valid:
        raise ValueError("closed recent observation state required")
    return payload


class RecentObservationStatusWriter:
    def __init__(self, path: Path) -> None:
        self._path = Path(path)

    def write(self, payload: dict[str, object]) -> None:
        checked = _validate_payload(payload)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        descriptor, temporary_name = tempfile.mkstemp(
            prefix=f".{self._path.name}.", suffix=".tmp", dir=self._path.parent
        )
        temporary_path = Path(temporary_name)
        try:
            os.fchmod(descriptor, 0o600)
            with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
                json.dump(checked, handle, separators=(",", ":"), sort_keys=True)
                handle.write("\n")
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary_path, self._path)
            os.chmod(self._path, 0o600)
        except Exception:
            try:
                os.close(descriptor)
            except OSError:
                pass
            temporary_path.unlink(missing_ok=True)
            raise

    def current_generation(self) -> str | None:
        try:
            payload = json.loads(self._path.read_text(encoding="utf-8"))
            return _validate_payload(payload)["worker_generation"]
        except (OSError, ValueError, json.JSONDecodeError):
            return None

    def current_payload(self) -> dict[str, Any] | None:
        try:
            payload = json.loads(self._path.read_text(encoding="utf-8"))
            return _validate_payload(payload)
        except (OSError, ValueError, json.JSONDecodeError):
            return None


def _public_payload(payload: dict[str, Any], *, now: datetime) -> dict[str, object]:
    result = {key: payload[key] for key in _PUBLIC_KEYS}
    if payload["state"] == "available":
        captured = _aware_timestamp(payload["input_frame_captured_at"], field="input_frame_captured_at")
        if now - captured > RECENT_OBSERVATION_STALE_AFTER:
            result["state"] = "stale"
            result["freshness"] = "stale"
            result["reason_code"] = "review_expired"
    return result


def read_recent_observation_status(path: Path, *, now: datetime | None = None) -> dict[str, object]:
    if now is None:
        now = datetime.now(UTC)
    if now.tzinfo is None or now.utcoffset() is None:
        raise ValueError("now must be timezone-aware")
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    return _public_payload(_validate_payload(payload), now=now)


class RecentObservationStatus:
    def __init__(
        self,
        *,
        writer: RecentObservationStatusWriter,
        wall_clock: Callable[[], datetime] | None = None,
        worker_generation: str | None = None,
    ) -> None:
        self._writer = writer
        self._wall_clock = wall_clock or (lambda: datetime.now(UTC))
        self._worker_generation = worker_generation or uuid4().hex
        self._frames: tuple[PreparedAnalysisFrame, ...] = ()

    def mark_worker_restarted(self, *, at: datetime | None = None) -> None:
        moment = at or self._wall_clock()
        self._write(
            state="worker_restarted",
            baby_visibility=None,
            captured=None,
            completed=None,
            freshness="unknown",
            reason="worker_restarted",
            written_at=moment,
            force=True,
        )

    def record_request(self, frames: Sequence[PreparedAnalysisFrame], *, monotonic_now: float) -> None:
        del monotonic_now
        self._frames = tuple(frames)

    def record_timeout(self, *, monotonic_now: float) -> None:
        del monotonic_now
        self._write_failure("review_timeout")

    def record_completion(
        self,
        *,
        code: ReviewCompletionCode,
        review: VisualReview | None,
        monotonic_now: float,
        late: bool = False,
    ) -> None:
        del monotonic_now
        if late:
            return
        if code is ReviewCompletionCode.OK and review is not None and len(self._frames) == 4:
            captured = self._frames[-1].captured_at
            current = self._writer.current_payload()
            if current is not None and current["worker_generation"] == self._worker_generation:
                previous_captured = current["input_frame_captured_at"]
                if previous_captured is not None and captured <= _aware_timestamp(
                    previous_captured, field="input_frame_captured_at"
                ):
                    return
            completed = self._wall_clock()
            self._write(
                state="available",
                baby_visibility=review.baby_visibility.value,
                captured=captured,
                completed=completed,
                freshness="fresh",
                reason="none",
                written_at=completed,
            )
        else:
            self._write_failure("review_failed")
        self._frames = ()

    def _write_failure(self, reason: Literal["review_failed", "review_timeout"]) -> None:
        moment = self._wall_clock()
        self._write(
            state="failed",
            baby_visibility=None,
            captured=None,
            completed=None,
            freshness="unknown",
            reason=reason,
            written_at=moment,
        )

    def _write(
        self,
        *,
        state: str,
        baby_visibility: str | None,
        captured: datetime | None,
        completed: datetime | None,
        freshness: str,
        reason: str,
        written_at: datetime,
        force: bool = False,
    ) -> None:
        current = self._writer.current_generation()
        if not force and current is not None and current != self._worker_generation:
            return
        self._writer.write(
            {
                "schema_version": RECENT_OBSERVATION_SCHEMA_VERSION,
                "state": state,
                "baby_visibility": baby_visibility,
                "input_frame_captured_at": captured.isoformat() if captured else None,
                "result_completed_at": completed.isoformat() if completed else None,
                "freshness": freshness,
                "reason_code": reason,
                "written_at": written_at.isoformat(),
                "worker_generation": self._worker_generation,
            }
        )
