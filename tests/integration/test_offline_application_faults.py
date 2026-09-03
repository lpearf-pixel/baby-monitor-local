from __future__ import annotations

from pathlib import Path


EXPECTED = (
    ("FAULT-VISUAL-COMPONENT-01", "visual_component_failed"),
    ("FAULT-SEMANTIC-INVALID-01", "semantic_review_invalid"),
    ("FAULT-SEMANTIC-CONFLICT-01", "semantic_conflict_closed"),
    ("FAULT-DUPLICATE-REVIEW-01", "duplicate_review_rejected"),
    ("FAULT-NONMONOTONIC-REVIEW-01", "nonmonotonic_review_rejected"),
    ("FAULT-VOICE-NOMATCH-01", "voice_no_match"),
    ("FAULT-REPLY-TIMEOUT-01", "reply_timeout"),
    ("FAULT-REPLY-FAILURE-01", "reply_failed"),
    ("FAULT-EVENT-STORE-01", "event_store_failed"),
    ("FAULT-PROJECTION-01", "projection_failed"),
)


def test_fixed_fault_pack_closes_all_cases_in_order_and_continues(tmp_path: Path) -> None:
    from services.offline_application_rehearsal import (
        OfflineApplicationRehearsalRunner,
        run_fault_pack,
    )

    number = iter(range(1, 20))
    results = run_fault_pack(
        lambda: OfflineApplicationRehearsalRunner(tmp_path / f"runner-{next(number)}")
    )

    assert tuple((item.fault_id, item.reason) for item in results) == EXPECTED
    assert all(item.outcome == "CLOSED" for item in results)
    assert all(item.cleanup_count == 0 for item in results)
    assert len(results) == 10


def test_fault_results_never_retain_exception_prose(tmp_path: Path) -> None:
    from services.offline_application_rehearsal import run_fault_pack

    results = run_fault_pack(lambda: (_ for _ in ()).throw(RuntimeError("secret prose")))
    payload = "".join(item.model_dump_json() for item in results)
    assert "secret" not in payload
    assert len(results) == 10
    assert all(item.outcome == "UNEXPECTED" for item in results)


def test_unexpected_fault_does_not_suppress_later_siblings(tmp_path: Path) -> None:
    from services.offline_application_rehearsal import (
        OfflineApplicationRehearsalRunner,
        run_fault_pack,
    )

    calls = 0

    def factory() -> OfflineApplicationRehearsalRunner:
        nonlocal calls
        calls += 1
        if calls == 2:
            raise RuntimeError("unexpected private prose")
        return OfflineApplicationRehearsalRunner(tmp_path / f"runner-{calls}")

    results = run_fault_pack(factory)
    assert len(results) == 10
    assert results[1].outcome == "UNEXPECTED"
    assert results[-1].outcome == "CLOSED"
    assert "private" not in "".join(item.model_dump_json() for item in results)
