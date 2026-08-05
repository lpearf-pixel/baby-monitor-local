from __future__ import annotations

import ipaddress
import json
import re
import time
from collections.abc import Callable
from contextlib import AbstractContextManager
from typing import BinaryIO, Literal, Protocol
from urllib.parse import quote, urlsplit
from urllib.request import Request, urlopen

from pydantic import BaseModel, ConfigDict, Field, field_validator

from packages.contracts.events import EnvironmentReading, ReadingState
from services.events.environment_state import EnvironmentTransition


_DNS_LABEL = re.compile(r"^[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?$")
_INCIDENT_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
_ALLOWED_REASON_CODES = {
    "temperature_low",
    "temperature_high",
    "humidity_low",
    "humidity_high",
    "temperature_critical_low",
    "temperature_critical_high",
    "humidity_critical_low",
    "humidity_critical_high",
    "no_new_reading",
    "reading_unavailable",
    "calibration_missing",
    "calibration_invalid",
    "frame_source_unavailable",
    "frame_stale",
    "roi_out_of_bounds",
    "too_dark",
    "glare",
    "occluded",
    "needle_not_found",
    "insufficient_valid_frames",
    "inconsistent_frames",
    "low_confidence",
    "internal_error",
}


class NotificationModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


def _validate_https_dns_url(value: str, *, label: str) -> str:
    parsed = urlsplit(value)
    if (
        parsed.scheme != "https"
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
    ):
        raise ValueError(f"{label} must be a credential-free HTTPS DNS URL")
    try:
        ipaddress.ip_address(parsed.hostname)
    except ValueError:
        pass
    else:
        raise ValueError(f"{label} must use a DNS hostname, not an IP address")
    hostname = parsed.hostname.rstrip(".")
    labels = hostname.split(".")
    if hostname.lower() == "localhost" or len(labels) < 2 or not all(
        _DNS_LABEL.fullmatch(part) for part in labels
    ):
        raise ValueError(f"{label} must use a trusted DNS hostname")
    if any(part == ".." for part in parsed.path.split("/")):
        raise ValueError(f"{label} contains an invalid path")
    return value.rstrip("/")


class TrustedDashboardLink(NotificationModel):
    url: str = Field(min_length=1, max_length=2_048)

    @field_validator("url")
    @classmethod
    def validate_url(cls, value: str) -> str:
        return _validate_https_dns_url(value, label="dashboard link")

    def incident_url(self, incident_id: str) -> str:
        if not _INCIDENT_ID.fullmatch(incident_id):
            raise ValueError("incident_id is not safe for a notification link")
        return f"{self.url}/incidents/{quote(incident_id, safe='')}"


class NotificationResult(NotificationModel):
    delivered: bool
    code: Literal[
        "ok",
        "not_notifiable",
        "payload_rejected",
        "ntfy_rejected",
        "ntfy_unavailable",
    ]
    attempts: int = Field(ge=0, le=3)


class ResponseContext(Protocol):
    status: int

    def __enter__(self) -> BinaryIO: ...

    def __exit__(self, *args: object) -> None: ...


NtfyOpener = Callable[[Request, float], AbstractContextManager[BinaryIO]]


def _default_opener(request: Request, timeout: float) -> AbstractContextManager[BinaryIO]:
    return urlopen(request, timeout=timeout)  # type: ignore[return-value]


class NtfyEnvironmentNotifier:
    def __init__(
        self,
        *,
        ntfy_base_url: str,
        topic: str,
        token: str | None,
        dashboard_link: TrustedDashboardLink,
        opener: NtfyOpener = _default_opener,
        sleep: Callable[[float], None] = time.sleep,
        timeout_seconds: float = 5,
    ) -> None:
        self._base_url = _validate_https_dns_url(
            ntfy_base_url, label="ntfy base URL"
        )
        if not topic or len(topic) > 256 or any(character.isspace() for character in topic):
            raise ValueError("ntfy topic is invalid")
        if not 0 < timeout_seconds <= 10:
            raise ValueError("timeout_seconds must be between 0 and 10")
        self._topic = topic
        self._token = token
        self._dashboard_link = dashboard_link
        self._opener = opener
        self._sleep = sleep
        self._timeout_seconds = timeout_seconds

    def notify(
        self,
        transition: EnvironmentTransition,
        reading: EnvironmentReading,
    ) -> NotificationResult:
        if transition.kind == "reasons_changed":
            return NotificationResult(
                delivered=False,
                code="not_notifiable",
                attempts=0,
            )
        if any(reason not in _ALLOWED_REASON_CODES for reason in transition.incident.reasons):
            return NotificationResult(
                delivered=False,
                code="payload_rejected",
                attempts=0,
            )
        try:
            click = self._dashboard_link.incident_url(
                transition.incident.incident_id
            )
        except ValueError:
            return NotificationResult(
                delivered=False,
                code="payload_rejected",
                attempts=0,
            )
        payload = self._payload(transition, reading, click)
        request = Request(
            self._base_url,
            data=json.dumps(
                payload,
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
            except Exception:
                status = 0
            if 200 <= status < 300:
                return NotificationResult(delivered=True, code="ok", attempts=attempt)
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
        transition: EnvironmentTransition,
        reading: EnvironmentReading,
        click: str,
    ) -> dict[str, object]:
        incident = transition.incident
        duration_seconds = max(
            0,
            round((transition.occurred_at - incident.opened_at).total_seconds()),
        )
        if reading.state is ReadingState.AVAILABLE:
            values = (
                f"{reading.temperature_c:.1f}°C, "
                f"{reading.humidity_rh:.1f}%RH"
            )
        else:
            values = "读数不可用"
        reasons = ",".join(incident.reasons)
        message = (
            f"事件={incident.kind}; 状态={transition.kind}; "
            f"级别={incident.severity}; 数值={values}; "
            f"采集时间={reading.captured_at.isoformat()}; "
            f"持续秒数={duration_seconds}; 原因={reasons}"
        )
        priority = "max" if incident.severity == "critical" else "high"
        return {
            "topic": self._topic,
            "title": "Baby Monitor Local 环境提醒",
            "message": message,
            "priority": priority,
            "tags": ["thermometer", incident.kind],
            "click": click,
        }
