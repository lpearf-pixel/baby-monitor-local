from __future__ import annotations

import json
import re
from datetime import datetime
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator

from packages.contracts.vision import VisualReview


MAX_SCENARIO_BYTES = 256 * 1024
LaneName = Literal[
    "visual_observation",
    "guardian_deterministic",
    "voice_generated",
]
RunStatus = Literal["PASS", "FAIL", "SKIP"]
_COUNT_KEY = re.compile(r"^[a-z0-9][a-z0-9_.-]{0,95}$")


class OfflineScenarioContract(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class VisualScenarioV1(OfflineScenarioContract):
    clip_id: str = Field(pattern=r"^[A-Z][A-Z0-9-]{1,63}$")
    profile: Literal["analysis_realtime", "analysis_slow"]
    minimum_frames_processed: int = Field(ge=1, le=18_000)
    provenance: Literal["PUBLIC_VIDEO", "GENERATED_VISUAL"]


class GuardianTimelineEntryV1(OfflineScenarioContract):
    observed_at: datetime
    review: VisualReview

    @field_validator("observed_at")
    @classmethod
    def require_aware_time(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("offline_scenario_time_invalid")
        return value


class GuardianScenarioV1(OfflineScenarioContract):
    provenance: Literal["SYNTHETIC_SEMANTIC_ORACLE"]
    timeline: tuple[GuardianTimelineEntryV1, ...] = Field(min_length=1, max_length=64)
    transition_counts: dict[str, int] = Field(default_factory=dict)
    event_counts: dict[str, int] = Field(default_factory=dict)
    dashboard_event_count: int = Field(ge=0, le=20)
    dashboard_open_event_count: int = Field(ge=0, le=20)

    @field_validator("transition_counts", "event_counts")
    @classmethod
    def require_counts(cls, value: dict[str, int]) -> dict[str, int]:
        if (
            len(value) > 32
            or any(_COUNT_KEY.fullmatch(key) is None for key in value)
            or any(type(count) is not int or count < 0 for count in value.values())
        ):
            raise ValueError("offline_scenario_counts_invalid")
        return value

    @model_validator(mode="after")
    def require_ordered_timeline(self) -> "GuardianScenarioV1":
        times = [entry.observed_at for entry in self.timeline]
        if any(right <= left for left, right in zip(times, times[1:])):
            raise ValueError("offline_scenario_time_invalid")
        if self.dashboard_open_event_count > self.dashboard_event_count:
            raise ValueError("offline_scenario_counts_invalid")
        return self


class VoiceScenarioStepV1(OfflineScenarioContract):
    step_id: str = Field(pattern=r"^[a-z0-9][a-z0-9_-]{0,63}$")
    speech_expected: bool
    from_replay: bool = False
    expected_reason: str = Field(pattern=r"^[a-z0-9_]+$")
    expected_response_code: str | None = Field(
        default=None,
        pattern=r"^[a-z0-9_]+$",
    )


class VoiceScenarioV1(OfflineScenarioContract):
    provenance: Literal["GENERATED_AUDIO"]
    fixture_id: str = Field(pattern=r"^[a-z0-9][a-z0-9_-]{0,63}$")
    steps: tuple[VoiceScenarioStepV1, ...] = Field(min_length=1, max_length=16)
    expected_response_count: int = Field(ge=0, le=16)

    @model_validator(mode="after")
    def require_unique_steps(self) -> "VoiceScenarioV1":
        identifiers = [step.step_id for step in self.steps]
        if len(set(identifiers)) != len(identifiers):
            raise ValueError("offline_scenario_voice_invalid")
        return self


class OfflineGuardianScenarioV1(OfflineScenarioContract):
    schema_version: Literal[1] = 1
    scenario_id: str = Field(pattern=r"^[A-Z][A-Z0-9-]{2,63}$")
    required_lanes: tuple[LaneName, ...] = Field(min_length=1, max_length=3)
    visual: VisualScenarioV1 | None = None
    guardian: GuardianScenarioV1 | None = None
    voice: VoiceScenarioV1 | None = None

    @model_validator(mode="after")
    def require_coherent_lanes(self) -> "OfflineGuardianScenarioV1":
        if len(set(self.required_lanes)) != len(self.required_lanes):
            raise ValueError("offline_scenario_lane_invalid")
        configured = {
            name
            for name, value in (
                ("visual_observation", self.visual),
                ("guardian_deterministic", self.guardian),
                ("voice_generated", self.voice),
            )
            if value is not None
        }
        if configured != set(self.required_lanes):
            raise ValueError("offline_scenario_lane_invalid")
        return self


class OfflineScenarioSuiteV1(OfflineScenarioContract):
    schema_version: Literal[1] = 1
    suite_id: str = Field(pattern=r"^[a-z0-9][a-z0-9_.-]{0,63}$")
    scenarios: tuple[OfflineGuardianScenarioV1, ...] = Field(
        min_length=1,
        max_length=8,
    )

    @model_validator(mode="after")
    def require_unique_scenarios(self) -> "OfflineScenarioSuiteV1":
        identifiers = [scenario.scenario_id for scenario in self.scenarios]
        if len(set(identifiers)) != len(identifiers):
            raise ValueError("offline_scenario_duplicate")
        return self


class ScenarioLaneResult(OfflineScenarioContract):
    lane: LaneName
    status: RunStatus
    reason: str = Field(pattern=r"^[a-z0-9_]+$")
    counts: dict[str, int] = Field(default_factory=dict)
    metrics_ms: dict[str, float] = Field(default_factory=dict)

    @field_validator("counts")
    @classmethod
    def require_result_counts(cls, value: dict[str, int]) -> dict[str, int]:
        if (
            len(value) > 64
            or any(_COUNT_KEY.fullmatch(key) is None for key in value)
            or any(type(count) is not int or count < 0 for count in value.values())
        ):
            raise ValueError("offline_scenario_counts_invalid")
        return value

    @field_validator("metrics_ms")
    @classmethod
    def require_metrics(cls, value: dict[str, float]) -> dict[str, float]:
        if (
            len(value) > 16
            or any(_COUNT_KEY.fullmatch(key) is None for key in value)
            or any(
                type(metric) not in {int, float}
                or not 0 <= float(metric) <= 3_600_000
                for metric in value.values()
            )
        ):
            raise ValueError("offline_scenario_metrics_invalid")
        return {key: float(metric) for key, metric in value.items()}


class OfflineScenarioResultV1(OfflineScenarioContract):
    schema_version: Literal[1] = 1
    scenario_id: str = Field(pattern=r"^[A-Z][A-Z0-9-]{2,63}$")
    status: RunStatus
    reason: str = Field(pattern=r"^[a-z0-9_]+$")
    lanes: tuple[ScenarioLaneResult, ...] = Field(min_length=1, max_length=3)

    @model_validator(mode="after")
    def require_unique_lanes(self) -> "OfflineScenarioResultV1":
        lanes = [lane.lane for lane in self.lanes]
        if len(set(lanes)) != len(lanes):
            raise ValueError("offline_scenario_lane_invalid")
        return self


class OfflineScenarioRunV1(OfflineScenarioContract):
    schema_version: Literal[1] = 1
    suite_id: str = Field(pattern=r"^[a-z0-9][a-z0-9_.-]{0,63}$")
    status: RunStatus
    reason: str = Field(pattern=r"^[a-z0-9_]+$")
    results: tuple[OfflineScenarioResultV1, ...] = Field(min_length=1, max_length=8)
    production_state_touched: Literal[False] = False
    notification_dispatch_attempted: Literal[False] = False
    evidence_persisted: Literal[False] = False
    camera_opened: Literal[False] = False
    raw_audio_persisted: Literal[False] = False
    baby_care_called: Literal[False] = False

    @model_validator(mode="after")
    def require_unique_results(self) -> "OfflineScenarioRunV1":
        identifiers = [result.scenario_id for result in self.results]
        if len(set(identifiers)) != len(identifiers):
            raise ValueError("offline_scenario_duplicate")
        return self


def load_offline_scenario_suite(path: Path) -> OfflineScenarioSuiteV1:
    try:
        candidate = Path(path)
        if candidate.is_symlink() or not candidate.is_file():
            raise ValueError
        raw = candidate.read_bytes()
        if not raw or len(raw) > MAX_SCENARIO_BYTES:
            raise ValueError
        return OfflineScenarioSuiteV1.model_validate_json(raw)
    except (OSError, ValueError, ValidationError):
        raise ValueError("offline_scenario_manifest_invalid") from None


def canonical_offline_scenario_bytes(value: OfflineScenarioSuiteV1) -> bytes:
    return _canonical(value)


def canonical_offline_run_bytes(value: OfflineScenarioRunV1) -> bytes:
    return _canonical(value)


def _canonical(value: BaseModel) -> bytes:
    return json.dumps(
        value.model_dump(mode="json"),
        ensure_ascii=True,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("ascii")


__all__ = [
    "GuardianScenarioV1",
    "GuardianTimelineEntryV1",
    "LaneName",
    "OfflineGuardianScenarioV1",
    "OfflineScenarioResultV1",
    "OfflineScenarioRunV1",
    "OfflineScenarioSuiteV1",
    "ScenarioLaneResult",
    "VisualScenarioV1",
    "VoiceScenarioStepV1",
    "VoiceScenarioV1",
    "canonical_offline_run_bytes",
    "canonical_offline_scenario_bytes",
    "load_offline_scenario_suite",
]
