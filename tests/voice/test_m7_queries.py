from __future__ import annotations

import json
from datetime import datetime, timezone

import pytest

from services.voice.m7_queries import M7AuthoritativeQueryClient
from services.voice.m7_session import M6ToolExecutor
from services.voice.m7_tools import ValidatedToolCall


def test_query_client_reuses_authoritative_summary_and_timeline_routes() -> None:
    calls: list[str] = []
    now = datetime(2026, 10, 11, 2, 3, 4, tzinfo=timezone.utc)

    def transport(path: str) -> tuple[int, bytes]:
        calls.append(path)
        if path.startswith("/api/care/summary?"):
            return 200, json.dumps({"asOf": now.isoformat(), "lastFeeding": None,
                "lastDiaper": None, "rolling24h": {"bottleTotalMl": 90,
                "expressedBreastMilkMl": 60, "formulaMl": 30,
                "directBreastfeedingSessions": 1, "directBreastfeedingMinutes": 12},
                "currentSleep": None}).encode()
        return 200, json.dumps({"items": [{"id": "event-1", "eventType": "feeding",
            "occurredAt": now.isoformat(), "createdAt": now.isoformat(),
            "updatedAt": now.isoformat(), "status": "active", "source": "voice",
            "actorUserId": None, "actorDisplayName": None, "note": None, "version": 1,
            "isBackfilled": False, "payload": {"components": [], "relatedActions": []}}],
            "nextCursor": None}).encode()

    client = M7AuthoritativeQueryClient(transport)
    summary = client.get_feeding_summary(now)
    recent = client.get_recent_feedings(now, from_time=now.replace(hour=0))

    assert summary["rolling24h"]["bottleTotalMl"] == 90
    assert recent[0]["id"] == "event-1"
    assert calls[0].startswith("/api/care/summary?at=2026-10-11T02%3A03%3A04")
    assert "category=feeding" in calls[1]


def test_query_client_rejects_non_authoritative_or_malformed_results() -> None:
    client = M7AuthoritativeQueryClient(lambda _path: (200, b"{}"))
    with pytest.raises(ValueError, match="m7_query_invalid_summary"):
        client.get_feeding_summary(datetime(2026, 10, 11, tzinfo=timezone.utc))

    unavailable = M7AuthoritativeQueryClient(lambda _path: (503, b"{}"))
    with pytest.raises(ValueError, match="m7_query_unavailable"):
        unavailable.get_feeding_summary(datetime(2026, 10, 11, tzinfo=timezone.utc))


def test_tool_executor_routes_query_tools_to_authoritative_client() -> None:
    class Bridge:
        def process(self, *_args, **_kwargs):
            raise AssertionError("query must not use the local M6 parser")

    class Query:
        def get_feeding_summary(self, _at):
            return {"rolling24h": {"bottleTotalMl": 90}}

        def get_recent_feedings(self, _at, *, from_time=None, limit=20):
            return ({"id": "event-1", "eventType": "feeding"},)

    executor = M6ToolExecutor(
        Bridge(), clock=lambda: datetime(2026, 10, 11, tzinfo=timezone.utc), query_client=Query()
    )
    assert executor.execute(ValidatedToolCall("get_feeding_summary", {})) == "query_result"
    assert executor.last_query == {"rolling24h": {"bottleTotalMl": 90}}
    assert executor.execute(ValidatedToolCall("get_recent_feedings", {})) == "query_result"
    assert executor.last_query == ({"id": "event-1", "eventType": "feeding"},)
