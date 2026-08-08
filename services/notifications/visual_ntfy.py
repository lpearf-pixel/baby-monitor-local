from __future__ import annotations

import json
import time
from collections.abc import Callable
from urllib.error import HTTPError
from urllib.request import Request

from services.notifications.ntfy import (
    NotificationResult,
    NtfyOpener,
    _default_opener,
    _validate_https_dns_url,
)
from services.storage.visual_health import StoredVisualHealthIncident


class NtfyVisualHealthNotifier:
    def __init__(
        self,
        *,
        ntfy_base_url: str,
        topic: str,
        token: str | None,
        opener: NtfyOpener = _default_opener,
        sleep: Callable[[float], None] = time.sleep,
        timeout_seconds: float = 5,
    ) -> None:
        self._base_url = _validate_https_dns_url(
            ntfy_base_url,
            label="ntfy base URL",
        )
        if not topic or len(topic) > 256 or any(character.isspace() for character in topic):
            raise ValueError("ntfy topic is invalid")
        if not 0 < timeout_seconds <= 10:
            raise ValueError("timeout_seconds must be between 0 and 10")
        self._topic = topic
        self._token = token
        self._opener = opener
        self._sleep = sleep
        self._timeout_seconds = timeout_seconds

    def notify(
        self,
        incident: StoredVisualHealthIncident,
        transition_kind: str,
    ) -> NotificationResult:
        if transition_kind not in {"opened", "recovered"}:
            return NotificationResult(
                delivered=False,
                code="payload_rejected",
                attempts=0,
            )
        if (
            transition_kind == "opened" and incident.state != "open"
        ) or (
            transition_kind == "recovered" and incident.state != "recovered"
        ):
            return NotificationResult(
                delivered=False,
                code="payload_rejected",
                attempts=0,
            )
        request = Request(
            self._base_url,
            data=json.dumps(
                self._payload(incident, transition_kind),
                ensure_ascii=False,
                separators=(",", ":"),
            ).encode("utf-8"),
            method="POST",
            headers={
                "Content-Type": "application/json",
                **(
                    {"Authorization": f"Bearer {self._token}"}
                    if self._token
                    else {}
                ),
            },
        )
        delays = (0.1, 0.5)
        for attempt in range(1, 4):
            try:
                with self._opener(request, self._timeout_seconds) as response:
                    status = int(getattr(response, "status", 0))
            except HTTPError as error:
                status = error.code
            except Exception:
                status = 0
            if 200 <= status < 300:
                return NotificationResult(
                    delivered=True,
                    code="ok",
                    attempts=attempt,
                )
            if 400 <= status < 500 and status != 429:
                return NotificationResult(
                    delivered=False,
                    code="ntfy_rejected",
                    attempts=attempt,
                )
            if attempt < 3:
                self._sleep(delays[attempt - 1])
        return NotificationResult(
            delivered=False,
            code="ntfy_unavailable",
            attempts=3,
        )

    def _payload(
        self,
        incident: StoredVisualHealthIncident,
        transition_kind: str,
    ) -> dict[str, object]:
        recovered = transition_kind == "recovered"
        severity = "recovered" if recovered else "critical"
        message = (
            f"event={incident.code}; state={transition_kind}; "
            f"severity={severity}; occurred_at={incident.updated_at.isoformat()}; "
            f"duration_seconds={round(incident.duration_seconds)}"
        )
        return {
            "topic": self._topic,
            "title": "Baby Monitor Local 摄像头提醒",
            "message": message,
            "priority": 3 if recovered else 5,
            "tags": (
                ["white_check_mark", "camera"]
                if recovered
                else ["warning", "camera"]
            ),
        }
