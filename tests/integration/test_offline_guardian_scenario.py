from __future__ import annotations

import stat
import subprocess
import threading
from pathlib import Path

import pytest

from packages.contracts.offline_guardian_scenario import (
    OfflineGuardianScenarioV1,
    OfflineScenarioResultV1,
    OfflineScenarioRunV1,
    ScenarioLaneResult,
    canonical_offline_run_bytes,
    load_offline_scenario_suite,
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


class AvailableVisualBackend:
    def infer(self, _bgr: object) -> RealtimeModelSignals:
        return RealtimeModelSignals(
            face_boxes=((0.4, 0.3, 0.2, 0.2),),
            pose_centers=((0.5, 0.5),),
        )


class DegradedVisualBackend:
    def infer(self, _bgr: object) -> RealtimeModelSignals:
        raise RealtimeModelError("private model detail")


def generated_video(path: Path) -> None:
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
            "2",
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


def test_visual_lane_replays_real_file_through_current_worker(tmp_path: Path) -> None:
    from services.offline_guardian_scenario import run_visual_lane

    media = tmp_path / "public-fixture.mkv"
    generated_video(media)

    result = run_visual_lane(
        scenario("SAFE-SLEEP-01"),
        load_manifest(VISUAL_MANIFEST),
        lambda _clip, _profile: media,
        AvailableVisualBackend(),
    )

    assert result.lane == "visual_observation"
    assert result.status == "PASS"
    assert result.reason == "ok"
    assert result.counts["frames.total"] == 10
    assert result.counts["frames.processed"] >= 1
    assert result.counts["errors.decode"] == 0
    assert result.counts["errors.worker"] == 0
    assert result.metrics_ms["pipeline.p95"] >= 0
    assert result.metrics_ms["model.p95"] >= 0
    assert not (tmp_path / "guardian-events.sqlite3").exists()
    assert not hasattr(result, "frame_observations")


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
        AvailableVisualBackend(),
    )

    assert result.status == "FAIL"
    assert result.reason == "offline_scenario_clip_missing"
    assert called == []


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
        AvailableVisualBackend(),
    )

    assert result.status == "FAIL"
    assert result.reason == "visual_corpus_input_invalid"
    assert "private-household-name" not in repr(result)


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
    pcm = {
        "wake": generated_pcm(4_000),
        "feeding": generated_pcm(5_000),
        "no_wake": generated_pcm(6_000),
        "unsupported": generated_pcm(7_000),
    }
    return pcm, ScenarioAsr(
        {
            pcm["wake"]: "小小",
            pcm["feeding"]: "我是爸爸，开始喂奶",
            pcm["no_wake"]: "今天天气如何",
            pcm["unsupported"]: "播放音乐",
        }
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


def build_runner(tmp_path: Path, media: Path, *, backend: object | None = None):
    from services.offline_guardian_scenario import OfflineGuardianScenarioRunner

    fixtures, asr = voice_fixtures()
    return OfflineGuardianScenarioRunner(
        runtime_root=tmp_path / "scenario-run",
        visual_manifest=load_manifest(VISUAL_MANIFEST),
        prepared_resolver=lambda _clip, _profile: media,
        model_backend=backend if backend is not None else AvailableVisualBackend(),
        voice_fixture_provider=fixtures.__getitem__,
        voice_vad=speech_vad(),
        voice_asr=asr,
        voice_synthesizer=RecordingScenarioSynth(),
    )


def test_runner_executes_all_required_lanes_in_declared_order(tmp_path: Path) -> None:
    media = tmp_path / "public-fixture.mkv"
    generated_video(media)
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
        visual_manifest=load_manifest(VISUAL_MANIFEST),
        prepared_resolver=lambda clip, _profile: (resolved.append(clip.clip_id), media)[1],
        model_backend=None,
        voice_fixture_provider=fixtures.__getitem__,
        voice_vad=speech_vad(),
        voice_asr=asr,
        voice_synthesizer=RecordingScenarioSynth(),
    )

    result = runner.run(suite)

    assert result.status == "FAIL"
    assert result.reason == "visual_corpus_model_unavailable"
    assert resolved == []
    assert [item.status for item in result.results] == ["FAIL", "FAIL", "FAIL", "PASS"]


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
    assert "<script" not in html.lower()
    assert "http:" not in html.lower()
    assert "https:" not in html.lower()
    assert stat.S_IMODE(json_path.stat().st_mode) == 0o600
    assert stat.S_IMODE(html_path.stat().st_mode) == 0o600
    assert {item.name for item in json_path.parent.iterdir()} == {
        "scenario-result.v1.json",
        "scenario-report.html",
    }


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
