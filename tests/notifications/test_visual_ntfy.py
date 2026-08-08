from __future__ import annotations

from contextlib import AbstractContextManager
from datetime import datetime, timedelta, timezone
import json
from typing import BinaryIO

from services.notifications.visual_ntfy import NtfyVisualHealthNotifier
from services.storage.visual_health import StoredVisualHealthIncident


NOW = datetime(2026, 8, 8, 18, 0, tzinfo=timezone(timedelta(hours=8)))


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


def incident(*, code: str = "source_offline", state: str = "open"):
    recovered = state == "recovered"
    return StoredVisualHealthIncident(
        incident_id="visual-health-1",
        code=code,
        state=state,
        opened_at=NOW,
        updated_at=NOW + (timedelta(seconds=90) if recovered else timedelta()),
        recovered_at=NOW + timedelta(seconds=90) if recovered else None,
        duration_seconds=20.0 if recovered else 60.0,
        opened_notified=True if recovered else False,
        recovered_notified=False,
    )


def notifier(opener: object, *, sleep=lambda _delay: None):
    return NtfyVisualHealthNotifier(
        ntfy_base_url="https://ntfy.example.test",
        topic="private-topic-name",
        token="local-secret-token",
        opener=opener,
        sleep=sleep,
    )


def test_open_payload_contains_only_fixed_privacy_safe_fields() -> None:
    opener = RecordingOpener([200])

    result = notifier(opener).notify(incident(), "opened")

    assert result.delivered is True
    assert result.code == "ok"
    request = opener.requests[0]
    payload = json.loads(request.data.decode())
    assert set(payload) == {"topic", "title", "message", "priority", "tags"}
    assert payload["topic"] == "private-topic-name"
    assert payload["priority"] == "max"
    assert payload["tags"] == ["warning", "camera"]
    assert "source_offline" in payload["message"]
    assert "opened" in payload["message"]
    serialized = json.dumps(payload)
    for forbidden in (
        "image",
        "attachment",
        "192.168.",
        "127.0.0.1",
        "local-secret-token",
        "nursery-main",
        "cs2",
    ):
        assert forbidden not in serialized
    assert request.headers["Authorization"] == "Bearer local-secret-token"


def test_recovery_payload_uses_recovery_state_and_lower_priority() -> None:
    opener = RecordingOpener([204])

    result = notifier(opener).notify(incident(state="recovered"), "recovered")

    payload = json.loads(opener.requests[0].data.decode())
    assert result.delivered is True
    assert payload["priority"] == "default"
    assert payload["tags"] == ["white_check_mark", "camera"]
    assert "recovered" in payload["message"]
    assert "20" in payload["message"]


def test_network_and_server_failures_retry_with_bounded_delays() -> None:
    opener = RecordingOpener([OSError("private path"), 503, 200])
    delays: list[float] = []

    result = notifier(opener, sleep=delays.append).notify(incident(), "opened")

    assert result.delivered is True
    assert len(opener.requests) == 3
    assert delays == [0.1, 0.5]


def test_client_rejection_does_not_retry() -> None:
    opener = RecordingOpener([403, 200])

    result = notifier(opener).notify(incident(), "opened")

    assert result.code == "ntfy_rejected"
    assert result.delivered is False
    assert len(opener.requests) == 1


def test_invalid_transition_kind_is_rejected_without_network() -> None:
    opener = RecordingOpener([200])

    result = notifier(opener).notify(incident(), "changed")

    assert result.code == "payload_rejected"
    assert opener.requests == []
