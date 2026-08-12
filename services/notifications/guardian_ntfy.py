from __future__ import annotations

import json
import re
import time
from collections.abc import Callable
from urllib.error import HTTPError
from urllib.request import Request

from packages.contracts.vision import VisualRiskKind
from services.notifications.ntfy import (
    NotificationResult,
    NtfyOpener,
    _default_opener,
    _validate_https_dns_url,
)
from services.storage.visual_risk import (
    StoredVisualRiskEvent,
    StoredVisualRiskNotification,
)


_SAFE_ID = re.compile(r"\A[A-Za-z0-9][A-Za-z0-9._-]{0,127}\Z")
_RISK_LABELS = {
    VisualRiskKind.FACE_NOT_VISIBLE: "口鼻或脸部疑似遮挡",
    VisualRiskKind.PRONE_CANDIDATE: "疑似趴睡",
    VisualRiskKind.OUTSIDE_CANDIDATE: "疑似离床",
}
_STAGE_LABELS = {
    "risk_opened": "风险已确认",
    "risk_recovered": "风险已恢复",
    "adult_intervention": "检测到成人介入",
}
_EVIDENCE_LABELS = {
    "collecting": "采集中",
    "ready": "已就绪",
    "failed": "生成失败",
    "interrupted": "采集中断",
    "unavailable": "暂无",
}


class NtfyGuardianNotifier:
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
        if not topic or len(topic) > 256 or any(
            character.isspace() for character in topic
        ):
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
        notification: StoredVisualRiskNotification,
        event: StoredVisualRiskEvent,
        evidence_state: str,
    ) -> NotificationResult:
        if not self._is_safe(notification, event, evidence_state):
            return NotificationResult(
                delivered=False,
                code="payload_rejected",
                attempts=0,
            )
        request = Request(
            self._base_url,
            data=json.dumps(
                self._payload(notification, event, evidence_state),
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

    @staticmethod
    def _is_safe(
        notification: StoredVisualRiskNotification,
        event: StoredVisualRiskEvent,
        evidence_state: str,
    ) -> bool:
        if notification.state != "pending":
            return False
        if notification.event_id != event.event_id:
            return False
        if _SAFE_ID.fullmatch(event.event_id) is None:
            return False
        if notification.stage not in _STAGE_LABELS:
            return False
        if evidence_state not in _EVIDENCE_LABELS:
            return False
        if notification.stage == "risk_recovered" and event.state != "recovered":
            return False
        return event.risk_kind in _RISK_LABELS

    def _payload(
        self,
        notification: StoredVisualRiskNotification,
        event: StoredVisualRiskEvent,
        evidence_state: str,
    ) -> dict[str, object]:
        stage = notification.stage
        occurred_at = (
            event.recovered_at
            if stage == "risk_recovered" and event.recovered_at is not None
            else notification.queued_at
        )
        message = (
            f"事件={event.event_id}; 风险={_RISK_LABELS[event.risk_kind]}; "
            f"状态={_STAGE_LABELS[stage]}; 级别=高; "
            f"时间={occurred_at.isoformat()}; "
            f"证据={_EVIDENCE_LABELS[evidence_state]}"
        )
        priority = {
            "risk_opened": 5,
            "risk_recovered": 3,
            "adult_intervention": 4,
        }[stage]
        tags = {
            "risk_opened": ["warning", "baby"],
            "risk_recovered": ["white_check_mark", "baby"],
            "adult_intervention": ["adult", "baby"],
        }[stage]
        return {
            "topic": self._topic,
            "title": "Baby Monitor Local 守护提醒",
            "message": message,
            "priority": priority,
            "tags": tags,
        }
