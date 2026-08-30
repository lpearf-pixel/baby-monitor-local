from __future__ import annotations

import copy
from pathlib import Path

import pytest
from pydantic import ValidationError


FIXTURE = (
    Path(__file__).parents[1]
    / "fixtures/offline_guardian_scenarios/scenarios.v1.json"
)


def contracts():
    from packages.contracts import offline_guardian_scenario

    return offline_guardian_scenario


def review(*, hidden: bool = False, adult: bool = False) -> dict[str, object]:
    return {
        "baby_visibility": "visible",
        "face_visibility": "not_visible" if hidden else "clear",
        "posture": "supine",
        "bed_state": "inside",
        "adult_presence": "present" if adult else "absent",
        "image_quality": "usable",
        "risk": "high" if hidden else "none",
        "reason_codes": (
            ["face_not_visible", "adult_intervention"]
            if hidden and adult
            else ["face_not_visible"]
            if hidden
            else []
        ),
        "confidence": 0.9,
    }


def scenario_payload() -> dict[str, object]:
    return {
        "schema_version": 1,
        "scenario_id": "FACE-OCCLUSION-01",
        "required_lanes": ["visual_observation", "guardian_deterministic"],
        "visual": {
            "clip_id": "OCC-02",
            "profile": "analysis_realtime",
            "expected_frames_processed": 50,
            "provenance": "GENERATED_VISUAL",
        },
        "guardian": {
            "provenance": "SYNTHETIC_SEMANTIC_ORACLE",
            "timeline": [
                {"observed_at": "2026-08-29T00:00:00Z", "review": review(hidden=True)},
                {"observed_at": "2026-08-29T00:00:10Z", "review": review(hidden=True)},
            ],
            "transition_counts": {
                "watch_started.face_not_visible": 1,
                "alert_opened.face_not_visible": 1,
            },
            "event_counts": {"face_not_visible.open": 1},
            "dashboard_event_count": 1,
            "dashboard_open_event_count": 1,
        },
        "voice": None,
        "visual_oracle_relationship": "INDEPENDENT",
    }


def suite_payload() -> dict[str, object]:
    return {
        "schema_version": 1,
        "suite_id": "offline-guardian-v1",
        "scenarios": [scenario_payload()],
    }


def lane_result() -> dict[str, object]:
    return {
        "lane": "guardian_deterministic",
        "status": "PASS",
        "reason": "ok",
        "counts": {"dashboard_event_count": 1},
        "metrics_ms": {},
    }


def run_payload() -> dict[str, object]:
    return {
        "schema_version": 1,
        "suite_id": "offline-guardian-v1",
        "status": "PASS",
        "reason": "ok",
        "results": [
            {
                "schema_version": 1,
                "scenario_id": "FACE-OCCLUSION-01",
                "status": "PASS",
                "reason": "ok",
                "lanes": [lane_result()],
            }
        ],
        "production_state_touched": False,
        "notification_dispatch_attempted": False,
        "evidence_persisted": False,
        "camera_opened": False,
        "raw_audio_persisted": False,
        "baby_care_called": False,
    }


def test_valid_scenario_and_run_are_canonical() -> None:
    module = contracts()
    suite = module.OfflineScenarioSuiteV1.model_validate(suite_payload())
    run = module.OfflineScenarioRunV1.model_validate(run_payload())

    assert module.OfflineScenarioSuiteV1.model_validate_json(
        module.canonical_offline_scenario_bytes(suite)
    ) == suite
    assert module.OfflineScenarioRunV1.model_validate_json(
        module.canonical_offline_run_bytes(run)
    ) == run


@pytest.mark.parametrize(
    ("key", "value"),
    [
        ("source_url", "https://example.invalid/video"),
        ("path", "fixture.mkv"),
        ("host", "localhost"),
        ("camera_uri", "camera-source"),
        ("transcript", "private words"),
    ],
)
def test_suite_rejects_locator_and_private_fields(key: str, value: str) -> None:
    module = contracts()
    payload = suite_payload()
    payload["scenarios"][0][key] = value  # type: ignore[index]

    with pytest.raises(ValidationError):
        module.OfflineScenarioSuiteV1.model_validate(payload)


def test_suite_rejects_duplicate_ids_and_unordered_timeline() -> None:
    module = contracts()
    duplicate = suite_payload()
    duplicate["scenarios"].append(copy.deepcopy(duplicate["scenarios"][0]))  # type: ignore[union-attr,index]
    unordered = suite_payload()
    timeline = unordered["scenarios"][0]["guardian"]["timeline"]  # type: ignore[index]
    timeline.reverse()

    with pytest.raises(ValidationError):
        module.OfflineScenarioSuiteV1.model_validate(duplicate)
    with pytest.raises(ValidationError):
        module.OfflineScenarioSuiteV1.model_validate(unordered)


@pytest.mark.parametrize(
    "mutation",
    [
        {"required_lanes": ["visual_observation", "visual_observation"]},
        {"visual": None},
        {"scenario_id": "private-room-name"},
    ],
)
def test_scenario_rejects_incoherent_or_unbounded_lanes(
    mutation: dict[str, object],
) -> None:
    module = contracts()
    payload = scenario_payload()
    payload.update(mutation)

    with pytest.raises(ValidationError):
        module.OfflineGuardianScenarioV1.model_validate(payload)


@pytest.mark.parametrize(
    "proof",
    [
        "production_state_touched",
        "notification_dispatch_attempted",
        "evidence_persisted",
        "camera_opened",
        "raw_audio_persisted",
        "baby_care_called",
    ],
)
def test_result_requires_all_isolation_proofs_false(proof: str) -> None:
    module = contracts()
    payload = run_payload()
    payload[proof] = True

    with pytest.raises(ValidationError):
        module.OfflineScenarioRunV1.model_validate(payload)


def test_run_rejects_duplicate_scenarios_and_invalid_count_keys() -> None:
    module = contracts()
    duplicate = run_payload()
    duplicate["results"].append(copy.deepcopy(duplicate["results"][0]))  # type: ignore[union-attr,index]
    invalid = run_payload()
    invalid["results"][0]["lanes"][0]["counts"] = {"Private Value": 1}  # type: ignore[index]

    with pytest.raises(ValidationError):
        module.OfflineScenarioRunV1.model_validate(duplicate)
    with pytest.raises(ValidationError):
        module.OfflineScenarioRunV1.model_validate(invalid)


def test_tracked_eight_scenario_fixture_loads_with_exact_identity() -> None:
    module = contracts()
    suite = module.load_offline_scenario_suite(FIXTURE)

    assert tuple(item.scenario_id for item in suite.scenarios) == (
        "SAFE-SLEEP-01",
        "FACE-OCCLUSION-01",
        "ADULT-INTERVENTION-01",
        "VOICE-FEEDING-01",
        "PRONE-CANDIDATE-01",
        "OUTSIDE-CANDIDATE-01",
        "VOICE-DIAPER-01",
        "VOICE-BURPING-01",
    )
    assert sum(len(item.required_lanes) for item in suite.scenarios) == 13
    assert [
        item.visual.expected_frames_processed
        for item in suite.scenarios
        if item.visual is not None
    ] == [65, 50, 50, 100, 65]


def test_visual_guardian_pair_requires_independent_relationship() -> None:
    module = contracts()
    payload = scenario_payload()
    payload["visual_oracle_relationship"] = None

    with pytest.raises(ValidationError):
        module.OfflineGuardianScenarioV1.model_validate(payload)


def test_voice_step_rejects_half_bound_action_identity() -> None:
    module = contracts()
    payload = {
        "step_id": "burping_start",
        "speech_expected": True,
        "from_replay": False,
        "expected_reason": "listen_only_acknowledged",
        "expected_response_code": "listen_only_received",
        "expected_action_code": "burping_start",
        "expected_match_kind": None,
    }

    with pytest.raises(ValidationError):
        module.VoiceScenarioStepV1.model_validate(payload)
