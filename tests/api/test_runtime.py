from __future__ import annotations

from typing import Any
from pathlib import Path
from datetime import UTC, datetime

import pytest

import apps.api.runtime as runtime_module
from apps.api.runtime import runtime_from_env


def _environment(**overrides: str) -> dict[str, str]:
    values = {
        "BABY_MONITOR_USERNAME": "parent",
        "BABY_MONITOR_PASSWORD": "dedicated-secret",
        "GO2RTC_BASE_URL": "http://127.0.0.1:1984",
    }
    values.update(overrides)
    return values


def test_runtime_wires_hd_service_to_fixed_profiles_on_configured_loopback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: list[dict[str, Any]] = []
    service = object()

    def recording_service(**options: Any) -> object:
        captured.append(options)
        return service

    monkeypatch.setattr(
        runtime_module,
        "HdStreamService",
        recording_service,
        raising=False,
    )

    runtime = runtime_from_env(
        _environment(GO2RTC_BASE_URL="https://127.0.0.1:2999")
    )

    assert captured == [
        {
            "upstream_base_url": "https://127.0.0.1:2999",
            "native_stream_name": "source",
            "compat_stream_name": "source_compat",
        }
    ]
    assert runtime.hd_stream is service


def test_runtime_rejects_non_loopback_hd_upstream_at_startup() -> None:
    with pytest.raises(ValueError, match="loopback"):
        runtime_from_env(
            _environment(GO2RTC_BASE_URL="http://go2rtc.invalid:1984")
        )


def test_runtime_enables_persistent_environment_dashboard_from_settings(
    tmp_path: Path,
) -> None:
    settings = tmp_path / "settings.yaml"
    settings.write_text(
        f"""
app:
  data_dir: {tmp_path.as_posix()}
camera:
  identifier: nursery-main
  model: MJSXJ17CM
  account_secret_env: MI_ACCOUNT_SECRET_REF
notifications:
  ntfy_topic: private-topic
  ntfy_token_env: NTFY_TOKEN_SECRET_REF
  enable_wecom: false
security:
  session_secret_env: SESSION_SECRET_REF
""",
        encoding="utf-8",
    )

    runtime = runtime_from_env(
        _environment(BABY_MONITOR_SETTINGS_PATH=str(settings))
    )

    assert runtime.environment is not None
    snapshot = runtime.environment.current(
        datetime(2026, 8, 5, tzinfo=UTC)
    )
    assert snapshot.current_reading is None
    assert (tmp_path / "environment.sqlite3").is_file()
