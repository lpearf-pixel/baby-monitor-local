from __future__ import annotations

import argparse
import logging
import os
import secrets
import stat
import sys
import threading
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

from packages.contracts.offline_guardian_scenario import (
    OfflineScenarioSuiteV1,
    load_offline_scenario_suite,
)
from packages.contracts.visual_corpus import (
    VisualCorpusClip,
    VisualCorpusManifest,
)
from services.offline_guardian_report import publish_offline_scenario_report
from services.offline_guardian_scenario import (
    DEFAULT_RUN_TIMEOUT_SECONDS,
    OfflineGuardianScenarioRunner,
    OfflineScenarioTimeout,
    offline_scenario_deadline,
    validate_visual_scenario_bindings,
)
from services.vision.corpus_download import CorpusDownloader, MAX_FIRST_STAGE_BYTES
from services.vision.corpus_manifest import load_manifest
from services.vision.corpus_prepare import CorpusPreparer
from services.vision.corpus_storage import CorpusLayout
from services.vision.realtime_models import build_realtime_model_backend
from services.voice.asr import AsrResult
from services.voice.vad import VoiceActivityDetector


SCENARIO_SUITE_PATH = (
    REPOSITORY_ROOT / "tests/fixtures/offline_guardian_scenarios/scenarios.v1.json"
)
VISUAL_MANIFEST_PATH = REPOSITORY_ROOT / "tests/fixtures/visual_corpus/manifest.json"
MODEL_ROOT = REPOSITORY_ROOT / "runtime/models/openvino-2025.4.1"
RUN_PARENT = REPOSITORY_ROOT / "runtime/test-corpus/offline-scenario"
VISUAL_CLIP_IDS = ("DAY-01", "OCC-02", "NEG-03", "DAY-03", "OCC-03")
EXPECTED_SCENARIO_IDS = (
    "SAFE-SLEEP-01",
    "FACE-OCCLUSION-01",
    "ADULT-INTERVENTION-01",
    "VOICE-FEEDING-01",
    "PRONE-CANDIDATE-01",
    "OUTSIDE-CANDIDATE-01",
    "VOICE-DIAPER-01",
    "VOICE-BURPING-01",
)
EXPECTED_PUBLIC_SOURCE_IDS = (
    "cdc-two-month-movement",
    "cdc-safe-sleep-babies",
    "wikimedia-infant-active-sleep",
)
EXPECTED_SCENARIO_COUNT = 8
EXPECTED_LANE_COUNT = 13
EXPECTED_VISUAL_CLIP_COUNT = 5
EXPECTED_FRAME_COUNT = 330
EXPECTED_PUBLIC_SOURCE_COUNT = 3
EXPECTED_DECLARED_SOURCE_BYTES = 25_964_039
SAFE_REASONS = frozenset(
    {
        "offline_scenario_visual_provenance_invalid",
        "offline_scenario_runtime_unsafe",
        "offline_scenario_report_unsafe",
        "offline_scenario_report_failed",
        "offline_scenario_report_too_large",
        "visual_corpus_source_unavailable",
        "visual_corpus_download_failed",
        "visual_corpus_checksum_mismatch",
        "visual_corpus_existing_invalid",
        "visual_corpus_prepare_failed",
        "visual_corpus_prepare_timeout",
        "visual_corpus_profile_mismatch",
        "visual_corpus_model_unavailable",
    }
)


def parser() -> argparse.ArgumentParser:
    command = argparse.ArgumentParser(description="Run fixed offline Guardian scenarios")
    subcommands = command.add_subparsers(dest="command", required=True)
    subcommands.add_parser("validate")
    subcommands.add_parser("run")
    return command


def main(argv: list[str] | None = None) -> int:
    arguments = parser().parse_args(argv)
    try:
        if arguments.command == "validate":
            return _validate()
        return _run()
    except KeyboardInterrupt:
        _emit(result="FAIL", reason="offline_scenario_interrupted")
        return 130
    except OfflineScenarioTimeout:
        _emit(result="FAIL", reason="offline_scenario_timeout")
        return 2
    except Exception as exc:
        reason = str(exc)
        if reason not in SAFE_REASONS:
            reason = "offline_scenario_command_failed"
        _emit(result="FAIL", reason=reason)
        return 2


def _validate() -> int:
    suite = load_offline_scenario_suite(SCENARIO_SUITE_PATH)
    manifest = load_manifest(VISUAL_MANIFEST_PATH)
    clips, lane_count, frame_count, source_ids, declared_bytes = _validate_fixed_suite(
        suite,
        manifest,
    )
    _emit(
        result="PASS",
        suite_id=suite.suite_id,
        scenario_count=len(suite.scenarios),
        lane_count=lane_count,
        visual_clip_count=len(clips),
        expected_frame_count=frame_count,
        public_source_count=len(source_ids),
        declared_source_bytes=declared_bytes,
    )
    return 0


def _run() -> int:
    with offline_scenario_deadline(DEFAULT_RUN_TIMEOUT_SECONDS):
        run, report_name = _execute_fixed_flow()
    lanes = tuple(lane for result in run.results for lane in result.lanes)
    visual_lanes = tuple(lane for lane in lanes if lane.lane == "visual_observation")
    frame_count = sum(lane.counts.get("frames.processed", 0) for lane in visual_lanes)
    pass_count = sum(result.status == "PASS" for result in run.results)
    skip_count = sum(result.status == "SKIP" for result in run.results)
    fail_count = sum(result.status == "FAIL" for result in run.results)
    exact_pass = (
        run.suite_id == "offline-guardian-v1"
        and run.status == "PASS"
        and run.reason == "ok"
        and tuple(result.scenario_id for result in run.results) == EXPECTED_SCENARIO_IDS
        and len(run.results) == EXPECTED_SCENARIO_COUNT
        and pass_count == EXPECTED_SCENARIO_COUNT
        and skip_count == 0
        and fail_count == 0
        and len(lanes) == EXPECTED_LANE_COUNT
        and all(lane.status == "PASS" for lane in lanes)
        and len(visual_lanes) == EXPECTED_VISUAL_CLIP_COUNT
        and frame_count == EXPECTED_FRAME_COUNT
    )
    _emit(
        result="PASS" if exact_pass else "FAIL",
        reason=(
            "ok"
            if exact_pass
            else run.reason
            if run.status == "FAIL"
            else "offline_scenario_command_failed"
        ),
        scenario_count=len(run.results),
        pass_count=pass_count,
        skip_count=skip_count,
        fail_count=fail_count,
        lane_count=len(lanes),
        visual_clip_count=len(visual_lanes),
        frame_count=frame_count,
        public_source_count=EXPECTED_PUBLIC_SOURCE_COUNT,
        declared_source_bytes=EXPECTED_DECLARED_SOURCE_BYTES,
        report=report_name,
    )
    return 0 if exact_pass else 2


def _execute_fixed_flow():
    suite = load_offline_scenario_suite(SCENARIO_SUITE_PATH)
    manifest = load_manifest(VISUAL_MANIFEST_PATH)
    clips, _lanes, _frames, _sources, _bytes = _validate_fixed_suite(suite, manifest)
    prepared, prepared_root = _prepare_selected_visuals(manifest, clips)
    backend = _build_model_backend_quietly()
    fixture_pcm, asr_factory = _generated_voice_fixture()
    run_root = _new_run_root_path()
    runner = OfflineGuardianScenarioRunner(
        runtime_root=run_root,
        runtime_boundary=RUN_PARENT,
        visual_manifest=manifest,
        prepared_resolver=lambda clip, profile: prepared[clip.clip_id][
            profile.profile_id
        ],
        prepared_root=prepared_root,
        model_backend=backend,
        voice_fixture_provider=fixture_pcm.__getitem__,
        voice_vad_factory=lambda: VoiceActivityDetector(
            lambda waveform: 0.9 if waveform.any() else 0.0,
        ),
        voice_asr_factory=asr_factory,
        voice_synthesizer_factory=_RecordingSynthesizer,
    )
    run = runner.run(suite)
    report_root = run_root / "report"
    report_root.mkdir(mode=0o700)
    report_root.chmod(0o700)
    publish_offline_scenario_report(run, report_root)
    return run, f"{run_root.name}/report"


def _prepare_selected_visuals(
    manifest: VisualCorpusManifest,
    clips: tuple[VisualCorpusClip, ...],
) -> tuple[
    dict[str, dict[str, Path]],
    Path,
]:
    layout = CorpusLayout.for_repository(REPOSITORY_ROOT)
    sources_by_id = {source.source_id: source for source in manifest.sources}
    selected_source_ids = tuple(dict.fromkeys(clip.source_id for clip in clips))
    expected_total = sum(
        sources_by_id[source_id].expected_bytes or MAX_FIRST_STAGE_BYTES + 1
        for source_id in selected_source_ids
    )
    if expected_total > MAX_FIRST_STAGE_BYTES:
        raise RuntimeError("offline_scenario_command_failed")
    downloaded = {
        source_id: CorpusDownloader(layout=layout).fetch(sources_by_id[source_id]).path
        for source_id in selected_source_ids
    }
    profiles = tuple(
        profile
        for profile in manifest.profiles
        if profile.profile_id == "analysis_realtime"
    )
    if len(profiles) != 1:
        raise RuntimeError("offline_scenario_command_failed")
    preparer = CorpusPreparer(
        layout=layout,
        profiles=profiles,
        source_resolver=downloaded.__getitem__,
    )
    prepared = tuple(preparer.prepare_clip(clip) for clip in clips)
    return (
        {
            item.clip_id: {
                artifact.profile_id: artifact.path for artifact in item.artifacts
            }
            for item in prepared
        },
        layout.prepared,
    )


def _validate_fixed_suite(
    suite: OfflineScenarioSuiteV1,
    manifest: VisualCorpusManifest,
) -> tuple[tuple[VisualCorpusClip, ...], int, int, tuple[str, ...], int]:
    clips = validate_visual_scenario_bindings(suite, manifest)
    scenario_ids = tuple(scenario.scenario_id for scenario in suite.scenarios)
    lane_count = sum(len(scenario.required_lanes) for scenario in suite.scenarios)
    visual_ids = tuple(clip.clip_id for clip in clips)
    frame_count = sum(
        scenario.visual.expected_frames_processed
        for scenario in suite.scenarios
        if scenario.visual is not None
    )
    source_ids = tuple(dict.fromkeys(clip.source_id for clip in clips))
    sources_by_id = {source.source_id: source for source in manifest.sources}
    try:
        declared_bytes = sum(
            sources_by_id[source_id].expected_bytes for source_id in source_ids
        )
    except (KeyError, TypeError):
        raise RuntimeError("offline_scenario_command_failed") from None
    if (
        suite.suite_id != "offline-guardian-v1"
        or scenario_ids != EXPECTED_SCENARIO_IDS
        or len(suite.scenarios) != EXPECTED_SCENARIO_COUNT
        or lane_count != EXPECTED_LANE_COUNT
        or visual_ids != VISUAL_CLIP_IDS
        or len(clips) != EXPECTED_VISUAL_CLIP_COUNT
        or frame_count != EXPECTED_FRAME_COUNT
        or source_ids != EXPECTED_PUBLIC_SOURCE_IDS
        or len(source_ids) != EXPECTED_PUBLIC_SOURCE_COUNT
        or declared_bytes != EXPECTED_DECLARED_SOURCE_BYTES
        or declared_bytes > MAX_FIRST_STAGE_BYTES
    ):
        raise RuntimeError("offline_scenario_command_failed")
    return clips, lane_count, frame_count, source_ids, declared_bytes


def _new_run_root_path() -> Path:
    if _path_has_symlink(RUN_PARENT):
        raise ValueError("offline_scenario_runtime_unsafe")
    RUN_PARENT.mkdir(mode=0o700, parents=True, exist_ok=True)
    RUN_PARENT.chmod(0o700)
    metadata = RUN_PARENT.lstat()
    if (
        RUN_PARENT.is_symlink()
        or not stat.S_ISDIR(metadata.st_mode)
        or metadata.st_uid != os.getuid()
        or stat.S_IMODE(metadata.st_mode) != 0o700
    ):
        raise ValueError("offline_scenario_runtime_unsafe")
    for _attempt in range(8):
        candidate = RUN_PARENT / f"run-{secrets.token_hex(8)}"
        if not candidate.exists() and not candidate.is_symlink():
            return candidate
    raise ValueError("offline_scenario_runtime_unsafe")


def _path_has_symlink(path: Path) -> bool:
    absolute = path.absolute()
    return any(candidate.is_symlink() for candidate in (absolute, *absolute.parents))


def _generated_voice_fixture():
    text_by_step = {
        "wake": "\u5c0f\u5c0f",
        "feeding": "\u6211\u662f\u7238\u7238\uff0c\u5f00\u59cb\u5582\u5976",
        "no_wake": "\u4eca\u5929\u5929\u6c14\u5982\u4f55",
        "unsupported": "\u64ad\u653e\u97f3\u4e50",
        "diaper_wake": "\u5c0f\u5c0f",
        "diaper_start": "\u5f00\u59cb\u6362\u5c3f\u5e03",
        "diaper_wake_complete": "\u5c0f\u5c0f",
        "diaper_complete": "\u6362\u597d\u5c3f\u5e03\u4e86",
        "diaper_cross_burping": "\u5c0f\u5c0f\u5f00\u59cb\u62cd\u55dd",
        "diaper_ambiguous": "\u5c0f\u5c0f\u5f00\u59cb\u6362\u5c3f\u5e03\u7136\u540e\u5f00\u59cb\u62cd\u55dd",
        "diaper_no_wake": "\u5f00\u59cb\u6362\u5c3f\u5e03",
        "burping_wake": "\u5c0f\u5c0f",
        "burping_start": "\u5f00\u59cb\u62cd\u55dd",
        "burping_wake_complete": "\u5c0f\u5c0f",
        "burping_complete": "\u62cd\u55dd\u7ed3\u675f",
        "burping_cross_diaper": "\u5c0f\u5c0f\u5f00\u59cb\u6362\u5c3f\u5e03",
        "burping_ambiguous": "\u5c0f\u5c0f\u5f00\u59cb\u62cd\u55dd\u7136\u540e\u5f00\u59cb\u6362\u5c3f\u5e03",
        "burping_no_wake": "\u5f00\u59cb\u62cd\u55dd",
    }
    values = {
        step_id: _pcm(4_000 + index)
        for index, step_id in enumerate(text_by_step)
    }
    mapping = {
        values[step_id]: text for step_id, text in text_by_step.items()
    }
    return values, lambda: _FixtureAsr(mapping)


def _pcm(amplitude: int) -> bytes:
    return amplitude.to_bytes(2, "little", signed=True) * 3_200


class _FixtureAsr:
    def __init__(self, mapping: dict[bytes, str]) -> None:
        self._mapping = mapping

    def transcribe(self, pcm: bytes) -> AsrResult:
        return AsrResult(self._mapping[pcm], "zh", 1)


class _RecordingSynthesizer:
    def __init__(self) -> None:
        self.codes: list[str] = []

    def speak_code(self, code: str, _cancelled: threading.Event) -> bool:
        self.codes.append(code)
        return True


def _build_model_backend_quietly():
    previous_disable = logging.root.manager.disable
    try:
        logging.disable(logging.CRITICAL)
        with Path(os.devnull).open("w", encoding="ascii") as sink:
            with redirect_stdout(sink), redirect_stderr(sink):
                return build_realtime_model_backend(MODEL_ROOT)
    finally:
        logging.disable(previous_disable)


def _emit(**values: object) -> None:
    for key, value in values.items():
        if isinstance(value, bool):
            rendered = "true" if value else "false"
        else:
            rendered = str(value)
        print(f"{key}={rendered}")


if __name__ == "__main__":
    raise SystemExit(main())
