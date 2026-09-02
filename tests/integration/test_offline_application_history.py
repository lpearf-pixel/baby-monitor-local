from __future__ import annotations

from pathlib import Path

import pytest

from packages.contracts.offline_application_rehearsal import (
    ApplicationScenarioResultV1,
    load_historical_ledger,
)


HISTORY = Path(__file__).parents[1] / "fixtures/offline_application_rehearsal/history.v1.json"


def test_historical_summary_is_read_only_and_separate_from_fresh_results() -> None:
    from services.offline_application_history import summarize_historical_evidence

    items = load_historical_ledger(HISTORY)
    summary = summarize_historical_evidence(items)

    assert summary.items == items
    assert dict(summary.counts) == {"PARTIAL": 2, "FAIL": 1}
    assert all(item.fresh_for_this_run is False for item in summary.items)
    with pytest.raises(TypeError):
        summary.counts["PASS"] = 1  # type: ignore[index]


def test_historical_items_cannot_be_fresh_scenario_results() -> None:
    item = load_historical_ledger(HISTORY)[0]

    with pytest.raises(Exception):
        ApplicationScenarioResultV1.model_validate(item.model_dump(mode="json"))
    assert "transcript" not in type(item).model_fields
    assert "path" not in type(item).model_fields
    assert "reason" not in type(item).model_fields
