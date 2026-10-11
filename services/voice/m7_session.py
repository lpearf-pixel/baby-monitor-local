"""M7 facade that keeps language context separate from the M6 care session."""

from __future__ import annotations

from datetime import datetime

from services.voice.m6_feeding import M6FeedingCoordinator, M6Result, M6SessionGateway


class M7SessionBridge:
    """Delegate care state to M6; only the language turn window is local."""

    def __init__(self, gateway: M6SessionGateway, *, context_seconds: float = 8.0) -> None:
        self._coordinator = M6FeedingCoordinator(gateway, context_seconds=context_seconds)

    def process(self, text: str, observed_at: datetime, *, request_id: str) -> M6Result:
        return self._coordinator.process(text, observed_at, request_id=request_id)

    def resume(self, observed_at: datetime, *, request_id: str) -> M6Result:
        return self.process("继续喂奶", observed_at, request_id=request_id)

    def query(self, observed_at: datetime, *, request_id: str) -> M6Result:
        return self.process("查询记录", observed_at, request_id=request_id)

    def cancel(self, observed_at: datetime, *, request_id: str) -> M6Result:
        return self.process("取消", observed_at, request_id=request_id)


__all__ = ["M7SessionBridge"]
