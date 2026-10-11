"""Strict client for Baby Care's existing authoritative read-only routes."""

from __future__ import annotations

import json
from collections.abc import Callable
from datetime import datetime
from urllib.parse import urlencode


QueryTransport = Callable[[str], tuple[int, bytes]]
MAX_RESPONSE_BYTES = 64 * 1024


class M7AuthoritativeQueryClient:
    def __init__(self, transport: QueryTransport) -> None:
        self._transport = transport

    def get_feeding_summary(self, at: datetime) -> dict[str, object]:
        path = "/api/care/summary?" + urlencode({"at": at.isoformat()})
        value = self._request(path)
        if not isinstance(value, dict) or not isinstance(value.get("rolling24h"), dict):
            raise ValueError("m7_query_invalid_summary")
        return value

    def get_recent_feedings(
        self,
        at: datetime,
        *,
        from_time: datetime | None = None,
        limit: int = 20,
    ) -> tuple[dict[str, object], ...]:
        if type(limit) is not int or not 1 <= limit <= 50:
            raise ValueError("m7_query_invalid_limit")
        params: dict[str, str | int] = {"category": "feeding", "to": at.isoformat(), "limit": limit}
        if from_time is not None:
            params["from"] = from_time.isoformat()
        value = self._request("/api/care/timeline?" + urlencode(params))
        if not isinstance(value, dict) or not isinstance(value.get("items"), list):
            raise ValueError("m7_query_invalid_timeline")
        items = value["items"]
        if not all(isinstance(item, dict) and item.get("eventType") == "feeding" for item in items):
            raise ValueError("m7_query_invalid_timeline")
        return tuple(item for item in items if isinstance(item, dict))

    def _request(self, path: str) -> object:
        status, raw = self._transport(path)
        if status != 200:
            raise ValueError("m7_query_unavailable")
        if len(raw) > MAX_RESPONSE_BYTES:
            raise ValueError("m7_query_response_too_large")
        try:
            return json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ValueError("m7_query_invalid_json") from exc


__all__ = ["M7AuthoritativeQueryClient", "QueryTransport"]
