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


class _AcceptedResponse:
    status = 202

    def __enter__(self) -> "_AcceptedResponse":
        return self

    def __exit__(self, *args: object) -> None:
        return None


def test_gateway_test_notification_is_clearly_non_risk_and_text_only(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    opened: list[tuple[object, float]] = []

    def recording_urlopen(request: object, timeout: float) -> _AcceptedResponse:
        opened.append((request, timeout))
        return _AcceptedResponse()

    monkeypatch.setattr(runtime_module, "urlopen", recording_urlopen)
    gateway = runtime_module.Go2RTCAlphaGateway(
        base_url="http://127.0.0.1:1984",
        stream_name="live",
        ntfy_base_url="https://ntfy.example.test",
        ntfy_topic="private-topic",
        ntfy_token="private-token",
        timeout_seconds=3.5,
    )

    gateway.send_test_notification()

    assert len(opened) == 1
    request, timeout = opened[0]
    body = request.data.decode("utf-8")
    assert timeout == 3.5
    assert "验收测试" in body
    assert "不是宝宝风险告警" in body
    assert "Acceptance Test" in request.headers["Title"]
    request.headers["Title"].encode("ascii")
    assert request.headers["Authorization"] == "Bearer private-token"
    assert request.headers["Tags"] == "test_tube,white_check_mark"
    for forbidden in (
        "private-token",
        "private-topic",
        "ntfy.example.test",
        "127.0.0.1",
        "http://",
        "https://",
    ):
        assert forbidden not in body


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


def test_runtime_injects_guardian_query_from_centralized_data_dir(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = tmp_path / "settings.yaml"
    settings.write_text(
        """
app:
  data_dir: relative-runtime
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
    captured: list[Path] = []

    class RecordingGuardianQuery:
        def __init__(self, database_path: Path) -> None:
            captured.append(database_path)

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(
        runtime_module,
        "GuardianEventQueryService",
        RecordingGuardianQuery,
    )

    runtime = runtime_from_env(
        _environment(BABY_MONITOR_SETTINGS_PATH=str(settings))
    )

    assert captured == [tmp_path / "relative-runtime" / "events.sqlite3"]
    assert isinstance(runtime.guardian_events, RecordingGuardianQuery)


def test_runtime_wires_dashboard_from_existing_services_and_central_data_dir(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = tmp_path / "settings.yaml"
    settings.write_text(
        """
app:
  data_dir: relative-runtime
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
    gateway = object()
    environment = object()
    guardian = object()
    dashboard = object()
    guardian_paths: list[Path] = []
    dashboard_options: list[dict[str, Any]] = []

    def recording_guardian(database_path: Path) -> object:
        guardian_paths.append(database_path)
        return guardian

    def recording_dashboard(**options: Any) -> object:
        dashboard_options.append(options)
        return dashboard

    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(
        runtime_module,
        "notification_gateway_from_env",
        lambda environ: gateway,
    )
    monkeypatch.setattr(
        runtime_module,
        "build_dashboard_service",
        lambda loaded_settings, root: environment,
    )
    monkeypatch.setattr(
        runtime_module,
        "GuardianDashboardQuery",
        recording_guardian,
        raising=False,
    )
    monkeypatch.setattr(
        runtime_module,
        "LocalDashboardService",
        recording_dashboard,
        raising=False,
    )

    runtime = runtime_from_env(
        _environment(BABY_MONITOR_SETTINGS_PATH=str(settings))
    )

    assert guardian_paths == [tmp_path / "relative-runtime" / "events.sqlite3"]
    assert dashboard_options == [
        {
            "camera": gateway,
            "guardian": guardian,
            "environment": environment,
            "camera_reply_enabled": False,
            "timezone_name": "Asia/Shanghai",
        }
    ]
    assert runtime.gateway is gateway
    assert runtime.environment is environment
    assert runtime.dashboard is dashboard


def test_runtime_without_settings_still_wires_honest_degraded_dashboard(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    gateway = object()
    dashboard = object()
    dashboard_options: list[dict[str, Any]] = []

    def recording_dashboard(**options: Any) -> object:
        dashboard_options.append(options)
        return dashboard

    monkeypatch.setattr(
        runtime_module,
        "notification_gateway_from_env",
        lambda environ: gateway,
    )
    monkeypatch.setattr(
        runtime_module,
        "LocalDashboardService",
        recording_dashboard,
        raising=False,
    )

    runtime = runtime_from_env(_environment())

    assert dashboard_options == [
        {
            "camera": gateway,
            "guardian": None,
            "environment": None,
            "camera_reply_enabled": False,
            "timezone_name": "Asia/Shanghai",
        }
    ]
    assert runtime.dashboard is dashboard


def test_gateway_status_failure_uses_stable_public_code(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def failing_urlopen(url: str, timeout: float) -> None:
        raise OSError("private transport detail")

    monkeypatch.setattr(runtime_module, "urlopen", failing_urlopen)
    gateway = runtime_module.Go2RTCAlphaGateway(
        base_url="http://127.0.0.1:1984",
        stream_name="live",
        ntfy_base_url="https://ntfy.example.test",
        ntfy_topic="",
        ntfy_token=None,
    )

    result = gateway.status()

    assert result == {
        "camera": "offline",
        "stream": "live",
        "detail": "camera_status_unavailable",
    }
    assert "OSError" not in repr(result)
    assert "private transport detail" not in repr(result)


def test_runtime_dashboard_closes_provider_failure_and_keeps_camera_reply_disabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def failing_urlopen(url: str, timeout: float) -> None:
        raise OSError(
            "sqlite path ProviderExplosion known_streams token topic confidence "
            "rule_version evidence_key"
        )

    monkeypatch.setattr(runtime_module, "urlopen", failing_urlopen)
    runtime = runtime_from_env(_environment())

    assert runtime.dashboard is not None
    payload = runtime.dashboard.system(
        datetime(2026, 9, 3, tzinfo=UTC)
    ).model_dump(mode="json")

    components = {
        component["component_id"]: component for component in payload["components"]
    }
    assert components["camera"]["state"] == "unavailable"
    assert components["camera"]["reason_code"] == "camera_offline"
    assert components["camera_reply"]["state"] == "disabled"
    assert components["camera_reply"]["reason_code"] == "camera_reply_disabled"
    serialized = repr(payload).lower()
    for forbidden in (
        "sqlite",
        "path",
        "providerexplosion",
        "known_streams",
        "token",
        "topic",
        "confidence",
        "rule_version",
        "evidence_key",
    ):
        assert forbidden not in serialized


def test_gateway_status_success_preserves_existing_stream_shape(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class StreamsResponse:
        def __enter__(self) -> "StreamsResponse":
            return self

        def __exit__(self, *args: object) -> None:
            return None

        def read(self) -> bytes:
            return b'{"other": {}, "live": {}}'

    monkeypatch.setattr(
        runtime_module,
        "urlopen",
        lambda url, timeout: StreamsResponse(),
    )
    gateway = runtime_module.Go2RTCAlphaGateway(
        base_url="http://127.0.0.1:1984",
        stream_name="live",
        ntfy_base_url="https://ntfy.example.test",
        ntfy_topic="",
        ntfy_token=None,
    )

    assert gateway.status() == {
        "camera": "online",
        "stream": "live",
        "known_streams": ["live", "other"],
    }
