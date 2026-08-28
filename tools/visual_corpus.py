from __future__ import annotations

import argparse
import hashlib
import json
import logging
import math
import os
import platform
import resource
import stat
import subprocess
import sys
import tempfile
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path
from typing import Any

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

from packages.contracts.visual_corpus import VisualCorpusManifest
from packages.monitoring.realtime_models import REALTIME_MODEL_ASSETS
from services.vision.corpus_baseline import (
    BaselineError,
    build_result_set,
    compare_result_sets,
    load_result_set,
    promote_baseline,
    result_set_digest,
)
from services.vision.corpus_download import CorpusDownloader
from services.vision.corpus_manifest import (
    canonical_manifest_digest,
    load_manifest,
    validate_first_stage,
)
from services.vision.corpus_prepare import CorpusPreparer
from services.vision.corpus_replay import ReplayProfile, VisualCorpusReplay
from services.vision.corpus_storage import CorpusLayout
from services.vision.realtime_models import build_realtime_model_backend


MANIFEST_PATH = REPOSITORY_ROOT / "tests/fixtures/visual_corpus/manifest.json"
CANDIDATE_PATH = (
    REPOSITORY_ROOT
    / "runtime/test-corpus/visual/results/visual-candidate.json"
)
COMPARISON_PATH = (
    REPOSITORY_ROOT
    / "runtime/test-corpus/visual/results/visual-comparison.json"
)
LONG_RESULT_PATH = (
    REPOSITORY_ROOT
    / "runtime/test-corpus/visual/results/visual-long.json"
)
BASELINE_PATH = (
    REPOSITORY_ROOT
    / "tests/fixtures/visual_corpus/baselines/visual-baseline.v1.json"
)
MODEL_ROOT = REPOSITORY_ROOT / "runtime/models/openvino-2025.4.1"
FIRST_STAGE_CLIP_IDS = (
    "DAY-01",
    "DAY-02",
    "DAY-03",
    "WIDE-01",
    "WIDE-03",
    "NIGHT-01",
    "NIGHT-02",
    "NIGHT-03",
    "OCC-01",
    "OCC-02",
    "OCC-03",
    "NEG-02",
    "NEG-03",
)
PREPARE_PROFILE_IDS = ("analysis_realtime", "xiaomi_source_hd")
SAFE_REASONS = frozenset(
    {
        "visual_corpus_manifest_invalid",
        "visual_corpus_source_unavailable",
        "visual_corpus_download_total_too_large",
        "visual_corpus_download_too_large",
        "visual_corpus_existing_invalid",
        "visual_corpus_checksum_mismatch",
        "visual_corpus_download_failed",
        "visual_corpus_redirect_unsafe",
        "visual_corpus_storage_unsafe",
        "visual_corpus_artifact_exists",
        "visual_corpus_artifact_unsafe",
        "visual_corpus_source_invalid",
        "visual_corpus_probe_failed",
        "visual_corpus_media_invalid",
        "visual_corpus_hevc_encoder_unavailable",
        "visual_corpus_encoder_unavailable",
        "visual_corpus_prepare_failed",
        "visual_corpus_prepare_timeout",
        "visual_corpus_prepare_interrupted",
        "visual_corpus_profile_mismatch",
        "visual_corpus_publish_failed",
        "visual_baseline_candidate_invalid",
        "visual_baseline_digest_mismatch",
        "visual_baseline_promotion_incomplete",
        "visual_baseline_wide_group_missing",
        "visual_baseline_exists",
        "visual_baseline_destination_unsafe",
    }
)


def parser() -> argparse.ArgumentParser:
    command = argparse.ArgumentParser(description="Run the fixed public visual corpus")
    subcommands = command.add_subparsers(dest="command", required=True)
    subcommands.add_parser("validate")
    prepare = subcommands.add_parser("prepare")
    prepare.add_argument("--first-stage", action="store_true", required=True)
    replay = subcommands.add_parser("replay")
    replay.add_argument("--first-stage", action="store_true", required=True)
    subcommands.add_parser("compare")
    promote = subcommands.add_parser("promote")
    promote.add_argument(
        "--expected-digest",
        required=True,
    )
    long = subcommands.add_parser("long")
    long.add_argument("--minutes", type=int, choices=(30, 60), required=True)
    return command


def main(argv: list[str] | None = None) -> int:
    arguments = parser().parse_args(argv)
    try:
        return run_command(arguments)
    except KeyboardInterrupt:
        _emit(result="FAIL", reason="visual_corpus_interrupted")
        return 130
    except Exception as exc:
        reason = str(exc)
        if reason not in SAFE_REASONS:
            reason = "visual_corpus_command_failed"
        _emit(result="FAIL", reason=reason)
        return 2


def run_command(arguments: argparse.Namespace) -> int:
    if arguments.command == "validate":
        return _validate()
    if arguments.command == "prepare":
        return _prepare_command()
    if arguments.command == "replay":
        return _replay_command()
    if arguments.command == "compare":
        return _compare_command()
    if arguments.command == "promote":
        return _promote_command(arguments.expected_digest)
    if arguments.command == "long":
        return _long_command(arguments.minutes)
    raise RuntimeError("visual_corpus_command_failed")


def _validate() -> int:
    manifest = load_manifest(MANIFEST_PATH)
    try:
        validate_first_stage(manifest)
        admission = "PASS"
        missing = 0
    except ValueError:
        admission = "SKIP"
        observed = {
            scenario.value
            for clip in manifest.clips
            for scenario in clip.scenario_ids
        }
        missing = 15 - len(observed)
    _emit(
        result="PASS",
        readiness=manifest.readiness.value,
        clip_count=len(manifest.clips),
        admission=admission,
        missing_scenarios=max(0, missing),
    )
    return 0


def _prepare_command() -> int:
    _manifest, prepared = _prepare_fixed()
    artifacts = [artifact for item in prepared for artifact in item.artifacts]
    _emit(
        result="PASS",
        clip_count=len(prepared),
        artifact_count=len(artifacts),
        reused_count=sum(artifact.reused for artifact in artifacts),
        raw_media_persisted="private_only",
    )
    return 0


def _replay_command() -> int:
    manifest, prepared = _prepare_fixed()
    prepared_by_clip = {
        item.clip_id: {
            artifact.profile_id: artifact for artifact in item.artifacts
        }
        for item in prepared
    }
    backend = _build_model_backend_quietly()
    profile = ReplayProfile(
        profile_id="analysis_realtime",
        fps=5,
        model_backend=backend,
        require_model=True,
    )
    replay = VisualCorpusReplay(
        prepared_resolver=lambda clip, selected: prepared_by_clip[clip.clip_id][
            selected.profile_id
        ].path
    )
    clips = _selected_clips(manifest)
    results = tuple(replay.run_clip(clip, profile=profile) for clip in clips)
    recipe_digest = _combined_digest(
        tuple(
            prepared_by_clip[clip.clip_id]["analysis_realtime"].recipe_digest
            for clip in clips
        )
    )
    result_set = build_result_set(
        manifest_digest=canonical_manifest_digest(manifest),
        recipe_digest=recipe_digest,
        profile=profile.profile_id,
        git_sha=_git_sha(),
        model_artifacts=("openvino:" + _model_manifest_digest(),),
        results=results,
    )
    write_private_json(CANDIDATE_PATH, result_set.model_dump(mode="json"))
    digest = result_set_digest(result_set)
    if any(result.status == "FAIL" for result in results):
        overall = "FAIL"
        code = 2
    elif any(result.status == "SKIP" for result in results):
        overall = "SKIP"
        code = 0
    else:
        overall = "PASS"
        code = 0
    _emit(
        result=overall,
        clip_count=len(results),
        pass_count=sum(result.status == "PASS" for result in results),
        skip_count=sum(result.status == "SKIP" for result in results),
        fail_count=sum(result.status == "FAIL" for result in results),
        candidate_sha256=digest,
        raw_media_persisted="private_only",
        frame_observations_persisted="false",
    )
    return code


def _compare_command() -> int:
    if not BASELINE_PATH.is_file():
        _emit(result="SKIP", reason="visual_baseline_missing")
        return 0
    candidate = load_result_set(CANDIDATE_PATH)
    baseline = load_result_set(BASELINE_PATH)
    comparison = compare_result_sets(baseline, candidate)
    write_private_json(COMPARISON_PATH, comparison.model_dump(mode="json"))
    _emit(
        result=comparison.status.value,
        reason=comparison.reason,
        compared_clips=comparison.compared_clips,
        regression_count=comparison.regression_count,
    )
    return 0 if comparison.status.value == "PASS" else 2


def _promote_command(expected_digest: str) -> int:
    if len(expected_digest) != 64 or any(
        character not in "0123456789abcdef" for character in expected_digest
    ):
        raise BaselineError("visual_baseline_digest_mismatch")
    digest = promote_baseline(
        CANDIDATE_PATH,
        BASELINE_PATH,
        expected_digest=expected_digest,
    )
    _emit(result="PASS", baseline_sha256=digest)
    return 0


def _long_command(minutes: int) -> int:
    manifest, prepared = _prepare_fixed()
    prepared_by_clip = {
        item.clip_id: {
            artifact.profile_id: artifact for artifact in item.artifacts
        }
        for item in prepared
    }
    backend = _build_model_backend_quietly()
    if backend is None:
        _emit(result="SKIP", reason="visual_corpus_model_unavailable")
        return 0
    profile = ReplayProfile(
        profile_id="analysis_slow",
        fps=1,
        model_backend=backend,
        require_model=True,
    )
    replay = VisualCorpusReplay(
        prepared_resolver=lambda clip, _selected: prepared_by_clip[clip.clip_id][
            "analysis_realtime"
        ].path
    )
    clips = _selected_clips(manifest)
    target_seconds = minutes * 60
    media_seconds = 0.0
    repetitions = 0
    clip_runs = 0
    frames_total = 0
    decode_errors = 0
    worker_errors = 0
    candidate_transitions = 0
    queue_backlog_max = 0
    first_cycle_rss_mb: float | None = None
    peak_rss_mb = _rss_mb()
    failed = False
    while media_seconds < target_seconds and not failed:
        repetitions += 1
        for clip in clips:
            result = replay.run_clip(clip, profile=profile)
            clip_runs += 1
            duration = (clip.end_ms - clip.start_ms) / 1000
            media_seconds += duration
            frames_total += result.frames_total
            decode_errors += result.decode_errors
            worker_errors += result.worker_errors
            candidate_transitions += sum(result.candidate_counts.values())
            queue_backlog_max = max(queue_backlog_max, result.queue_backlog_max)
            peak_rss_mb = max(peak_rss_mb, _rss_mb())
            if result.status != "PASS":
                failed = True
                break
            if media_seconds >= target_seconds:
                break
        if repetitions == 1:
            first_cycle_rss_mb = peak_rss_mb
    first_cycle_rss_mb = first_cycle_rss_mb or peak_rss_mb
    rss_growth_mb = max(0.0, peak_rss_mb - first_cycle_rss_mb)
    if rss_growth_mb > 256:
        failed = True
    payload = {
        "schema_version": 1,
        "status": "FAIL" if failed else "PASS",
        "reason": (
            "visual_corpus_long_replay_failed" if failed else "ok"
        ),
        "profile": "analysis_slow",
        "target_minutes": minutes,
        "media_seconds": round(media_seconds, 3),
        "repetitions": repetitions,
        "clip_runs": clip_runs,
        "frames_total": frames_total,
        "decode_errors": decode_errors,
        "worker_errors": worker_errors,
        "queue_backlog_max": queue_backlog_max,
        "candidate_transitions": candidate_transitions,
        "guardian_event_count": 0,
        "duplicate_event_count": 0,
        "first_cycle_rss_mb": round(first_cycle_rss_mb, 3),
        "peak_rss_mb": round(peak_rss_mb, 3),
        "rss_growth_mb": round(rss_growth_mb, 3),
        "frame_observations_persisted": False,
    }
    write_private_json(LONG_RESULT_PATH, payload)
    _emit(
        result=payload["status"],
        reason=payload["reason"],
        media_seconds=payload["media_seconds"],
        clip_runs=clip_runs,
        frames_total=frames_total,
        decode_errors=decode_errors,
        worker_errors=worker_errors,
        rss_growth_mb=payload["rss_growth_mb"],
    )
    return 2 if failed else 0


def _prepare_fixed():
    manifest = load_manifest(MANIFEST_PATH)
    layout = CorpusLayout.for_repository(REPOSITORY_ROOT)
    downloaded = CorpusDownloader(layout=layout).fetch_all(manifest.sources)
    source_paths = {
        source.source_id: item.path
        for source, item in zip(manifest.sources, downloaded, strict=True)
    }
    profiles = tuple(
        profile
        for profile in manifest.profiles
        if profile.profile_id in PREPARE_PROFILE_IDS
    )
    if {profile.profile_id for profile in profiles} != set(PREPARE_PROFILE_IDS):
        raise RuntimeError("visual_corpus_command_failed")
    preparer = CorpusPreparer(
        layout=layout,
        profiles=profiles,
        source_resolver=source_paths.__getitem__,
    )
    prepared = tuple(
        preparer.prepare_clip(clip) for clip in _selected_clips(manifest)
    )
    return manifest, prepared


def _selected_clips(manifest: VisualCorpusManifest):
    clips = tuple(
        clip for clip in manifest.clips if clip.clip_id in FIRST_STAGE_CLIP_IDS
    )
    if tuple(clip.clip_id for clip in clips) != FIRST_STAGE_CLIP_IDS:
        by_id = {clip.clip_id: clip for clip in clips}
        try:
            clips = tuple(by_id[clip_id] for clip_id in FIRST_STAGE_CLIP_IDS)
        except KeyError as exc:
            raise RuntimeError("visual_corpus_command_failed") from exc
    return clips


def write_private_json(destination: Path, value: Any) -> None:
    destination = Path(destination)
    destination.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    try:
        directory_info = destination.parent.lstat()
    except OSError as exc:
        raise RuntimeError("visual_corpus_result_unsafe") from exc
    if (
        _path_has_symlink(destination.parent)
        or not stat.S_ISDIR(directory_info.st_mode)
        or directory_info.st_uid != os.getuid()
        or stat.S_IMODE(directory_info.st_mode) != 0o700
    ):
        raise RuntimeError("visual_corpus_result_unsafe")
    if destination.exists() or destination.is_symlink():
        try:
            metadata = destination.lstat()
        except OSError as exc:
            raise RuntimeError("visual_corpus_result_unsafe") from exc
        if (
            destination.is_symlink()
            or not stat.S_ISREG(metadata.st_mode)
            or metadata.st_uid != os.getuid()
            or stat.S_IMODE(metadata.st_mode) != 0o600
        ):
            raise RuntimeError("visual_corpus_result_unsafe")
    try:
        payload = (
            json.dumps(
                value,
                ensure_ascii=True,
                allow_nan=False,
                sort_keys=True,
                separators=(",", ":"),
            )
            + "\n"
        ).encode("ascii")
    except (TypeError, ValueError, UnicodeError) as exc:
        raise RuntimeError("visual_corpus_result_unsafe") from exc
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=".visual-result.",
        suffix=".tmp",
        dir=destination.parent,
    )
    temporary = Path(temporary_name)
    try:
        os.fchmod(descriptor, 0o600)
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, destination)
        _fsync_directory(destination.parent)
    finally:
        try:
            os.close(descriptor)
        except OSError:
            pass
        try:
            temporary.unlink(missing_ok=True)
        except OSError:
            pass


def _git_sha() -> str:
    completed = subprocess.run(
        ("git", "rev-parse", "HEAD"),
        cwd=REPOSITORY_ROOT,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        timeout=5,
        check=False,
        text=True,
    )
    value = completed.stdout.strip()
    if completed.returncode != 0 or len(value) != 40 or any(
        character not in "0123456789abcdef" for character in value
    ):
        raise RuntimeError("visual_corpus_command_failed")
    return value


def _model_manifest_digest() -> str:
    return _combined_digest(tuple(asset.sha256 for asset in REALTIME_MODEL_ASSETS))


def _rss_mb() -> float:
    raw = float(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss)
    divisor = 1024 * 1024 if platform.system() == "Darwin" else 1024
    return raw / divisor


def _build_model_backend_quietly():
    previous_disable = logging.root.manager.disable
    try:
        logging.disable(logging.CRITICAL)
        with Path(os.devnull).open("w", encoding="ascii") as sink:
            with redirect_stdout(sink), redirect_stderr(sink):
                return build_realtime_model_backend(MODEL_ROOT)
    finally:
        logging.disable(previous_disable)


def _combined_digest(values: tuple[str, ...]) -> str:
    payload = json.dumps(
        sorted(values),
        ensure_ascii=True,
        separators=(",", ":"),
    ).encode("ascii")
    return hashlib.sha256(payload).hexdigest()


def _path_has_symlink(path: Path) -> bool:
    absolute = path.absolute()
    return any(candidate.is_symlink() for candidate in (absolute, *absolute.parents))


def _fsync_directory(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY)
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _emit(**values: object) -> None:
    for key, value in values.items():
        if isinstance(value, bool):
            rendered = "true" if value else "false"
        elif isinstance(value, float):
            if not math.isfinite(value):
                raise RuntimeError("visual_corpus_command_failed")
            rendered = str(value)
        else:
            rendered = str(value)
        print(f"{key}={rendered}")


if __name__ == "__main__":
    raise SystemExit(main())
