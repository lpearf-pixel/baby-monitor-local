from __future__ import annotations

import hashlib
import json
import os
import re
import stat
from datetime import datetime
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator

from packages.contracts.offline_guardian_scenario import (
    ScenarioActionCode,
    ScenarioMatchKind,
)
from packages.contracts.vision import VisualReview


MAX_INPUT_BYTES = 256 * 1024
EvidenceClass = Literal["HISTORICAL", "SOFTWARE_REHEARSAL", "PANORAMIC_DEVICE"]
EvidenceResult = Literal["PASS", "FAIL", "PARTIAL", "NOT_PROVEN"]
ApplicationLane = Literal["application_oracle", "voice_application", "joined_application"]
RunStatus = Literal["PASS", "FAIL"]
ReplyBehavior = Literal["success", "timeout", "failure"]
_SAFE_KEY = re.compile(r"^[a-z0-9][a-z0-9_.-]{0,95}$")
_ID = re.compile(r"^[A-Z][A-Z0-9-]{2,95}$")
_HEX40 = re.compile(r"^[0-9a-f]{40}$")
_HEX64 = re.compile(r"^[0-9a-f]{64}$")
_LOW_RISK = frozenset({
    "feeding_command", "diaper_change_start", "diaper_change_complete",
    "burping_start", "burping_complete",
})
_SCENARIOS = (
    "APP-SAFE-SLEEP-01", "APP-FACE-OCCLUSION-01", "APP-EMPTY-BED-01",
    "APP-ADULT-ONLY-01", "APP-CROSS-RISK-LEGACY-01",
    "APP-FACE-TO-OUTSIDE-01", "APP-VOICE-FEEDING-01",
    "APP-VOICE-DIAPER-01", "APP-VOICE-BURPING-01",
    "APP-JOINED-FEEDING-SAFE-01", "APP-JOINED-DIAPER-ADULT-ONLY-01",
    "APP-JOINED-BURPING-FACE-TO-OUTSIDE-01",
)


class OfflineApplicationContract(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


def _counts(value: dict[str, int]) -> dict[str, int]:
    if (
        len(value) > 128
        or any(_SAFE_KEY.fullmatch(key) is None for key in value)
        or any(type(count) is not int or not 0 <= count <= 1_000_000 for count in value.values())
    ):
        raise ValueError("offline_application_counts_invalid")
    return value


class HistoricalEvidenceV1(OfflineApplicationContract):
    evidence_class: Literal["HISTORICAL"] = "HISTORICAL"
    evidence_id: str = Field(pattern=r"^[A-Z][A-Z0-9-]{2,95}$")
    source_commit: str
    observed_at: datetime
    scope: Literal[
        "low_risk_voice_reachability", "empty_room_zero_event_sample",
        "camera_reply_v3e",
    ]
    result: EvidenceResult
    fresh_for_this_run: Literal[False] = False

    @field_validator("source_commit")
    @classmethod
    def require_commit(cls, value: str) -> str:
        if _HEX40.fullmatch(value) is None:
            raise ValueError("offline_application_commit_invalid")
        return value

    @field_validator("observed_at")
    @classmethod
    def require_aware(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("offline_application_time_invalid")
        return value


class ApplicationStepV1(OfflineApplicationContract):
    step_id: str = Field(pattern=r"^[a-z0-9][a-z0-9_-]{0,63}$")
    offset_ms: int = Field(ge=0, le=3_600_000)
    visual_review: VisualReview | None = None
    voice_fixture_id: str | None = Field(default=None, pattern=r"^[a-z0-9][a-z0-9_-]{0,63}$")
    expected_action_code: ScenarioActionCode | None = None
    expected_match_kind: ScenarioMatchKind | None = None
    reply_behavior: ReplyBehavior | None = None

    @model_validator(mode="after")
    def require_one_input_and_coherent_voice(self) -> "ApplicationStepV1":
        if (self.visual_review is None) == (self.voice_fixture_id is None):
            raise ValueError("offline_application_step_invalid")
        if self.visual_review is not None:
            if any(value is not None for value in (
                self.expected_action_code, self.expected_match_kind, self.reply_behavior
            )):
                raise ValueError("offline_application_step_invalid")
            return self
        if (self.expected_action_code is None) != (self.expected_match_kind is None):
            raise ValueError("offline_application_voice_invalid")
        if self.expected_action_code is not None and (
            self.expected_action_code not in _LOW_RISK
            or self.expected_match_kind != "exact"
        ):
            raise ValueError("offline_application_voice_invalid")
        return self


class RehearsalScenarioV1(OfflineApplicationContract):
    scenario_id: str = Field(pattern=r"^[A-Z][A-Z0-9-]{2,95}$")
    lane: ApplicationLane
    steps: tuple[ApplicationStepV1, ...] = Field(min_length=1, max_length=32)
    expected_counts: dict[str, int]

    _validate_counts = field_validator("expected_counts")(_counts)

    @model_validator(mode="after")
    def require_ordered_unique_steps(self) -> "RehearsalScenarioV1":
        identifiers = [step.step_id for step in self.steps]
        offsets = [step.offset_ms for step in self.steps]
        if len(set(identifiers)) != len(identifiers):
            raise ValueError("offline_application_step_invalid")
        if any(right <= left for left, right in zip(offsets, offsets[1:])):
            raise ValueError("offline_application_step_invalid")
        has_visual = any(step.visual_review is not None for step in self.steps)
        has_voice = any(step.voice_fixture_id is not None for step in self.steps)
        expected = {
            "application_oracle": (True, False),
            "voice_application": (False, True),
            "joined_application": (True, True),
        }[self.lane]
        if (has_visual, has_voice) != expected:
            raise ValueError("offline_application_lane_invalid")
        return self


class RehearsalSuiteV1(OfflineApplicationContract):
    schema_version: Literal[1] = 1
    suite_id: Literal["offline-application-rehearsal-v1"]
    scenarios: tuple[RehearsalScenarioV1, ...] = Field(min_length=12, max_length=12)

    @model_validator(mode="after")
    def require_exact_pack(self) -> "RehearsalSuiteV1":
        identifiers = tuple(item.scenario_id for item in self.scenarios)
        lanes = tuple(item.lane for item in self.scenarios)
        if identifiers != _SCENARIOS or len(set(identifiers)) != 12:
            raise ValueError("offline_application_scenarios_invalid")
        if tuple(lanes.count(name) for name in (
            "application_oracle", "voice_application", "joined_application"
        )) != (6, 3, 3):
            raise ValueError("offline_application_lanes_invalid")
        return self


class ApplicationScenarioResultV1(OfflineApplicationContract):
    evidence_class: Literal["SOFTWARE_REHEARSAL"] = "SOFTWARE_REHEARSAL"
    scenario_id: str = Field(pattern=r"^[A-Z][A-Z0-9-]{2,95}$")
    lane: ApplicationLane
    status: RunStatus
    reason: str = Field(pattern=r"^[a-z0-9_]+$")
    counts: dict[str, int]
    event_ids: tuple[str, ...] = Field(default=(), max_length=32)
    reply_ids: tuple[str, ...] = Field(default=(), max_length=32)

    _validate_counts = field_validator("counts")(_counts)


class FaultResultV1(OfflineApplicationContract):
    fault_id: str = Field(pattern=r"^[A-Z][A-Z0-9-]{2,95}$")
    outcome: Literal["CLOSED", "UNEXPECTED"]
    reason: str = Field(pattern=r"^[a-z0-9_]+$")
    cleanup_count: int = Field(ge=0, le=32)


class RepetitionIterationV1(OfflineApplicationContract):
    iteration: int = Field(ge=1, le=10)
    status: RunStatus
    stable_digest: str = Field(pattern=r"^[0-9a-f]{64}$")
    counts: dict[str, int]

    _validate_counts = field_validator("counts")(_counts)


class RepetitionResultV1(OfflineApplicationContract):
    status: RunStatus
    reason: str = Field(pattern=r"^[a-z0-9_]+$")
    iterations: tuple[RepetitionIterationV1, ...] = Field(min_length=10, max_length=10)
    cross_risk_instances: Literal[50]
    cross_risk_pass: int = Field(ge=0, le=50)


class SideEffectCountsV1(OfflineApplicationContract):
    camera_access: Literal[False] = False
    camera_reply_enabled: Literal[False] = False
    ptz_commands: Literal[False] = False
    real_notifications: Literal[False] = False
    baby_care_writes: Literal[False] = False
    private_media_reads: Literal[False] = False
    raw_audio_persisted: Literal[False] = False


class OfflineApplicationRunV1(OfflineApplicationContract):
    schema_version: Literal[1] = 1
    suite_id: Literal["offline-application-rehearsal-v1"]
    run_id: str = Field(pattern=r"^run-[0-9a-f]{16}$")
    generated_at: datetime
    status: RunStatus
    reason: str = Field(pattern=r"^[a-z0-9_]+$")
    evidence_class: Literal["SOFTWARE_REHEARSAL"]
    historical: tuple[HistoricalEvidenceV1, ...] = Field(min_length=3, max_length=3)
    results: tuple[ApplicationScenarioResultV1, ...] = Field(min_length=12, max_length=12)
    faults: tuple[FaultResultV1, ...] = Field(min_length=10, max_length=10)
    repetition: RepetitionResultV1
    imported_status: Literal["PASS"]
    imported_scenarios: Literal[8]
    imported_lanes: Literal[13]
    imported_visual_clips: Literal[5]
    imported_frames: Literal[330]
    imported_skipped_frames: Literal[0]
    imported_dropped_frames: Literal[0]
    imported_decode_errors: Literal[0]
    imported_worker_errors: Literal[0]
    imported_visual_oracle_relationship: Literal["INDEPENDENT"]
    side_effects: SideEffectCountsV1
    counts: dict[str, int]

    _validate_counts = field_validator("counts")(_counts)

    @field_validator("generated_at")
    @classmethod
    def require_aware(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("offline_application_time_invalid")
        return value

    @model_validator(mode="after")
    def require_exact_identifiers_and_zeroes(self) -> "OfflineApplicationRunV1":
        if tuple(item.scenario_id for item in self.results) != _SCENARIOS:
            raise ValueError("offline_application_scenarios_invalid")
        required_zero = {
            "no_baby_face_watch", "no_baby_face_alert", "no_baby_face_event",
            "no_baby_face_notification", "residual_reply_sessions",
        }
        if any(self.counts.get(key) != 0 for key in required_zero):
            raise ValueError("offline_application_counts_invalid")
        return self


def _read_private_json(path: Path) -> bytes:
    candidate = Path(path)
    try:
        before = candidate.lstat()
        if not stat.S_ISREG(before.st_mode) or before.st_size <= 0 or before.st_size > MAX_INPUT_BYTES:
            raise ValueError
        flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
        fd = os.open(candidate, flags)
        try:
            opened = os.fstat(fd)
            if (opened.st_dev, opened.st_ino) != (before.st_dev, before.st_ino):
                raise ValueError
            raw = os.read(fd, MAX_INPUT_BYTES + 1)
        finally:
            os.close(fd)
        if not raw or len(raw) > MAX_INPUT_BYTES:
            raise ValueError
        return raw
    except (OSError, ValueError):
        raise ValueError("offline_application_manifest_invalid") from None


def load_rehearsal_suite(path: Path) -> RehearsalSuiteV1:
    try:
        return RehearsalSuiteV1.model_validate_json(_read_private_json(path))
    except (ValidationError, ValueError):
        raise ValueError("offline_application_manifest_invalid") from None


def load_historical_ledger(path: Path) -> tuple[HistoricalEvidenceV1, ...]:
    try:
        raw = json.loads(_read_private_json(path))
        if not isinstance(raw, list) or len(raw) != 3:
            raise ValueError
        result = tuple(HistoricalEvidenceV1.model_validate(item) for item in raw)
        if len({item.evidence_id for item in result}) != 3:
            raise ValueError
        return result
    except (json.JSONDecodeError, ValidationError, ValueError):
        raise ValueError("offline_application_history_invalid") from None


def canonical_application_run_bytes(run: OfflineApplicationRunV1) -> bytes:
    return json.dumps(
        run.model_dump(mode="json"), ensure_ascii=True, sort_keys=True,
        separators=(",", ":"),
    ).encode("ascii")


def stable_application_digest(run: OfflineApplicationRunV1) -> str:
    payload = run.model_dump(mode="json")
    payload["run_id"] = "run-0000000000000000"
    payload["generated_at"] = "2000-01-01T00:00:00Z"
    event_ids: dict[str, str] = {}
    reply_ids: dict[str, str] = {}
    for result in payload["results"]:
        result["event_ids"] = [
            event_ids.setdefault(value, f"event-{len(event_ids) + 1:04d}")
            for value in result["event_ids"]
        ]
        result["reply_ids"] = [
            reply_ids.setdefault(value, f"reply-{len(reply_ids) + 1:04d}")
            for value in result["reply_ids"]
        ]
    canonical = json.dumps(payload, ensure_ascii=True, sort_keys=True, separators=(",", ":")).encode("ascii")
    return hashlib.sha256(canonical).hexdigest()


__all__ = [
    "ApplicationScenarioResultV1", "ApplicationStepV1", "FaultResultV1",
    "HistoricalEvidenceV1", "OfflineApplicationRunV1", "RehearsalScenarioV1",
    "RehearsalSuiteV1", "RepetitionIterationV1", "RepetitionResultV1",
    "SideEffectCountsV1", "canonical_application_run_bytes",
    "load_historical_ledger", "load_rehearsal_suite", "stable_application_digest",
]
