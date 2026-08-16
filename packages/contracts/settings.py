from __future__ import annotations

import ipaddress
from pathlib import Path
from typing import Annotated, Any, Literal

import yaml
from pydantic import (
    AfterValidator,
    BaseModel,
    ConfigDict,
    Field,
    PositiveInt,
    field_validator,
    model_validator,
)

from packages.contracts.events import EnvironmentSourceKind
from packages.contracts.vision import NormalizedPolygon


VISUAL_MODEL_NAME = "qwen3-vl:8b-instruct-q4_K_M"
VISUAL_OLLAMA_BASE_URL = "http://127.0.0.1:11435"


class UnsafeCredentialError(ValueError):
    """Raised when a configuration file contains a literal credential."""


def _validate_env_name(value: str) -> str:
    if not value or not value.replace("_", "A").isalnum() or not value[0].isalpha():
        raise ValueError("must be an environment variable name")
    if value.upper() != value:
        raise ValueError("must be an environment variable name")
    return value


EnvironmentVariableName = Annotated[str, AfterValidator(_validate_env_name)]


class StrictSettingsModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class ApplicationSettings(StrictSettingsModel):
    timezone: str = "Asia/Shanghai"
    data_dir: Path = Path("./runtime")


class CameraSettings(StrictSettingsModel):
    identifier: str = Field(min_length=1)
    model: str = Field(min_length=1)
    account_secret_env: EnvironmentVariableName


class StreamSettings(StrictSettingsModel):
    go2rtc_api_host: str = "127.0.0.1"
    go2rtc_api_port: int = Field(default=1984, ge=1, le=65535)
    analysis_width: PositiveInt = 960
    analysis_height: PositiveInt = 540
    analysis_fps: int = Field(default=5, ge=1, le=5)

    @field_validator("go2rtc_api_host")
    @classmethod
    def require_loopback_host(cls, value: str) -> str:
        if value == "localhost":
            return value
        try:
            address = ipaddress.ip_address(value)
        except ValueError as exc:
            raise ValueError("go2rtc API host must be a loopback address") from exc
        if not address.is_loopback:
            raise ValueError("go2rtc API host must be a loopback address")
        return value


class RetentionSettings(StrictSettingsModel):
    event_retention_days: PositiveInt = 30
    event_quota_gb: int = Field(default=30, ge=1)
    reading_retention_days: PositiveInt = 365


class ThresholdSettings(StrictSettingsModel):
    temperature_low_c: float = 18
    temperature_high_c: float = 26
    temperature_critical_low_c: float = 15
    temperature_critical_high_c: float = 30
    humidity_low_rh: float = Field(default=35, ge=0, le=100)
    humidity_high_rh: float = Field(default=60, ge=0, le=100)
    humidity_critical_low_rh: float = Field(default=25, ge=0, le=100)
    humidity_critical_high_rh: float = Field(default=75, ge=0, le=100)
    sustained_seconds: PositiveInt = 300

    @model_validator(mode="after")
    def require_ordered_ranges(self) -> "ThresholdSettings":
        if not (
            self.temperature_critical_low_c
            < self.temperature_low_c
            < self.temperature_high_c
            < self.temperature_critical_high_c
        ):
            raise ValueError("temperature thresholds must be strictly nested")
        if not (
            self.humidity_critical_low_rh
            < self.humidity_low_rh
            < self.humidity_high_rh
            < self.humidity_critical_high_rh
        ):
            raise ValueError("humidity thresholds must be strictly nested")
        return self


class EnvironmentPolicySettings(StrictSettingsModel):
    mode: Literal["monitor_only"] = "monitor_only"
    required_independent_sources_for_control: int = Field(default=2, ge=2)


class EnvironmentSettings(StrictSettingsModel):
    enabled: bool = True
    source_kind: EnvironmentSourceKind = EnvironmentSourceKind.WS2021_GAUGE
    interval_seconds: PositiveInt = 60
    freshness_seconds: PositiveInt = 90
    burst_frames: int = Field(default=5, ge=3, le=5)
    burst_interval_ms: int = Field(default=500, ge=0, le=2_000)
    minimum_confidence: float = Field(default=0.75, ge=0.5, le=1)
    unreadable_seconds: PositiveInt = 600
    normal_sustained_seconds: PositiveInt = 300
    recovery_sustained_seconds: PositiveInt = 300
    critical_confirmations: int = Field(default=2, ge=2, le=10)
    critical_min_span_seconds: PositiveInt = 60
    calibration_path: Path = Path("runtime/calibration/ws2021-v1.json")
    auto_localization: bool = False
    localization_model_path: Path = Path(
        "runtime/training/ws2021/model/ws2021.xml"
    )
    policy: EnvironmentPolicySettings = EnvironmentPolicySettings()

    @field_validator("calibration_path", "localization_model_path")
    @classmethod
    def require_relative_local_calibration_path(cls, value: Path) -> Path:
        if value.is_absolute() or ".." in value.parts:
            raise ValueError("environment paths must be relative local paths")
        return value

    @model_validator(mode="after")
    def require_coherent_sampling_windows(self) -> "EnvironmentSettings":
        if self.freshness_seconds < self.interval_seconds:
            raise ValueError("freshness_seconds must cover one sampling interval")
        if self.unreadable_seconds < self.interval_seconds:
            raise ValueError("unreadable_seconds must cover one sampling interval")
        if self.critical_min_span_seconds < self.interval_seconds:
            raise ValueError(
                "critical_min_span_seconds must cover one sampling interval"
            )
        return self


class RealtimeVisualSettings(StrictSettingsModel):
    enabled: bool = False


class VisualSettings(StrictSettingsModel):
    enabled: bool = False
    model: Literal["qwen3-vl:8b-instruct-q4_K_M"] = VISUAL_MODEL_NAME
    ollama_base_url: Literal["http://127.0.0.1:11435"] = (
        VISUAL_OLLAMA_BASE_URL
    )
    bed_zone: NormalizedPolygon | None = None
    privacy_masks: tuple[NormalizedPolygon, ...] = ()
    request_timeout_seconds: Literal[20] = 20
    model_degraded_seconds: Literal[60] = 60
    model_failure_threshold: Literal[3] = 3
    model_recovery_successes: Literal[2] = 2
    realtime: RealtimeVisualSettings = RealtimeVisualSettings()

    @model_validator(mode="after")
    def require_bed_zone_when_enabled(self) -> "VisualSettings":
        if self.enabled and self.bed_zone is None:
            raise ValueError("VISUAL_BED_ZONE_REQUIRED")
        return self


class NotificationSettings(StrictSettingsModel):
    ntfy_topic: str = Field(min_length=1)
    ntfy_token_env: EnvironmentVariableName
    enable_wecom: bool = True
    wecom_webhook_env: EnvironmentVariableName | None = None

    @model_validator(mode="after")
    def require_wecom_reference_when_enabled(self) -> "NotificationSettings":
        if self.enable_wecom and self.wecom_webhook_env is None:
            raise ValueError("wecom_webhook_env is required when enable_wecom is true")
        return self


class SecuritySettings(StrictSettingsModel):
    session_secret_env: EnvironmentVariableName
    public_port_mapping_allowed: bool = False

    @field_validator("public_port_mapping_allowed")
    @classmethod
    def reject_public_mapping(cls, value: bool) -> bool:
        if value:
            raise ValueError("public port mapping must remain disabled")
        return value


_SENSITIVE_KEY_PARTS = (
    "password",
    "passwd",
    "token",
    "secret",
    "webhook",
    "api_key",
    "auth_key",
)
_ALLOWED_REFERENCE_SUFFIXES = ("_env", "_secret_ref")


def _reject_literal_credentials(value: Any, path: tuple[str, ...] = ()) -> None:
    if isinstance(value, dict):
        for raw_key, child in value.items():
            key = str(raw_key).lower()
            current_path = (*path, str(raw_key))
            is_sensitive = any(part in key for part in _SENSITIVE_KEY_PARTS)
            is_reference = key.endswith(_ALLOWED_REFERENCE_SUFFIXES)
            if is_sensitive and not is_reference:
                joined = ".".join(current_path)
                raise UnsafeCredentialError(
                    f"literal credential key '{joined}' is forbidden; use an environment reference"
                )
            _reject_literal_credentials(child, current_path)
    elif isinstance(value, list):
        for index, child in enumerate(value):
            _reject_literal_credentials(child, (*path, str(index)))


class AppSettings(StrictSettingsModel):
    app: ApplicationSettings = ApplicationSettings()
    camera: CameraSettings
    stream: StreamSettings = StreamSettings()
    retention: RetentionSettings = RetentionSettings()
    thresholds: ThresholdSettings = ThresholdSettings()
    environment: EnvironmentSettings = EnvironmentSettings()
    visual: VisualSettings = VisualSettings()
    notifications: NotificationSettings
    security: SecuritySettings

    @classmethod
    def load(cls, path: Path) -> "AppSettings":
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
        if not isinstance(raw, dict):
            raise ValueError("settings file must contain a YAML mapping")
        _reject_literal_credentials(raw)
        return cls.model_validate(raw)
