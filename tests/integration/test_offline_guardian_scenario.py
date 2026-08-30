from __future__ import annotations

import json
import stat
import subprocess
import signal
import threading
import time
from pathlib import Path

import pytest

from packages.contracts.offline_guardian_scenario import (
    OfflineGuardianScenarioV1,
    OfflineScenarioResultV1,
    OfflineScenarioRunV1,
    ScenarioLaneResult,
    VoiceScenarioStepV1,
    canonical_offline_run_bytes,
    load_offline_scenario_suite,
)
from packages.contracts.visual_corpus import ReplayResult, ReviewState, SourceType
from packages.contracts.vision import (
    RealtimeCandidateKind,
    RealtimeCandidateTransitionKind,
)
from services.vision.corpus_manifest import load_manifest
from services.vision.realtime_models import RealtimeModelError, RealtimeModelSignals
from services.voice.asr import AsrResult
from services.voice.vad import VoiceActivityDetector


FIXTURE = (
    Path(__file__).parents[1]
    / "fixtures/offline_guardian_scenarios/scenarios.v1.json"
)
VISUAL_MANIFEST = Path(__file__).parents[1] / "fixtures/visual_corpus/manifest.json"


def scenario(identifier: str) -> OfflineGuardianScenarioV1:
    suite = load_offline_scenario_suite(FIXTURE)
    return next(item for item in suite.scenarios if item.scenario_id == identifier)


def private_root(tmp_path: Path) -> Path:
    root = tmp_path / "scenario"
    root.mkdir(mode=0o700)
    return root


@pytest.mark.parametrize(
    ("identifier", "expected"),
    [
        (
            "SAFE-SLEEP-01",
            {
                "dashboard.event": 0,
                "dashboard.open": 0,
            },
        ),
        (
            "FACE-OCCLUSION-01",
            {
                "transition.watch_started.face_not_visible": 1,
                "transition.alert_opened.face_not_visible": 1,
                "transition.recovered.face_not_visible": 1,
                "event.face_not_visible.recovered": 1,
                "dashboard.event": 1,
                "dashboard.open": 0,
            },
        ),
        (
            "ADULT-INTERVENTION-01",
            {
                "transition.watch_started.face_not_visible": 1,
                "transition.alert_opened.face_not_visible": 1,
                "transition.adult_intervention.none": 1,
                "event.face_not_visible.open": 1,
                "dashboard.event": 1,
                "dashboard.open": 1,
            },
        ),
        (
            "PRONE-CANDIDATE-01",
            {
                "transition.watch_started.prone_candidate": 1,
                "transition.alert_opened.prone_candidate": 1,
                "transition.recovered.prone_candidate": 1,
                "event.prone_candidate.recovered": 1,
                "dashboard.event": 1,
                "dashboard.open": 0,
            },
        ),
        (
            "OUTSIDE-CANDIDATE-01",
            {
                "transition.watch_started.outside_candidate": 1,
                "transition.alert_opened.outside_candidate": 1,
                "transition.recovered.outside_candidate": 1,
                "event.outside_candidate.recovered": 1,
                "dashboard.event": 1,
                "dashboard.open": 0,
            },
        ),
    ],
)
def test_guardian_lane_runs_current_rules_and_dashboard_projection(
    tmp_path: Path,
    identifier: str,
    expected: dict[str, int],
) -> None:
    from services.offline_guardian_scenario import run_guardian_lane

    root = private_root(tmp_path)
    result = run_guardian_lane(scenario(identifier), root)

    assert result.lane == "guardian_deterministic"
    assert result.status == "PASS"
    assert result.reason == "ok"
    assert result.counts == expected
    database = root / "guardian-events.sqlite3"
    assert database.is_file()
    assert stat.S_IMODE(database.stat().st_mode) == 0o600


def test_guardian_lane_rejects_existing_store_without_reading_it(
    tmp_path: Path,
) -> None:
    from services.offline_guardian_scenario import run_guardian_lane

    root = private_root(tmp_path)
    database = root / "guardian-events.sqlite3"
    database.write_bytes(b"private-existing-state")
    database.chmod(0o600)

    result = run_guardian_lane(scenario("SAFE-SLEEP-01"), root)

    assert result.status == "FAIL"
    assert result.reason == "guardian_store_not_empty"
    assert database.read_bytes() == b"private-existing-state"


def test_guardian_lane_rejects_symlink_runtime_root(tmp_path: Path) -> None:
    from services.offline_guardian_scenario import run_guardian_lane

    actual = private_root(tmp_path)
    linked = tmp_path / "linked"
    linked.symlink_to(actual, target_is_directory=True)

    result = run_guardian_lane(scenario("SAFE-SLEEP-01"), linked)

    assert result.status == "FAIL"
    assert result.reason == "offline_scenario_runtime_unsafe"
    assert list(actual.iterdir()) == []


def test_guardian_lane_reports_expectation_mismatch_without_changing_rules(
    tmp_path: Path,
) -> None:
    from services.offline_guardian_scenario import run_guardian_lane

    value = scenario("SAFE-SLEEP-01")
    guardian = value.guardian.model_copy(
        update={"dashboard_event_count": 1},
    )
    changed = value.model_copy(update={"guardian": guardian})

    result = run_guardian_lane(changed, private_root(tmp_path))

    assert result.status == "FAIL"
    assert result.reason == "scenario_guardian_mismatch"
    assert result.counts["dashboard.event"] == 0


def test_guardian_lane_requires_declared_independence(tmp_path: Path) -> None:
    from services.offline_guardian_scenario import run_guardian_lane

    value = scenario("PRONE-CANDIDATE-01")
    changed = value.model_copy(update={"visual_oracle_relationship": None})

    result = run_guardian_lane(changed, private_root(tmp_path))

    assert (result.status, result.reason) == (
        "FAIL",
        "offline_scenario_lane_relationship_invalid",
    )


class AvailableVisualBackend:
    def infer(self, _bgr: object) -> RealtimeModelSignals:
        return RealtimeModelSignals(
            face_boxes=((0.4, 0.3, 0.2, 0.2),),
            pose_centers=((0.5, 0.5),),
        )


class DegradedVisualBackend:
    def infer(self, _bgr: object) -> RealtimeModelSignals:
        raise RealtimeModelError("private model detail")


def generated_video(path: Path, *, duration_seconds: int = 2) -> None:
    completed = subprocess.run(
        (
            "ffmpeg",
            "-nostdin",
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            "-f",
            "lavfi",
            "-i",
            "testsrc=size=320x180:rate=10",
            "-t",
            str(duration_seconds),
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            "-an",
            "-f",
            "matroska",
            str(path),
        ),
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        timeout=15,
        check=False,
    )
    assert completed.returncode == 0
    path.chmod(0o600)


def generated_visual_media(tmp_path: Path) -> dict[str, Path]:
    ten_seconds = tmp_path / "ten-seconds.mkv"
    thirteen_seconds = tmp_path / "thirteen-seconds.mkv"
    twenty_seconds = tmp_path / "twenty-seconds.mkv"
    generated_video(ten_seconds, duration_seconds=10)
    generated_video(thirteen_seconds, duration_seconds=13)
    generated_video(twenty_seconds, duration_seconds=20)
    return {
        "DAY-01": thirteen_seconds,
        "OCC-02": ten_seconds,
        "NEG-03": ten_seconds,
        "DAY-03": twenty_seconds,
        "OCC-03": thirteen_seconds,
    }


def test_visual_lane_replays_real_file_through_current_worker(tmp_path: Path) -> None:
    from services.offline_guardian_scenario import run_visual_lane

    media = tmp_path / "public-fixture.mkv"
    generated_video(media, duration_seconds=13)

    result = run_visual_lane(
        scenario("SAFE-SLEEP-01"),
        load_manifest(VISUAL_MANIFEST),
        lambda _clip, _profile: media,
        tmp_path,
        AvailableVisualBackend(),
    )

    assert result.lane == "visual_observation"
    assert result.status == "PASS"
    assert result.reason == "ok"
    assert result.counts["frames.total"] == 65
    assert result.counts["frames.processed"] == 65
    assert result.counts["frames.skipped"] == 0
    assert result.counts["frames.dropped"] == 0
    assert result.counts["errors.decode"] == 0
    assert result.counts["errors.worker"] == 0
    assert result.counts["observation.pose_count.1"] == 65
    assert result.counts["observation.face_count.1"] == 65
    assert result.counts["candidate.watch_opened.significant_bed_motion"] == 1
    expected_candidate_keys = {
        f"candidate.{transition.value}.{candidate.value}"
        for transition in RealtimeCandidateTransitionKind
        for candidate in RealtimeCandidateKind
    }
    actual_candidate_counts = {
        key: value
        for key, value in result.counts.items()
        if key.startswith("candidate.")
    }
    assert set(actual_candidate_counts) == expected_candidate_keys
    assert all(
        value == 0
        for key, value in actual_candidate_counts.items()
        if key != "candidate.watch_opened.significant_bed_motion"
    )
    assert result.metrics_ms["pipeline.p95"] >= 0
    assert result.metrics_ms["model.p95"] >= 0
    assert not (tmp_path / "guardian-events.sqlite3").exists()
    assert not hasattr(result, "frame_observations")


def test_visual_lane_rejects_non_exact_frame_accounting(tmp_path: Path) -> None:
    from services.offline_guardian_scenario import run_visual_lane

    media = tmp_path / "public-fixture.mkv"
    generated_video(media, duration_seconds=13)
    value = scenario("SAFE-SLEEP-01")
    assert value.visual is not None
    changed = value.model_copy(
        update={
            "visual": value.visual.model_copy(
                update={"expected_frames_processed": 64}
            )
        }
    )

    result = run_visual_lane(
        changed,
        load_manifest(VISUAL_MANIFEST),
        lambda _clip, _profile: media,
        tmp_path,
        AvailableVisualBackend(),
    )

    assert (result.status, result.reason) == (
        "FAIL",
        "offline_scenario_visual_frame_mismatch",
    )
    assert result.counts["frames.total"] == 65
    assert result.counts["frames.processed"] == 65


def test_visual_lane_rejects_manifest_provenance_mismatch_before_media() -> None:
    from services.offline_guardian_scenario import run_visual_lane

    value = scenario("SAFE-SLEEP-01")
    assert value.visual is not None
    changed = value.model_copy(
        update={
            "visual": value.visual.model_copy(
                update={"provenance": "GENERATED_VISUAL"}
            )
        }
    )
    called: list[str] = []

    result = run_visual_lane(
        changed,
        load_manifest(VISUAL_MANIFEST),
        lambda _clip, _profile: called.append("resolver"),
        Path.cwd(),
        AvailableVisualBackend(),
    )

    assert (result.status, result.reason) == (
        "FAIL",
        "offline_scenario_visual_provenance_mismatch",
    )
    assert called == []


def test_visual_lane_rejects_unknown_clip_before_resolving_media() -> None:
    from services.offline_guardian_scenario import run_visual_lane

    value = scenario("SAFE-SLEEP-01")
    changed = value.model_copy(
        update={"visual": value.visual.model_copy(update={"clip_id": "DAY-99"})},
    )
    called: list[object] = []

    result = run_visual_lane(
        changed,
        load_manifest(VISUAL_MANIFEST),
        lambda *_args: called.append("resolver"),
        Path.cwd(),
        AvailableVisualBackend(),
    )

    assert result.status == "FAIL"
    assert result.reason == "offline_scenario_clip_missing"
    assert called == []


def test_suite_manifest_binding_validator_rejects_every_unsafe_provenance() -> None:
    from services.offline_guardian_scenario import validate_visual_scenario_bindings

    suite = load_offline_scenario_suite(FIXTURE)
    manifest = load_manifest(VISUAL_MANIFEST)
    by_id = {clip.clip_id: clip for clip in manifest.clips}

    def changed_scenario(identifier: str, **visual_updates: object):
        original = scenario(identifier)
        assert original.visual is not None
        replacement = original.model_copy(
            update={
                "visual": original.visual.model_copy(update=visual_updates),
            }
        )
        return suite.model_copy(
            update={
                "scenarios": tuple(
                    replacement if item.scenario_id == identifier else item
                    for item in suite.scenarios
                )
            }
        )

    def changed_manifest(*replacements):
        replacement_by_id = {clip.clip_id: clip for clip in replacements}
        return manifest.model_copy(
            update={
                "clips": tuple(
                    replacement_by_id.get(clip.clip_id, clip)
                    for clip in manifest.clips
                )
            }
        )

    invalid_cases = {
        "unknown scenario clip": (
            changed_scenario("SAFE-SLEEP-01", clip_id="DAY-99"),
            manifest,
        ),
        "public declared generated": (
            changed_scenario("SAFE-SLEEP-01", provenance="GENERATED_VISUAL"),
            manifest,
        ),
        "synthetic declared public": (
            changed_scenario("OUTSIDE-CANDIDATE-01", provenance="PUBLIC_VIDEO"),
            manifest,
        ),
        "duplicate clip id": (
            suite,
            manifest.model_copy(
                update={"clips": (*manifest.clips, by_id["DAY-01"])}
            ),
        ),
        "missing selected clip": (
            suite,
            manifest.model_copy(
                update={
                    "clips": tuple(
                        clip for clip in manifest.clips if clip.clip_id != "DAY-01"
                    )
                }
            ),
        ),
        "synthetic missing parent": (
            suite,
            changed_manifest(by_id["OCC-03"].model_copy(update={"parent_clip_id": None})),
        ),
        "synthetic parent is synthetic": (
            suite,
            changed_manifest(
                by_id["OCC-03"].model_copy(update={"parent_clip_id": "OCC-02"})
            ),
        ),
        "synthetic parent source mismatch": (
            suite,
            changed_manifest(
                by_id["OCC-03"].model_copy(
                    update={"source_id": by_id["NEG-03"].source_id}
                )
            ),
        ),
        "synthetic parent unreviewed": (
            suite,
            changed_manifest(
                by_id["DAY-01"].model_copy(update={"review_state": ReviewState.UNREVIEWED})
            ),
        ),
        "synthetic parent has deeper ancestry": (
            suite,
            changed_manifest(
                by_id["DAY-01"].model_copy(update={"parent_clip_id": "DAY-02"})
            ),
        ),
        "synthetic ancestry cycle": (
            suite,
            changed_manifest(
                by_id["DAY-01"].model_copy(
                    update={
                        "source_type": SourceType.SYNTHETIC,
                        "parent_clip_id": "OCC-03",
                    }
                ),
                by_id["OCC-03"].model_copy(update={"parent_clip_id": "DAY-01"}),
            ),
        ),
        "private local source type": (
            suite,
            changed_manifest(
                by_id["DAY-01"].model_copy(update={"source_type": SourceType.REAL})
            ),
        ),
        "public clip has parent": (
            suite,
            changed_manifest(
                by_id["DAY-01"].model_copy(update={"parent_clip_id": "DAY-02"})
            ),
        ),
    }

    for name, (changed_suite, changed_manifest_value) in invalid_cases.items():
        with pytest.raises(
            ValueError,
            match="^offline_scenario_visual_provenance_invalid$",
        ):
            validate_visual_scenario_bindings(changed_suite, changed_manifest_value)

    selected = validate_visual_scenario_bindings(suite, manifest)
    assert tuple(clip.clip_id for clip in selected) == (
        "DAY-01",
        "OCC-02",
        "NEG-03",
        "DAY-03",
        "OCC-03",
    )


def test_runner_rejects_invalid_visual_binding_before_runtime_root(tmp_path: Path) -> None:
    from services.offline_guardian_scenario import OfflineGuardianScenarioRunner

    value = scenario("SAFE-SLEEP-01")
    assert value.visual is not None
    visual_only = value.model_copy(
        update={
            "required_lanes": ("visual_observation",),
            "visual": value.visual.model_copy(update={"provenance": "GENERATED_VISUAL"}),
            "guardian": None,
            "visual_oracle_relationship": None,
        }
    )
    suite = load_offline_scenario_suite(FIXTURE).model_copy(
        update={"scenarios": (visual_only,)}
    )
    fixtures, asr = voice_fixtures()
    runtime_root = tmp_path / "scenario-run"
    runner = OfflineGuardianScenarioRunner(
        runtime_root=runtime_root,
        runtime_boundary=tmp_path,
        visual_manifest=load_manifest(VISUAL_MANIFEST),
        prepared_resolver=lambda *_args: tmp_path / "unused.mkv",
        prepared_root=tmp_path,
        model_backend=AvailableVisualBackend(),
        voice_fixture_provider=fixtures.__getitem__,
        voice_vad_factory=speech_vad,
        voice_asr_factory=lambda: ScenarioAsr(asr.mapping),
        voice_synthesizer_factory=RecordingScenarioSynth,
    )

    with pytest.raises(
        ValueError,
        match="^offline_scenario_visual_provenance_invalid$",
    ):
        runner.run(suite)

    assert not runtime_root.exists()


@pytest.mark.parametrize(
    ("backend", "reason"),
    [
        (None, "visual_corpus_model_unavailable"),
        (DegradedVisualBackend(), "visual_corpus_model_degraded"),
    ],
)
def test_visual_lane_fails_closed_for_required_model_state(
    tmp_path: Path,
    backend: object | None,
    reason: str,
) -> None:
    from services.offline_guardian_scenario import run_visual_lane

    media = tmp_path / "public-fixture.mkv"
    generated_video(media)

    result = run_visual_lane(
        scenario("SAFE-SLEEP-01"),
        load_manifest(VISUAL_MANIFEST),
        lambda _clip, _profile: media,
        tmp_path,
        backend,
    )

    assert result.status == "FAIL"
    assert result.reason == reason


def test_visual_lane_reports_missing_prepared_artifact_without_path(
    tmp_path: Path,
) -> None:
    from services.offline_guardian_scenario import run_visual_lane

    result = run_visual_lane(
        scenario("SAFE-SLEEP-01"),
        load_manifest(VISUAL_MANIFEST),
        lambda _clip, _profile: tmp_path / "private-household-name.mkv",
        tmp_path,
        AvailableVisualBackend(),
    )

    assert result.status == "FAIL"
    assert result.reason == "visual_corpus_input_invalid"
    assert "private-household-name" not in repr(result)


def replay_aggregate(
    *,
    candidate_counts: dict[str, int] | None = None,
    observation_counts: dict[str, int] | None = None,
) -> ReplayResult:
    return ReplayResult(
        clip_id="DAY-01",
        status="PASS",
        reason="ok",
        frames_total=65,
        frames_processed=65,
        frames_skipped=0,
        decode_errors=0,
        worker_errors=0,
        model_state="available",
        observation_counts=observation_counts or {},
        candidate_counts=candidate_counts or {},
        processing_p50_ms=0,
        processing_p95_ms=0,
        processing_max_ms=0,
        pipeline_p50_ms=0,
        pipeline_p95_ms=0,
        pipeline_max_ms=0,
        dropped_frames=0,
        queue_backlog_max=0,
    )


def stub_visual_replay(monkeypatch: pytest.MonkeyPatch, aggregate: ReplayResult) -> None:
    import services.offline_guardian_scenario as module

    class StubVisualCorpusReplay:
        def __init__(self, **_kwargs: object) -> None:
            pass

        def run_clip(self, *_args: object, **_kwargs: object) -> ReplayResult:
            return aggregate

    monkeypatch.setattr(module, "VisualCorpusReplay", StubVisualCorpusReplay)


def test_visual_lane_emits_fixed_candidate_cartesian_zeros(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from services.offline_guardian_scenario import run_visual_lane

    stub_visual_replay(monkeypatch, replay_aggregate())
    result = run_visual_lane(
        scenario("SAFE-SLEEP-01"),
        load_manifest(VISUAL_MANIFEST),
        lambda *_args: tmp_path / "unused.mkv",
        tmp_path,
        AvailableVisualBackend(),
    )
    expected = {
        f"candidate.{transition.value}.{candidate.value}"
        for transition in RealtimeCandidateTransitionKind
        for candidate in RealtimeCandidateKind
    }

    assert result.status == "PASS"
    assert {
        key for key in result.counts if key.startswith("candidate.")
    } == expected
    assert all(result.counts[key] == 0 for key in expected)


def test_visual_lane_rejects_unexpected_candidate_key(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from services.offline_guardian_scenario import run_visual_lane

    stub_visual_replay(
        monkeypatch,
        replay_aggregate(candidate_counts={"watch_opened.private_candidate": 1}),
    )
    result = run_visual_lane(
        scenario("SAFE-SLEEP-01"),
        load_manifest(VISUAL_MANIFEST),
        lambda *_args: tmp_path / "unused.mkv",
        tmp_path,
        AvailableVisualBackend(),
    )

    assert (result.status, result.reason) == (
        "FAIL",
        "offline_scenario_visual_aggregate_invalid",
    )


def test_visual_lane_rejects_bounded_count_overflow(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from services.offline_guardian_scenario import run_visual_lane

    stub_visual_replay(
        monkeypatch,
        replay_aggregate(
            observation_counts={f"signal_{index}": 1 for index in range(47)}
        ),
    )
    result = run_visual_lane(
        scenario("SAFE-SLEEP-01"),
        load_manifest(VISUAL_MANIFEST),
        lambda *_args: tmp_path / "unused.mkv",
        tmp_path,
        AvailableVisualBackend(),
    )

    assert (result.status, result.reason) == (
        "FAIL",
        "offline_scenario_visual_aggregate_overflow",
    )


def test_visual_lane_rejects_prepared_media_below_symlink_ancestor(
    tmp_path: Path,
) -> None:
    from services.offline_guardian_scenario import run_visual_lane

    actual = tmp_path / "actual"
    nested = actual / "prepared"
    nested.mkdir(mode=0o700, parents=True)
    actual.chmod(0o700)
    media = nested / "fixture.mkv"
    generated_video(media)
    linked = tmp_path / "linked"
    linked.symlink_to(actual, target_is_directory=True)

    result = run_visual_lane(
        scenario("SAFE-SLEEP-01"),
        load_manifest(VISUAL_MANIFEST),
        lambda _clip, _profile: linked / "prepared/fixture.mkv",
        linked / "prepared",
        AvailableVisualBackend(),
    )

    assert result.status == "FAIL"
    assert result.reason == "visual_corpus_input_invalid"


def generated_pcm(amplitude: int) -> bytes:
    return int(amplitude).to_bytes(2, "little", signed=True) * 3_200


class ScenarioAsr:
    def __init__(self, mapping: dict[bytes, str | Exception]) -> None:
        self.mapping = mapping

    def transcribe(self, pcm: bytes) -> AsrResult:
        value = self.mapping[pcm]
        if isinstance(value, Exception):
            raise value
        return AsrResult(value, "zh", 1)


class RecordingScenarioSynth:
    def __init__(self, *, succeed: bool = True) -> None:
        self.succeed = succeed
        self.codes: list[str] = []

    def speak_code(self, code: str, _cancelled: threading.Event) -> bool:
        self.codes.append(code)
        return self.succeed


def voice_fixtures() -> tuple[dict[str, bytes], ScenarioAsr]:
    text_by_step = {
        "wake": "小小",
        "feeding": "我是爸爸，开始喂奶",
        "no_wake": "今天天气如何",
        "unsupported": "播放音乐",
        "diaper_wake": "小小",
        "diaper_start": "开始换尿布",
        "diaper_wake_complete": "小小",
        "diaper_complete": "换好尿布了",
        "diaper_cross_burping": "小小开始拍嗝",
        "diaper_ambiguous": "小小开始换尿布然后开始拍嗝",
        "diaper_no_wake": "开始换尿布",
        "burping_wake": "小小",
        "burping_start": "开始拍嗝",
        "burping_wake_complete": "小小",
        "burping_complete": "拍嗝结束",
        "burping_cross_diaper": "小小开始换尿布",
        "burping_ambiguous": "小小开始拍嗝然后开始换尿布",
        "burping_no_wake": "开始拍嗝",
    }
    pcm = {
        step_id: generated_pcm(4_000 + index)
        for index, step_id in enumerate(text_by_step)
    }
    return pcm, ScenarioAsr(
        {pcm[step_id]: text for step_id, text in text_by_step.items()}
    )


def speech_vad() -> VoiceActivityDetector:
    return VoiceActivityDetector(lambda waveform: 0.9 if waveform.any() else 0.0)


def test_voice_lane_runs_generated_pcm_vad_and_current_controller() -> None:
    from services.offline_guardian_scenario import run_voice_lane

    fixtures, asr = voice_fixtures()
    synth = RecordingScenarioSynth()

    result = run_voice_lane(
        scenario("VOICE-FEEDING-01"),
        fixtures.__getitem__,
        speech_vad(),
        asr,
        synth,
    )

    assert result.lane == "voice_generated"
    assert result.status == "PASS"
    assert result.reason == "ok"
    assert result.counts == {
        "action.feeding_command": 1,
        "action.diaper_change_start": 0,
        "action.diaper_change_complete": 0,
        "action.burping_start": 0,
        "action.burping_complete": 0,
        "steps.total": 4,
        "vad.speech": 4,
        "responses.total": 2,
        "outcome.listen_only_acknowledged": 1,
        "outcome.listen_only_armed": 1,
        "outcome.listen_only_ignored": 2,
    }
    assert synth.codes == ["listen_only_ready", "listen_only_received"]
    assert "pcm" not in repr(result).lower()
    assert "transcript" not in repr(result).lower()


@pytest.mark.parametrize(
    ("identifier", "expected_actions"),
    [
        (
            "VOICE-DIAPER-01",
            {
                "action.feeding_command": 0,
                "action.diaper_change_start": 1,
                "action.diaper_change_complete": 1,
                "action.burping_start": 1,
                "action.burping_complete": 0,
            },
        ),
        (
            "VOICE-BURPING-01",
            {
                "action.feeding_command": 0,
                "action.burping_start": 1,
                "action.burping_complete": 1,
                "action.diaper_change_start": 1,
                "action.diaper_change_complete": 0,
            },
        ),
    ],
)
def test_voice_lane_counts_target_and_cross_action_exactly(
    identifier: str,
    expected_actions: dict[str, int],
) -> None:
    from services.offline_guardian_scenario import run_voice_lane

    fixtures, asr = voice_fixtures()
    synth = RecordingScenarioSynth()

    result = run_voice_lane(
        scenario(identifier),
        fixtures.__getitem__,
        speech_vad(),
        asr,
        synth,
    )

    assert result.status == "PASS"
    assert result.reason == "ok"
    assert result.counts["steps.total"] == 7
    assert result.counts["responses.total"] == 5
    assert {
        key: value for key, value in result.counts.items() if key.startswith("action.")
    } == expected_actions
    assert synth.codes == [
        "listen_only_ready",
        "listen_only_received",
        "listen_only_ready",
        "listen_only_received",
        "listen_only_received",
    ]


def test_voice_lane_emits_five_zero_action_keys_for_closed_controls() -> None:
    from services.offline_guardian_scenario import run_voice_lane

    base = scenario("VOICE-FEEDING-01")
    assert base.voice is not None
    steps = (
        VoiceScenarioStepV1(
            step_id="question",
            speech_expected=True,
            expected_reason="listen_only_ignored",
            expected_response_code=None,
            expected_action_code=None,
            expected_match_kind=None,
        ),
        VoiceScenarioStepV1(
            step_id="unsupported_control",
            speech_expected=True,
            expected_reason="listen_only_ignored",
            expected_response_code=None,
            expected_action_code=None,
            expected_match_kind=None,
        ),
        VoiceScenarioStepV1(
            step_id="medication_control",
            speech_expected=True,
            expected_reason="listen_only_high_risk_candidate",
            expected_response_code=None,
            expected_action_code="medication_start_candidate",
            expected_match_kind="high_risk_candidate",
        ),
    )
    changed = base.model_copy(
        update={
            "voice": base.voice.model_copy(
                update={"steps": steps, "expected_response_count": 0}
            )
        }
    )
    texts = {
        "question": "小小开始换尿布吗",
        "unsupported_control": "小小播放音乐",
        "medication_control": "小小开始喂药",
    }
    fixtures = {
        step_id: generated_pcm(7_000 + index)
        for index, step_id in enumerate(texts)
    }
    asr = ScenarioAsr({fixtures[key]: value for key, value in texts.items()})

    result = run_voice_lane(
        changed,
        fixtures.__getitem__,
        speech_vad(),
        asr,
        RecordingScenarioSynth(),
    )

    assert result.status == "PASS"
    assert {
        key: value for key, value in result.counts.items() if key.startswith("action.")
    } == {
        "action.feeding_command": 0,
        "action.diaper_change_start": 0,
        "action.diaper_change_complete": 0,
        "action.burping_start": 0,
        "action.burping_complete": 0,
    }


def test_voice_lane_rejects_right_response_with_wrong_action() -> None:
    from services.offline_guardian_scenario import run_voice_lane

    value = scenario("VOICE-FEEDING-01")
    assert value.voice is not None
    steps = list(value.voice.steps)
    steps[1] = steps[1].model_copy(update={"expected_action_code": "burping_start"})
    changed = value.model_copy(
        update={"voice": value.voice.model_copy(update={"steps": tuple(steps)})}
    )
    fixtures, asr = voice_fixtures()

    result = run_voice_lane(
        changed,
        fixtures.__getitem__,
        speech_vad(),
        asr,
        RecordingScenarioSynth(),
    )

    assert (result.status, result.reason) == ("FAIL", "scenario_voice_mismatch")


def test_voice_lane_rejects_empty_pcm_before_asr() -> None:
    from services.offline_guardian_scenario import run_voice_lane

    fixtures, asr = voice_fixtures()
    fixtures["wake"] = b""

    result = run_voice_lane(
        scenario("VOICE-FEEDING-01"),
        fixtures.__getitem__,
        speech_vad(),
        asr,
        RecordingScenarioSynth(),
    )

    assert result.status == "FAIL"
    assert result.reason == "offline_scenario_voice_fixture_invalid"


def test_voice_lane_propagates_model_and_output_failure_codes() -> None:
    from services.offline_guardian_scenario import run_voice_lane

    fixtures, _asr = voice_fixtures()
    failed_asr = ScenarioAsr(
        {value: RuntimeError("private model detail") for value in fixtures.values()}
    )
    model_result = run_voice_lane(
        scenario("VOICE-FEEDING-01"),
        fixtures.__getitem__,
        speech_vad(),
        failed_asr,
        RecordingScenarioSynth(),
    )
    output_result = run_voice_lane(
        scenario("VOICE-FEEDING-01"),
        fixtures.__getitem__,
        speech_vad(),
        voice_fixtures()[1],
        RecordingScenarioSynth(succeed=False),
    )

    assert (model_result.status, model_result.reason) == (
        "FAIL",
        "voice_model_unavailable",
    )
    assert (output_result.status, output_result.reason) == (
        "FAIL",
        "voice_output_unavailable",
    )


def test_voice_lane_fails_closed_when_expectation_changes() -> None:
    from services.offline_guardian_scenario import run_voice_lane

    value = scenario("VOICE-FEEDING-01")
    voice = value.voice.model_copy(update={"expected_response_count": 3})
    changed = value.model_copy(update={"voice": voice})
    fixtures, asr = voice_fixtures()

    result = run_voice_lane(
        changed,
        fixtures.__getitem__,
        speech_vad(),
        asr,
        RecordingScenarioSynth(),
    )

    assert result.status == "FAIL"
    assert result.reason == "scenario_voice_mismatch"


def build_runner(
    tmp_path: Path,
    media: Path | dict[str, Path],
    *,
    backend: object | None = None,
    timeout_seconds: float = 180.0,
):
    from services.offline_guardian_scenario import OfflineGuardianScenarioRunner

    fixtures, asr = voice_fixtures()
    prepared_root = (
        next(iter(media.values())).parent if isinstance(media, dict) else media.parent
    )
    return OfflineGuardianScenarioRunner(
        runtime_root=tmp_path / "scenario-run",
        runtime_boundary=tmp_path,
        visual_manifest=load_manifest(VISUAL_MANIFEST),
        prepared_resolver=(
            (lambda clip, _profile: media[clip.clip_id])
            if isinstance(media, dict)
            else (lambda _clip, _profile: media)
        ),
        prepared_root=prepared_root,
        model_backend=backend if backend is not None else AvailableVisualBackend(),
        voice_fixture_provider=fixtures.__getitem__,
        voice_vad_factory=speech_vad,
        voice_asr_factory=lambda: ScenarioAsr(asr.mapping),
        voice_synthesizer_factory=RecordingScenarioSynth,
        timeout_seconds=timeout_seconds,
    )


def test_runner_executes_all_required_lanes_in_declared_order(tmp_path: Path) -> None:
    media = generated_visual_media(tmp_path)
    suite = load_offline_scenario_suite(FIXTURE)

    result = build_runner(tmp_path, media).run(suite)

    assert result.status == "PASS"
    assert result.reason == "ok"
    assert [item.scenario_id for item in result.results] == [
        item.scenario_id for item in suite.scenarios
    ]
    assert [[lane.lane for lane in item.lanes] for item in result.results] == [
        list(item.required_lanes) for item in suite.scenarios
    ]
    assert all(item.status == "PASS" for item in result.results)
    assert len(result.results) == 8
    assert sum(len(item.lanes) for item in result.results) == 13
    assert [
        item.visual_oracle_relationship for item in result.results
    ] == [
        "INDEPENDENT",
        "INDEPENDENT",
        "INDEPENDENT",
        None,
        "INDEPENDENT",
        "INDEPENDENT",
        None,
        None,
    ]
    assert result.production_state_touched is False
    assert result.notification_dispatch_attempted is False
    assert result.evidence_persisted is False
    assert result.camera_opened is False
    assert result.raw_audio_persisted is False
    assert result.baby_care_called is False
    root = tmp_path / "scenario-run"
    assert stat.S_IMODE(root.stat().st_mode) == 0o700
    assert {item.name for item in root.iterdir()} == {
        item.scenario_id for item in suite.scenarios
    }
    assert all(stat.S_IMODE(item.stat().st_mode) == 0o700 for item in root.iterdir())


def test_runner_retains_first_failure_and_does_not_retry_lane(tmp_path: Path) -> None:
    from services.offline_guardian_scenario import OfflineGuardianScenarioRunner

    media = tmp_path / "public-fixture.mkv"
    generated_video(media)
    suite = load_offline_scenario_suite(FIXTURE)
    fixtures, asr = voice_fixtures()
    resolved: list[str] = []
    runner = OfflineGuardianScenarioRunner(
        runtime_root=tmp_path / "scenario-run",
        runtime_boundary=tmp_path,
        visual_manifest=load_manifest(VISUAL_MANIFEST),
        prepared_resolver=lambda clip, _profile: (resolved.append(clip.clip_id), media)[1],
        prepared_root=media.parent,
        model_backend=None,
        voice_fixture_provider=fixtures.__getitem__,
        voice_vad_factory=speech_vad,
        voice_asr_factory=lambda: ScenarioAsr(asr.mapping),
        voice_synthesizer_factory=RecordingScenarioSynth,
    )

    result = runner.run(suite)

    assert result.status == "FAIL"
    assert result.reason == "visual_corpus_model_unavailable"
    assert resolved == []
    assert [item.status for item in result.results] == [
        "FAIL",
        "FAIL",
        "FAIL",
        "PASS",
        "FAIL",
        "FAIL",
        "PASS",
        "PASS",
    ]


@pytest.mark.parametrize("kind", ["directory", "symlink"])
def test_runner_rejects_preexisting_runtime_root(tmp_path: Path, kind: str) -> None:
    media = tmp_path / "public-fixture.mkv"
    generated_video(media)
    root = tmp_path / "scenario-run"
    if kind == "directory":
        root.mkdir(mode=0o700)
        (root / "unknown").write_text("private", encoding="utf-8")
    else:
        actual = tmp_path / "actual"
        actual.mkdir(mode=0o700)
        root.symlink_to(actual, target_is_directory=True)

    with pytest.raises(ValueError, match="^offline_scenario_runtime_unsafe$"):
        build_runner(tmp_path, media).run(load_offline_scenario_suite(FIXTURE))


def test_runner_rejects_runtime_root_below_symlink_ancestor(tmp_path: Path) -> None:
    media = tmp_path / "public-fixture.mkv"
    generated_video(media)
    actual = tmp_path / "actual"
    nested = actual / "nested"
    nested.mkdir(mode=0o700, parents=True)
    actual.chmod(0o700)
    linked = tmp_path / "linked"
    linked.symlink_to(actual, target_is_directory=True)

    with pytest.raises(ValueError, match="^offline_scenario_runtime_unsafe$"):
        build_runner(linked / "nested", media).run(
            load_offline_scenario_suite(FIXTURE)
        )


def test_runner_does_not_turn_interruption_into_result(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import services.offline_guardian_scenario as module

    media = tmp_path / "public-fixture.mkv"
    generated_video(media)
    monkeypatch.setattr(
        module,
        "run_visual_lane",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(KeyboardInterrupt()),
    )

    with pytest.raises(KeyboardInterrupt):
        build_runner(tmp_path, media).run(load_offline_scenario_suite(FIXTURE))


def test_runner_deadline_interrupts_blocking_lane(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import services.offline_guardian_scenario as module

    media = tmp_path / "public-fixture.mkv"
    generated_video(media)
    monkeypatch.setattr(module, "run_visual_lane", lambda *_args: time.sleep(1))

    with pytest.raises(module.OfflineScenarioTimeout):
        build_runner(tmp_path, media, timeout_seconds=0.01).run(
            load_offline_scenario_suite(FIXTURE)
        )


def test_runner_rejects_an_external_alarm_without_replacing_it(
    tmp_path: Path,
) -> None:
    import services.offline_guardian_scenario as module

    media = tmp_path / "public-fixture.mkv"
    generated_video(media)
    previous_handler = signal.getsignal(signal.SIGALRM)

    def external_handler(_signum: int, _frame: object) -> None:
        return None

    signal.signal(signal.SIGALRM, external_handler)
    signal.setitimer(signal.ITIMER_REAL, 5.0)
    try:
        with pytest.raises(ValueError, match="^offline_scenario_runtime_unsafe$"):
            build_runner(tmp_path, media).run(
                load_offline_scenario_suite(FIXTURE)
            )
        assert signal.getsignal(signal.SIGALRM) is external_handler
        assert signal.getitimer(signal.ITIMER_REAL)[0] > 0
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
        signal.signal(signal.SIGALRM, previous_handler)


def test_runner_builds_and_closes_fresh_voice_components(tmp_path: Path) -> None:
    from services.offline_guardian_scenario import OfflineGuardianScenarioRunner

    media = tmp_path / "public-fixture.mkv"
    generated_video(media)
    suite = load_offline_scenario_suite(FIXTURE)
    voice_only = suite.model_copy(update={"scenarios": (suite.scenarios[-1],)})
    fixtures, asr = voice_fixtures()
    closed: list[str] = []

    class ClosingVad(VoiceActivityDetector):
        def close(self) -> None:
            closed.append("vad")

    class ClosingAsr(ScenarioAsr):
        def close(self) -> None:
            closed.append("asr")

    class ClosingSynth(RecordingScenarioSynth):
        def close(self) -> None:
            closed.append("synth")

    runner = OfflineGuardianScenarioRunner(
        runtime_root=tmp_path / "scenario-run",
        runtime_boundary=tmp_path,
        visual_manifest=load_manifest(VISUAL_MANIFEST),
        prepared_resolver=lambda _clip, _profile: media,
        prepared_root=tmp_path,
        model_backend=AvailableVisualBackend(),
        voice_fixture_provider=fixtures.__getitem__,
        voice_vad_factory=lambda: ClosingVad(
            lambda waveform: 0.9 if waveform.any() else 0.0
        ),
        voice_asr_factory=lambda: ClosingAsr(asr.mapping),
        voice_synthesizer_factory=ClosingSynth,
    )

    result = runner.run(voice_only)

    assert result.status == "PASS"
    assert closed == ["synth", "asr", "vad"]


def test_runner_closes_created_voice_components_when_factory_fails(
    tmp_path: Path,
) -> None:
    from services.offline_guardian_scenario import OfflineGuardianScenarioRunner

    media = tmp_path / "public-fixture.mkv"
    generated_video(media)
    suite = load_offline_scenario_suite(FIXTURE)
    voice_only = suite.model_copy(update={"scenarios": (suite.scenarios[-1],)})
    fixtures, _asr = voice_fixtures()
    closed: list[str] = []

    class ClosingVad(VoiceActivityDetector):
        def close(self) -> None:
            closed.append("vad")

    def failing_asr_factory():
        raise RuntimeError("private factory failure")

    runner = OfflineGuardianScenarioRunner(
        runtime_root=tmp_path / "scenario-run",
        runtime_boundary=tmp_path,
        visual_manifest=load_manifest(VISUAL_MANIFEST),
        prepared_resolver=lambda _clip, _profile: media,
        prepared_root=tmp_path,
        model_backend=AvailableVisualBackend(),
        voice_fixture_provider=fixtures.__getitem__,
        voice_vad_factory=lambda: ClosingVad(
            lambda waveform: 0.9 if waveform.any() else 0.0
        ),
        voice_asr_factory=failing_asr_factory,
        voice_synthesizer_factory=RecordingScenarioSynth,
    )

    with pytest.raises(RuntimeError, match="private factory failure"):
        runner.run(voice_only)

    assert closed == ["vad"]


def test_runner_fails_when_voice_component_close_fails(tmp_path: Path) -> None:
    from services.offline_guardian_scenario import OfflineGuardianScenarioRunner

    media = tmp_path / "public-fixture.mkv"
    generated_video(media)
    suite = load_offline_scenario_suite(FIXTURE)
    voice_only = suite.model_copy(update={"scenarios": (suite.scenarios[-1],)})
    fixtures, asr = voice_fixtures()

    class FailingSynth(RecordingScenarioSynth):
        def close(self) -> None:
            raise RuntimeError("private close failure")

    runner = OfflineGuardianScenarioRunner(
        runtime_root=tmp_path / "scenario-run",
        runtime_boundary=tmp_path,
        visual_manifest=load_manifest(VISUAL_MANIFEST),
        prepared_resolver=lambda _clip, _profile: media,
        prepared_root=tmp_path,
        model_backend=AvailableVisualBackend(),
        voice_fixture_provider=fixtures.__getitem__,
        voice_vad_factory=speech_vad,
        voice_asr_factory=lambda: ScenarioAsr(asr.mapping),
        voice_synthesizer_factory=FailingSynth,
    )

    result = runner.run(voice_only)

    assert result.status == "FAIL"
    assert result.reason == "offline_scenario_voice_cleanup_failed"


def test_runner_preserves_voice_mismatch_when_cleanup_also_fails(tmp_path: Path) -> None:
    from services.offline_guardian_scenario import OfflineGuardianScenarioRunner

    suite = load_offline_scenario_suite(FIXTURE)
    value = suite.scenarios[-1]
    assert value.voice is not None
    steps = list(value.voice.steps)
    steps[0] = steps[0].model_copy(update={"expected_reason": "listen_only_ignored"})
    changed = value.model_copy(
        update={"voice": value.voice.model_copy(update={"steps": tuple(steps)})}
    )
    voice_only = suite.model_copy(update={"scenarios": (changed,)})
    fixtures, asr = voice_fixtures()

    class FailingSynth(RecordingScenarioSynth):
        def close(self) -> None:
            raise RuntimeError("private close failure")

    runner = OfflineGuardianScenarioRunner(
        runtime_root=tmp_path / "scenario-run",
        runtime_boundary=tmp_path,
        visual_manifest=load_manifest(VISUAL_MANIFEST),
        prepared_resolver=lambda *_args: tmp_path / "unused.mkv",
        prepared_root=tmp_path,
        model_backend=AvailableVisualBackend(),
        voice_fixture_provider=fixtures.__getitem__,
        voice_vad_factory=speech_vad,
        voice_asr_factory=lambda: ScenarioAsr(asr.mapping),
        voice_synthesizer_factory=FailingSynth,
    )

    result = runner.run(voice_only)

    assert result.status == "FAIL"
    assert result.reason == "scenario_voice_mismatch"
    assert result.results[0].reason == "scenario_voice_mismatch"


def test_runner_timeout_keeps_voice_cleanup_bounded(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import services.offline_guardian_scenario as module

    media = tmp_path / "public-fixture.mkv"
    generated_video(media)
    suite = load_offline_scenario_suite(FIXTURE)
    voice_only = suite.model_copy(update={"scenarios": (suite.scenarios[-1],)})
    fixtures, asr = voice_fixtures()

    class BlockingSynth(RecordingScenarioSynth):
        def close(self) -> None:
            time.sleep(1)

    monkeypatch.setattr(module, "SETTLEMENT_TIMEOUT_SECONDS", 0.02)
    monkeypatch.setattr(module, "run_voice_lane", lambda *_args: time.sleep(1))
    runner = module.OfflineGuardianScenarioRunner(
        runtime_root=tmp_path / "scenario-run",
        runtime_boundary=tmp_path,
        visual_manifest=load_manifest(VISUAL_MANIFEST),
        prepared_resolver=lambda _clip, _profile: media,
        prepared_root=tmp_path,
        model_backend=AvailableVisualBackend(),
        voice_fixture_provider=fixtures.__getitem__,
        voice_vad_factory=speech_vad,
        voice_asr_factory=lambda: ScenarioAsr(asr.mapping),
        voice_synthesizer_factory=BlockingSynth,
        timeout_seconds=0.01,
    )

    started = time.monotonic()
    with pytest.raises(module.OfflineScenarioTimeout):
        runner.run(voice_only)
    assert time.monotonic() - started < 0.2


def report_run() -> OfflineScenarioRunV1:
    return OfflineScenarioRunV1(
        suite_id="offline-guardian-v1",
        status="PASS",
        reason="ok",
        results=(
            OfflineScenarioResultV1(
                scenario_id="SAFE-SLEEP-01",
                status="PASS",
                reason="ok",
                visual_oracle_relationship="INDEPENDENT",
                lanes=(
                    ScenarioLaneResult(
                        lane="visual_observation",
                        status="PASS",
                        reason="ok",
                        counts={"frames.processed": 10},
                        metrics_ms={"pipeline.p95": 12.5},
                    ),
                    ScenarioLaneResult(
                        lane="guardian_deterministic",
                        status="PASS",
                        reason="ok",
                        counts={"dashboard.event": 0, "dashboard.open": 0},
                    ),
                ),
            ),
        ),
    )


def report_destination(tmp_path: Path) -> Path:
    destination = tmp_path / "report"
    destination.mkdir(mode=0o700)
    return destination


def test_report_publishes_canonical_json_and_static_html(tmp_path: Path) -> None:
    from services.offline_guardian_report import publish_offline_scenario_report

    run = report_run()
    json_path, html_path = publish_offline_scenario_report(
        run,
        report_destination(tmp_path),
    )

    assert json_path.read_bytes() == canonical_offline_run_bytes(run)
    html = html_path.read_text(encoding="ascii")
    assert "SAFE-SLEEP-01" in html
    assert "visual_observation" in html
    assert "frames.processed" in html
    assert "dashboard.event" in html
    assert "pipeline.p95" in html
    assert "INDEPENDENT" in html
    assert "<script" not in html.lower()
    assert "http:" not in html.lower()
    assert "https:" not in html.lower()
    assert "does not prove model accuracy" in html
    assert (
        "Visual counts are observational; Guardian counts come from independent "
        "synthetic semantic oracles."
    ) in html
    assert stat.S_IMODE(json_path.stat().st_mode) == 0o600
    assert stat.S_IMODE(html_path.stat().st_mode) == 0o600
    assert {item.name for item in json_path.parent.iterdir()} == {
        "scenario-result.v1.json",
        "scenario-report.html",
    }
    payload = json.loads(json_path.read_text(encoding="ascii"))
    assert payload["results"][0]["visual_oracle_relationship"] == "INDEPENDENT"


@pytest.mark.parametrize("kind", ["existing", "symlink", "wrong_mode"])
def test_report_fails_closed_for_unsafe_destination(tmp_path: Path, kind: str) -> None:
    from services.offline_guardian_report import publish_offline_scenario_report

    destination = report_destination(tmp_path)
    if kind == "existing":
        existing = destination / "scenario-result.v1.json"
        existing.write_text("private-existing", encoding="ascii")
        existing.chmod(0o600)
    elif kind == "wrong_mode":
        destination.chmod(0o755)
    else:
        actual = destination
        destination = tmp_path / "linked-report"
        destination.symlink_to(actual, target_is_directory=True)

    with pytest.raises(ValueError, match="^offline_scenario_report_unsafe$"):
        publish_offline_scenario_report(report_run(), destination)
    if kind == "existing":
        assert (destination / "scenario-result.v1.json").read_text() == "private-existing"


def test_report_rolls_back_owned_first_publication_when_second_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import services.offline_guardian_report as module

    destination = report_destination(tmp_path)
    real_link = module._link_no_replace
    calls = 0

    def fail_second(source: Path, target: Path) -> None:
        nonlocal calls
        calls += 1
        if calls == 2:
            raise OSError("private failure")
        real_link(source, target)

    monkeypatch.setattr(module, "_link_no_replace", fail_second)

    with pytest.raises(ValueError, match="^offline_scenario_report_failed$"):
        module.publish_offline_scenario_report(report_run(), destination)

    assert list(destination.iterdir()) == []


def test_report_rolls_back_finals_when_second_temp_cleanup_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import services.offline_guardian_report as module

    destination = report_destination(tmp_path)
    real_unlink = Path.unlink

    def fail_html_temp(path: Path, *args, **kwargs) -> None:
        if path.name == ".scenario-report.html.tmp":
            raise OSError("private cleanup failure")
        real_unlink(path, *args, **kwargs)

    monkeypatch.setattr(Path, "unlink", fail_html_temp)

    with pytest.raises(ValueError, match="^offline_scenario_report_failed$"):
        module.publish_offline_scenario_report(report_run(), destination)

    assert not (destination / "scenario-result.v1.json").exists()
    assert not (destination / "scenario-report.html").exists()
    retained = destination / ".scenario-report.html.tmp"
    assert retained.is_file()
    assert stat.S_IMODE(retained.stat().st_mode) == 0o600


def test_report_rolls_back_finals_when_interrupted(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import services.offline_guardian_report as module

    destination = report_destination(tmp_path)
    real_link = module._link_no_replace
    calls = 0

    def interrupt_second(source: Path, target: Path) -> None:
        nonlocal calls
        calls += 1
        if calls == 2:
            raise KeyboardInterrupt
        real_link(source, target)

    monkeypatch.setattr(module, "_link_no_replace", interrupt_second)

    with pytest.raises(KeyboardInterrupt):
        module.publish_offline_scenario_report(report_run(), destination)

    assert not (destination / "scenario-result.v1.json").exists()
    assert not (destination / "scenario-report.html").exists()


def test_report_rejects_destination_below_symlink_ancestor(tmp_path: Path) -> None:
    from services.offline_guardian_report import publish_offline_scenario_report

    actual = tmp_path / "actual"
    nested = actual / "nested"
    nested.mkdir(mode=0o700, parents=True)
    actual.chmod(0o700)
    linked = tmp_path / "linked"
    linked.symlink_to(actual, target_is_directory=True)

    with pytest.raises(ValueError, match="^offline_scenario_report_unsafe$"):
        publish_offline_scenario_report(report_run(), linked / "nested")


def test_report_size_limit_fails_before_publication(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import services.offline_guardian_report as module

    destination = report_destination(tmp_path)
    monkeypatch.setattr(module, "MAX_REPORT_JSON_BYTES", 1)

    with pytest.raises(ValueError, match="^offline_scenario_report_too_large$"):
        module.publish_offline_scenario_report(report_run(), destination)

    assert list(destination.iterdir()) == []
