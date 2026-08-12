from __future__ import annotations

from contextlib import AbstractContextManager
from datetime import UTC, datetime
import json
from typing import BinaryIO

import pytest

from packages.contracts.vision import VisualRiskKind
from services.notifications.guardian_ntfy import NtfyGuardianNotifier
from services.storage.visual_risk import (
    StoredVisualRiskEvent,
    StoredVisualRiskNotification,
)


NOW = datetime(2026, 8, 11, 12, 0, tzinfo=UTC)


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


def event(
    *,
    event_id: str = "event-face",
    risk_kind: VisualRiskKind = VisualRiskKind.FACE_NOT_VISIBLE,
    recovered: bool = False,
) -> StoredVisualRiskEvent:
    return StoredVisualRiskEvent(
        event_id=event_id,
        risk_kind=risk_kind,
        state="recovered" if recovered else "open",
        opened_at=NOW,
        updated_at=NOW,
        recovered_at=NOW if recovered else None,
        confidence=0.82,
        rule_version="visual-risk-v1",
    )


def notification(
    *,
    stage: str = "risk_opened",
    event_id: str = "event-face",
) -> StoredVisualRiskNotification:
    return StoredVisualRiskNotification(
        notification_id=f"notification-{stage}",
        event_id=event_id,
        stage=stage,
        intervention_id=(
            "intervention-1" if stage == "adult_intervention" else None
        ),
        state="pending",
        queued_at=NOW,
        updated_at=NOW,
        next_attempt_at=NOW,
        dispatch_count=0,
    )


def notifier(opener: object, *, sleep=lambda _delay: None) -> NtfyGuardianNotifier:
    return NtfyGuardianNotifier(
        ntfy_base_url="https://ntfy.example.test",
        topic="private-topic-name",
        token="local-secret-token",
        opener=opener,
        sleep=sleep,
    )


@pytest.mark.parametrize(
    ("risk_kind", "label"),
    [
        (VisualRiskKind.FACE_NOT_VISIBLE, "口鼻或脸部疑似遮挡"),
        (VisualRiskKind.PRONE_CANDIDATE, "疑似趴睡"),
        (VisualRiskKind.OUTSIDE_CANDIDATE, "疑似离床"),
    ],
)
def test_open_payload_uses_only_allowlisted_text_fields(
    risk_kind: VisualRiskKind,
    label: str,
) -> None:
    opener = RecordingOpener([200])

    result = notifier(opener).notify(
        notification(),
        event(risk_kind=risk_kind),
        "ready",
    )

    assert result.code == "ok"
    request = opener.requests[0]
    payload = json.loads(request.data.decode())
    assert set(payload) == {"topic", "title", "message", "priority", "tags"}
    assert payload["topic"] == "private-topic-name"
    assert payload["priority"] == 5
    assert label in payload["message"]
    assert "event-face" in payload["message"]
    assert "证据=已就绪" in payload["message"]
    serialized = json.dumps(payload, ensure_ascii=False)
    for forbidden in (
        "image",
        "attachment",
        "click",
        "/private/",
        "visual-risk/",
        "127.0.0.1",
        "192.168.",
        "local-secret-token",
        "cs2",
        "model",
    ):
        assert forbidden not in serialized
    assert request.headers["Authorization"] == "Bearer local-secret-token"


@pytest.mark.parametrize(
    ("stage", "recovered", "priority", "text"),
    [
        ("risk_recovered", True, 3, "风险已恢复"),
        ("adult_intervention", False, 4, "检测到成人介入"),
    ],
)
def test_recovery_and_intervention_use_fixed_copy(
    stage: str,
    recovered: bool,
    priority: int,
    text: str,
) -> None:
    opener = RecordingOpener([204])

    result = notifier(opener).notify(
        notification(stage=stage),
        event(recovered=recovered),
        "collecting",
    )

    payload = json.loads(opener.requests[0].data.decode())
    assert result.delivered is True
    assert payload["priority"] == priority
    assert text in payload["message"]


def test_invalid_event_identity_or_mismatched_state_is_rejected_without_network() -> None:
    opener = RecordingOpener([200])
    unsafe_id = "/private/family/192.168.1.5?token=secret"

    unsafe = notifier(opener).notify(
        notification(event_id=unsafe_id),
        event(event_id=unsafe_id),
        "failed",
    )
    mismatch = notifier(opener).notify(
        notification(stage="risk_recovered"),
        event(recovered=False),
        "ready",
    )

    assert unsafe.code == "payload_rejected"
    assert mismatch.code == "payload_rejected"
    assert opener.requests == []


def test_network_failures_retry_three_times_with_bounded_delays() -> None:
    opener = RecordingOpener([OSError("/private/a"), 503, 200])
    delays: list[float] = []

    result = notifier(opener, sleep=delays.append).notify(
        notification(),
        event(),
        "unavailable",
    )

    assert result.code == "ok"
    assert len(opener.requests) == 3
    assert delays == [0.1, 0.5]


def test_client_rejection_is_terminal_for_this_dispatch() -> None:
    opener = RecordingOpener([400, 200])

    result = notifier(opener).notify(notification(), event(), "interrupted")

    assert result.code == "ntfy_rejected"
    assert result.attempts == 1
    assert len(opener.requests) == 1


@pytest.mark.parametrize(
    "url",
    [
        "http://ntfy.example.test",
        "https://127.0.0.1",
        "https://user:secret@ntfy.example.test",
        "https://ntfy.example.test?token=secret",
    ],
)
def test_untrusted_ntfy_base_url_is_rejected(url: str) -> None:
    with pytest.raises(ValueError):
        NtfyGuardianNotifier(
            ntfy_base_url=url,
            topic="private-topic-name",
            token=None,
        )
