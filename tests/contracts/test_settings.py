from __future__ import annotations

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
  humidity_low_rh: 35
  humidity_high_rh: 60
  sustained_seconds: 300
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
