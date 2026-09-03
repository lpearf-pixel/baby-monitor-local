from __future__ import annotations

import copy
from datetime import datetime, timezone
from pathlib import Path

import pytest
from pydantic import ValidationError


FIXTURE_ROOT = (
    Path(__file__).parents[1] / "fixtures/offline_application_rehearsal"
)


def contracts():
    from packages.contracts import offline_application_rehearsal

    return offline_application_rehearsal


def test_exact_tracked_contract_fixtures_load() -> None:
    module = contracts()
    suite = module.load_rehearsal_suite(FIXTURE_ROOT / "scenarios.v1.json")
    history = module.load_historical_ledger(FIXTURE_ROOT / "history.v1.json")

    assert len(suite.scenarios) == 12
    assert [sum(item.lane == lane for item in suite.scenarios) for lane in (
        "application_oracle", "voice_application", "joined_application"
    )] == [6, 3, 3]
    assert len(history) == 3
    assert all(item.fresh_for_this_run is False for item in history)


def suite_payload() -> dict[str, object]:
    module = contracts()
    return module.load_rehearsal_suite(
        FIXTURE_ROOT / "scenarios.v1.json"
    ).model_dump(mode="json")


def run_payload() -> dict[str, object]:
    module = contracts()
    suite = module.load_rehearsal_suite(FIXTURE_ROOT / "scenarios.v1.json")
    history = module.load_historical_ledger(FIXTURE_ROOT / "history.v1.json")
    return {
        "schema_version": 1,
        "suite_id": "offline-application-rehearsal-v1",
        "run_id": "run-1111111111111111",
        "generated_at": "2026-09-02T00:00:00Z",
        "status": "PASS",
        "reason": "ok",
        "evidence_class": "SOFTWARE_REHEARSAL",
        "historical": [item.model_dump(mode="json") for item in history],
        "results": [
            {
                "scenario_id": item.scenario_id,
                "lane": item.lane,
                "status": "PASS",
                "reason": "ok",
                "counts": item.expected_counts,
                "event_ids": [f"event-{index:04d}"],
                "reply_ids": [f"reply-{index:04d}"],
            }
            for index, item in enumerate(suite.scenarios, 1)
        ],
        "faults": [
            {
                "fault_id": f"FAULT-{index:02d}",
                "outcome": "CLOSED",
                "reason": "closed",
                "cleanup_count": 0,
            }
            for index in range(1, 11)
        ],
        "repetition": {
            "status": "PASS",
            "reason": "ok",
            "iterations": [
                {
                    "iteration": index,
                    "status": "PASS",
                    "stable_digest": "a" * 64,
                    "counts": {"functional_pass": 12},
                }
                for index in range(1, 11)
            ],
            "cross_risk_instances": 50,
            "cross_risk_pass": 50,
        },
        "imported_status": "PASS",
        "imported_scenarios": 8,
        "imported_lanes": 13,
        "imported_visual_clips": 5,
        "imported_frames": 330,
        "imported_skipped_frames": 0,
        "imported_dropped_frames": 0,
        "imported_decode_errors": 0,
        "imported_worker_errors": 0,
        "imported_visual_oracle_relationship": "INDEPENDENT",
        "side_effects": {},
        "counts": {
            "no_baby_face_watch": 0,
            "no_baby_face_alert": 0,
            "no_baby_face_event": 0,
            "no_baby_face_notification": 0,
            "residual_reply_sessions": 0,
        },
    }


@pytest.mark.parametrize("mutation", ["unknown", "missing", "changed", "lane"])
def test_suite_rejects_non_exact_pack(mutation: str) -> None:
    module = contracts()
    payload = suite_payload()
    if mutation == "unknown":
        payload["private_path"] = "forbidden"
    elif mutation == "missing":
        payload["scenarios"].pop()  # type: ignore[union-attr]
    elif mutation == "changed":
        payload["scenarios"][0]["scenario_id"] = "APP-CHANGED-01"  # type: ignore[index]
    else:
        payload["scenarios"][0]["lane"] = "voice_application"  # type: ignore[index]
    with pytest.raises(ValidationError):
        module.RehearsalSuiteV1.model_validate(payload)


def test_scenario_rejects_duplicate_or_unordered_steps() -> None:
    module = contracts()
    duplicate = suite_payload()
    steps = duplicate["scenarios"][0]["steps"]  # type: ignore[index]
    steps.append(copy.deepcopy(steps[0]))
    unordered = suite_payload()
    unordered["scenarios"][1]["steps"][1]["offset_ms"] = 0  # type: ignore[index]
    with pytest.raises(ValidationError):
        module.RehearsalSuiteV1.model_validate(duplicate)
    with pytest.raises(ValidationError):
        module.RehearsalSuiteV1.model_validate(unordered)


@pytest.mark.parametrize("kind", ["zero", "two", "pair", "medication"])
def test_step_rejects_incoherent_inputs_and_action_identity(kind: str) -> None:
    module = contracts()
    payload: dict[str, object] = {
        "step_id": "invalid",
        "offset_ms": 0,
        "voice_fixture_id": "wake",
    }
    if kind == "zero":
        payload.pop("voice_fixture_id")
    elif kind == "two":
        payload["visual_review"] = suite_payload()["scenarios"][0]["steps"][0]["visual_review"]  # type: ignore[index]
    elif kind == "pair":
        payload["expected_action_code"] = "feeding_command"
    else:
        payload["expected_action_code"] = "medication_start_candidate"
        payload["expected_match_kind"] = "high_risk_candidate"
    with pytest.raises(ValidationError):
        module.ApplicationStepV1.model_validate(payload)


@pytest.mark.parametrize(
    ("field", "value"),
    [("source_commit", "ABC"), ("observed_at", "2026-09-02T00:00:00"),
     ("fresh_for_this_run", True)],
)
def test_history_rejects_untrusted_identity_or_freshness(field: str, value: object) -> None:
    module = contracts()
    payload = module.load_historical_ledger(
        FIXTURE_ROOT / "history.v1.json"
    )[0].model_dump(mode="json")
    payload[field] = value
    with pytest.raises(ValidationError):
        module.HistoricalEvidenceV1.model_validate(payload)


def test_counts_and_side_effects_fail_closed() -> None:
    module = contracts()
    negative = run_payload()
    negative["counts"]["bad"] = -1  # type: ignore[index]
    side_effect = run_payload()
    side_effect["side_effects"]["camera_access"] = True  # type: ignore[index]
    missing_zero = run_payload()
    missing_zero["counts"].pop("no_baby_face_watch")  # type: ignore[union-attr]
    for payload in (negative, side_effect, missing_zero):
        with pytest.raises(ValidationError):
            module.OfflineApplicationRunV1.model_validate(payload)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("event_ids", ["/Users/private/family.jpg"]),
        ("reply_ids", ["free prose and token=secret"]),
        ("event_ids", ["event-good", "event-good"]),
    ],
)
def test_result_ids_are_closed_bounded_and_unique(field: str, value: list[str]) -> None:
    module = contracts()
    payload = run_payload()["results"][0]  # type: ignore[index]
    payload[field] = value
    with pytest.raises(ValidationError):
        module.ApplicationScenarioResultV1.model_validate(payload)


def test_every_voice_step_declares_expected_reason_and_phase() -> None:
    suite = contracts().load_rehearsal_suite(FIXTURE_ROOT / "scenarios.v1.json")
    voice_steps = [
        step for scenario in suite.scenarios for step in scenario.steps
        if step.voice_fixture_id is not None
    ]
    assert voice_steps
    assert all(step.expected_reason is not None for step in voice_steps)
    assert all(step.expected_phase is not None for step in voice_steps)


@pytest.mark.parametrize("mutation", ["phase", "reply"])
def test_voice_step_rejects_incoherent_expected_lifecycle(mutation: str) -> None:
    module = contracts()
    payload = suite_payload()["scenarios"][6]["steps"][0]  # type: ignore[index]
    if mutation == "phase":
        payload["expected_phase"] = "idle"
    else:
        payload["reply_behavior"] = "timeout"
    with pytest.raises(ValidationError):
        module.ApplicationStepV1.model_validate(payload)


def test_loaders_reject_oversize_input(tmp_path: Path) -> None:
    module = contracts()
    candidate = tmp_path / "oversize.json"
    candidate.write_bytes(b" " * (module.MAX_INPUT_BYTES + 1))
    with pytest.raises(ValueError, match="offline_application_manifest_invalid"):
        module.load_rehearsal_suite(candidate)


def test_canonical_bytes_and_digest_normalize_only_generated_identity() -> None:
    module = contracts()
    first = module.OfflineApplicationRunV1.model_validate(run_payload())
    changed = run_payload()
    changed["run_id"] = "run-2222222222222222"
    changed["generated_at"] = "2026-09-03T00:00:00Z"
    for index, result in enumerate(changed["results"], 1):  # type: ignore[union-attr]
        result["event_ids"] = [f"event-other-{index}"]
        result["reply_ids"] = [f"reply-other-{index}"]
    second = module.OfflineApplicationRunV1.model_validate(changed)
    assert module.stable_application_digest(first) == module.stable_application_digest(second)
    semantic = run_payload()
    semantic["reason"] = "different"
    assert module.stable_application_digest(
        module.OfflineApplicationRunV1.model_validate(semantic)
    ) != module.stable_application_digest(first)
    assert module.canonical_application_run_bytes(first).isascii()
