from __future__ import annotations

import hashlib
import json
import os
import re
import stat
import tempfile
from pathlib import Path

from pydantic import ValidationError

from packages.contracts.visual_corpus import (
    BaselineComparison,
    ReplayResult,
    ReplayResultSet,
)


OBSERVATION_RATIO_TOLERANCE = 0.05
LATENCY_MULTIPLIER = 1.25
LATENCY_ALLOWANCE_MS = 5.0
MAX_RESULT_SET_BYTES = 4 * 1024 * 1024
MANDATORY_CLIP_IDS = frozenset(
    {
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
    }
)
MANDATORY_WIDE_GROUPS = frozenset(
    {
        "wide_role:caregiver_with_crib",
        "wide_role:room_context_with_crib",
        "wide_role:empty_or_object_only_crib_wide",
    }
)
_PRIVATE_ASSET_ID = re.compile(r"^plc-[0-9a-f]{32}$")


class BaselineError(RuntimeError):
    pass


def build_result_set(
    *,
    manifest_digest: str,
    recipe_digest: str,
    profile: str,
    git_sha: str,
    model_artifacts: tuple[str, ...],
    results: tuple[ReplayResult, ...],
) -> ReplayResultSet:
    if any(_is_private_result(result) for result in results):
        raise BaselineError("private_baseline_operation_forbidden")
    clip_ids = [result.clip_id for result in results]
    if len(set(clip_ids)) != len(clip_ids):
        raise BaselineError("visual_baseline_clip_identity_invalid")
    if len(set(model_artifacts)) != len(model_artifacts):
        raise BaselineError("visual_baseline_identity_invalid")
    try:
        return ReplayResultSet(
            manifest_digest=manifest_digest,
            recipe_digest=recipe_digest,
            profile=profile,
            git_sha=git_sha,
            model_artifacts=tuple(sorted(model_artifacts)),
            results=tuple(sorted(results, key=lambda item: item.clip_id)),
        )
    except (ValidationError, ValueError) as exc:
        raise BaselineError("visual_baseline_identity_invalid") from exc


def compare_result_sets(
    baseline: ReplayResultSet,
    candidate: ReplayResultSet,
) -> BaselineComparison:
    baseline = _validated_result_set(baseline)
    candidate = _validated_result_set(candidate)
    if _identity(baseline) != _identity(candidate):
        raise BaselineError("visual_baseline_identity_mismatch")
    baseline_by_clip = {item.clip_id: item for item in baseline.results}
    candidate_by_clip = {item.clip_id: item for item in candidate.results}
    if baseline_by_clip.keys() != candidate_by_clip.keys():
        raise BaselineError("visual_baseline_clip_identity_invalid")

    failed = [item for item in candidate.results if item.status == "FAIL"]
    if failed:
        return BaselineComparison(
            status="FAILED",
            reason="candidate_failed",
            compared_clips=len(candidate.results),
            regression_count=len(failed),
            group_deltas={},
        )
    incomplete = [item for item in candidate.results if item.status == "SKIP"]
    if incomplete:
        return BaselineComparison(
            status="INCOMPARABLE",
            reason="candidate_incomplete",
            compared_clips=len(candidate.results),
            regression_count=0,
            group_deltas={},
        )
    if any(item.status != "PASS" for item in baseline.results):
        return BaselineComparison(
            status="INCOMPARABLE",
            reason="baseline_incomplete",
            compared_clips=len(candidate.results),
            regression_count=0,
            group_deltas={},
        )

    regression_count = 0
    group_deltas: dict[str, float] = {}
    for clip_id in sorted(baseline_by_clip):
        baseline_clip = baseline_by_clip[clip_id]
        candidate_clip = candidate_by_clip[clip_id]
        regressed, delta = _compare_clip(baseline_clip, candidate_clip)
        if regressed:
            regression_count += 1
        for group in baseline_clip.groups:
            if group not in group_deltas and len(group_deltas) >= 128:
                raise BaselineError("visual_baseline_group_overflow")
            group_deltas[group] = max(group_deltas.get(group, 0.0), delta)

    return BaselineComparison(
        status="REGRESSION" if regression_count else "PASS",
        reason="visual_regression_detected" if regression_count else "ok",
        compared_clips=len(candidate.results),
        regression_count=regression_count,
        group_deltas={
            key: round(value, 6) for key, value in sorted(group_deltas.items())
        },
    )


def result_set_digest(value: ReplayResultSet) -> str:
    validated = _validated_result_set(value)
    return hashlib.sha256(canonical_result_set_bytes(validated)).hexdigest()


def promote_baseline(
    candidate_path: Path,
    destination: Path,
    *,
    expected_digest: str,
) -> str:
    candidate = load_result_set(candidate_path)
    digest = result_set_digest(candidate)
    if digest != expected_digest:
        raise BaselineError("visual_baseline_digest_mismatch")
    if any(result.status != "PASS" for result in candidate.results):
        raise BaselineError("visual_baseline_promotion_incomplete")
    clip_ids = {result.clip_id for result in candidate.results}
    if not MANDATORY_CLIP_IDS.issubset(clip_ids):
        raise BaselineError("visual_baseline_promotion_incomplete")
    groups = {group for result in candidate.results for group in result.groups}
    if not MANDATORY_WIDE_GROUPS.issubset(groups):
        raise BaselineError("visual_baseline_wide_group_missing")

    destination = Path(destination)
    if destination.exists() or destination.is_symlink():
        raise BaselineError("visual_baseline_exists")
    destination.parent.mkdir(parents=True, exist_ok=True)
    if _path_has_symlink(destination.parent):
        raise BaselineError("visual_baseline_destination_unsafe")

    payload = canonical_result_set_bytes(candidate)
    temporary: Path | None = None
    try:
        descriptor, temporary_name = tempfile.mkstemp(
            prefix=".visual-baseline.",
            suffix=".tmp",
            dir=destination.parent,
        )
        temporary = Path(temporary_name)
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        try:
            os.link(temporary, destination, follow_symlinks=False)
        except FileExistsError as exc:
            raise BaselineError("visual_baseline_exists") from exc
        _fsync_directory(destination.parent)
    finally:
        if temporary is not None:
            try:
                temporary.unlink(missing_ok=True)
            except OSError:
                pass
    return digest


def _identity(value: ReplayResultSet) -> tuple[object, ...]:
    return (
        value.schema_version,
        value.manifest_digest,
        value.recipe_digest,
        value.profile,
        value.model_artifacts,
    )


def _validated_result_set(value: ReplayResultSet) -> ReplayResultSet:
    if _is_private_result_set(value):
        raise BaselineError("private_baseline_operation_forbidden")
    try:
        return ReplayResultSet.model_validate(value.model_dump())
    except (ValidationError, ValueError) as exc:
        raise BaselineError("visual_baseline_result_invalid") from exc


def _compare_clip(
    baseline: ReplayResult,
    candidate: ReplayResult,
) -> tuple[bool, float]:
    if baseline.groups != candidate.groups:
        raise BaselineError("visual_baseline_clip_identity_invalid")
    exact_fields = (
        "status",
        "reason",
        "frames_total",
        "frames_processed",
        "frames_skipped",
        "decode_errors",
        "worker_errors",
        "model_state",
        "candidate_counts",
        "dropped_frames",
        "queue_backlog_max",
        "guardian",
    )
    regression = any(
        getattr(baseline, field) != getattr(candidate, field)
        for field in exact_fields
    )
    delta = 1.0 if regression else 0.0

    observation_keys = set(baseline.observation_counts) | set(
        candidate.observation_counts
    )
    baseline_denominator = max(1, baseline.frames_processed)
    candidate_denominator = max(1, candidate.frames_processed)
    for key in observation_keys:
        baseline_ratio = (
            baseline.observation_counts.get(key, 0) / baseline_denominator
        )
        candidate_ratio = (
            candidate.observation_counts.get(key, 0) / candidate_denominator
        )
        ratio_delta = abs(candidate_ratio - baseline_ratio)
        delta = max(delta, ratio_delta)
        if ratio_delta > OBSERVATION_RATIO_TOLERANCE:
            regression = True

    for field in (
        "processing_p50_ms",
        "processing_p95_ms",
        "processing_max_ms",
        "pipeline_p50_ms",
        "pipeline_p95_ms",
        "pipeline_max_ms",
    ):
        baseline_latency = getattr(baseline, field)
        candidate_latency = getattr(candidate, field)
        allowed = baseline_latency * LATENCY_MULTIPLIER + LATENCY_ALLOWANCE_MS
        if candidate_latency > allowed:
            regression = True
            delta = max(delta, (candidate_latency - allowed) / max(1.0, allowed))
    return regression, delta


def canonical_result_set_bytes(value: ReplayResultSet) -> bytes:
    value = _validated_result_set(value)
    payload = json.dumps(
        value.model_dump(mode="json"),
        ensure_ascii=True,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return (payload + "\n").encode("ascii")


def load_result_set(path: Path) -> ReplayResultSet:
    path = Path(path)
    try:
        metadata = path.lstat()
        if not stat.S_ISREG(metadata.st_mode) or path.is_symlink():
            raise BaselineError("visual_baseline_candidate_invalid")
        if metadata.st_size <= 0 or metadata.st_size > MAX_RESULT_SET_BYTES:
            raise BaselineError("visual_baseline_candidate_invalid")
        raw = path.read_bytes()
        payload = json.loads(raw)
        if _is_private_payload(payload):
            raise BaselineError("private_baseline_operation_forbidden")
        return ReplayResultSet.model_validate(payload)
    except BaselineError:
        raise
    except (OSError, ValidationError, ValueError) as exc:
        raise BaselineError("visual_baseline_candidate_invalid") from exc


def _is_private_result(value: object) -> bool:
    clip_id = getattr(value, "clip_id", None)
    return isinstance(clip_id, str) and _PRIVATE_ASSET_ID.fullmatch(clip_id) is not None


def _is_private_result_set(value: object) -> bool:
    results = getattr(value, "results", ())
    return isinstance(results, (tuple, list)) and any(
        _is_private_result(result) for result in results
    )


def _is_private_payload(payload: object) -> bool:
    if not isinstance(payload, dict):
        return False
    if payload.get("source_type") == "PRIVATE_LOCAL_CAPTURE":
        return True
    if _PRIVATE_ASSET_ID.fullmatch(str(payload.get("private_asset_id", ""))):
        return True
    results = payload.get("results")
    if not isinstance(results, list):
        return False
    return any(
        isinstance(result, dict)
        and _PRIVATE_ASSET_ID.fullmatch(str(result.get("clip_id", ""))) is not None
        for result in results
    )


def _path_has_symlink(path: Path) -> bool:
    absolute = path.absolute()
    return any(candidate.is_symlink() for candidate in (absolute, *absolute.parents))


def _fsync_directory(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)
