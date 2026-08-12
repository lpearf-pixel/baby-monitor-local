from __future__ import annotations

from datetime import UTC, datetime, timedelta

from packages.contracts.vision import RiskTransitionKind, VisualReview
from services.vision.review_scheduler import (
    ReviewCompletion,
    ReviewCompletionCode,
)
from services.vision.risk_state import VisualRiskStateMachine


NOW = datetime(2026, 8, 6, 12, 0, tzinfo=UTC)


def review(*, hidden: bool = False) -> VisualReview:
    return VisualReview.model_validate(
        {
            "schema_version": 1,
            "baby_visibility": "visible",
            "face_visibility": "not_visible" if hidden else "clear",
            "posture": "supine",
            "bed_state": "inside",
            "adult_presence": "absent",
            "image_quality": "usable",
            "risk": "high" if hidden else "none",
            "reason_codes": ["face_not_visible"] if hidden else [],
            "confidence": 0.9,
        }
    )


def runtime_module():
    from services.vision import review_runtime

    return review_runtime


def test_successful_reviews_feed_the_real_risk_machine() -> None:
    module = runtime_module()
    times = iter([NOW, NOW + timedelta(seconds=10)])
    ticks = iter([0.0, 10.0])
    runtime = module.VisualReviewRuntime(
        risk_machine=VisualRiskStateMachine(),
        now=lambda: next(times),
        monotonic=lambda: next(ticks),
    )

    first = runtime.handle(
        ReviewCompletion(code=ReviewCompletionCode.OK, review=review(hidden=True))
    )
    second = runtime.handle(
        ReviewCompletion(code=ReviewCompletionCode.OK, review=review(hidden=True))
    )

    assert [item.transition_kind for item in first.risk_transitions] == [
        RiskTransitionKind.WATCH_STARTED
    ]
    assert [item.transition_kind for item in second.risk_transitions] == [
        RiskTransitionKind.ALERT_OPENED
    ]
    assert first.model_health_transition is None
    assert second.code is module.ReviewRuntimeCode.OK


def test_failed_completion_never_advances_visual_risk_evidence() -> None:
    module = runtime_module()
    times = iter([NOW, NOW + timedelta(seconds=10)])
    ticks = iter([0.0, 5.0, 10.0])
    runtime = module.VisualReviewRuntime(
        risk_machine=VisualRiskStateMachine(),
        now=lambda: next(times),
        monotonic=lambda: next(ticks),
    )

    first = runtime.handle(
        ReviewCompletion(code=ReviewCompletionCode.OK, review=review(hidden=True))
    )
    failed = runtime.handle(ReviewCompletion(code=ReviewCompletionCode.REVIEW_FAILED))
    second = runtime.handle(
        ReviewCompletion(code=ReviewCompletionCode.OK, review=review(hidden=True))
    )

    assert first.risk_transitions[0].transition_kind is RiskTransitionKind.WATCH_STARTED
    assert failed.risk_transitions == ()
    assert failed.code is module.ReviewRuntimeCode.REVIEW_FAILED
    assert second.risk_transitions[0].transition_kind is RiskTransitionKind.ALERT_OPENED


def test_model_degraded_and_recovered_callbacks_fire_once() -> None:
    module = runtime_module()
    transitions: list[object] = []
    ticks = iter([0.0, 10.0, 20.0, 30.0, 40.0, 50.0])
    times = iter([NOW, NOW + timedelta(seconds=10)])
    runtime = module.VisualReviewRuntime(
        risk_machine=VisualRiskStateMachine(),
        monotonic=lambda: next(ticks),
        now=lambda: next(times),
        on_model_health=transitions.append,
    )

    for _ in range(4):
        runtime.handle(ReviewCompletion(code=ReviewCompletionCode.REVIEW_FAILED))
    runtime.handle(ReviewCompletion(code=ReviewCompletionCode.OK, review=review()))
    runtime.handle(ReviewCompletion(code=ReviewCompletionCode.OK, review=review()))

    assert [item.code.value for item in transitions] == [
        "model_degraded",
        "model_recovered",
    ]


def test_callback_failure_is_redacted_and_does_not_escape() -> None:
    module = runtime_module()
    ticks = iter([0.0, 10.0, 20.0])

    def broken_callback(_transition: object) -> None:
        raise RuntimeError("credential at /private/family/callback")

    runtime = module.VisualReviewRuntime(
        risk_machine=VisualRiskStateMachine(),
        monotonic=lambda: next(ticks),
        on_model_health=broken_callback,
    )

    runtime.handle(ReviewCompletion(code=ReviewCompletionCode.REVIEW_FAILED))
    runtime.handle(ReviewCompletion(code=ReviewCompletionCode.REVIEW_FAILED))
    update = runtime.handle(ReviewCompletion(code=ReviewCompletionCode.REVIEW_FAILED))

    assert update.code is module.ReviewRuntimeCode.CALLBACK_FAILED
    assert "/private" not in repr(update)
