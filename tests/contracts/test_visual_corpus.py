from __future__ import annotations

import hashlib
import importlib
import json
from copy import deepcopy
from pathlib import Path

import pytest
from pydantic import ValidationError


def contracts():
    return importlib.import_module("packages.contracts.visual_corpus")


def manifest_module():
    return importlib.import_module("services.vision.corpus_manifest")


def source(source_id: str = "public-source") -> dict[str, object]:
    return {
        "source_id": source_id,
        "name": "Reviewed public infant video",
        "source_url": "https://upload.wikimedia.org/example.webm",
        "project_or_paper": "Wikimedia Commons",
        "license": "public-domain",
        "download_method": "DIRECT_HTTPS",
        "research_use_allowed": True,
        "commercial_use": "ALLOWED",
        "redistribution_allowed": True,
        "github_allowed": False,
        "privacy_notes": "publicly released educational media",
        "local_only": True,
        "expected_sha256": "1" * 64,
        "expected_bytes": 1024,
    }


def labels(
    *,
    framing: str = "medium",
    wide_content_role: str = "none",
) -> dict[str, object]:
    return {
        "framing": framing,
        "subject_scale": "medium",
        "subject_frame_area_ratio": 0.25,
        "camera_angle": "high_oblique",
        "environment": "crib",
        "lighting": "day",
        "baby_visibility": "full",
        "motion": "mild",
        "adult_visibility": "absent",
        "object_state": "mixed",
        "wide_content_role": wide_content_role,
    }


def clip(
    clip_id: str,
    *,
    scenario_id: str,
    framing: str = "medium",
    source_type: str = "PUBLIC_DATASET",
    recipe_kind: str = "SOURCE_SEGMENT",
    parent_clip_id: str | None = None,
    wide_content_role: str = "none",
) -> dict[str, object]:
    value: dict[str, object] = {
        "clip_id": clip_id,
        "source_id": "public-source",
        "source_type": source_type,
        "scenario_ids": [scenario_id],
        "start_ms": 0,
        "end_ms": 10_000,
        "recipe": {"kind": recipe_kind},
        "labels": labels(
            framing=framing,
            wide_content_role=wide_content_role,
        ),
        "temporal_labels": [
            {
                "start_ms": 1_000,
                "end_ms": 2_000,
                "labels": labels(
                    framing=framing,
                    wide_content_role=wide_content_role,
                ),
            }
        ],
        "label_provenance": "frame_review",
        "label_confidence": 0.9,
        "review_state": "reviewed",
    }
    if parent_clip_id is not None:
        value["parent_clip_id"] = parent_clip_id
    return value


def first_stage_payload() -> dict[str, object]:
    clips = [
        clip("DAY-01", scenario_id="DAY-01"),
        clip("DAY-02", scenario_id="DAY-02"),
        clip("DAY-03", scenario_id="DAY-03"),
        clip(
            "WIDE-01",
            scenario_id="WIDE-01",
            framing="room_wide",
            wide_content_role="infant_small",
        ),
        clip(
            "WIDE-02",
            scenario_id="WIDE-02",
            framing="crib_wide",
            wide_content_role="empty_or_object_only",
        ),
        clip(
            "WIDE-03",
            scenario_id="WIDE-03",
            framing="room_wide",
            wide_content_role="adult_present_or_entering",
        ),
        clip("NIGHT-01", scenario_id="NIGHT-01"),
        clip("NIGHT-02", scenario_id="NIGHT-02"),
        clip("NIGHT-03", scenario_id="NIGHT-03"),
        clip("OCC-01", scenario_id="OCC-01"),
        clip("OCC-02", scenario_id="OCC-02"),
        clip("OCC-03", scenario_id="OCC-03"),
        clip("NEG-01", scenario_id="NEG-01"),
        clip("NEG-02", scenario_id="NEG-02"),
        clip("NEG-03", scenario_id="NEG-03"),
    ]
    return {
        "schema_version": 1,
        "corpus_id": "visual-first-stage-v1",
        "readiness": "READY",
        "sources": [source()],
        "profiles": [
            {
                "profile_id": "analysis_realtime",
                "width": 960,
                "height": 540,
                "fps": 5,
                "codec": "mjpeg",
            }
        ],
        "clips": clips,
    }


def test_manifest_module_is_required() -> None:
    module = contracts()
    assert module.VisualCorpusManifest is not None


def test_valid_first_stage_manifest_has_stable_canonical_digest() -> None:
    module = contracts()
    loader = manifest_module()
    parsed = module.VisualCorpusManifest.model_validate(first_stage_payload())

    loader.validate_first_stage(parsed)
    first = loader.canonical_manifest_digest(parsed)
    second = loader.canonical_manifest_digest(
        module.VisualCorpusManifest.model_validate(
            json.loads(json.dumps(first_stage_payload(), sort_keys=True))
        )
    )

    assert first == second
    assert len(first) == 64
    assert first == hashlib.sha256(loader.canonical_manifest_bytes(parsed)).hexdigest()


def test_loader_rejects_invalid_json_without_exposing_path(tmp_path: Path) -> None:
    loader = manifest_module()
    manifest = tmp_path / "private-name.json"
    manifest.write_text("{", encoding="utf-8")

    with pytest.raises(
        loader.VisualCorpusManifestError,
        match="^visual_corpus_manifest_invalid$",
    ) as failure:
        loader.load_manifest(manifest)

    assert "private-name" not in str(failure.value)


def test_contract_rejects_extra_fields() -> None:
    module = contracts()
    payload = first_stage_payload()
    payload["private_note"] = "must not be accepted"

    with pytest.raises(ValidationError):
        module.VisualCorpusManifest.model_validate(payload)


def test_contract_rejects_duplicate_source_and_clip_ids() -> None:
    module = contracts()
    duplicate_source = first_stage_payload()
    duplicate_source["sources"] = [source(), source()]
    duplicate_clip = first_stage_payload()
    duplicate_clip["clips"] = [
        *duplicate_clip["clips"],  # type: ignore[list-item]
        deepcopy(duplicate_clip["clips"][0]),  # type: ignore[index]
    ]

    with pytest.raises(ValidationError, match="source_id"):
        module.VisualCorpusManifest.model_validate(duplicate_source)
    with pytest.raises(ValidationError, match="clip_id"):
        module.VisualCorpusManifest.model_validate(duplicate_clip)


def test_unclear_redistribution_cannot_be_github_allowed() -> None:
    module = contracts()
    payload = first_stage_payload()
    payload_source = payload["sources"][0]  # type: ignore[index]
    payload_source["redistribution_allowed"] = False
    payload_source["github_allowed"] = True

    with pytest.raises(ValidationError, match="github_allowed"):
        module.VisualCorpusManifest.model_validate(payload)


def test_temporal_span_must_be_inside_clip() -> None:
    module = contracts()
    payload = first_stage_payload()
    first_clip = payload["clips"][0]  # type: ignore[index]
    first_clip["temporal_labels"][0]["end_ms"] = 10_001

    with pytest.raises(ValidationError, match="temporal"):
        module.VisualCorpusManifest.model_validate(payload)


def test_derived_recipe_requires_parent_and_non_derived_rejects_parent() -> None:
    module = contracts()
    missing_parent = first_stage_payload()
    missing_parent["clips"][0]["source_type"] = "SYNTHETIC"  # type: ignore[index]
    missing_parent["clips"][0]["recipe"] = {"kind": "SIMULATED_IR"}  # type: ignore[index]
    unexpected_parent = first_stage_payload()
    unexpected_parent["clips"][0]["parent_clip_id"] = "DAY-02"  # type: ignore[index]

    with pytest.raises(ValidationError, match="parent_clip_id"):
        module.VisualCorpusManifest.model_validate(missing_parent)
    with pytest.raises(ValidationError, match="parent_clip_id"):
        module.VisualCorpusManifest.model_validate(unexpected_parent)


def test_first_stage_requires_ten_to_twenty_clips_and_all_scenario_families() -> None:
    module = contracts()
    loader = manifest_module()
    too_small = first_stage_payload()
    too_small["clips"] = too_small["clips"][:9]  # type: ignore[index]
    parsed = module.VisualCorpusManifest.model_validate(too_small)

    with pytest.raises(ValueError, match="visual_corpus_clip_count_invalid"):
        loader.validate_first_stage(parsed)

    missing_negative = first_stage_payload()
    missing_negative["clips"] = [
        item
        for item in missing_negative["clips"]  # type: ignore[union-attr]
        if not item["clip_id"].startswith("NEG-")
    ]
    parsed_missing = module.VisualCorpusManifest.model_validate(missing_negative)
    with pytest.raises(ValueError, match="visual_corpus_scenario_missing"):
        loader.validate_first_stage(parsed_missing)


def test_first_stage_requires_three_real_wide_roles() -> None:
    module = contracts()
    loader = manifest_module()
    payload = first_stage_payload()
    payload["clips"][3]["labels"]["wide_content_role"] = "none"  # type: ignore[index]
    parsed = module.VisualCorpusManifest.model_validate(payload)

    with pytest.raises(ValueError, match="visual_corpus_real_wide_required"):
        loader.validate_first_stage(parsed)


def test_synthetic_scale_never_satisfies_real_wide_gate() -> None:
    module = contracts()
    loader = manifest_module()
    payload = first_stage_payload()
    for index, parent in zip((3, 4, 5), ("DAY-01", "DAY-02", "DAY-03"), strict=True):
        payload["clips"][index]["source_type"] = "SYNTHETIC"  # type: ignore[index]
        payload["clips"][index]["parent_clip_id"] = parent  # type: ignore[index]
        payload["clips"][index]["recipe"] = {"kind": "SYNTHETIC_SCALE"}  # type: ignore[index]
    parsed = module.VisualCorpusManifest.model_validate(payload)

    with pytest.raises(ValueError, match="visual_corpus_real_wide_required"):
        loader.validate_first_stage(parsed)


def test_replay_contract_does_not_expose_frame_observations() -> None:
    module = contracts()
    result = module.ReplayResult(
        clip_id="DAY-01",
        status="PASS",
        reason="ok",
        frames_total=10,
        frames_processed=8,
        frames_skipped=2,
        decode_errors=0,
        worker_errors=0,
        model_state="available",
        observation_counts={"scene_quality.usable": 8},
        candidate_counts={},
        processing_p50_ms=10.0,
        processing_p95_ms=12.0,
        processing_max_ms=13.0,
        pipeline_p50_ms=11.0,
        pipeline_p95_ms=13.0,
        pipeline_max_ms=14.0,
        dropped_frames=0,
        queue_backlog_max=0,
        frame_observations_persisted=False,
    )

    assert result.frames_processed + result.frames_skipped == result.frames_total
    assert "frame_observations" not in result.model_dump()


def test_guardian_replay_contract_contains_aggregates_only() -> None:
    module = contracts()
    aggregate = module.GuardianReplayAggregate(
        status="PASS",
        reason="ok",
        semantic_profile="synthetic_test",
        transition_counts={"alert_opened.face_not_visible": 1},
        event_counts={"face_not_visible.open": 1},
        dashboard_event_count=1,
        dashboard_open_event_count=1,
        production_state_touched=False,
        notification_dispatch_attempted=False,
        evidence_persisted=False,
    )

    payload = aggregate.model_dump(mode="json")
    assert payload["event_counts"] == {"face_not_visible.open": 1}
    assert not any(
        key in str(payload).lower()
        for key in ("review", "frame", "path", "notification_payload")
    )
