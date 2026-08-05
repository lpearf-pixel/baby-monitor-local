from __future__ import annotations

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from packages.contracts.settings import AppSettings, UnsafeCredentialError


def write_settings(tmp_path: Path, content: str) -> Path:
    path = tmp_path / "settings.yaml"
    path.write_text(content, encoding="utf-8")
    return path


def valid_yaml() -> str:
    return """
app:
  timezone: Asia/Shanghai
  data_dir: ./runtime
camera:
  identifier: nursery-main
  model: MJSXJ17CM
  account_secret_env: MI_ACCOUNT_SECRET_REF
stream:
  go2rtc_api_host: 127.0.0.1
  go2rtc_api_port: 1984
  analysis_width: 960
  analysis_height: 540
  analysis_fps: 5
retention:
  event_retention_days: 30
  event_quota_gb: 30
  reading_retention_days: 365
thresholds:
  temperature_low_c: 18
  temperature_high_c: 26
  temperature_critical_low_c: 15
  temperature_critical_high_c: 30
  humidity_low_rh: 35
  humidity_high_rh: 60
  humidity_critical_low_rh: 25
  humidity_critical_high_rh: 75
  sustained_seconds: 300
environment:
  enabled: true
  source_kind: ws2021_gauge
  interval_seconds: 60
  freshness_seconds: 90
  burst_frames: 5
  burst_interval_ms: 500
  minimum_confidence: 0.75
  unreadable_seconds: 600
  normal_sustained_seconds: 300
  recovery_sustained_seconds: 300
  critical_confirmations: 2
  critical_min_span_seconds: 60
  calibration_path: runtime/calibration/ws2021-v1.json
  policy:
    mode: monitor_only
    required_independent_sources_for_control: 2
notifications:
  ntfy_topic: private-topic-name
  ntfy_token_env: NTFY_TOKEN_SECRET_REF
  enable_wecom: true
  wecom_webhook_env: WECOM_WEBHOOK_SECRET_REF
security:
  session_secret_env: SESSION_SECRET_REF
  public_port_mapping_allowed: false
"""


def test_loads_valid_settings(tmp_path: Path) -> None:
    settings = AppSettings.load(write_settings(tmp_path, valid_yaml()))

    assert settings.camera.identifier == "nursery-main"
    assert settings.camera.model == "MJSXJ17CM"
    assert settings.stream.go2rtc_api_host == "127.0.0.1"
    assert settings.stream.analysis_fps == 5
    assert settings.retention.event_quota_gb == 30
    assert settings.environment.interval_seconds == 60
    assert settings.environment.policy.mode == "monitor_only"


def test_rejects_missing_camera_identifier(tmp_path: Path) -> None:
    path = write_settings(
        tmp_path,
        valid_yaml().replace("  identifier: nursery-main\n", ""),
    )

    with pytest.raises(ValidationError, match="identifier"):
        AppSettings.load(path)


def test_rejects_non_loopback_go2rtc_host(tmp_path: Path) -> None:
    path = write_settings(
        tmp_path,
        valid_yaml().replace("127.0.0.1", "0.0.0.0"),
    )

    with pytest.raises(ValidationError, match="loopback"):
        AppSettings.load(path)


def test_rejects_negative_event_quota(tmp_path: Path) -> None:
    path = write_settings(
        tmp_path,
        valid_yaml().replace("event_quota_gb: 30", "event_quota_gb: -1"),
    )

    with pytest.raises(ValidationError, match="event_quota_gb"):
        AppSettings.load(path)


def test_rejects_raw_credential_keys_before_model_validation(tmp_path: Path) -> None:
    path = write_settings(
        tmp_path,
        valid_yaml().replace(
            "  ntfy_token_env: NTFY_TOKEN_SECRET_REF\n",
            "  ntfy_token: super-secret-token\n",
        ),
    )

    with pytest.raises(UnsafeCredentialError, match="ntfy_token"):
        AppSettings.load(path)


def test_rejects_literal_secret_in_environment_reference_field(tmp_path: Path) -> None:
    path = write_settings(
        tmp_path,
        valid_yaml().replace(
            "MI_ACCOUNT_SECRET_REF",
            "actual-account-password",
        ),
    )

    with pytest.raises(ValidationError, match="environment variable"):
        AppSettings.load(path)


def test_rejects_invalid_analysis_fps(tmp_path: Path) -> None:
    path = write_settings(
        tmp_path,
        valid_yaml().replace("analysis_fps: 5", "analysis_fps: 10"),
    )

    with pytest.raises(ValidationError, match="less than or equal to 5"):
        AppSettings.load(path)


@pytest.mark.parametrize(
    ("old", "new", "message"),
    [
        (
            "temperature_critical_low_c: 15",
            "temperature_critical_low_c: 18",
            "temperature thresholds must be strictly nested",
        ),
        (
            "temperature_critical_high_c: 30",
            "temperature_critical_high_c: 26",
            "temperature thresholds must be strictly nested",
        ),
        (
            "humidity_critical_low_rh: 25",
            "humidity_critical_low_rh: 35",
            "humidity thresholds must be strictly nested",
        ),
        (
            "humidity_critical_high_rh: 75",
            "humidity_critical_high_rh: 60",
            "humidity thresholds must be strictly nested",
        ),
    ],
)
def test_rejects_non_nested_critical_thresholds(
    tmp_path: Path,
    old: str,
    new: str,
    message: str,
) -> None:
    path = write_settings(tmp_path, valid_yaml().replace(old, new))

    with pytest.raises(ValidationError, match=message):
        AppSettings.load(path)


def test_rejects_absolute_or_parent_traversal_calibration_path(tmp_path: Path) -> None:
    absolute = write_settings(
        tmp_path,
        valid_yaml().replace(
            "runtime/calibration/ws2021-v1.json",
            "/private/family/ws2021.json",
        ),
    )
    with pytest.raises(ValidationError, match="relative local path"):
        AppSettings.load(absolute)

    traversal = write_settings(
        tmp_path,
        valid_yaml().replace(
            "runtime/calibration/ws2021-v1.json",
            "../family/ws2021.json",
        ),
    )
    with pytest.raises(ValidationError, match="relative local path"):
        AppSettings.load(traversal)


def test_environment_policy_cannot_enable_control(tmp_path: Path) -> None:
    path = write_settings(
        tmp_path,
        valid_yaml().replace("mode: monitor_only", "mode: automatic_control"),
    )

    with pytest.raises(ValidationError, match="monitor_only"):
        AppSettings.load(path)


def test_checked_in_schema_contains_strict_environment_contract() -> None:
    schema = json.loads(
        Path("config/settings.schema.json").read_text(encoding="utf-8")
    )

    assert schema["properties"]["environment"]["$ref"] == (
        "#/$defs/EnvironmentSettings"
    )
    environment = schema["$defs"]["EnvironmentSettings"]
    assert environment["additionalProperties"] is False
    assert environment["properties"]["interval_seconds"]["default"] == 60
    assert environment["properties"]["burst_frames"]["default"] == 5
    assert environment["properties"]["policy"]["$ref"] == (
        "#/$defs/EnvironmentPolicySettings"
    )
    policy = schema["$defs"]["EnvironmentPolicySettings"]
    assert policy["properties"]["mode"]["const"] == "monitor_only"
    thresholds = schema["$defs"]["ThresholdSettings"]["properties"]
    assert thresholds["temperature_critical_low_c"]["default"] == 15
    assert thresholds["humidity_critical_high_rh"]["default"] == 75
