"""M7 facade that keeps language context separate from the M6 care session."""

from __future__ import annotations

from datetime import datetime

from services.voice.m6_feeding import M6FeedingCoordinator, M6Result, M6SessionGateway
from services.voice.m7_tools import ValidatedToolCall


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


class M6ToolExecutor:
    """Translate validated M7 feeding tools to the existing M6 coordinator."""

    def __init__(self, bridge: M7SessionBridge, *, clock) -> None:
        self._bridge = bridge
        self._clock = clock
        self._sequence = 0

    def execute(self, call: ValidatedToolCall) -> str:
        self._sequence += 1
        request_id = f"m7-tool-{self._sequence}"
        args = call.arguments
        text = {
            "start_feeding": "开始喂奶",
            "end_feeding": "结束",
            "request_feeding_confirmation": "结束",
            "confirm_feeding": "确认保存",
            "cancel_feeding": "取消",
            "get_active_feeding": "查询记录",
            "get_recent_feedings": "查询记录",
            "get_feeding_summary": "查询记录",
        }.get(call.name)
        if call.name == "add_feeding_component":
            if args["kind"] == "direct_breastfeeding":
                text = f"亲喂{args['duration_minutes']}分钟"
            else:
                liquid = "母乳" if args["liquid_type"] == "expressed_breast_milk" else "配方奶"
                text = f"{liquid}{args['amount_ml']}毫升"
        elif call.name == "correct_feeding_component":
            liquid = "母乳" if args["target"] == "expressed_breast_milk" else "配方奶"
            text = f"改成{liquid}{args['amount_ml']}毫升"
        if text is None:
            return "rejected"
        return self._bridge.process(text, self._clock(), request_id=request_id).code


__all__ = ["M6ToolExecutor", "M7SessionBridge"]
