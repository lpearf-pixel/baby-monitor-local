from __future__ import annotations

from pathlib import Path

import pytest

from packages.contracts.visual_corpus import ReplayResult
from services.vision.corpus_baseline import (
    BaselineError,
    build_result_set,
    compare_result_sets,
    load_result_set,
    promote_baseline,
    result_set_digest,
)
from services.vision.corpus_replay import PrivateReplayProjection


MANDATORY_CLIPS = (
    "DAY-01",
    "DAY-02",
    "DAY-03",
    "WIDE-01",
    "WIDE-02",
    "WIDE-03",
    "NIGHT-01",
    "NIGHT-02",
    "NIGHT-03",
    "OCC-01",
    "OCC-02",
    "OCC-03",
    "NEG-01",
    "NEG-02",
    "NEG-03",
)
PRIVATE_ASSET_ID = "plc-0123456789abcdef0123456789abcdef"


def replay_result(
    clip_id: str = "DAY-01",
    *,
    status: str = "PASS",
    scene_usable: int = 90,
    pipeline_p95_ms: float = 20.0,
    dropped_frames: int = 0,
    groups: tuple[str, ...] = (
        "framing:crib_wide",
        "scale:small",
        "lighting:day",
        "visibility:full",
    ),
) -> ReplayResult:
    reason = "ok" if status == "PASS" else "visual_corpus_model_unavailable"
    return ReplayResult(
        clip_id=clip_id,
        status=status,
        reason=reason,
        frames_total=100,
        frames_processed=100,
        frames_skipped=0,
        decode_errors=0,
        worker_errors=0,
        model_state="available" if status == "PASS" else "unavailable",
        observation_counts={"scene_quality.usable": scene_usable},
        candidate_counts={},
        processing_p50_ms=10.0,
        processing_p95_ms=15.0,
        processing_max_ms=18.0,
        pipeline_p50_ms=12.0,
        pipeline_p95_ms=pipeline_p95_ms,
        pipeline_max_ms=max(22.0, pipeline_p95_ms),
        dropped_frames=dropped_frames,
        queue_backlog_max=0,
        frame_observations_persisted=False,
        groups=groups,
    )


def result_set(
    *,
    manifest_digest: str = "a" * 64,
    recipe_digest: str = "b" * 64,
    profile: str = "analysis_realtime",
    model_artifacts: tuple[str, ...] = ("openvino:" + "c" * 64,),
    results: tuple[ReplayResult, ...] | None = None,
):
    return build_result_set(
        manifest_digest=manifest_digest,
        recipe_digest=recipe_digest,
        profile=profile,
        git_sha="d" * 40,
        model_artifacts=model_artifacts,
        results=results or (replay_result(),),
    )


def test_build_result_set_sorts_clips_and_rejects_duplicates() -> None:
    built = result_set(
        results=(replay_result("DAY-02"), replay_result("DAY-01"))
    )
    assert [item.clip_id for item in built.results] == ["DAY-01", "DAY-02"]

    with pytest.raises(BaselineError, match="visual_baseline_clip_identity_invalid"):
        result_set(results=(replay_result(), replay_result()))


def test_build_rejects_private_projection_with_stable_reason() -> None:
    private = PrivateReplayProjection(
        clip_id=PRIVATE_ASSET_ID,
        groups=("scenario:NEG-01", "scenario:WIDE-02"),
    )

    with pytest.raises(BaselineError, match="^private_baseline_operation_forbidden$"):
        build_result_set(
            manifest_digest="a" * 64,
            recipe_digest="b" * 64,
            profile="analysis_realtime",
            git_sha="d" * 40,
            model_artifacts=("openvino:" + "c" * 64,),
            results=(private,),  # type: ignore[arg-type]
        )


def test_compare_rejects_directly_constructed_private_result_set() -> None:
    public = result_set()
    private = public.model_copy(
        update={"results": (replay_result(PRIVATE_ASSET_ID),)}
    )

    with pytest.raises(BaselineError, match="^private_baseline_operation_forbidden$"):
        compare_result_sets(public, private)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("manifest_digest", "e" * 64),
        ("recipe_digest", "e" * 64),
        ("profile", "analysis_slow"),
        ("model_artifacts", ("openvino:" + "e" * 64,)),
    ],
)
def test_comparison_refuses_identity_mismatch(field: str, value: object) -> None:
    baseline = result_set()
    candidate = result_set(**{field: value})

    with pytest.raises(BaselineError, match="visual_baseline_identity_mismatch"):
        compare_result_sets(baseline, candidate)


def test_comparison_refuses_missing_or_extra_clip() -> None:
    baseline = result_set(
        results=(replay_result("DAY-01"), replay_result("DAY-02"))
    )
    candidate = result_set(results=(replay_result("DAY-01"),))

    with pytest.raises(BaselineError, match="visual_baseline_clip_identity_invalid"):
        compare_result_sets(baseline, candidate)


def test_equal_result_sets_pass_and_git_sha_may_change() -> None:
    baseline = result_set()
    candidate = baseline.model_copy(update={"git_sha": "e" * 40})

    comparison = compare_result_sets(baseline, candidate)

    assert comparison.status == "PASS"
    assert comparison.reason == "ok"
    assert comparison.compared_clips == 1
    assert comparison.regression_count == 0


def test_exact_count_regression_is_grouped_without_editing_baseline() -> None:
    baseline = result_set()
    candidate = result_set(results=(replay_result(dropped_frames=1),))
    original = baseline.model_dump_json()

    comparison = compare_result_sets(baseline, candidate)

    assert comparison.status == "REGRESSION"
    assert comparison.reason == "visual_regression_detected"
    assert comparison.regression_count == 1
    assert comparison.group_deltas["framing:crib_wide"] > 0
    assert baseline.model_dump_json() == original


def test_ratio_and_latency_use_fixed_tolerances() -> None:
    baseline = result_set()
    within = result_set(
        results=(replay_result(scene_usable=86, pipeline_p95_ms=29.9),)
    )
    outside = result_set(
        results=(replay_result(scene_usable=80, pipeline_p95_ms=31.0),)
    )

    assert compare_result_sets(baseline, within).status == "PASS"
    assert compare_result_sets(baseline, outside).status == "REGRESSION"


def test_failed_and_skipped_candidates_are_not_comparable_successes() -> None:
    baseline = result_set()

    failed = compare_result_sets(
        baseline,
        result_set(results=(replay_result(status="FAIL"),)),
    )
    skipped = compare_result_sets(
        baseline,
        result_set(results=(replay_result(status="SKIP"),)),
    )

    assert (failed.status, failed.reason) == ("FAILED", "candidate_failed")
    assert (skipped.status, skipped.reason) == (
        "INCOMPARABLE",
        "candidate_incomplete",
    )


def test_comparison_revalidates_nonfinite_or_schema_drift() -> None:
    baseline = result_set()
    invalid_result = replay_result().model_copy(
        update={"pipeline_p95_ms": float("nan")}
    )
    candidate = result_set().model_copy(update={"results": (invalid_result,)})

    with pytest.raises(BaselineError, match="visual_baseline_result_invalid"):
        compare_result_sets(baseline, candidate)


def test_comparison_refuses_unbounded_group_cardinality() -> None:
    baseline_results = tuple(
        replay_result(
            f"DAY-{index:02d}",
            groups=tuple(
                f"group_{index}_{group}:value" for group in range(16)
            ),
        )
        for index in range(9)
    )
    baseline = result_set(results=baseline_results)

    with pytest.raises(BaselineError, match="visual_baseline_group_overflow"):
        compare_result_sets(baseline, baseline)


def promotable_result_set():
    wide_roles = {
        "WIDE-01": "wide_role:caregiver_with_crib",
        "WIDE-02": "wide_role:room_context_with_crib",
        "WIDE-03": "wide_role:empty_or_object_only_crib_wide",
    }
    return result_set(
        results=tuple(
            replay_result(
                clip_id,
                groups=(
                    "framing:room_wide" if clip_id.startswith("WIDE") else "framing:medium",
                    wide_roles.get(clip_id, "wide_role:none"),
                    "lighting:day",
                    "visibility:full",
                ),
            )
            for clip_id in MANDATORY_CLIPS
        )
    )


def write_candidate(path: Path, value: object) -> None:
    path.write_text(value.model_dump_json(), encoding="utf-8")


def test_promotion_requires_digest_passes_and_complete_wide_groups(
    tmp_path: Path,
) -> None:
    candidate = promotable_result_set()
    candidate_path = tmp_path / "candidate.json"
    destination = tmp_path / "baseline.json"
    write_candidate(candidate_path, candidate)

    with pytest.raises(BaselineError, match="visual_baseline_digest_mismatch"):
        promote_baseline(
            candidate_path,
            destination,
            expected_digest="0" * 64,
        )

    incomplete = result_set(results=(replay_result("DAY-01"),))
    write_candidate(candidate_path, incomplete)
    with pytest.raises(BaselineError, match="visual_baseline_promotion_incomplete"):
        promote_baseline(
            candidate_path,
            destination,
            expected_digest=result_set_digest(incomplete),
        )

    missing_wide = promotable_result_set().model_copy(
        update={
            "results": tuple(
                item.model_copy(update={"groups": ("framing:medium",)})
                for item in promotable_result_set().results
            )
        }
    )
    write_candidate(candidate_path, missing_wide)
    with pytest.raises(BaselineError, match="visual_baseline_wide_group_missing"):
        promote_baseline(
            candidate_path,
            destination,
            expected_digest=result_set_digest(missing_wide),
        )


def test_promotion_is_canonical_atomic_and_never_replaces(tmp_path: Path) -> None:
    candidate = promotable_result_set()
    candidate_path = tmp_path / "candidate.json"
    destination = tmp_path / "baselines" / "visual-baseline.v1.json"
    write_candidate(candidate_path, candidate)

    digest = promote_baseline(
        candidate_path,
        destination,
        expected_digest=result_set_digest(candidate),
    )

    assert digest == result_set_digest(candidate)
    assert destination.read_bytes().endswith(b"\n")
    assert destination.stat().st_mode & 0o777 == 0o600
    original = destination.read_bytes()
    with pytest.raises(BaselineError, match="visual_baseline_exists"):
        promote_baseline(
            candidate_path,
            destination,
            expected_digest=digest,
        )
    assert destination.read_bytes() == original


def test_private_envelope_is_rejected_before_baseline_destination_creation(
    tmp_path: Path,
) -> None:
    candidate = tmp_path / "private-candidate.json"
    candidate.write_text(
        "{\"schema_version\":1,\"source_type\":\"PRIVATE_LOCAL_CAPTURE\","
        f"\"private_asset_id\":\"{PRIVATE_ASSET_ID}\",\"results\":[]}}",
        encoding="ascii",
    )
    destination = tmp_path / "not-created" / "baseline.json"

    with pytest.raises(BaselineError, match="^private_baseline_operation_forbidden$"):
        load_result_set(candidate)
    with pytest.raises(BaselineError, match="^private_baseline_operation_forbidden$"):
        promote_baseline(candidate, destination, expected_digest="0" * 64)

    assert not destination.exists()
    assert not destination.parent.exists()
