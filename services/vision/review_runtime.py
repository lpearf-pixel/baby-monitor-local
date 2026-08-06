from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum

from packages.contracts.vision import RiskTransition
from services.vision.model_health import (
    ModelHealthTransition,
    VisualModelHealthMonitor,
)
from services.vision.review_scheduler import (
    ReviewCompletion,
    ReviewCompletionCode,
)
from services.vision.risk_state import VisualRiskStateMachine


class ReviewRuntimeCode(StrEnum):
    OK = "ok"
    REVIEW_FAILED = "review_failed"
    CALLBACK_FAILED = "callback_failed"
    INTERNAL_FAILED = "internal_failed"


@dataclass(frozen=True)
class ReviewRuntimeUpdate:
    code: ReviewRuntimeCode
    risk_transitions: tuple[RiskTransition, ...] = ()
    model_health_transition: ModelHealthTransition | None = None


class VisualReviewRuntime:
    def __init__(
        self,
        *,
        risk_machine: VisualRiskStateMachine,
        model_health: VisualModelHealthMonitor | None = None,
        now: Callable[[], datetime] | None = None,
        monotonic: Callable[[], float] = time.monotonic,
        on_model_health: Callable[[ModelHealthTransition], None] | None = None,
        on_risk_transition: Callable[[RiskTransition], None] | None = None,
    ) -> None:
        self._risk_machine = risk_machine
        self._model_health = model_health or VisualModelHealthMonitor()
        self._now = now or (lambda: datetime.now(UTC))
        self._monotonic = monotonic
        self._on_model_health = on_model_health or (lambda _transition: None)
        self._on_risk_transition = on_risk_transition or (lambda _transition: None)

    def handle(self, completion: ReviewCompletion) -> ReviewRuntimeUpdate:
        monotonic_now = self._monotonic()
        if (
            completion.code is not ReviewCompletionCode.OK
            or completion.review is None
        ):
            health_transition = self._model_health.failed(
                monotonic_now=monotonic_now
            )
            return self._emit(
                ReviewRuntimeUpdate(
                    code=ReviewRuntimeCode.REVIEW_FAILED,
                    model_health_transition=health_transition,
                )
            )

        health_transition = self._model_health.succeeded(
            monotonic_now=monotonic_now
        )
        try:
            risk_transitions = self._risk_machine.evaluate(
                completion.review,
                self._now(),
            )
        except Exception:
            return self._emit(
                ReviewRuntimeUpdate(
                    code=ReviewRuntimeCode.INTERNAL_FAILED,
                    model_health_transition=health_transition,
                )
            )
        return self._emit(
            ReviewRuntimeUpdate(
                code=ReviewRuntimeCode.OK,
                risk_transitions=risk_transitions,
                model_health_transition=health_transition,
            )
        )

    def _emit(self, update: ReviewRuntimeUpdate) -> ReviewRuntimeUpdate:
        try:
            if update.model_health_transition is not None:
                self._on_model_health(update.model_health_transition)
            for transition in update.risk_transitions:
                self._on_risk_transition(transition)
        except Exception:
            return ReviewRuntimeUpdate(
                code=ReviewRuntimeCode.CALLBACK_FAILED,
                risk_transitions=update.risk_transitions,
                model_health_transition=update.model_health_transition,
            )
        return update
