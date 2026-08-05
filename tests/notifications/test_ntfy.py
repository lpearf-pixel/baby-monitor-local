from __future__ import annotations

from contextlib import AbstractContextManager
from datetime import UTC, datetime
import importlib
import json
from typing import BinaryIO

import pytest
from pydantic import ValidationError

from packages.contracts.events import (
    EnvironmentReading,
    EnvironmentSourceKind,
)
from services.events.environment_state import EnvironmentIncident, EnvironmentTransition


NOW = datetime(2026, 8, 5, 12, 0, tzinfo=UTC)


def ntfy_module():
    return importlib.import_module("services.notifications.ntfy")


def reading() -> EnvironmentReading:
    return EnvironmentReading.available(
        reading_id="reading-1",
        source_kind=EnvironmentSourceKind.WS2021_GAUGE,
        captured_at=NOW,
        temperature_c=31,
        humidity_rh=48,
        confidence=0.9,
        calibration_version="calibration-1",
        sample_count=5,
        valid_temperature_samples=5,
        valid_humidity_samples=5,
    )


def transition(kind: str = "opened") -> EnvironmentTransition:
    incident = EnvironmentIncident(
        incident_id="incident-1",
        kind="range",
        state="open" if kind != "recovered" else "recovered",
        severity="critical",
        opened_at=NOW,
        updated_at=NOW,
        recovered_at=NOW if kind == "recovered" else None,
        reasons=("temperature_critical_high",),
        opening_reading_id="reading-1",
        data_available=True,
    )
    return EnvironmentTransition(
        kind=kind,
        occurred_at=NOW,
        incident=incident,
        reading_id="reading-1",
    )


@pytest.mark.parametrize(
    "url",
    [
        "http://monitor.example.test/events",
        "https://127.0.0.1/events",
        "https://192.168.1.5/events",
        "https://user:pass@monitor.example.test/events",
        "https://monitor.example.test/events?token=secret",
        "https://monitor.example.test/events#secret",
        "file:///private/family/event",
        "https://localhost/events",
    ],
)
def test_untrusted_dashboard_links_are_rejected(url: str) -> None:
    module = ntfy_module()

    with pytest.raises(ValidationError):
        module.TrustedDashboardLink(url=url)


class FakeResponse(AbstractContextManager[BinaryIO]):
    def __init__(self, status: int) -> None:
        self.status = status

    def __enter__(self) -> "FakeResponse":
        return self

    def __exit__(self, *args: object) -> None:
        return None


class RecordingOpener:
    def __init__(self, outcomes: list[int | Exception]) -> None:
        self.outcomes = outcomes
        self.requests: list[object] = []

    def __call__(self, request: object, timeout: float) -> FakeResponse:
        self.requests.append(request)
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return FakeResponse(outcome)


def notifier(module: object, opener: object, *, sleep=lambda _: None):
    return module.NtfyEnvironmentNotifier(
        ntfy_base_url="https://ntfy.example.test",
        topic="private-topic-name",
        token="local-secret-token",
        dashboard_link=module.TrustedDashboardLink(
            url="https://nursery.tailnet.ts.net/environment"
        ),
        opener=opener,
        sleep=sleep,
    )


def test_payload_has_fixed_text_only_fields_and_authenticated_link() -> None:
    module = ntfy_module()
    opener = RecordingOpener([200])
    result = notifier(module, opener).notify(transition(), reading())

    assert result.code == "ok"
    assert len(opener.requests) == 1
    request = opener.requests[0]
    payload = json.loads(request.data.decode())
    assert set(payload) == {"topic", "title", "message", "priority", "tags", "click"}
    assert payload["topic"] == "private-topic-name"
    assert payload["click"] == (
        "https://nursery.tailnet.ts.net/environment/incidents/incident-1"
    )
    assert "31.0°C" in payload["message"]
    assert "48.0%RH" in payload["message"]
    assert "temperature_critical_high" in payload["message"]
    serialized = json.dumps(payload)
    for forbidden in (
        "image",
        "attachment",
        "/private/",
        "127.0.0.1",
        "192.168.",
        "local-secret-token",
        "calibration-1",
    ):
        assert forbidden not in serialized
    assert request.headers["Authorization"] == "Bearer local-secret-token"


def test_network_failures_retry_at_most_three_times_with_bounded_delays() -> None:
    module = ntfy_module()
    opener = RecordingOpener([OSError("private path"), OSError("token"), 200])
    delays: list[float] = []

    result = notifier(module, opener, sleep=delays.append).notify(
        transition(), reading()
    )

    assert result.code == "ok"
    assert len(opener.requests) == 3
    assert delays == [0.1, 0.5]


def test_exhausted_network_failure_returns_stable_redacted_code() -> None:
    module = ntfy_module()
    opener = RecordingOpener([OSError("/private/a"), OSError("secret"), OSError("stack")])

    result = notifier(module, opener).notify(transition(), reading())

    assert result.code == "ntfy_unavailable"
    assert result.delivered is False
    assert "/private" not in result.model_dump_json()
    assert "stack" not in result.model_dump_json()


def test_client_rejection_does_not_retry() -> None:
    module = ntfy_module()
    opener = RecordingOpener([400, 200])

    result = notifier(module, opener).notify(transition(), reading())

    assert result.code == "ntfy_rejected"
    assert len(opener.requests) == 1


def test_reason_change_is_not_sent_to_ntfy() -> None:
    module = ntfy_module()
    opener = RecordingOpener([200])

    result = notifier(module, opener).notify(
        transition("reasons_changed"), reading()
    )

    assert result.code == "not_notifiable"
    assert opener.requests == []
