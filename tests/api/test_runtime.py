from __future__ import annotations

from typing import Any

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
