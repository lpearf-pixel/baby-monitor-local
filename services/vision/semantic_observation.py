from __future__ import annotations

from collections import Counter
from collections.abc import Callable, Sequence
from datetime import UTC, datetime
import json
from math import ceil
import os
from pathlib import Path
import re
import tempfile
import threading
from typing import Any, Literal

from packages.contracts.vision import RiskTransition, VisualReview


MAX_OBSERVATION_SECONDS = 600
_VISIBILITY_VALUES = ("visible", "partial", "not_visible", "uncertain")
_BRIDGE_EVENTS = {"failure", "reconnect", "recovery"}


def _now_utc() -> datetime:
    return datetime.now(UTC)


def _fresh_frame_result(frames: Sequence[Any]) -> tuple[bool, bool]:
    """Return (distinct timestamps, existing chronological freshness contract)."""
    if len(frames) != 4:
        return False, False
    captured = tuple(getattr(frame, "captured_at", None) for frame in frames)
    if any(value is None for value in captured):
        return False, False
    distinct = len(set(captured)) == 4
    chronological = all(
        current > previous
        for previous, current in zip(captured, captured[1:])
    )
    return distinct, distinct and chronological


class SemanticObservationSession:
    """Bounded, aggregate-only semantic review diagnostics.

    The session is inert unless explicitly enabled. It never stores frames,
    response text, paths, or identifiers from household data.
    """

    def __init__(
        self,
        *,
        enabled: bool,
        deployment_version: str | None = None,
        max_duration_seconds: int = MAX_OBSERVATION_SECONDS,
        wall_clock: Callable[[], datetime] = _now_utc,
    ) -> None:
        if not 1 <= max_duration_seconds <= MAX_OBSERVATION_SECONDS:
            raise ValueError("semantic observation duration must be 1..600 seconds")
        if deployment_version is not None and (
            deployment_version != "unknown"
            and not re.fullmatch(r"[0-9a-f]{7,64}", deployment_version)
        ):
            raise ValueError("deployment version must be an opaque commit id")
        self._enabled = enabled
        self._deployment_version = deployment_version
        self._max_duration_seconds = max_duration_seconds
        self._wall_clock = wall_clock
        self._state: Literal["disabled", "idle", "active", "stopped", "expired"] = (
            "idle" if enabled else "disabled"
        )
        self._started_at: datetime | None = None
        self._ended_at: datetime | None = None
        self._started_monotonic: float | None = None
        self._last_monotonic: float | None = None
        self._request_count = 0
        self._success_count = 0
        self._failure_count = 0
        self._timeout_count = 0
        self._late_response_count = 0
        self._distinct_timestamp_requests = 0
        self._fresh_frame_requests = 0
        self._visibility: Counter[str] = Counter()
        self._latencies_ms: list[float] = []
        self._guardian_transition_count = 0
        self._bridge_counts: dict[str, int] | None = None
        self._request_started_at: float | None = None
        self._request_timed_out = False
        self._expiry_timer: threading.Timer | None = None

    def start(self, *, monotonic_now: float) -> dict[str, object]:
        if not self._enabled:
            return self.snapshot()
        if self._state == "idle":
            self._started_monotonic = monotonic_now
            self._last_monotonic = monotonic_now
            self._started_at = self._wall_clock()
            self._state = "active"
            self._expiry_timer = threading.Timer(
                self._max_duration_seconds,
                self._expire_from_timer,
            )
            self._expiry_timer.daemon = True
            self._expiry_timer.start()
        return self.snapshot()

    def tick(self, *, monotonic_now: float) -> dict[str, object]:
        self._require_time(monotonic_now)
        if (
            self._state == "active"
            and self._started_monotonic is not None
            and monotonic_now - self._started_monotonic >= self._max_duration_seconds
        ):
            return self._finish("expired")
        return self.snapshot()

    def record_request(self, frames: Sequence[Any], *, monotonic_now: float) -> None:
        if self.tick(monotonic_now=monotonic_now)["state"] != "active":
            return
        distinct, fresh = _fresh_frame_result(frames)
        self._request_count += 1
        if distinct:
            self._distinct_timestamp_requests += 1
        if fresh:
            self._fresh_frame_requests += 1
        self._request_started_at = monotonic_now
        self._request_timed_out = False

    def record_timeout(self, *, monotonic_now: float) -> None:
        if self.tick(monotonic_now=monotonic_now)["state"] != "active":
            return
        if self._request_started_at is not None and not self._request_timed_out:
            self._timeout_count += 1
            self._request_timed_out = True

    def record_completion(
        self,
        *,
        code: object,
        review: VisualReview | None,
        monotonic_now: float,
        late: bool = False,
    ) -> None:
        if self.tick(monotonic_now=monotonic_now)["state"] != "active":
            return
        if self._request_started_at is None:
            return
        is_late = late or self._request_timed_out
        if is_late:
            self._late_response_count += 1
        elif getattr(code, "value", code) == "ok" and review is not None:
            self._success_count += 1
            self._visibility[review.baby_visibility.value] += 1
            self._latencies_ms.append(
                round((monotonic_now - self._request_started_at) * 1000, 3)
            )
        else:
            self._failure_count += 1
        self._request_started_at = None
        self._request_timed_out = False

    def record_transition(self, transition: RiskTransition | object, *, monotonic_now: float) -> None:
        if self.tick(monotonic_now=monotonic_now)["state"] == "active":
            self._guardian_transition_count += 1

    def record_bridge_event(self, event: str, *, monotonic_now: float) -> None:
        if event not in _BRIDGE_EVENTS:
            raise ValueError("unknown bridge event")
        if self.tick(monotonic_now=monotonic_now)["state"] != "active":
            return
        if self._bridge_counts is None:
            self._bridge_counts = {name: 0 for name in _BRIDGE_EVENTS}
        self._bridge_counts[event] += 1

    def stop(self, *, monotonic_now: float) -> dict[str, object]:
        self._require_time(monotonic_now)
        if self._state == "active":
            return self._finish("stopped")
        return self.snapshot()

    def snapshot(self) -> dict[str, object]:
        if not self._enabled:
            return {"enabled": False, "state": "disabled"}
        latencies = sorted(self._latencies_ms)
        latency_payload: dict[str, float] | None = None
        if latencies:
            latency_payload = {
                "p50": latencies[ceil(len(latencies) * 0.50) - 1],
                "p95": latencies[ceil(len(latencies) * 0.95) - 1],
                "max": latencies[-1],
            }
        visibility = {name: self._visibility[name] for name in _VISIBILITY_VALUES}
        bridges = self._bridge_counts
        return {
            "enabled": True,
            "state": self._state,
            "started_at": self._started_at.isoformat() if self._started_at else None,
            "ended_at": self._ended_at.isoformat() if self._ended_at else None,
            "deployment_version": self._deployment_version,
            "request_count": self._request_count,
            "success_count": self._success_count,
            "failure_count": self._failure_count,
            "timeout_count": self._timeout_count,
            "late_response_count": self._late_response_count,
            "distinct_timestamp_requests": self._distinct_timestamp_requests,
            "fresh_frame_requests": self._fresh_frame_requests,
            "baby_visibility": visibility,
            "latency_ms": latency_payload,
            "guardian_transition_count": self._guardian_transition_count,
            "bridge_failures": None if bridges is None else bridges["failure"],
            "bridge_reconnects": None if bridges is None else bridges["reconnect"],
            "bridge_recoveries": None if bridges is None else bridges["recovery"],
        }

    def _finish(self, state: Literal["stopped", "expired"]) -> dict[str, object]:
        if self._expiry_timer is not None:
            self._expiry_timer.cancel()
            self._expiry_timer = None
        self._state = state
        self._ended_at = self._wall_clock()
        return self.snapshot()

    def _expire_from_timer(self) -> None:
        if self._state == "active":
            self._state = "expired"
            self._ended_at = self._wall_clock()

    def _require_time(self, value: float) -> None:
        if value < 0 or (
            self._last_monotonic is not None and value < self._last_monotonic
        ):
            raise ValueError("semantic observation time cannot decrease")
        self._last_monotonic = value


def write_semantic_observation_report(path: Path, snapshot: dict[str, object]) -> None:
    """Atomically write only the bounded aggregate snapshot with mode 0600."""
    if set(snapshot) == {"enabled", "state"} and snapshot.get("enabled") is False:
        raise ValueError("disabled observation has no report")
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
    )
    temporary_path = Path(temporary_name)
    try:
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(snapshot, handle, ensure_ascii=True, sort_keys=True, separators=(",", ":"))
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_path, path)
    except Exception:
        try:
            os.close(descriptor)
        except OSError:
            pass
        temporary_path.unlink(missing_ok=True)
        raise
